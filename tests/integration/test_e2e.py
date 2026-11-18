"""端到端纵切：开题 → Bootstrap → 判定 → Reason → Explore → 判定 → 关题。全程假 CLI，没有真模型、没有真密钥。

每个组件都是真的那一份：图服务（SQLite 日志 + HTTP 绑定）、司南循环、Adapter 会话运行器（端点代理、工具端点、
假 CLI 进程）、判官运行器（保密库、内建判官）。执行层有两种：进程内替身（任何机器都能跑），与真 Docker
（任务容器、题目环境容器、判官的洁净重放容器）。

人只做一件事：经 HTTP 开题。之后的每一条事件都由组件按自己的令牌写入；网页那一侧（SSE、as_of）全程旁观。
"""
import hashlib
import http.client
import json
import sys
import threading
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "adapter" / "tests"))

from adapter_rig import CFG, FETCH, IMAGE, DockerRig, Rig, docker_ok, graph, upstream  # noqa: E402,F401

from paoding_adapter.proxy import ledger_diff  # noqa: E402
from paoding_executor.contract import ExecResult  # noqa: E402
from paoding_graph.contract import (GraphHttp, GraphService, HttpConfig, intent_status,  # noqa: E402
                                    node_levels)
from paoding_judgebox.contract import JudgeConfig, JudgeRunner, Vault, load_registry  # noqa: E402
from paoding_pd import render  # noqa: E402
from paoding_sinan.contract import Sinan, SinanConfig  # noqa: E402

EXEC, SUBMIT, SHOW = "mcp__paoding__exec", "mcp__paoding__submit", "mcp__paoding__show"
ANSWER = "value-7f3a91"
PID = "p1"


class CannedExec:
    """执行层的进程内替身（SandboxPort）：命令的输出是定好的，登记与出处字段和真执行层同形。"""

    def __init__(self, graph, blobs, answers: dict):
        self.graph, self.blobs, self.answers = graph, blobs, answers
        self.launched, self.destroyed = [], []

    def launch(self, spec, lease_id, mount_workspace=True):
        sid = f"sb-{lease_id}-{len(self.launched)}"
        self.launched.append({"sid": sid, "lease": lease_id, "egress": spec.egress_allow, "mount": mount_workspace})
        return sid

    def destroy(self, sid):
        self.destroyed.append(sid)

    def exec(self, sid, cmd, pid, idem_key, timeout_s=60, cwd="/workspace", register_as="exec"):
        text = next((v for k, v in self.answers.items() if k in cmd), "")
        data = text.encode()
        h = self.blobs.put(data)
        prov = {"sandbox_id": sid, "base": "basic", "baseline_ref": "basic@1", "tool": "shell", "command": cmd,
                "cwd": cwd, "exit_code": 0, "touched": [], "started_at": 1000, "ended_at": 3000, "truncated": False}
        aid = None
        if register_as == "exec":
            out = self.graph.submit("tok-exec", pid, idem_key, [{"op": "register_artifact", "body": {
                "hash": h, "size": len(data), "media_type": "text/plain; charset=utf-8", "class": "exec",
                "exec": prov}}])
            assert out["ok"], out
            aid = out["results"][0]["id"]
        return ExecResult(aid, h, 0, text, False, prov)


class Watcher(threading.Thread):
    """网页那一侧：从开题前就挂在 SSE 上，记下每一帧。"""

    def __init__(self, url, pid):
        super().__init__(daemon=True)
        u = urllib.parse.urlsplit(url)
        self.conn = http.client.HTTPConnection(u.hostname, u.port, timeout=30)
        self.path, self.frames, self.closed = f"/v1/problems/{pid}/stream?after=0", [], threading.Event()

    def run(self):
        self.conn.request("GET", self.path, headers={"Accept": "text/event-stream"})
        resp = self.conn.getresponse()
        f = {}
        while not self.closed.is_set():
            line = resp.readline().decode().rstrip("\n")
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


def http_json(url, path, body=None, token=None):
    req = urllib.request.Request(url + path, data=None if body is None else json.dumps(body).encode(),
                                 method="GET" if body is None else "POST",
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def scripts(rig, host):
    """三个角色各一份脚本。假 CLI 不会想，只会照做；但每一步都走真的代理与真的工具端点。"""
    probe = FETCH.format(host=host, path="status")
    rig.scripts = {}
    rig.cfg.env_for = lambda lease: {"PD_FAKE_SCRIPT": str(rig.scripts[lease["kind"]])}

    def put(role, steps):
        p = rig.tmp / f"e2e-{role}.json"
        p.write_text(json.dumps({"steps": steps, "resume_steps": []}))
        rig.scripts[role] = p

    put("bootstrap", [
        {"tool": EXEC, "input": {"cmd": probe}},
        {"tool": "Write", "input": {"file_path": "probe.sh", "content": probe + "\n"}},
        {"tool": SUBMIT, "input": {"ops": [
            {"op": "add_fact", "tmp_id": "f", "claim_type": "observation", "title": "目标在线并报告 ready",
             "summary": "读 /status 得到 ready", "premises": [], "grounds": ["$r0.artifact"],
             "check": {"judge_id": "replay", "expect": {"stdout_contains": "ready", "exit_code": 0},
                       "spec_path": "probe.sh"}},
            {"op": "request_judge", "target": "f"}], "final": {"outcome": "found"}}}])
    put("reason", [
        {"tool": SHOW, "input": {"list": "all"}},
        {"tool": SUBMIT, "input": {"ops": [
            {"op": "add_intent", "title": "读取 /value 并提交", "summary": "目标在线，直接读取取值",
             "premises": ["$r0.items.0.id"], "risk": "r0", "expected_gain": 0.8,
             "budget_hint": {"usd_milli": 400, "wall_s": 300}}], "final": {"outcome": "found"}}}])
    put("explore", [
        {"tool": EXEC, "input": {"cmd": FETCH.format(host=host, path="value")}},
        {"tool": "Write", "input": {"file_path": "answer.txt", "content": "$r0.output"}},
        {"tool": SUBMIT, "input": {"ops": [{"op": "claim_done", "target": "goal", "candidate_path": "answer.txt"}],
                                   "final": {"outcome": "found"}}}])


def run_chain(rig, host):
    g = rig.graph
    g.tokens.issue({"kind": "judge", "id": "jr1"}, "tok-judge")
    app = GraphHttp(g, rig.blobs, HttpConfig(heartbeat_s=0.2))
    url = app.serve()
    watcher = Watcher(url, PID)
    vault = Vault(rig.tmp / "vault")
    sealed = vault.put("answer", ANSWER.encode())
    statement = "目标服务在 8080 端口。取回 /value 的内容，原样提交。".encode()
    try:
        # —— 人：经 HTTP 开题（与网页、pd 同一条提议通道） ——
        req = urllib.request.Request(url + "/v1/blobs", data=statement, method="PUT", headers={
            "Authorization": "Bearer tok-human", "Content-Type": "application/octet-stream"})
        with urllib.request.urlopen(req, timeout=10) as r:
            h = json.loads(r.read())["hash"]
        opened = http_json(url, "/v1/problems", {"id": PID, "idem_key": "open-e2e", "ops": [
            {"op": "register_artifact", "body": {"hash": h, "size": len(statement), "media_type": "text/plain",
                                                  "class": "input"}},
            {"op": "open_problem", "body": {
                "title": "取回目标上的取值", "origin": {"statement_ref": "$0", "materials": []},
                "goal": {"statement": "取回 /value 的内容并原样提交",
                         "check": {"judge_id": "exact_match", "sealed": [sealed]}, "max_attempts": 3, "accept": "judge"},
                "scope": [{"resource": "net", "pattern": f"{host}:8080", "actions": ["connect"], "risk": "r0"}],
                "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
                "env": {"base": "basic", "baseline_ref": "basic@1"}, "judges": ["exact_match", "replay"]}}]},
            token="tok-human")
        assert opened["ok"], opened
        watcher.start()

        # —— 组件：司南循环 + 判官运行器（单进程部署，判官在每一步之间被驱动） ——
        scripts(rig, host)
        judge = JudgeRunner(JudgeConfig(token="tok-judge", registry=load_registry(), bases=rig.cfg.bases),
                            g, g, rig.blobs, vault, rig.executor)
        sinan = Sinan(SinanConfig(token="tok-sinan"), g, g, rig.blobs, rig.runner)
        verdicts = []
        out = sinan.run(PID, between=lambda: verdicts.extend(judge.tick(PID)))
        watcher.closed.wait(10)
        return {"url": url, "out": out, "verdicts": verdicts, "frames": list(watcher.frames), "sinan": sinan,
                "live": {k: http_json(url, f"/v1/problems/{PID}/{k}") for k in ("status", "budget", "work")},
                "events": http_json(url, f"/v1/problems/{PID}/events?after=0&limit=1000")["events"],
                "at": lambda seq: http_json(url, f"/v1/problems/{PID}/status?as_of={seq}"),
                "close": app.close}
    except BaseException:
        app.close()
        raise


def check_chain(rig, r):
    g, st = rig.graph, rig.graph.state
    p = st["problems"][PID]
    # 1. 走完了，而且是按规定的次序走完的
    assert r["out"]["stop"] == "closed", r["out"]
    assert [s["did"]["kind"] for s in r["out"]["steps"]] == ["bootstrap", "reason", "explore"]
    assert [s["outcome"] for s in r["out"]["steps"]] == ["done", "done", "done"]
    assert [(v["result"], v["status"]) for v in r["verdicts"]] == [("pass", "judged")] * 2
    assert p["closed"] and p["terminal"] == "solved"
    kinds = [e["kind"] for e in r["events"]]
    order = [kinds.index(k) for k in ("open_problem", "add_fact", "add_intent", "close_problem")]
    assert order == sorted(order)
    # 关题后只剩交回：记账、释放，以及在途会话的留档登记
    assert set(kinds[kinds.index("close_problem") + 1:]) <= {"cost", "release", "register_artifact"}
    close = next(e for e in r["events"] if e["kind"] == "close_problem")
    assert close["actor"]["kind"] == "graph" and close["body"]["terminal"] == "solved"   # 没有人、没有 Worker 关题

    # 2. 等级只来自判官：论断与 Goal 都是 E3，支持记录指向 judge 类 Artifact
    lv = node_levels(st, PID)
    [fact] = [f for f in st["facts"].values() if f["problem_id"] == PID]
    [intent] = [i for i in st["intents"].values() if i["problem_id"] == PID]
    assert lv[fact["id"]] == "E3" and lv["goal"] == "E3"
    assert intent["premises"] == [fact["id"]] and intent_status(st, PID, intent["id"]) in ("done", "achieved")
    assert st["artifacts"][fact["grounds"][0]]["class"] == "exec"
    assert st["artifacts"][fact["grounds"][0]]["producer"]["actor"] == "ex1"       # 证据由执行层登记，不由会话
    for v in st["verdicts"]:
        assert [st["artifacts"][a]["class"] for a in v["evidence"]] == ["judge"]
    goal_v = next(v for v in st["verdicts"] if v["target"] == "goal")
    cand = st["artifacts"][goal_v["candidate"]]
    assert cand["class"] == "authored" and rig.blobs.get(cand["hash"]).decode().strip() == ANSWER

    # 3. 身份：每类事件都由该写它的令牌写
    who = {}
    for e in r["events"]:
        who.setdefault(e["kind"], set()).add(e["actor"]["kind"])
    assert who["open_problem"] == {"human"} and who["judge_verdict"] == {"judge"}
    assert who["add_fact"] == who["add_intent"] == who["request_judge"] == {"adapter"}
    assert who["lease"] == {"sinan", "judge"} and who["close_problem"] == {"graph"}

    # 4. 保密库：答案只在候选里出现过，判官输出、日志事件体里都没有
    for a in st["artifacts"].values():
        if a["class"] == "judge":
            assert ANSWER.encode() not in rig.blobs.get(a["hash"])
    assert ANSWER not in json.dumps(r["events"], ensure_ascii=False)

    # 5. 账：三个任务的 token 成本经代理入账，与代理自记逐任务一致；判官成本计入验证池；没有预留悬着
    b = g.budget(PID)
    assert set(b["by_kind"]) == {"bootstrap", "reason", "explore", "judge"}
    assert 0 < b["spent"]["usd_milli"] == rig.proxy.global_spent <= b["cap"]["usd_milli"]
    assert b["reserved"]["usd_milli"] == 0 and ledger_diff(rig.proxy, st) == []
    assert not [l for l in st["leases"].values() if l["active"]]

    # 6. 网页一侧：SSE 帧逐条等于日志；as_of 回放看得到解出之前的图；只读端点与进程内同源
    upto = [e for e in r["events"] if e["seq"] <= close["seq"]]
    assert [(f["id"], f["kind"]) for f in r["frames"]] == [(e["seq"], e["kind"]) for e in upto]
    assert r["frames"][-1]["kind"] == "close_problem"
    assert r["live"]["status"]["problem"]["closed"] and r["live"]["status"]["problem"]["terminal"] == "solved"
    assert r["live"]["work"]["items"] == [] and r["live"]["work"]["as_of"] == st["seq"]
    before = r["at"](goal_v["seq"] - 1)
    assert before["as_of"] == goal_v["seq"] - 1 and not before["problem"]["closed"]
    assert before["problem"]["terminal"] != "solved"

    # 7. 报告是日志的确定性投影
    text = render.report(st, PID, b)
    first = text.splitlines()[0]
    assert first.startswith("[证据] 终态 solved") and "E3" in first and fact["id"] in text

    # 8. 重放：同一日志文件重新打开，状态逐字段相同
    g2 = GraphService(rig.tmp / "g.sqlite", CFG, g.tokens)
    for key in ("problems", "facts", "intents", "verdicts", "requests", "leases", "costs", "artifacts"):
        assert g2.state[key] == st[key], key
    assert node_levels(g2.state, PID) == lv


def test_e2e_fake_cli_with_stub_executor(tmp_path, graph, upstream):  # noqa: F811
    rig = Rig(tmp_path, graph, upstream)
    rig.executor = rig.runner.executor = CannedExec(graph, rig.blobs, {
        "/status": "ready\n", "/value": ANSWER + "\n", "sh /workspace/spec": "ready\n"})
    r = None
    try:
        r = run_chain(rig, "target-a")
        check_chain(rig, r)
        ex = rig.executor
        assert len(ex.launched) == 3 and sorted(ex.destroyed) == sorted(b["sid"] for b in ex.launched)
        assert [b["mount"] for b in ex.launched] == [True, False, True]      # 中间那个是判官的洁净容器
        assert all(b["egress"] for b in ex.launched)                         # r0 规则编进了每个容器
    finally:
        if r:
            r["close"]()
        rig.close()


@pytest.mark.skipif(not docker_ok(), reason="需要 Docker 与本地镜像 python:3.12-slim")
def test_e2e_fake_cli_with_docker(tmp_path, graph, upstream):  # noqa: F811
    """同一条链，执行层换成真的：取值来自题目环境容器，经任务容器的网络取回；论断由洁净容器重放确认。"""
    rig = DockerRig(tmp_path, graph, upstream)
    r = None
    try:
        host = rig.target({"status": "ready", "value": ANSWER})
        r = run_chain(rig, host)
        check_chain(rig, r)
        assert rig.sandboxes() == []                                         # 任务容器与判官容器都已销毁
        st = graph.state
        fact_v = next(v for v in st["verdicts"] if v["target"] != "goal")
        ev = st["artifacts"][fact_v["evidence"][0]]
        assert ev["exec"]["tool"] == "replay" and b"ready" in rig.blobs.get(ev["hash"])
        boxes = {a["exec"]["sandbox_id"] for a in st["artifacts"].values() if a["class"] in ("exec", "judge")
                 and a["exec"]["sandbox_id"] != "builtin"}
        assert len(boxes) == 3                                               # bootstrap、判官重放、explore 各一个
    finally:
        if r:
            r["close"]()
        rig.close()
