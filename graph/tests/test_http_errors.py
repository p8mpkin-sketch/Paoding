"""HTTP 分发的异常去向（审计 P1-4）：调用方的坏输入一律 4xx；服务端自己的缺陷是 500 `internal`，不伪装成 400。

此前分发处宽接 ValueError、KeyError、TypeError 并一律回 400 schema_error，
视图或内核里的缺陷会被说成“请求不合形状”。
"""
import json
import random

import pytest
from http_rig import Api, drive

from paoding_graph import views


@pytest.fixture
def api(tmp_path):
    a = Api(tmp_path)
    yield a
    a.close()


JUNK = [None, True, 0, -1, 1.5, 10 ** 30, "", "x", "$0", "$9", [], [1], {}, {"a": 1}, [[]], "f_1", "i_999"]


def test_bad_query_and_headers_are_400(api):
    drive(api, "p1")
    for path in ("/v1/problems/p1/view?layer=nope", "/v1/problems/p1/view?after_seq=x",
                 "/v1/problems/p1/view?limit=0", "/v1/problems/p1/events?wait=soon",
                 "/v1/problems/p1/events?after=-1", "/v1/problems/p1/status?as_of=abc",
                 "/v1/nodes/f_1?layer=nope", "/v1/problems/p1/invalidations", "/v1/blobs/zz",
                 "/v1/blobs/" + "0" * 64 + "?range=a-b"):
        st, body, _ = api.req("GET", path)
        assert st == 400 and body["code"] == "schema_error", (path, st, body)
    st, body, _ = api.req("POST", "/v1/problems/p1/proposals", b"{not json", token="tok-human")
    assert st == 400 and body["code"] == "schema_error"
    st, body, _ = api.req("POST", "/v1/problems/p1/proposals", b"[1]", token="tok-human")
    assert st == 400 and body["code"] == "schema_error"


def test_op_body_must_be_an_object(api):
    """此前 body 不是对象时，Blob 前置检查里的 .get 抛 AttributeError，连接被直接掐断。"""
    api.open("p1")
    for bad in ("x", 3, [1], None):
        st, body, _ = api.req("POST", "/v1/problems/p1/proposals",
                              {"idem_key": f"k-{bad!r}", "ops": [{"op": "register_artifact", "body": bad}]},
                              token="tok-exec")
        assert st == 400 and body["code"] == "schema_error", (bad, st, body)


def test_malformed_requests_never_500(api):
    """随机的坏请求体打遍写端点：只会是 2xx 或 4xx，且日志的链头不被坏请求推进到坏状态。"""
    drive(api, "p1")
    api.open("p2")
    rng = random.Random(20261118)
    lease_ids = list(api.svc.state["leases"])
    seen = set()
    for n in range(300):
        def junk(depth=0):
            v = rng.choice(JUNK)
            if depth < 2 and rng.random() < 0.3:
                return {rng.choice(["op", "body", "kind", "target", "hash", "class", "lease", "id", "ops"]):
                        junk(depth + 1) for _ in range(rng.randint(0, 3))}
            return v
        body = {k: junk() for k in rng.sample(
            ["id", "idem_key", "ops", "kind", "target", "holder", "reserve", "ttl_s", "problem_id", "hash", "class",
             "outcome", "transcript_ref", "goal", "scope", "budget", "origin", "judges"], rng.randint(0, 6))}
        if rng.random() < 0.6:
            body["idem_key"] = f"z{n}"
        if rng.random() < 0.5:
            body["ops"] = [{"op": rng.choice(["add_fact", "approve", "lease", "release", "hint", "x", "open_problem",
                                              "register_artifact", "close_problem"]), "body": junk()}
                           for _ in range(rng.randint(1, 3))]
        path = rng.choice(["/v1/problems", "/v1/problems/p2/proposals", "/v1/problems/p1/proposals",
                           "/v1/problems/p2/leases", f"/v1/leases/{rng.choice(lease_ids)}/renew",
                           f"/v1/leases/{rng.choice(lease_ids)}/release", "/v1/artifacts", "/v1/profile/preview"])
        st, out, _ = api.req("POST", path, body, token=rng.choice(["tok-human", "tok-sinan", "tok-exec"]))
        assert st < 500, (path, body, st, out)
        seen.add(st)
    assert 400 in seen and len(seen) >= 2, seen
    assert api.get("/v1/health")["ok"]


def test_server_defect_is_500_not_400(api, monkeypatch, capsys):
    """视图里的缺陷（这里人为注入 KeyError、TypeError、ValueError）回 500 internal，栈留在标准错误里。"""
    api.open("p1")
    for exc in (KeyError("budget"), TypeError("unhashable"), ValueError("oops")):
        def broken(state, pid, exc=exc):
            raise exc
        monkeypatch.setattr(views, "status", broken)
        st, body, _ = api.req("GET", "/v1/problems/p1/status")
        assert (st, body["code"], body["detail"]) == (500, "internal", type(exc).__name__)
        assert "Traceback" in capsys.readouterr().err
    monkeypatch.undo()
    assert api.get("/v1/problems/p1/status")                       # 服务没有被坏请求带倒


def test_catalog_skips_unparseable_entries(tmp_path):
    d = tmp_path / "tpl"
    d.mkdir()
    (d / "ok.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    (d / "bad.json").write_text("{", encoding="utf-8")
    (d / "bad.yaml").write_text("a: [1", encoding="utf-8")
    a = Api(tmp_path, templates_dir=d)
    try:
        items = {i["name"] + "." + ("y" if i["text"].startswith("a:") else "j"): i for i in a.get("/v1/templates")["items"]}
        assert items["ok.j"]["data"] == {"a": 1}
        assert items["bad.j"]["data"] is None and items["bad.y"]["data"] is None
    finally:
        a.close()
