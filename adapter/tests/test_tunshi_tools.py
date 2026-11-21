"""方案分析会话的宿主工具（paoding_adapter.tunshi）：简报、产物登记前的检查、交付闸、抓取的边界。

直接对着 ToolHost 调（真图服务、真 Blob 仓库），不起驱动程序。整条链在 test_tunshi_session.py、test_tunshi_fetch.py。
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest
from tunshi_rig import cases, engine_gongfa, fixture_tar, trig  # noqa: F401

from paoding_adapter import tunshi
from paoding_adapter.tools import Session, ToolHost, tool_order, tool_schemas
from paoding_executor.contract import ExecResult
from paoding_fenjue.contract import GONGFA_ENV, analysis, current, digest, gongfa

TOOLS = ("deliver", "intake", "fetch", "check")
UPLOAD = [{"no": 1, "form": "code", "via": "upload", "artifact": "$material"}]


def host_for(rig, pid="p1", secrets=(), executor="rig", sandbox="sb-1", with_analysis=True, tools=TOOLS, lease=None):
    """一个会话的 ToolHost。lease 给出时沿用那个租约（内核同一时刻只许一个求解会话），工作区另起一个目录。"""
    lid = lease or rig.lease(pid)
    tok = rig.graph.tokens.issue({"kind": "adapter", "id": "ad1", "session": lid, "role": "solve"})
    rig.n += 1
    ws = rig.tmp / "ws" / f"{lid}-{rig.n}"
    ws.mkdir(parents=True)
    s = Session(pid, lid, "solve", tok, ws, tools, sandbox)
    s.secrets = tuple(secrets)
    an = tunshi.Analysis("h1.tunshi@1", lambda _pid: rig.profile) if with_analysis else None
    ex = rig.executor if executor == "rig" else executor
    return ToolHost(s, rig.graph, rig.graph, rig.blobs, ex, analysis=an, access=lambda: {"added": []}), ws


def opened(trig, **kw):  # noqa: F811
    rig = trig(cases.recording("alpha", "code"))
    rig.open(intake={**cases.intake("alpha", "code"), "sources": UPLOAD}, material=fixture_tar("alpha"), **kw)
    return rig


def release(rig, lid, outcome="nothing", pid="p1"):
    rig.n += 1
    out = rig.graph.submit(
        "tok-sinan", pid, f"rel-{rig.n}", [{"op": "release", "body": {"lease": lid, "outcome": outcome}}]
    )
    assert out["ok"], out


def product(ws, obj, name=None):
    sha = digest(obj)
    d = ws / "analysis" / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name or sha}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return f"analysis/artifacts/{name or sha}.json"


# ---------------------------------------------------------------- intake


def test_the_brief_comes_from_the_ledger_and_the_configured_profile(trig):  # noqa: F811
    rig = opened(trig)
    h, ws = host_for(rig)
    b = h.call("intake", {})
    p = rig.graph.state["problems"]["p1"]
    mat = p["origin"]["materials"][0]
    assert b["ok"] and b["run"] == "p1" and b["form"] == "h1.tunshi@1" and b["statement"] == p["goal"]["statement"]
    assert b["intake"]["sources"] == [{"no": 1, "form": "code", "via": "upload", "artifact": mat}]
    assert set(b["materials"]) == {mat}  # 立项单本身不算材料
    row = b["materials"][mat]
    blob = ws / row["path"]
    assert blob.read_bytes() == fixture_tar("alpha") and row["size"] == len(fixture_tar("alpha"))
    assert b["budget"] == {"usd_milli": 400_000, "spent_usd_milli": 0}
    assert b["relays_left"] == tunshi.OPEN_RELAYS - 1 and b["closing"] is None and b["follow_ups"] == []
    assert b["models"] == rig.profile["models"] and b["bang"] == rig.profile["bang"]
    assert b["access_wait_s"] == 3.0 and b["deliveries"] == 0
    # 已经在的材料不重拷；被动过的换回账上的那份；被换成链接的也换回来（不顺着链接写）
    before = blob.stat().st_mtime_ns
    h.call("intake", {})
    assert blob.stat().st_mtime_ns == before
    blob.write_bytes(b"tampered")
    h.call("intake", {})
    assert blob.read_bytes() == fixture_tar("alpha")
    victim = rig.tmp / "victim.txt"
    victim.write_text("keep")
    blob.unlink()
    os.symlink(victim, blob)
    h.call("intake", {})
    assert not blob.is_symlink() and blob.read_bytes() == fixture_tar("alpha") and victim.read_text() == "keep"
    # 收尾轮的标记由运行器给；参数一概不收
    h.analysis.phase = "budget"
    assert h.call("intake", {})["closing"] == "budget"
    bad = h.call("intake", {"pid": "p2"})
    assert bad["ok"] is False and bad["code"] == "schema_error"


def test_relays_left_counts_this_rounds_sessions_only(trig):  # noqa: F811
    assert tunshi.OPEN_RELAYS == __import__("paoding_graph.work", fromlist=["x"]).OPEN_RELAYS
    rig = opened(trig)
    for want in (4, 3, 2):
        h, _ = host_for(rig)
        assert h.call("intake", {})["relays_left"] == want
        release(rig, h.s.lease_id)


def test_a_broken_or_oversized_intake_sheet_is_reported_in_the_brief(trig, monkeypatch):  # noqa: F811
    rig = trig(cases.recording("alpha", "code"))
    bad = rig.put(b"{not json", analysis.INTAKE_MEDIA, "p1")
    rig.open(extra_materials=(bad,))
    h, _ = host_for(rig)
    b = h.call("intake", {})
    assert "intake" not in b and b["intake_errors"] == ["立项单不是合法的 JSON"]
    monkeypatch.setattr(tunshi, "INTAKE_BYTES", 4)
    assert "超过" in h.call("intake", {})["intake_errors"][0]
    # 没有立项单的抓取请求：照实说
    assert h.call("fetch", {"source": 1})["status"] == "failed"


def test_an_oversized_material_is_named_not_copied(trig, monkeypatch):  # noqa: F811
    rig = opened(trig)
    monkeypatch.setattr(tunshi, "FETCH_BYTES", 10)
    h, ws = host_for(rig)
    (row,) = h.call("intake", {})["materials"].values()
    assert "path" not in row and "超过" in row["error"] and not list((ws / "materials").glob("*.blob"))


def test_ordinary_sessions_do_not_have_these_tools(trig):  # noqa: F811
    rig = opened(trig)
    h, _ = host_for(rig, tools=("exec", "show", "deliver"))
    assert h.call("intake", {})["code"] == "forbidden_op"
    h2, _ = host_for(rig, with_analysis=False, lease=h.s.lease_id)  # 工具面上有、却不是方案分析会话：拒
    for name, args in (("intake", {}), ("fetch", {"source": 1}), ("check", {"name": "x", "path": "y"})):
        out = h2.call(name, args)
        assert out["ok"] is False and "不是方案分析会话" in out["detail"]
    out = h2.call("deliver", {"outcome": "blocked", "needs": ["x"], "artifacts": []})
    assert out["ok"] is False and "多了 ['artifacts']" in out["detail"]


def test_tool_order_is_unchanged_for_the_main_gongfa_and_extended_for_the_engine_one(engine_gongfa, monkeypatch):  # noqa: F811
    engine = os.environ[GONGFA_ENV]
    monkeypatch.delenv(GONGFA_ENV)
    gongfa.cache_clear()
    main = current()
    monkeypatch.setenv(GONGFA_ENV, engine)
    gongfa.cache_clear()
    base = (*main.params("H3", "h3.base")["order"], *main.params("H3", "h3.kb")["tools"])
    assert tool_order(main) == base
    eng = tool_order(current())
    assert eng == (*base, "intake", "fetch", "check")
    assert [t["name"] for t in tool_schemas(TOOLS, eng)] == ["deliver", "intake", "fetch", "check"]
    assert [t["name"] for t in tool_schemas(("exec", "show", "deliver"), base)] == ["exec", "show", "deliver"]


# ---------------------------------------------------------------- check 与交付闸


def test_check_registers_a_valid_product_as_an_authored_artifact(trig):  # noqa: F811
    rig = opened(trig)
    h, ws = host_for(rig)
    obj = {"markdown": "# 报告\n正文"}
    out = h.call("check", {"name": "report:S3", "path": product(ws, obj)})
    art = rig.graph.state["artifacts"][out["artifact"]]
    assert out["ok"] and out["sha256"] == digest(obj) and out["name"] == "report:S3"
    assert art["class"] == "authored" and art["media_type"] == tunshi.PRODUCT_MEDIA
    assert art["producer"]["session"] == h.s.lease_id and json.loads(rig.blobs.get(art["hash"])) == obj
    assert h.analysis.checked == {out["artifact"]}


@pytest.mark.parametrize(
    ("name", "path", "said"),
    [
        ("report:S3", "analysis/run.json", "path 须是"),
        ("report:S3", "analysis/artifacts/../../../etc/passwd", "path 须是"),
        ("report:S3", "analysis/artifacts/" + "0" * 64 + ".json", "工作区里没有文件"),
        ("bad name!", "analysis/artifacts/" + "0" * 64 + ".json", "name 只含"),
        ("n" * 81, "analysis/artifacts/" + "0" * 64 + ".json", "name 只含"),
    ],
)
def test_check_refuses_paths_and_names_outside_its_shape(trig, name, path, said):  # noqa: F811
    rig = opened(trig)
    h, ws = host_for(rig)
    out = h.call("check", {"name": name, "path": path})
    assert out["ok"] is False and said in out["detail"]
    assert h.call("check", {"name": name, "path": path, "class": "exec"})["code"] == "schema_error"


def test_check_refuses_bad_content(trig, monkeypatch):  # noqa: F811
    rig = opened(trig)
    token = "ghp_Q7wErTy9UiOp1234aSdF"
    h, ws = host_for(rig, secrets=(token,))
    before = len(rig.graph.state["artifacts"])
    wrong = product(ws, {"a": 1}, name="1" * 64)  # 文件名里的摘要与内容对不上
    assert "摘要与内容对不上" in h.call("check", {"name": "report:S3", "path": wrong})["detail"]
    bad = h.call("check", {"name": "candidates.json", "path": product(ws, {"v": 1})})  # 不合它的 Schema
    assert bad["ok"] is False and bad["errors"]
    leak = h.call("check", {"name": "report:S3", "path": product(ws, {"markdown": f"令牌是 {token}"})})
    assert "凭据" in leak["detail"]
    raw = ws / "analysis" / "artifacts" / ("2" * 64 + ".json")
    raw.write_bytes(b"\xff\xfe not utf8")
    assert (
        "UTF-8 JSON" in h.call("check", {"name": "report:S3", "path": f"analysis/artifacts/{'2' * 64}.json"})["detail"]
    )
    raw.write_text("[1, 2]")
    assert (
        "JSON 对象" in h.call("check", {"name": "report:S3", "path": f"analysis/artifacts/{'2' * 64}.json"})["detail"]
    )
    monkeypatch.setattr(tunshi, "PRODUCT_BYTES", 5)
    assert "超过" in h.call("check", {"name": "report:S3", "path": product(ws, {"markdown": "long enough"})})["detail"]
    assert len(rig.graph.state["artifacts"]) == before and h.analysis.checked == set()  # 一份都没登记
    # 链接指到工作区外面：读不到
    monkeypatch.setattr(tunshi, "PRODUCT_BYTES", 4 * 1024 * 1024)
    secret = rig.tmp / "host-secret.json"
    secret.write_text('{"k": "v"}')
    link = ws / "analysis" / "artifacts" / ("3" * 64 + ".json")
    os.symlink(secret, link)
    assert (
        "越出工作区" in h.call("check", {"name": "report:S3", "path": f"analysis/artifacts/{'3' * 64}.json"})["detail"]
    )


def test_check_has_a_per_session_quota(trig, monkeypatch):  # noqa: F811
    rig = opened(trig)
    monkeypatch.setattr(tunshi, "CHECK_MAX", 2)
    h, ws = host_for(rig)
    outs = [h.call("check", {"name": "report:S3", "path": product(ws, {"markdown": str(i)})}) for i in range(3)]
    assert [o["ok"] for o in outs] == [True, True, False] and outs[2]["code"] == "quota_exceeded"


def test_delivery_lists_only_products_that_went_through_check(trig):  # noqa: F811
    rig = opened(trig)
    h, ws = host_for(rig)
    good = h.call("check", {"name": "report:S3", "path": product(ws, {"markdown": "x"})})["artifact"]
    p = rig.graph.state["problems"]["p1"]
    statement, material = p["origin"]["statement_ref"], p["origin"]["materials"][0]
    base = {"outcome": "partial", "answer": "报告", "needs": ["请确认"]}
    for ids in ([statement], [material], ["a_99999"], [good, statement], "a_1", [1], [good] * 65):
        out = h.call("deliver", {**base, "artifacts": ids})
        assert out["ok"] is False and out["code"] == "schema_error", ids
    assert rig.deliveries() == []
    # 别的题登记的产物也不行
    rig.open(pid="p2", material=fixture_tar("alpha"))
    h2, ws2 = host_for(rig, pid="p2")
    other = h2.call("check", {"name": "report:S3", "path": product(ws2, {"markdown": "y"})})["artifact"]
    assert h.call("deliver", {**base, "artifacts": [other]})["ok"] is False
    out = h.call("deliver", {**base, "artifacts": [good]})
    assert out["ok"] and out["artifacts"] == 1 and rig.deliveries()[-1]["outcome"] == "partial"
    # 接力后的会话可以列前一个会话登记过的产物（以事件账为准，不靠本会话的内存）
    release(rig, h.s.lease_id, "done")
    rig.follow_up("继续")
    h3, _ = host_for(rig)
    assert h3.call("deliver", {**base, "artifacts": [good]})["ok"]


# ---------------------------------------------------------------- fetch 的边界


class Scripted:
    """执行层替身：照剧本在工作区里留东西、回显一行 JSON。"""

    def __init__(self, rig, act):
        self.rig, self.act, self.calls = rig, act, []

    def destroy(self, sid):
        pass

    def exec(self, sid, cmd, pid, idem_key, timeout_s=60, cwd="/workspace", register_as="exec"):
        self.calls.append(cmd)
        code, output = self.act(cmd)
        return ExecResult("a_exec", "h", code, output, False, {})


def address_rig(trig, url="http://127.0.0.1:9/alpha.tar.gz", **src):  # noqa: F811
    rig = trig(cases.recording("alpha", "code"))
    source = {"no": 1, "form": "code", "via": "repo_url", "url": url, **src}
    scope = [{"resource": "net", "pattern": "127.0.0.1:9", "actions": ["connect"], "risk": "r1"}]
    rig.open(intake={**cases.intake("alpha", "code"), "sources": [source]}, scope=scope)
    return rig


def test_fetch_takes_a_source_number_and_nothing_else(trig):  # noqa: F811
    rig = address_rig(trig)
    h, _ = host_for(rig)
    for args in ({"source": 1, "url": "http://evil.example/x"}, {"source": 1, "target": "evil.example:443"}, {}):
        out = h.call("fetch", args)
        assert out["ok"] is False and out["code"] == "schema_error"
    assert "没有来源 7" in h.call("fetch", {"source": 7})["detail"]
    assert rig.executor.calls == [] and rig.requests() == []
    no_box, _ = host_for(rig, sandbox=None, lease=h.s.lease_id)
    assert "没有执行容器" in no_box.call("fetch", {"source": 1})["detail"]


def test_fetch_is_only_for_address_sources_and_never_for_refused_ones(trig):  # noqa: F811
    rig = opened(trig)
    h, _ = host_for(rig)
    assert "不是地址类来源" in h.call("fetch", {"source": 1})["detail"]
    rig2 = address_rig(trig, url="https://git.example/cz/paoding-bank", ref="v1")
    h2, _ = host_for(rig2)
    out = h2.call("fetch", {"source": 1})
    assert out["status"] == "refused" and rig2.requests() == [] and rig2.executor.calls == []
    rig3 = address_rig(trig, url="https://user:pw@git.example/a/b", ref="v1")
    h3, _ = host_for(rig3)
    assert "用户名或口令" in h3.call("fetch", {"source": 1})["detail"]


def test_what_the_sandbox_reports_is_checked_against_the_file_itself(trig):  # noqa: F811
    rig = address_rig(trig)
    ws_of = {}
    data = fixture_tar("alpha")

    def honest(cmd):
        (ws_of["ws"] / "materials" / "fetch" / "s1.blob").write_bytes(data)
        return 0, json.dumps({"ok": True, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})

    def lying(cmd):
        (ws_of["ws"] / "materials" / "fetch" / "s1.blob").write_bytes(data)
        return 0, json.dumps({"ok": True, "sha256": "0" * 64})

    def linking(cmd):
        target = rig.tmp / "host-file"
        target.write_bytes(data)
        os.symlink(target, ws_of["ws"] / "materials" / "fetch" / "s1.blob")
        return 0, json.dumps({"ok": True, "sha256": hashlib.sha256(data).hexdigest()})

    def nothing(cmd):
        return 0, json.dumps({"ok": True, "sha256": "0" * 64})

    def failing(cmd):
        return 1, "Traceback...\n" + json.dumps({"ok": False, "detail": "HTTP 500 boom"})

    def silent(cmd):
        return 127, "sh: python3: not found"

    lid = rig.lease()
    for act, status, said in (
        (honest, "fetched", ""),
        (lying, "failed", "摘要对不上"),
        (linking, "failed", "没有留下文件"),
        (nothing, "failed", "没有留下文件"),
        (failing, "failed", "HTTP 500 boom"),
        (silent, "failed", "退出码 127"),
    ):
        h, ws = host_for(rig, executor=Scripted(rig, act), lease=lid)
        ws_of["ws"] = ws
        out = h.call("fetch", {"source": 1})
        assert out["status"] == status and said in out.get("detail", ""), (act.__name__, out)
        if status == "fetched":
            assert out == {
                "status": "fetched",
                "path": "materials/fetch/s1.blob",
                "artifact": "a_exec",
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "targets": ["127.0.0.1:9"],
            }


def test_fetch_has_a_per_session_download_cap(trig, monkeypatch):  # noqa: F811
    rig = address_rig(trig)
    monkeypatch.setattr(tunshi, "FETCH_MAX", 1)
    h, _ = host_for(rig, executor=Scripted(rig, lambda cmd: (1, json.dumps({"ok": False, "detail": "x"}))))
    assert h.call("fetch", {"source": 1})["detail"] == "x"
    assert "上限" in h.call("fetch", {"source": 1})["detail"] and len(h.executor.calls) == 1


def test_an_approved_address_above_the_sessions_risk_ceiling_is_not_fetched(trig):  # noqa: F811
    rig = trig(cases.recording("alpha", "code"))
    source = {"no": 1, "form": "code", "via": "repo_url", "url": "http://127.0.0.1:9/a.tar.gz"}
    scope = [{"resource": "net", "pattern": "127.0.0.1:9", "actions": ["connect"], "risk": "r2"}]
    rig.open(intake={**cases.intake("alpha", "code"), "sources": [source]}, scope=scope)
    h, _ = host_for(rig)
    out = h.call("fetch", {"source": 1})
    assert out["status"] == "failed" and "风险" in out["detail"] and rig.executor.calls == []
