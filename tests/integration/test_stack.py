"""全栈端到端：scripts/run.py 的组装根（scripts/stack.py）整套起来，人只经 HTTP 开题，其余全由组件自己走完。

和 test_e2e.py 的区别：那条在单进程里由测试一步步驱动司南与判官（between 回调）；这条是部署形态——
图服务、判官运行器、司南、哮天犬各自一个循环并行跑，执行层是真 Docker，会话是假 CLI 子进程。

    开题 → 司南读到 bootstrap → 租约 → 假 CLI 会话 → add_fact → 判官裁决 → 司南读到 reason → 新租约 → 新会话
    → add_intent → explore 租约 → 会话提交结果 → 判官确认 Goal → 图服务自动关题 → 终态 solved

另一条测 run.py 进程本身：会话卡在半路时 SIGINT，进程要干净退出，不留假 CLI 进程、不留容器，租约记为 failed。
"""
import http.client
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
E2E = ROOT / "scripts" / "e2e"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(E2E))

from drive import ANSWER, call, open_problem, wait_terminal  # noqa: E402
from stack import Stack, StackConfig, docker_available  # noqa: E402

from paoding_graph.contract import node_levels  # noqa: E402

IMAGE = "python:3.12-slim"
PID = "e2e"


def docker_ok() -> bool:
    return docker_available() and subprocess.run(["docker", "image", "inspect", IMAGE],
                                                 capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(not docker_ok(), reason="需要 Docker 与本地镜像 python:3.12-slim")


class Watcher(threading.Thread):
    """网页那一侧：挂在 SSE 上，记下每一帧，直到看见关题。"""

    def __init__(self, url, pid):
        super().__init__(daemon=True)
        u = urllib.parse.urlsplit(url)
        self.conn = http.client.HTTPConnection(u.hostname, u.port, timeout=60)
        self.path, self.frames, self.closed = f"/v1/problems/{pid}/stream?after=0", [], threading.Event()

    def run(self):
        self.conn.request("GET", self.path, headers={"Accept": "text/event-stream"})
        resp = self.conn.getresponse()
        f = {}
        while not self.closed.is_set():
            line = resp.readline().decode()
            if not line:
                return
            line = line.rstrip("\n")
            if line.startswith(":"):
                continue
            if line == "":
                if "data" in f:
                    ev = json.loads(f["data"])
                    self.frames.append({"id": int(f["id"]), **ev})
                    if ev.get("kind") == "close_problem":
                        self.closed.set()
                f = {}
                continue
            k, _, v = line.partition(": ")
            f[k] = v


def config(home: Path, **over) -> StackConfig:
    return StackConfig.load(home, E2E / "config.json", port=0, static_dir=None, poll_s=0.2, dog_interval_s=0.5,
                            **over)


def owned_containers(owner: str) -> list[str]:
    out = subprocess.run(["docker", "ps", "-a", "--filter", f"label=paoding.owner={owner}", "--format",
                          "{{.Names}}"], capture_output=True).stdout.decode().split()
    return sorted(out)


def procs_under(path: Path) -> list[int]:
    """工作目录在 path 之下的进程（假 CLI 的 cwd 是会话的 workspace）。"""
    out = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            cwd = Path(os.readlink(d / "cwd"))
        except OSError:
            continue
        if cwd == path or path in cwd.parents:
            out.append(int(d.name))
    return out


def test_full_stack_solves_a_problem_end_to_end(tmp_path):
    home = tmp_path / "home"
    stack = Stack(config(home))
    url = stack.start()
    try:
        token = (home / "human.token").read_text().strip()
        opened = open_problem(url, token, PID)
        assert opened["ok"], opened
        watcher = Watcher(url, PID)
        watcher.start()
        hz = call(url, "/healthz")                      # 题在跑的时候各组件都报正常
        assert hz["ok"] and hz["status"] == "ok", hz
        assert {"graph", "blobs", "events", "judge", "sinan", "watchdog", "adapter", "executor"} <= set(hz["components"])
        assert all(c["ok"] for c in hz["components"].values()), hz
        final = wait_terminal(url, PID, 120)
        assert watcher.closed.wait(10)
        evs = call(url, f"/v1/problems/{PID}/events?after=0&limit=5000")["events"]
        budget = call(url, f"/v1/problems/{PID}/budget")
        g = stack.graph
        at = lambda seq, view="status": call(url, f"/v1/problems/{PID}/{view}?as_of={seq}")  # noqa: E731

        # —— 终态由图服务写出：solved，关题者是 graph，没有会话或人提交过 close_problem ——
        assert final["problem"]["closed"] and final["problem"]["terminal"] == "solved"
        closes = [e for e in evs if e["kind"] == "close_problem"]
        assert len(closes) == 1 and closes[0]["actor"]["kind"] == "graph" and closes[0]["body"]["terminal"] == "solved"
        close = closes[0]
        # 关题后只剩交回：用量、释放，以及在途会话自己的留档（authored 类；判官可能先于会话收尾一步关题）
        for e in evs:
            if e["seq"] > close["seq"]:
                assert e["kind"] in ("cost", "release") or (
                    e["kind"] == "register_artifact" and e["body"]["class"] == "authored"
                    and e["actor"].get("session")), e

        # —— 事件按规定的次序写入 ——
        def first(ev_kind, **match):
            return next(e["seq"] for e in evs if e["kind"] == ev_kind and all(
                e["body"].get(k) == v for k, v in match.items()))
        fact = next(e for e in evs if e["kind"] == "add_fact")
        fid = f"f_{fact['seq']}"
        rq_fact = next(e for e in evs if e["kind"] == "request_judge" and e["body"]["target"] == fid)
        rq_goal = next(e for e in evs if e["kind"] == "request_judge" and e["body"]["target"] == "goal")
        v_fact = next(e for e in evs if e["kind"] == "judge_verdict" and e["body"]["request"] == f"j_{rq_fact['seq']}")
        v_goal = next(e for e in evs if e["kind"] == "judge_verdict" and e["body"]["request"] == f"j_{rq_goal['seq']}")
        chain = [first("open_problem"), first("lease", kind="bootstrap"), fact["seq"], rq_fact["seq"], v_fact["seq"],
                 first("lease", kind="reason"), first("add_intent"), first("lease", kind="explore"), rq_goal["seq"],
                 v_goal["seq"], close["seq"]]
        assert chain == sorted(chain), chain
        assert v_fact["body"]["result"] == v_goal["body"]["result"] == "pass"
        # 司南在判官裁决落盘之后才开 Reason（判官在途也算判定未决）
        assert v_fact["seq"] < first("lease", kind="reason")

        # —— 身份：每类事件由该写它的组件写 ——
        who: dict[str, set] = {}
        for e in evs:
            who.setdefault(e["kind"], set()).add(e["actor"]["kind"])
        assert who["open_problem"] == {"human"} and who["judge_verdict"] == {"judge"}
        assert who["add_fact"] == who["add_intent"] == who["request_judge"] == {"adapter"}
        assert who["lease"] == {"sinan", "judge"} and who["close_problem"] == {"graph"}

        # —— 等级从 E0 升到 E3：论断与 Goal 都只因判官的裁决而升 ——
        def fact_level(seq):
            return next(f["level"] for f in at(seq)["facts"] if f["id"] == fid)
        assert fact_level(fact["seq"]) == "E0" and fact_level(v_fact["seq"] - 1) == "E0"
        assert fact_level(v_fact["seq"]) == "E3"
        assert at(first("open_problem"))["goal"]["predicate"]["level"] == "E0"
        assert at(v_goal["seq"] - 1)["goal"]["predicate"]["level"] == "E0"
        assert at(v_goal["seq"])["goal"]["predicate"]["level"] == "E3"
        assert node_levels(g.state, PID) == {**node_levels(g.state, PID), fid: "E3", "goal": "E3"}

        # —— 预算：每个租约在领时预留、释放后归零；花费 = cost 事件之和；没有悬着的预留 ——
        leases = [e for e in evs if e["kind"] == "lease"]
        assert len(leases) == 5                                   # bootstrap、reason、explore + 两次判官
        for e in leases:
            reserved = at(e["seq"], "budget")["reserved"]["usd_milli"]
            assert reserved >= e["body"]["reserve"]["usd_milli"] > 0, (e["body"], reserved)
            rel = next(r for r in evs if r["kind"] == "release" and r["body"]["lease"] == f"l_{e['seq']}")
            assert rel["seq"] > e["seq"]
        assert budget["reserved"]["usd_milli"] == 0
        assert budget["spent"]["usd_milli"] == sum(e["body"]["usd_milli"] for e in evs if e["kind"] == "cost") > 0
        assert set(budget["by_kind"]) == {"bootstrap", "reason", "explore", "judge"}
        assert stack.proxy.global_spent == budget["spent"]["usd_milli"] - budget["by_kind"]["judge"]["usd_milli"]
        assert not [l for l in g.state["leases"].values() if l["active"]]

        # —— 候选是会话写下的答案（判官按公开摘要比对） ——
        goal_v = next(v for v in g.state["verdicts"] if v["target"] == "goal")
        assert stack.blobs.get(g.state["artifacts"][goal_v["candidate"]]["hash"]).strip() == ANSWER


        # —— 网页一侧：SSE 帧逐条等于日志 ——
        upto = [e for e in evs if e["seq"] <= close["seq"]]
        assert [(f["id"], f["kind"]) for f in watcher.frames][:len(upto)] == [(e["seq"], e["kind"]) for e in upto]

        stack.stop()
        # —— 停机之后：没有在途会话、没有本进程起的容器 ——
        assert stack.runner.live == {} and owned_containers(stack.executor.owner) == []
        assert procs_under(home / "sessions") == []

        # —— 同一数据目录再起一套（进程重启）：端点代理的累计花费从账本恢复，不归零（审计 P1-1） ——
        again = Stack(config(home, executor="none"))
        try:
            assert again.proxy.global_spent == budget["spent"]["usd_milli"] > 0
            assert again.proxy.problem_spent == {PID: budget["spent"]["usd_milli"]}
        finally:
            again.stop()
    finally:
        stack.stop()


def test_run_py_exits_cleanly_with_a_session_in_flight(tmp_path):
    """Bootstrap 会话卡住时按 Ctrl+C：假 CLI 进程树被收掉、执行容器销毁、租约以 failed 释放，进程退出码 0。"""
    home = tmp_path / "home"
    home.mkdir()
    hang = tmp_path / "hang.json"
    hang.write_text(json.dumps({"steps": [{"tool": "mcp__paoding__exec", "input": {"cmd": "echo hi"}},
                                          {"hang": 300}], "resume_steps": []}))
    cfg = json.loads((E2E / "config.json").read_text())
    cfg["backend"]["scripts"] = {"bootstrap": str(hang)}
    (home / "config.json").write_text(json.dumps(cfg))
    ready = tmp_path / "ready"
    proc = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "run.py"), "--home", str(home), "--port", "0",
                             "--no-static", "--ready-file", str(ready)],
                            stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
    lines: list[str] = []
    threading.Thread(target=lambda: lines.extend(proc.stderr), daemon=True).start()
    try:
        for _ in range(100):
            if ready.exists() and ready.read_text().strip():
                break
            time.sleep(0.1)
        url = ready.read_text().strip()
        token = (home / "human.token").read_text().strip()
        assert open_problem(url, token, PID)["ok"]
        for _ in range(200):                                   # 等会话真的卡在半路：exec 已落盘
            evs = call(url, f"/v1/problems/{PID}/events?after=0&limit=500")["events"]
            if any(e["kind"] == "register_artifact" and e["actor"]["kind"] == "executor" for e in evs):
                break
            time.sleep(0.1)
        else:
            pytest.fail("会话没走到 exec：\n" + "".join(lines))
        assert procs_under(home / "sessions"), "假 CLI 应该还在跑"
        t0 = time.monotonic()
        proc.send_signal(signal.SIGINT)
        assert proc.wait(30) == 0, "".join(lines)
        assert time.monotonic() - t0 < 20
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    time.sleep(0.2)
    log = "".join(lines)
    assert procs_under(home / "sessions") == [], log
    leftover = subprocess.run(["docker", "ps", "-a", "--filter", "label=paoding.lease", "--format",
                               "{{.Names}} {{.Label \"paoding.owner\"}}"], capture_output=True).stdout.decode()
    assert f":{proc.pid}:" not in leftover, leftover               # 属主是 run.py 进程的容器一个不剩
    # 日志结构化：stderr 一行一个 JSON 对象（时间、级别、组件名、消息），文件里是同样的行
    recs = [json.loads(line) for line in log.strip().splitlines()]
    for r in recs:
        assert {"ts", "level", "component", "msg"} <= set(r), r
        assert r["component"] in ("graph", "judge", "sinan", "adapter", "watchdog", "stack"), r
        assert r["level"] in ("info", "warning", "error"), r
    assert any("已停" in r["msg"] for r in recs)
    lease_lines = [r for r in recs if r["component"] == "graph" and r.get("kind") == "lease"]
    assert lease_lines and all(r["problem_id"] and r["lease_id"] and r["seq"] for r in lease_lines), lease_lines
    filed = [json.loads(line) for line in (home / "logs" / "stack.log").read_text().splitlines()]
    assert [r["msg"] for r in filed] == [r["msg"] for r in recs if r["msg"] in {f["msg"] for f in filed}]
    assert any("已停" in r["msg"] for r in filed)

    # 重启读回同一份日志：租约以 failed 释放（停机不是花超），没有悬着的租约
    from paoding_graph.contract import Config, GraphService, TokenRegistry
    st = GraphService(home / "g.sqlite", Config(), TokenRegistry()).state
    [boot] = [l for l in st["leases"].values() if l["kind"] == "bootstrap"]
    assert not boot["active"] and boot["outcome"] == "failed"
    assert {r["lease_id"] for r in lease_lines} == set(st["leases"])    # 日志里的租约 id 就是图里的租约 id
