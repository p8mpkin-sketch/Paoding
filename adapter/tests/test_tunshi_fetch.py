"""方案分析的取材（docs/design/fenjue/13-kernel.md §4.2）：地址类来源经 `fetch` 工具抓取。

抓哪个地址、连哪个 host:port 由宿主从事件账里的立项单推出；没有授权就提访问申请，人批了才在沙箱里跑一条固定的
下载命令。这里的执行层替身真的把那条命令在本机跑一遍，连的是测试自己起的本机 HTTP 服务。
"""

from __future__ import annotations

import json
import threading
import time

import pytest
from tunshi_rig import HotExec, LocalExec, Site, cases, engine_gongfa, fixture_tar, trig  # noqa: F401

from paoding_adapter import tunshi


def repo(url: str, **kw):
    return {
        **cases.intake("alpha", "code"),
        "sources": [{"no": 1, "form": "code", "via": "repo_url", "url": url, **kw}],
    }


@pytest.fixture
def site():
    s = Site({"/alpha.tar.gz": fixture_tar("alpha")})
    yield s
    s.close()


def approve_when_asked(rig, decision="approve", after=0.3, **kw):
    def go():
        t0 = time.monotonic()
        while time.monotonic() - t0 < 20:
            pend = [x for x in rig.requests() if x["status"] == "pending"]
            if pend:
                time.sleep(after)
                rig.decide(pend[0]["id"], decision, **kw)
                return
            time.sleep(0.05)

    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t


def test_an_address_source_is_fetched_once_access_is_approved(trig, site):  # noqa: F811
    rig = trig(cases.recording("alpha", "code"), local_exec=True)
    rig.profile["access_wait_s"] = 15
    rig.open(intake=repo(f"{site.url}/alpha.tar.gz"))
    approve_when_asked(rig)
    lid, rec = rig.session()
    assert rec.release["outcome"] == "done", rig.stderr(lid)
    # 申请写明是哪个来源、只下载不执行；规则只有这一个 host:port 的 connect
    (req,) = rig.requests()
    assert req["status"] == "granted" and req["rules"] == [
        {"resource": "net", "pattern": site.target, "actions": ["connect"], "risk": "r1"}
    ]
    assert "来源 1" in req["why"] and "只下载、不执行" in req["why"] and req["session"] == lid
    assert site.seen == ["/alpha.tar.gz"]  # 批准之前一个字节都没取；批准之后只取了一次
    # 沙箱里跑的是宿主写死的下载程序：地址是立项单里的那个
    (cmd,) = rig.executor.calls
    assert cmd.startswith("python3 -I -c ") and f"{site.url}/alpha.tar.gz" in cmd
    # 主张的依据是那次下载的执行留档（exec 类）
    d = rig.deliveries()[-1]
    (claim,) = d["claims"]
    ev = rig.graph.state["artifacts"][claim["refs"][0]]
    assert d["outcome"] == "partial" and ev["class"] == "exec"
    # 活动面板：等批准期间每隔一会儿问一次，但同一个状态只出一对事件
    calls = [
        c["input"]
        for e in rec.events
        if e.get("type") == "assistant"
        for c in e["message"].get("content", [])
        if c.get("type") == "tool_use" and c["name"].endswith("__fetch")
    ]
    assert calls == [{"source": 1}, {"source": 1}]
    transcript = json.loads(rig.blobs.get(rig.graph.state["artifacts"][rec.transcript_ref]["hash"]))
    assert sum(1 for c in transcript["tool_calls"] if c["tool"] == "fetch") > 2  # 会话记录里每一次都在
    # 接着做第二轮：材料已经定版在工作区，不再抓
    rig.follow_up(cases.g1_block(json.loads(_artifact(rig, lid, "candidates.json"))))
    lid2, rec2 = rig.session()
    assert rig.run_units(lid2)["step"] == "G2" and len(rig.executor.calls) == 1 and site.seen == ["/alpha.tar.gz"]
    assert rig.deliveries()[-1]["claims"][0]["refs"] == claim["refs"]


def _artifact(rig, lid, name):
    sha = rig.run_units(lid)["artifacts"][name]
    return (rig.ws(lid) / "analysis" / "artifacts" / f"{sha}.json").read_text(encoding="utf-8")


def test_while_access_is_pending_nothing_is_fetched_and_the_person_is_told(trig, site):  # noqa: F811
    rig = trig(cases.recording("alpha", "code"), local_exec=True)
    rig.profile["access_wait_s"] = 0.6
    rig.open(intake=repo(f"{site.url}/alpha.tar.gz"))
    lid, rec = rig.session()
    d = rig.deliveries()[-1]
    assert d["outcome"] == "blocked" and site.target in d["needs"][0] and "批准或拒绝" in d["needs"][0]
    assert site.seen == [] and rig.executor.calls == [] and rig.replay.calls == []
    (req,) = rig.requests()
    assert req["status"] == "pending"
    # 人批了，再追问一句：下一个会话不再提申请，直接抓
    rig.decide(req["id"])
    rig.follow_up("继续")
    lid2, rec2 = rig.session()
    assert rig.deliveries()[-1]["outcome"] == "partial" and len(rig.requests()) == 1 and site.seen == ["/alpha.tar.gz"]


def test_a_denied_address_blocks_and_is_not_asked_again(trig, site):  # noqa: F811
    rig = trig(cases.recording("alpha", "code"), local_exec=True)
    rig.profile["access_wait_s"] = 15
    rig.open(intake=repo(f"{site.url}/alpha.tar.gz"))
    approve_when_asked(rig, "deny", reason="先不看这个")
    lid, rec = rig.session()
    d = rig.deliveries()[-1]
    assert d["outcome"] == "blocked" and "被拒绝" in " ".join(d["needs"]) and "先不看这个" in " ".join(d["needs"])
    assert site.seen == [] and rig.executor.calls == []
    rig.follow_up("继续")
    lid2, rec2 = rig.session()  # 人拒过的地址在这道题里不能再申请（内核的规则）：照实再说一遍，不绕路
    assert rig.deliveries()[-1]["outcome"] == "blocked" and len(rig.requests()) == 1 and site.seen == []


def test_an_executor_without_hot_gates_fetches_in_the_next_session(trig, site):  # noqa: F811
    """执行层不支持会话中途开闸（退路）：批下来的地址要等下一个会话起沙箱时才通。照实说，不假装抓到。"""
    rig = trig(cases.recording("alpha", "code"), local_exec="cold")
    rig.profile["access_wait_s"] = 15
    rig.open(intake=repo(f"{site.url}/alpha.tar.gz"))
    approve_when_asked(rig)
    lid, rec = rig.session()
    d = rig.deliveries()[-1]
    assert d["outcome"] == "blocked" and "下一个会话" in d["needs"][0] and site.seen == []
    rig.follow_up("继续")
    lid2, rec2 = rig.session()
    assert rig.deliveries()[-1]["outcome"] == "partial" and site.seen == ["/alpha.tar.gz"]


def test_runtime_grants_switched_off_is_reported_as_such(trig, site):  # noqa: F811
    rig = trig(cases.recording("alpha", "code"), local_exec=True, grants_runtime=False)
    rig.open(intake=repo(f"{site.url}/alpha.tar.gz"))
    lid, rec = rig.session()
    d = rig.deliveries()[-1]
    assert d["outcome"] == "blocked" and "grants.runtime" in " ".join(d["needs"]) and site.seen == []


def test_an_address_already_in_scope_needs_no_request(trig, site):  # noqa: F811
    rig = trig(cases.recording("alpha", "code"), local_exec=True)
    scope = [
        {"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"},
        {"resource": "net", "pattern": site.target, "actions": ["connect"], "risk": "r1"},
    ]
    rig.open(intake=repo(f"{site.url}/alpha.tar.gz"), scope=scope)
    lid, rec = rig.session()
    assert rig.deliveries()[-1]["outcome"] == "partial" and rig.requests() == [] and site.seen == ["/alpha.tar.gz"]


@pytest.mark.parametrize(
    ("files", "redirects", "said"),
    [
        ({}, {}, "HTTP 404"),
        ({}, {"/alpha.tar.gz": "http://other.invalid/alpha.tar.gz"}, "redirect to http://other.invalid"),
        ({"/alpha.tar.gz": b"this is not an archive"}, {}, ""),
    ],
)
def test_a_failed_or_odd_download_blocks_with_the_reason(trig, files, redirects, said):  # noqa: F811
    s = Site(files, redirects)
    try:
        rig = trig(cases.recording("alpha", "code"), local_exec=True)
        scope = [{"resource": "net", "pattern": s.target, "actions": ["connect"], "risk": "r1"}]
        rig.open(intake=repo(f"{s.url}/alpha.tar.gz"), scope=scope)
        lid, rec = rig.session()
        d = rig.deliveries()[-1]
        if said:
            assert d["outcome"] == "blocked" and said in " ".join(d["needs"]), d["needs"]
            assert rig.replay.calls == []
        else:  # 不是归档就当一个文件：照常立项（单文件材料）
            assert (rig.ws(lid) / "materials" / "s1" / "material.txt").read_bytes() == b"this is not an archive"
    finally:
        s.close()


def test_a_redirect_within_the_same_site_is_followed(trig):  # noqa: F811
    s = Site({"/real.tar.gz": fixture_tar("alpha")})
    s.redirects["/alpha.tar.gz"] = f"{s.url}/real.tar.gz"
    try:
        rig = trig(cases.recording("alpha", "code"), local_exec=True)
        scope = [{"resource": "net", "pattern": s.target, "actions": ["connect"], "risk": "r1"}]
        rig.open(intake=repo(f"{s.url}/alpha.tar.gz"), scope=scope)
        lid, rec = rig.session()
        assert rig.deliveries()[-1]["outcome"] == "partial" and s.seen == ["/alpha.tar.gz", "/real.tar.gz"]
    finally:
        s.close()


def test_a_service_source_is_probed_by_the_approved_plan_only(trig):  # noqa: F811
    fx = cases.HERE / "alpha" / "service"
    plan = json.loads((fx / "plan.json").read_text(encoding="utf-8"))
    resp = {r["item"]: r for r in json.loads((fx / "responses.json").read_text(encoding="utf-8"))["responses"]}
    files = {it["path"]: json.dumps(resp[it["no"]]["body"]).encode() for it in plan["items"]}
    s = Site(files)
    try:
        rig = trig(cases.recording("alpha", "service"), local_exec=True)
        src = {
            "no": 1,
            "form": "service",
            "via": "service_url",
            "url": s.url,
            "probe_plan": "\n".join(f"GET {it['path']}" for it in plan["items"]),
        }
        scope = [{"resource": "net", "pattern": s.target, "actions": ["connect"], "risk": "r1"}]
        rig.open(intake={**cases.intake("alpha", "service"), "sources": [src]}, scope=scope)
        lid, rec = rig.session()
        assert sorted(s.seen) == sorted(files)  # 只发了计划里的那几条 GET
        got = json.loads((rig.ws(lid) / "materials" / "s1" / "responses.json").read_text(encoding="utf-8"))
        assert [(r["item"], r["status"], r["body"]) for r in got["responses"]] == [
            (it["no"], 200, resp[it["no"]]["body"]) for it in plan["items"]
        ]
        snap = json.loads(_artifact(rig, lid, "snapshot:s1"))
        assert snap["form"] == "service" and "probe_plan_sha256" in snap["identity"]
    finally:
        s.close()


# ---------------------------------------------------------------- 抓取计划：纯函数


@pytest.mark.parametrize(
    ("src", "url", "target"),
    [
        (
            {"via": "repo_url", "url": "https://github.com/acme/widget", "ref": "v1.2.0"},
            "https://codeload.github.com/acme/widget/tar.gz/v1.2.0",
            "codeload.github.com:443",
        ),
        (
            {"via": "repo_url", "url": "https://github.com/acme/widget.git/", "ref": "0123abc"},
            "https://codeload.github.com/acme/widget/tar.gz/0123abc",
            "codeload.github.com:443",
        ),
        (
            {"via": "repo_url", "url": "https://gitlab.com/grp/sub/proj", "ref": "release/2.0"},
            "https://gitlab.com/grp/sub/proj/-/archive/release/2.0/proj-release-2.0.tar.gz",
            "gitlab.com:443",
        ),
        (
            {"via": "repo_url", "url": "http://git.lab:3000/a/b", "ref": "main-2026"},
            "http://git.lab:3000/a/b/archive/main-2026.tar.gz",
            "git.lab:3000",
        ),
        (
            {"via": "repo_url", "url": "https://dl.example/pkg/x-1.0.ZIP"},
            "https://dl.example/pkg/x-1.0.ZIP",
            "dl.example:443",
        ),
        (
            {"via": "doc_url", "url": "https://docs.example/guide.md"},
            "https://docs.example/guide.md",
            "docs.example:443",
        ),
    ],
)
def test_fetch_plan_turns_a_registered_source_into_one_download(src, url, target):
    plan = tunshi.fetch_plan({"no": 1, "form": "code", **src})
    assert plan == {"kind": "file", "url": url, "targets": [target]}


@pytest.mark.parametrize(
    "src",
    [
        {"via": "repo_url", "url": "https://github.com/acme/widget"},  # 没写提交或标签
        {"via": "repo_url", "url": "https://github.com/acme/widget", "ref": "../../etc"},
        {"via": "repo_url", "url": "https://github.com/acme/widget", "ref": "v1 --upload-pack=x"},
        {"via": "repo_url", "url": "https://github.com/acme/widget", "ref": "-x"},
        {"via": "repo_url", "url": "https://github.com/acme", "ref": "v1"},
        {"via": "repo_url", "url": "https://user:pw@git.example/a/b", "ref": "v1"},
        {"via": "repo_url", "url": "ssh://git.example/a/b", "ref": "v1"},
        {"via": "repo_url", "url": "file:///etc/passwd"},
        {"via": "doc_url", "url": "https://docs.example:notaport/x"},
        {"via": "service_url", "url": "https://svc.example", "probe_plan": "POST /admin/reset"},
        {"via": "service_url", "url": "https://svc.example", "probe_plan": "GET http://other.example/x"},
        {"via": "service_url", "url": "https://svc.example", "probe_plan": "\n".join(["GET /x"] * 21)},
        {"via": "service_url", "url": "https://svc.example", "probe_plan": "  \n"},
    ],
)
def test_fetch_plan_refuses_what_it_cannot_pin_down(src):
    with pytest.raises(tunshi.BadSource):
        tunshi.fetch_plan({"no": 1, "form": "code", **src})


def test_the_download_program_is_plain_stdlib_python():
    compile(tunshi.FETCH_PY, "fetch.py", "exec")
    assert "subprocess" not in tunshi.FETCH_PY and "os.system" not in tunshi.FETCH_PY


# ---------- 执行层开不了批下来的出站目标（M0 只认本机题目容器：互联网上的主机连不了） ----------

M0 = "M0 只支持本机题目容器作为出站目标：'codeload.github.com' 不是容器"


class M0Hot(HotExec):
    """真的 DockerExecutor（M0）在会话中途对齐到一个互联网主机时的样子：编不了这条授权就抛 ScopeError。"""

    def reconcile(self, sid, spec):
        from paoding_executor.contract import ScopeError

        super().reconcile(sid, spec)  # 记下这次对齐（只在授权范围变了的时候来）
        raise ScopeError(M0)


class M0Launch(LocalExec):
    """起执行容器时范围里已经有它连不了的主机（上一个会话批下来的）：launch 抛 ScopeError。"""

    def __init__(self, *a):
        super().__init__(*a)
        self.launched = 0

    def launch(self, spec, *a, **kw):
        from paoding_executor.contract import ScopeError

        self.launched += 1
        raise ScopeError(M0)


def test_an_approved_target_the_executor_cannot_open_blocks_with_a_way_forward(trig, site):  # noqa: F811
    """cz 2026-11-21 的实战阻断：批准后热对齐抛错曾让会话线程死掉、租约悬到过期（追问冲突“还没有交付”）。
    现在：照实交付 blocked，写明执行层开不了、怎么绕（随题上传），租约按 done 释放，下一个会话能照常派。"""
    rig = trig(cases.recording("alpha", "code"), local_exec=True)
    rig.executor = rig.runner.executor = M0Hot(rig.graph, rig.blobs, rig.cfg.root)
    rig.profile["access_wait_s"] = 15
    rig.open(intake=repo(f"{site.url}/alpha.tar.gz"))
    approve_when_asked(rig)
    lid, rec = rig.session()
    assert rec.release["ok"] and rec.release["outcome"] == "done", rig.stderr(lid)
    assert not rig.graph.state["leases"][lid]["active"]
    d = rig.deliveries()[-1]
    needs = " ".join(d["needs"])
    assert d["outcome"] == "blocked" and "执行层开不了这个出站目标" in needs and M0 in needs
    assert "随题上传" in needs and site.seen == [] and rig.executor.calls == [] and rig.executor.aligned
    (req,) = rig.requests()
    assert req["status"] == "granted"
    # 人照提示追问：交付已在，追问不冲突；下一个会话起得来、照实再说一遍，不再申请
    rig.follow_up("继续")
    lid2, rec2 = rig.session()
    assert rec2.release["ok"] and rig.deliveries()[-1]["outcome"] == "blocked" and len(rig.requests()) == 1


def test_a_driver_session_whose_sandbox_cannot_start_still_delivers(trig, site):  # noqa: F811
    rig = trig(cases.recording("alpha", "code"))
    ex = rig.executor = rig.runner.executor = M0Launch(rig.graph, rig.blobs, rig.cfg.root)
    rig.open(intake=repo(f"{site.url}/alpha.tar.gz"))
    lid = rig.lease("p1")
    rec = rig.runner.run("p1", lid, statement=rig.statement, sandbox_id=None)  # 会话自己起执行容器
    assert ex.launched == 1 and rec.release["ok"] and rec.release["outcome"] == "done", rig.stderr(lid)
    d = rig.deliveries()[-1]
    needs = " ".join(d["needs"])
    assert d["outcome"] == "blocked" and "执行容器起不来" in needs and M0 in needs and "随题上传" in needs
    assert rig.requests() == [] and site.seen == [] and ex.destroyed == []  # 没起来的容器不用销毁


class DownLaunch(LocalExec):
    """起执行容器时容器服务无响应：launch 抛客户端超时（不是“授权编不了”）。"""

    def launch(self, spec, *a, **kw):
        import subprocess

        raise subprocess.TimeoutExpired(["docker", "run", "-d", "--name", "pd-x", "-v", "/Users/x/ws:/workspace"], 120)


def test_a_driver_session_whose_sandbox_hits_an_environment_fault_is_released_as_failed(trig, site):  # noqa: F811
    """环境故障与“授权编不了”不同：容器服务出了故障，不是这道题用不着沙箱。驱动程序的会话也按失败释放
    （授权编不了时它照常跑、照实交付，见上一条），原因留下，不带命令与路径。"""
    rig = trig(cases.recording("alpha", "code"))
    ex = rig.executor = rig.runner.executor = DownLaunch(rig.graph, rig.blobs, rig.cfg.root)
    rig.open(intake=repo(f"{site.url}/alpha.tar.gz"))
    lid = rig.lease("p1")
    rec = rig.runner.run("p1", lid, statement=rig.statement, sandbox_id=None)
    why = "执行容器起不来：建容器并启动超时（等了 120 秒）"
    assert rec.status == "failed(error)" and rec.release["ok"] and rec.release["why"] == why
    lease = rig.graph.state["leases"][lid]
    assert not lease["active"] and lease["outcome"] == "failed"
    assert why in rig.stderr(lid) and "/Users" not in rig.stderr(lid)
    assert rig.deliveries() == [] and lid not in rig.runner.live and site.seen == [] and ex.destroyed == []
