"""图服务：整批原子、批内引用、幂等、自动追加事件、崩溃恢复（3.1.5 的 2）。"""
import hashlib
import os
import signal
import subprocess
import sys
import textwrap

from conftest import CFG, EXECUTOR, HUMAN

from paoding_graph.service import GraphService
from paoding_graph.tokens import TokenRegistry


def _svc(path, clock=None):
    reg = TokenRegistry()
    reg.issue(HUMAN, "tok-human")
    reg.issue(EXECUTOR, "tok-exec")
    reg.issue({"kind": "judge", "id": "jr1"}, "tok-judge")
    reg.issue({"kind": "sinan", "id": "sn1"}, "tok-sinan")
    t = [1000]

    def tick():
        t[0] += 1
        return t[0]
    return GraphService(path, CFG, reg, clock or tick)


def _art(content, cls="input"):
    return {"op": "register_artifact", "body": {"hash": hashlib.sha256(content).hexdigest(), "size": len(content),
                                                 "media_type": "text/plain", "class": cls}}


OPEN = {"op": "open_problem", "body": {
    "title": "t", "origin": {"statement_ref": "$0", "materials": []},
    "goal": {"statement": "g", "check": {"judge_id": "exact_match"}, "max_attempts": 3, "accept": "judge"},
    "scope": [{"resource": "target", "pattern": "*", "actions": ["read"], "risk": "r0"}],
    "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
    "env": {"base": "basic", "baseline_ref": "base@1"}, "judges": ["exact_match", "replay"]}}


def test_batch_with_local_refs(tmp_path):
    s = _svc(tmp_path / "g.sqlite")
    out = s.submit("tok-human", "p1", "open-1", [_art(b"stmt"), OPEN])
    assert out["ok"] and out["results"][0]["id"] == "a_1"
    assert s.state["problems"]["p1"]["origin"]["statement_ref"] == "a_1"


def test_batch_atomic(tmp_path):
    s = _svc(tmp_path / "g.sqlite")
    s.submit("tok-human", "p1", "open-1", [_art(b"stmt"), OPEN])
    n = len(list(s.log.events()))
    out = s.submit("tok-human", "p1", "h", [{"op": "hint", "body": {"text": "a"}},
                                            {"op": "hint", "body": {"close": "h_999"}}])
    assert not out["ok"] and out["results"][1]["code"] == "unknown_ref"
    assert len(list(s.log.events())) == n
    assert s.state["hints"] == {}
    again = s.submit("tok-human", "p1", "h", [{"op": "hint", "body": {"text": "a"}}])
    assert again == out                                    # 同一 idem_key 返回首次结果


def test_idempotent_and_forged_token(tmp_path):
    s = _svc(tmp_path / "g.sqlite")
    a = s.submit("tok-human", "p1", "open-1", [_art(b"stmt"), OPEN])
    b = s.submit("tok-human", "p1", "open-1", [_art(b"stmt"), OPEN])
    assert a == b and len(list(s.log.events())) == 2
    bad = s.submit("forged", "p1", "x", [_art(b"zz", "exec")])
    assert bad["results"][0]["code"] == "forbidden_op"


def test_auto_close_followup(tmp_path):
    s = _svc(tmp_path / "g.sqlite")
    s.submit("tok-human", "p1", "open-1", [_art(b"stmt"), OPEN])
    s.submit("tok-human", "p1", "cand", [{"op": "register_artifact", "body": {
        "hash": hashlib.sha256(b"c").hexdigest(), "size": 1, "media_type": "x", "class": "input"}},
        {"op": "request_judge", "body": {"target": "goal", "judge_id": "exact_match", "candidate": "$0"}}])
    rid = [r for r in s.state["requests"]][0]
    ex = {"sandbox_id": "s", "base": "b", "baseline_ref": "r", "tool": "shell", "command": "x", "cwd": "/",
          "exit_code": 0, "touched": [], "started_at": 1, "ended_at": 2, "truncated": False}
    out = s.submit("tok-judge", "p1", "v1", [
        {"op": "register_artifact", "body": {"hash": hashlib.sha256(b"v").hexdigest(), "size": 1,
                                             "media_type": "x", "class": "judge", "exec": ex}},
        {"op": "judge_verdict", "body": {"request": rid, "result": "pass", "version": "1", "evidence": ["$0"]}}])
    assert out["ok"]
    p = s.state["problems"]["p1"]
    assert p["closed"] and p["terminal"] == "solved"
    kinds = [e["kind"] for e in s.log.events("p1")]
    assert kinds[-2:] == ["judge_verdict", "close_problem"]
    s.log.verify("p1")


CHILD = textwrap.dedent("""
    import os, signal, sys
    sys.path.insert(0, {tests!r})
    from test_service import _svc, _art, OPEN
    mode = sys.argv[2]
    calls = [0]
    def clock():
        calls[0] += 1
        if mode == "mid" and calls[0] == 2:          # 批处理进行中被杀
            os.kill(os.getpid(), signal.SIGKILL)
        return 1000 + calls[0]
    s = _svc(sys.argv[1], clock)
    s.submit("tok-human", "p1", "open-1", [_art(b"stmt"), OPEN])
    if mode == "after":                              # 已提交、回应前被杀
        os.kill(os.getpid(), signal.SIGKILL)
""")


def _child(tmp_path, mode):
    script = tmp_path / "child.py"
    script.write_text(CHILD.format(tests=os.path.dirname(__file__)))
    p = subprocess.run([sys.executable, str(script), str(tmp_path / "g.sqlite"), mode])
    assert p.returncode == -signal.SIGKILL


def test_crash_mid_batch_exactly_once(tmp_path):
    """3.1.5 的 2：提议处理中 kill -9，重启后客户端重试，结果恰好一次。"""
    _child(tmp_path, "mid")
    s = _svc(tmp_path / "g.sqlite")
    assert list(s.log.events()) == []                       # 未提交的半批不留痕
    out = s.submit("tok-human", "p1", "open-1", [_art(b"stmt"), OPEN])
    assert out["ok"] and len(list(s.log.events())) == 2


def test_crash_after_commit_exactly_once(tmp_path):
    _child(tmp_path, "after")
    s = _svc(tmp_path / "g.sqlite")
    assert s.state["problems"]["p1"]["origin"]["statement_ref"] == "a_1"   # 重启即重放
    out = s.submit("tok-human", "p1", "open-1", [_art(b"stmt"), OPEN])
    assert out["ok"] and out["results"][0]["id"] == "a_1"
    assert len(list(s.log.events())) == 2
