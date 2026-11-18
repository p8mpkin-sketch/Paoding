"""审计 P1-3：司南并发。真的会话运行器 + 假 CLI 子进程 + 真图服务（执行层用替身，不需要 Docker）。

Reason 写下两个 Intent 之后，司南把两个 Explore 会话同时开出去：两个假 CLI 进程同时活着、
两个租约同时在途、各用各的工作区与任务令牌；同一 Intent 上不会有第二个会话。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "adapter" / "tests"))

from adapter_rig import graph, rig, upstream  # noqa: E402,F401（fixture）

from paoding_sinan.contract import Sinan, SinanConfig  # noqa: E402

SHOW = "mcp__paoding__show"
SUBMIT = "mcp__paoding__submit"
HANG_S = 1.5


def intent(n):
    return {"op": "add_intent", "title": f"路线 {n}", "summary": "", "premises": [], "risk": "r0",
            "expected_gain": 0.5, "budget_hint": {"usd_milli": 200, "wall_s": 120}}


def prepare(rig, tmp_path, **cfg):
    scripts = {}

    def put(role, steps):
        scripts[role] = rig.script(steps)
    put("bootstrap", [{"tool": SUBMIT, "input": {"ops": [], "final": {"outcome": "nothing"}}}])
    put("reason", [{"tool": SUBMIT, "input": {"ops": [intent(0), intent(1)], "final": {"outcome": "found"}}}])
    put("explore", [{"tool": "Write", "input": {"file_path": "note.txt", "content": "来过"}},
                    {"hang": HANG_S},
                    {"tool": SUBMIT, "input": {"ops": [], "final": {"outcome": "nothing"}}}])
    rig.cfg.extra_env = {}
    rig.cfg.env_for = lambda lease: {"PD_FAKE_SCRIPT": str(scripts[lease["kind"]])}
    real = rig.runner.run
    rig.runner.run = lambda pid, lid, **kw: real(pid, lid, sandbox_id="sb-test", **kw)   # 替身执行层：不起容器
    return Sinan(SinanConfig(token="tok-sinan", **cfg), rig.graph, rig.graph, rig.blobs, rig.runner)


def alive(rig, lease_id):
    proc = (rig.runner.live.get(lease_id) or {}).get("proc")
    return proc is not None and proc.poll() is None


def test_two_explore_sessions_run_in_parallel(rig, tmp_path):
    g = rig.graph
    sinan = prepare(rig, tmp_path)
    assert sinan.step("p1")["did"] == {"kind": "bootstrap"}
    assert sinan.step("p1")["did"] == {"kind": "reason"}
    intents = sorted(g.state["intents"])
    assert len(intents) == 2

    t0 = time.monotonic()
    a, b = sinan.dispatch("p1"), sinan.dispatch("p1")
    assert {a["started"]["target"], b["started"]["target"]} == set(intents)
    assert sinan.dispatch("p1") == {"wait": "in_flight"}                   # 没有第三项：同一 Intent 不开第二个会话
    deadline = time.monotonic() + 10
    while not (alive(rig, a["lease"]) and alive(rig, b["lease"])) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert alive(rig, a["lease"]) and alive(rig, b["lease"])              # 两个假 CLI 进程同时活着
    assert rig.runner.live[a["lease"]]["proc"].pid != rig.runner.live[b["lease"]]["proc"].pid
    assert sorted(l["target"] for l in g.state["leases"].values() if l["active"]) == intents

    done = []
    while len(done) < 2:
        done += sinan.collect(20)
    elapsed = time.monotonic() - t0
    assert {(d["status"], d["outcome"]) for d in done} == {("released", "nothing")}
    assert elapsed < 2 * HANG_S, f"两个各睡 {HANG_S}s 的会话用了 {elapsed:.2f}s：不是并行"

    # 两个租约同时在途：两条 lease 都排在任何一条 release 之前
    mine = (a["lease"], b["lease"])
    evs = [e["kind"] for e in g.events("p1", 0, 1000) if e["kind"] in ("lease", "release")
           and e["body"].get("lease", f"l_{e['seq']}") in mine]
    assert evs == ["lease", "lease", "release", "release"]
    # 各用各的工作区，各记各的账
    for lid in mine:
        assert (rig.tmp / "sessions" / lid / "workspace" / "note.txt").read_text() == "来过"
    by_task = {}
    for c in g.state["costs"]:
        by_task[c["task_id"]] = by_task.get(c["task_id"], 0) + c["usd_milli"]
    assert by_task[a["lease"]] > 0 and by_task[b["lease"]] > 0
    assert rig.runner.live == {} and sinan.in_flight() == []


def test_serial_when_capped_at_one(rig, tmp_path):
    """max_sessions=1：第二个 Explore 要等第一个收回才开（修复前的行为）。"""
    sinan = prepare(rig, tmp_path, max_sessions=1)
    sinan.step("p1"); sinan.step("p1")
    a = sinan.dispatch("p1")
    assert "started" in a and sinan.dispatch("p1") == {"wait": "capacity"}
    assert sinan.collect(20)[0]["lease"] == a["lease"]
    assert sinan.step("p1")["did"] == {"kind": "reason"}                  # 一个 Explore 结束后先轮到 Reason，与串行时相同
