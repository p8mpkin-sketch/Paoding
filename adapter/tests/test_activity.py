"""会话的实时活动（开放道进度可见性）：stream-json 折成条目、在途可读、结束后从会话目录读、凭据遮盖。

集成部分沿用 test_solve 的台子：假 CLI 走真的代理、真的工具端点、真的图服务。
"""

import threading
import time

from adapter_rig import graph, upstream  # noqa: F401  fixture
from test_solve import DELIVER, EXEC, STATEMENT, TOKEN, lease_solve, make

from paoding_adapter import activity as act
from paoding_adapter import creds


def test_fold_reads_calls_sayings_results_and_the_end():
    ev = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "先跑一下复现脚本。"},
                {"type": "tool_use", "id": "t1", "name": "mcp__paoding__exec", "input": {"cmd": "python repro.py"}},
            ]
        },
    }
    assert act.fold(ev, 1) == [
        {"round": 1, "kind": "say", "text": "先跑一下复现脚本。"},
        {"round": 1, "kind": "call", "tool": "exec", "gist": "python repro.py", "id": "t1"},
    ]
    res = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "is_error": True,
                    "content": [{"type": "text", "text": "Traceback"}],
                }
            ]
        },
    }
    assert act.fold(res, 1) == [{"round": 1, "kind": "result", "id": "t1", "ok": False, "gist": "Traceback"}]
    end = act.fold({"type": "result", "subtype": "success", "is_error": False, "num_turns": 3}, 2)
    assert end == [{"round": 2, "kind": "end", "ok": True, "turns": 3, "gist": "success"}]
    assert act.fold({"type": "system", "subtype": "init"}, 1) == []
    assert act.gist_of({"file_path": "NOTES.md", "content": "x" * 999}) == "NOTES.md"
    assert len(act.gist_of({"weird": "y" * 999})) == act.GIST


def test_view_gives_the_pending_call_and_the_last_saying_whatever_the_cursor():
    xs = [
        {"n": 1, "kind": "say", "text": "计划"},
        {"n": 2, "kind": "call", "tool": "exec", "id": "t1", "gist": "ls"},
        {"n": 3, "kind": "result", "id": "t1", "ok": True, "gist": "a"},
        {"n": 4, "kind": "say", "text": "再看一个"},
        {"n": 5, "kind": "call", "tool": "show", "id": "t2", "gist": "a_3"},
    ]
    v = act.view(xs, after=4)
    assert [x["n"] for x in v["items"]] == [5] and v["next_after"] == 5 and v["total"] == 5 and v["calls"] == 2
    assert v["now"]["id"] == "t2" and v["last_say"]["text"] == "再看一个"
    done = act.view([*xs, {"n": 6, "kind": "end", "ok": False}], after=6)
    assert done["items"] == [] and done["next_after"] == 6 and done["now"] is None  # 本轮已结束：没有“正在做”


def test_log_masks_credentials_from_the_statement(tmp_path):
    log = act.ActivityLog(tmp_path, creds.found(STATEMENT))
    log.feed(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": f"用 {TOKEN} 登录"},
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Bash",
                        "input": {"command": f"curl -H 'Authorization: {TOKEN}'"},
                    },
                ]
            },
        },
        1,
    )
    on_disk = (tmp_path / act.FILE).read_text(encoding="utf-8")
    assert TOKEN not in on_disk and TOKEN not in str(log.snapshot())
    assert creds.MASK in on_disk


def test_solve_session_activity_is_readable_live_and_after_it_ends(tmp_path, graph, upstream):  # noqa: F811
    rig = make(tmp_path, graph, upstream)
    try:
        lid = lease_solve(graph)
        rig.script(
            [
                {"tool": EXEC, "input": {"cmd": "python -c 'print(6*7)'"}, "say": f"先算一下，令牌 {TOKEN} 先不用。"},
                {"hang": 1.5},
                {"tool": DELIVER, "input": {"outcome": "answered", "answer": "42"}, "say": "交付。"},
            ]
        )
        assert rig.runner.activity(lid) is None  # 还没起来
        out = {}
        th = threading.Thread(target=lambda: out.setdefault("rec", rig.run(lid)))
        th.start()
        seen = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and th.is_alive():
            a = rig.runner.activity(lid)
            if a and a["live"] and a["calls"] >= 1 and any(x["kind"] == "result" for x in a["items"]):
                seen = a
                break
            time.sleep(0.05)
        th.join(timeout=30)
        assert seen is not None, "在途时读不到活动"
        assert seen["role"] == "solve" and seen["status"] == "running" and seen["rounds"] == 1
        assert [x["kind"] for x in seen["items"]][:3] == ["say", "call", "result"]
        assert seen["items"][1]["tool"] == "exec" and "6*7" in seen["items"][1]["gist"]
        assert TOKEN not in str(seen) and creds.MASK in seen["last_say"]["text"]
        assert seen["spent_usd_milli"] > 0  # 端点代理给这个任务令牌记的账

        rec = out["rec"]
        assert rec.release["outcome"] == "done"
        end = rig.runner.activity(lid)  # 结束后从会话目录读
        assert end is not None and end["live"] is False and end["status"] == "released"
        kinds = [x["kind"] for x in end["items"]]
        assert kinds.count("call") == 2 and kinds[-1] == "end" and end["now"] is None
        assert end["last_say"]["text"] == "交付。" and end["spent_usd_milli"] >= seen["spent_usd_milli"]
        tail = rig.runner.activity(lid, after=end["next_after"])
        assert tail["items"] == [] and tail["total"] == end["total"]
        assert TOKEN not in (tmp_path / "sessions" / lid / act.FILE).read_text(encoding="utf-8")
    finally:
        rig.close()
