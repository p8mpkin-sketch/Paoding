"""pd 与网页是同一个 API 的两个客户端（HMI §2、§11）。

HT-17：同一项人的操作，pd 发出的事件体与经 HTTP 提议通道发出的逐字段相同（idem_key 除外）。
HT-13 的一半：pd 写下的日志，HTTP 只读端点读得出同一份状态；两边的四语域表是同一张。
"""
import io
import json
import urllib.request

from test_pd import (
    PROBLEM,  # noqa: F401
    home,  # noqa: F401  fixture
)

from paoding_graph.contract import REGISTER, BlobStore, Config, GraphHttp, GraphService, TokenRegistry, views
from paoding_pd import render
from paoding_pd.cli import default_judges, main


def pd(home, *args):
    buf = io.StringIO()
    code = main(["--home", str(home / "data"), "--actor", "cz", *args], out=buf, read=lambda _: "yes")
    return code, buf.getvalue()


def serve(path, blobs):
    reg = TokenRegistry()
    reg.issue({"kind": "human", "id": "cz"}, "tok")
    svc = GraphService(path, Config(judges=default_judges()), reg)
    app = GraphHttp(svc, BlobStore(blobs))
    return svc, app, app.serve()


def call(url, path, body=None):
    req = urllib.request.Request(url + path, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET",
                                 headers={"Authorization": "Bearer tok", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _bodies(svc, pid="p1"):
    return [(e["kind"], e["actor"], e["body"]) for e in svc.log.events(pid)]


def test_same_event_bodies_from_pd_and_http(home, tmp_path):  # noqa: F811
    # 一边：pd
    assert pd(home, "problem", "open", str(home / "p.yaml"))[0] == 0
    assert pd(home, "--pid", "p1", "hint", "add", "先看配置文件")[0] == 0
    assert pd(home, "profile", "p1", "--override", "info=partial", "--reason", "材料不全")[0] == 0
    assert pd(home, "--pid", "p1", "hint", "close", "h_4")[0] == 0
    # 另一边：HTTP 提议通道
    svc, app, url = serve(tmp_path / "web.sqlite", tmp_path / "web-blobs")
    try:
        ops = []
        for name in ("statement.txt", "notes.txt"):
            data = (home / name).read_bytes()
            h = app.blobs.put(data)
            ops.append({"op": "register_artifact", "body": {"hash": h, "size": len(data), "media_type": "text/plain",
                                                             "class": "input"}})
        import yaml
        spec = yaml.safe_load(PROBLEM)
        problem = {"title": spec["title"], "origin": {"statement_ref": "$0", "materials": ["$1"]}, "goal": spec["goal"],
                   "scope": spec["scope"], "budget": spec["budget"], "env": spec["env"], "judges": spec["judges"]}
        assert call(url, "/v1/problems", {"id": "p1", "idem_key": "w1", "ops": ops + [{"op": "open_problem", "body": problem}]})["ok"]
        post = lambda op, body, k: call(url, "/v1/problems/p1/proposals", {"idem_key": k, "ops": [{"op": op, "body": body}]})  # noqa: E731
        assert post("hint", {"text": "先看配置文件"}, "w2")["ok"]
        assert post("profile_override", {"axis": "info", "value": "partial", "reason": "材料不全"}, "w3")["ok"]
        assert post("hint", {"close": "h_4"}, "w4")["ok"]
        from paoding_pd.cli import HUMAN_TOKEN, Local
        local = Local(home / "data", {"kind": "human", "id": "cz"})
        assert _bodies(local.graph) == _bodies(svc)                 # 事件种类、身份、事件体逐字段相同
        # 同一份状态，两种排版：pd 的文本与 HTTP 的结构化视图
        st = call(url, "/v1/problems/p1/status")
        text = render.status(local.graph.state, "p1", local.graph.budget("p1"))
        assert st["problem"]["profile"]["info"] == "partial" and "info=partial" in text
        assert st["problem"]["profile_overrides"][0]["reason"] == {"src": "human_reason", "register": "人", "value": "材料不全"}
        assert st["hints"][0]["closed"] and "（已关闭）" in text
        assert HUMAN_TOKEN
    finally:
        app.close()


def test_pd_and_web_share_register_table_and_level_words():
    assert render.REGISTER is REGISTER is views.REGISTER
    assert render.LEVEL_WORDS is views.LEVEL_WORDS
    o = render.Out()
    for src, reg in REGISTER.items():
        o.add(src, "x")
        assert o.lines[-1] == f"[{reg}] x" and views.tag(src, "x")["register"] == reg
