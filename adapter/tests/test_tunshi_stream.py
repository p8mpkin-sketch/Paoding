"""驱动程序的模型调用是流式的（docs/design/fenjue/13-kernel.md §3.2）：首字节不用等整段生成完，
时限从“等整段”换成“流上多久没有字节”与“一次调用总共多久”；每次调用的用时、重试、截断记在工作区的流水里。

前半是驱动程序直接对假上游（不经代理）：流怎么拼、各种没收完怎么归类。后半走整条链（真代理、真图服务）：
流水与汇总、思考块留在工作区而不进事件流、静默超时之后重试。
"""

from __future__ import annotations

import json
import re
import socket
import sys
import time
from pathlib import Path

import pytest
from adapter_rig import FakeUpstream
from tunshi_rig import cases, engine_gongfa, fixture_tar, trig  # noqa: F401

from paoding_adapter import tunshi_cli
from paoding_adapter.openai_compat import PING_EVERY_S, StreamTranslator
from paoding_adapter.tunshi_cli import Assembly, StreamFailed, stream_post, summarize

ROOT = Path(__file__).resolve().parents[2]
UPLOAD = [{"no": 1, "form": "code", "via": "upload", "artifact": "$material"}]
READ = "read:s1:README.md:1-14:H1:1"
BODY = {"model": "m", "max_tokens": 100, "messages": [{"role": "user", "content": "x"}], "stream": True}


@pytest.fixture
def upstream():
    made: list[FakeUpstream] = []

    def make(said: dict) -> str:
        up = FakeUpstream(reply=lambda body: said)
        made.append(up)
        return up.url + "/v1/messages"

    yield make
    for up in made:
        up.close()


def opened(trig):  # noqa: F811
    rig = trig(cases.recording("alpha", "code"))
    rig.open(intake={**cases.intake("alpha", "code"), "sources": UPLOAD}, material=fixture_tar("alpha"))
    return rig


def jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------- 流怎么拼


def test_a_stream_is_assembled_into_the_same_shape_as_a_whole_reply(upstream):
    said = {
        "content": [{"type": "thinking", "thinking": "先想一想再写"}, {"type": "text", "text": '{"a": 1}'}],
        "usage": {"input_tokens": 7, "cache_read_input_tokens": 3, "output_tokens": 42},
        "model": "claude-x",
        "pings": True,
    }
    status, out, timing = stream_post(upstream(said), BODY, {}, 5, 10)
    assert status == 200 and out["model"] == "claude-x" and out["stop_reason"] == "end_turn"
    assert out["content"] == said["content"]  # 增量拼回原样，块的顺序不变
    assert out["usage"] == {"input_tokens": 7, "cache_read_input_tokens": 3, "output_tokens": 42}  # 输出取累计的那个
    assert 0 <= timing["first_byte_s"] <= timing["elapsed_s"]


def test_usage_and_blocks_from_endpoints_that_place_them_differently():
    asm = Assembly()
    asm.take({"type": "message_start", "message": {"model": "m", "usage": {"input_tokens": 9, "output_tokens": None}}})
    asm.take({"type": "ping"})
    # 没有 content_block_start 就来增量：按增量的类型现开一块
    asm.take({"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "嗯"}})
    asm.take({"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "s"}})
    asm.take({"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "{}"}})
    asm.take({"type": "content_block_start", "index": 2, "content_block": {"type": "redacted_thinking", "data": "x"}})
    asm.take({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{"}})
    asm.take("不是对象")
    assert not asm.complete
    # 用量全在 message_delta 里，值为 null 的不覆盖已有的数
    asm.take({"type": "message_delta", "delta": {"stop_reason": "max_tokens"}, "usage": {"output_tokens": 5}})
    asm.take({"type": "message_delta", "delta": {}, "usage": {"input_tokens": None}})
    assert asm.complete and not asm.done  # 有停止原因就算收完，哪怕没有 message_stop
    m = asm.message()
    assert m["usage"] == {"input_tokens": 9, "output_tokens": 5} and m["stop_reason"] == "max_tokens"
    assert [b["type"] for b in m["content"]] == ["thinking", "text", "redacted_thinking"]
    assert m["content"][0]["thinking"] == "嗯" and m["content"][1]["text"] == "{}"


def test_an_endpoint_that_ignores_stream_or_omits_message_stop_still_works(upstream):
    status, out, _ = stream_post(upstream({"text": "{}", "as_json": True}), BODY, {}, 5, 10)
    assert status == 200 and out["content"] == [{"type": "text", "text": "{}"}] and out["stop_reason"] == "end_turn"
    status, out, _ = stream_post(upstream({"text": "{}", "no_stop_event": True}), BODY, {}, 5, 10)
    assert status == 200 and out["content"][0]["text"] == "{}" and out["stop_reason"] == "end_turn"


def test_an_error_status_comes_back_with_its_body(upstream):
    said = {"status": 529, "body": {"type": "error", "error": {"type": "overloaded_error"}}}
    status, out, timing = stream_post(upstream(said), BODY, {}, 5, 10)
    assert status == 529 and out["error"]["type"] == "overloaded_error" and "elapsed_s" in timing


# ---------------------------------------------------------------- 时限：静默与总时限各管各的


def test_slow_generation_is_not_a_timeout_as_long_as_bytes_keep_coming(upstream):
    """这次改造要治的就是它：生成得慢、整段要很久，但流上一直有字节。总用时超过静默时限也照样收完。"""
    t0 = time.monotonic()
    status, out, timing = stream_post(upstream({"text": "x" * 30, "drip_s": 0.25}), BODY, {}, 0.6, 30)
    assert status == 200 and out["content"][0]["text"] == "x" * 30
    assert time.monotonic() - t0 > 0.6 and timing["elapsed_s"] > 0.6


@pytest.mark.parametrize(("said", "where"), [({"stall_s": 3}, "等响应头"), ({"gap_s": 3}, "流上")])
def test_silence_longer_than_the_idle_limit_gives_up_this_attempt(upstream, said, where):
    t0 = time.monotonic()
    with pytest.raises(StreamFailed) as e:
        stream_post(upstream(said), BODY, {}, 0.5, 30)
    assert e.value.kind == "idle" and where in e.value.detail and "0.5 秒" in e.value.detail
    assert time.monotonic() - t0 < 2.5  # 到点就放手，不等上游
    assert tunshi_cli.is_timeout(0, str(e.value))


def test_a_trickle_that_never_finishes_hits_the_total_limit(upstream):
    """每次等字节都没超过静默时限，但永远收不完：总时限到点把连接关掉。"""
    t0 = time.monotonic()
    with pytest.raises(StreamFailed) as e:
        stream_post(upstream({"text": "x" * 30, "drip_s": 0.4}), BODY, {}, 5, 1.0)
    assert e.value.kind == "deadline" and "总时限 1 秒" in e.value.detail and time.monotonic() - t0 < 3
    assert tunshi_cli.is_timeout(0, str(e.value))


def test_a_stream_that_breaks_or_reports_an_error_is_not_taken_as_an_answer(upstream):
    with pytest.raises(StreamFailed) as e:
        stream_post(upstream({"text": '{"a": 1}', "cut": True}), BODY, {}, 5, 10)
    assert e.value.kind == "cut" and not tunshi_cli.is_timeout(0, str(e.value))  # 半截输出不当结果
    with pytest.raises(StreamFailed) as e:
        stream_post(upstream({"text": "{}", "stream_error": "overloaded_error"}), BODY, {}, 5, 10)
    assert e.value.kind == "stream_error" and e.value.detail == "overloaded_error"


def test_a_proxy_that_cannot_be_reached_is_a_connect_failure():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # 没有人在听的端口
    with pytest.raises(StreamFailed) as e:
        stream_post(f"http://127.0.0.1:{port}/v1/messages", BODY, {}, 5, 10)
    assert e.value.kind == "connect"


def test_what_counts_as_an_upstream_timeout():
    yes = [(504, ""), (502, "upstream_error:TimeoutError: The read operation timed out"), (0, "idle: 流上超过")]
    no = [(502, "upstream_error:ConnectionRefusedError: x"), (529, "overloaded_error"), (0, "cut: 流断了")]
    assert all(tunshi_cli.is_timeout(s, w) for s, w in yes) and not any(tunshi_cli.is_timeout(s, w) for s, w in no)


def test_the_drivers_idle_limit_is_always_the_one_that_fires_first():
    """端点代理等上游的时限写在 proxy.py 里（体质文件，这里不改）。驱动的静默时限连同配置能给的最大值都必须比它短：
    先到的总是驱动这一条，流水里量到的就是真正起作用的那个。谁改了代理的数，这条测试会叫。"""
    src = (ROOT / "adapter/src/paoding_adapter/proxy.py").read_text(encoding="utf-8")
    waits = {int(x) for x in re.findall(r"HTTPS?Connection\([^)]*timeout=(\d+)", src)}
    assert waits == {600}
    assert tunshi_cli.MODEL_IDLE_S < tunshi_cli.MODEL_IDLE_MAX_S < min(waits)
    dan = tunshi_cli.ModelDan("http://x", "t", "f", {}, "m", tunshi_cli.Events("s"), idle_s=9999, call_s=1)
    assert dan.idle_s == tunshi_cli.MODEL_IDLE_MAX_S and dan.call_s >= dan.idle_s  # 给大了也压回来
    sys.path.insert(0, str(ROOT / "scripts"))
    from stack import analysis_config

    cfg = analysis_config({"enabled": True})
    assert (cfg["model_idle_s"], cfg["model_call_s"]) == (tunshi_cli.MODEL_IDLE_S, tunshi_cli.MODEL_CALL_S)
    for bad in ({"model_idle_s": 600}, {"model_idle_s": 5}, {"model_idle_s": True}, {"model_call_s": 30}):
        with pytest.raises(ValueError):
            analysis_config(bad)
    with pytest.raises(ValueError):
        analysis_config({"model_idle_s": 400, "model_call_s": 300})  # 总时限不能比静默时限还短


def test_an_openai_style_upstream_that_is_busy_reasoning_is_not_silent():
    """推理模型先流一长段 reasoning，兼容层不转它；下游却要凭“流上有没有字节”判断上游挂没挂住，
    所以隔一会儿发个 ping。"""
    now = [0.0]
    tr = StreamTranslator("m", clock=lambda: now[0])
    think = b'data: {"choices":[{"delta":{"reasoning_content":"..."}}]}\n\n'
    assert b"message_start" in tr.feed(think)
    assert tr.feed(think) == b""  # 刚有过输出：不刷屏
    now[0] += PING_EVERY_S
    assert tr.feed(think) == b'event: ping\ndata: {"type": "ping"}\n\n'
    assert tr.feed(think) == b""
    now[0] += PING_EVERY_S
    assert tr.feed(b'data: {"choices":[{"delta":{"reasoning') == b""  # 半个事件：还没有可判断的东西
    out = tr.feed(b'_content":"."}}]}\n\ndata: {"choices":[{"delta":{"content":"hi"}}]}\n\n')
    assert b"text_delta" in out and b"ping" not in out  # 有真东西就不用 ping
    tr.finish()
    now[0] += PING_EVERY_S
    assert tr.feed(think) == b""  # 收过尾不再吐


# ---------------------------------------------------------------- 流水与汇总


def test_summary_reads_off_truncations_timeouts_and_the_slowest_call():
    rows = [
        {"template": "reader/v1", "max_tokens": 8000, "outcome": "ok", "tokens_out": 700, "elapsed_s": 12.0},
        {
            "key": "read:s1:a.py:1-9:H1:1",
            "template": "reader/v1",
            "max_tokens": 8000,
            "outcome": "ok",
            "tokens_out": 3000,
            "elapsed_s": 15.5,
            "failed_attempts": [
                {"status": 0, "why": "idle: 流上超过 300 秒没有任何字节", "timeout": True, "elapsed_s": 300.2},
                {"status": 529, "why": "overloaded_error", "timeout": False, "elapsed_s": 0.4},
            ],
        },
        {
            "key": "ruwei:C1:place:1",
            "template": "ruwei/place/v1",
            "max_tokens": 24000,
            "outcome": "truncated",
            "tokens_out": 24000,
            "elapsed_s": 486.0,
            "first_byte_s": 1.2,
            "tokens_per_s": 49.4,
        },
        {
            "template": "shihuo/v1",
            "max_tokens": 24000,
            "outcome": "unavailable",
            "failed_attempts": [{"timeout": True}],
        },
    ]
    st = summarize(rows)
    assert (st["calls"], st["truncated"], st["refused"], st["gave_up"]) == (4, 1, 0, 1)
    assert (st["retries"], st["upstream_timeouts"], st["wasted_s"]) == (3, 2, 300.6)
    assert st["slowest"]["key"] == "ruwei:C1:place:1" and st["slowest"]["elapsed_s"] == 486.0
    assert st["by_template"]["reader/v1"] == {
        "calls": 2,
        "max_tokens": 8000,
        "truncated": 0,
        "out_min": 700,
        "out_max": 3000,
    }
    assert st["by_template"]["ruwei/place/v1"]["truncated"] == 1
    assert st["by_template"]["shihuo/v1"]["out_min"] is None  # 一次都没收到回答
    assert summarize([])["slowest"] is None and summarize([])["calls"] == 0


def test_every_real_call_is_logged_and_memo_hits_are_not(trig):  # noqa: F811
    rig = opened(trig)
    lid, rec = rig.session()
    root = rig.ws(lid) / "analysis"
    rows = jsonl(root / "model_calls.jsonl")
    assert [r["key"] for r in rows] == rig.replay.calls and all(r["outcome"] == "ok" for r in rows)
    for r in rows:
        assert r["elapsed_s"] > 0 and r["first_byte_s"] >= 0 and r["failed_attempts"] == []
        assert r["template"] and r["model"] and r["max_tokens"] > 0 and r["tokens_out"] > 0
        assert "output" not in r and "system" not in r  # 流水只有读数，不带提示词与模型的输出
    st = json.loads((root / "model_stats.json").read_text(encoding="utf-8"))
    assert st["calls"] == len(rows) and st["truncated"] == st["upstream_timeouts"] == st["retries"] == 0
    assert st["slowest"]["elapsed_s"] == max(r["elapsed_s"] for r in rows)
    assert sum(t["calls"] for t in st["by_template"].values()) == len(rows)
    assert not (root / "thinking.jsonl").exists()  # 没有思考块就没有这个文件
    exported = rig.cfg.analysis_export / "p1"
    assert json.loads((exported / "model_stats.json").read_text(encoding="utf-8")) == st  # 导出给人读
    # 下一个会话接着同一份流水；同一轮重交付时调用全取备忘，不添新行
    n = len(rows)
    rig.follow_up("再看看")
    lid2, rec2 = rig.session()
    assert len(rig.replay.calls) == n and len(jsonl(rig.ws(lid2) / "analysis" / "model_calls.jsonl")) == n


def test_thinking_is_kept_in_the_workspace_and_never_enters_the_event_stream(trig):  # noqa: F811
    rig = opened(trig)
    good = rig.replay.entries[READ]
    secret = "这一段是模型的思考：README 里说它用了分阶段验证"
    rig.replay.override[READ] = {
        "content": [
            {"type": "thinking", "thinking": secret},
            {"type": "redacted_thinking", "data": "opaque"},
            {"type": "text", "text": json.dumps(good["output"], ensure_ascii=False)},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 900},
    }
    lid, rec = rig.session()
    assert rig.deliveries()[-1]["outcome"] == "partial", rig.stderr(lid)
    root = rig.ws(lid) / "analysis"
    kept = jsonl(root / "thinking.jsonl")
    assert kept == [{"key": READ, "at": kept[0]["at"], "chars": len(secret), "text": secret}]
    row = next(r for r in jsonl(root / "model_calls.jsonl") if r["key"] == READ)
    assert (row["thinking_blocks"], row["thinking_chars"], row["tokens_out"]) == (2, len(secret), 900)
    assert secret not in json.dumps(rec.events, ensure_ascii=False)  # 事件流里只有步骤名与用量（13 §3.1）
    assert not [x for x in rig.runner.activity(lid)["items"] if x["kind"] == "think"]


def test_a_stalled_upstream_costs_one_idle_limit_not_ten_minutes(trig):  # noqa: F811
    """trial-b 第二次重跑：上游挂住，两次各白等约 10 分钟。
    流式之后挂住的那一次到静默时限就放手、重试，流水里记一次超时。"""
    rig = opened(trig)
    rig.profile["model_idle_s"] = 1
    seen = {"n": 0}

    def stalls_once(key, body):
        seen["n"] += 1
        return {"text": "{}", "gap_s": 4} if seen["n"] == 1 else None

    rig.replay.override[READ] = stalls_once
    t0 = time.monotonic()
    lid, rec = rig.session()
    assert rig.deliveries()[-1]["outcome"] == "partial" and seen["n"] == 2, rig.stderr(lid)
    root = rig.ws(lid) / "analysis"
    row = next(r for r in jsonl(root / "model_calls.jsonl") if r["key"] == READ)
    assert row["outcome"] == "ok" and len(row["failed_attempts"]) == 1
    failed = row["failed_attempts"][0]
    assert failed["timeout"] is True and failed["why"].startswith("idle") and 1 <= failed["elapsed_s"] < 3
    st = json.loads((root / "model_stats.json").read_text(encoding="utf-8"))
    assert (st["upstream_timeouts"], st["retries"]) == (1, 1) and 1 <= st["wasted_s"] < 3
    assert time.monotonic() - t0 < 60


def test_truncations_and_dead_ends_show_up_in_the_summary(trig):  # noqa: F811
    rig = opened(trig)
    good = rig.replay.entries[READ]
    rig.replay.override[READ] = {
        "text": '{"observations": [',
        "stop_reason": "max_tokens",
        "usage": {"input_tokens": 10, "output_tokens": 8000},
    }
    rig.replay.entries[READ.rsplit(":", 1)[0] + ":2"] = good
    lid, rec = rig.session()
    assert rig.deliveries()[-1]["outcome"] == "partial", rig.stderr(lid)
    st = json.loads((rig.ws(lid) / "analysis" / "model_stats.json").read_text(encoding="utf-8"))
    assert st["truncated"] == 1 and st["by_template"]["reader/v1"]["truncated"] == 1
    assert st["by_template"]["reader/v1"]["out_max"] == 8000

    rig2 = trig(cases.recording("alpha", "code"))
    rig2.open(pid="p2", intake={**cases.intake("alpha", "code"), "sources": UPLOAD}, material=fixture_tar("alpha"))
    rig2.replay.override["*"] = {"status": 503, "body": {"error": "upstream down"}}
    lid, rec = rig2.session("p2")
    rows = jsonl(rig2.ws(lid) / "analysis" / "model_calls.jsonl")
    assert len(rows) == 1 and rows[0]["outcome"] == "unavailable" and len(rows[0]["failed_attempts"]) == 3
    assert all(a["status"] == 503 and not a["timeout"] for a in rows[0]["failed_attempts"])
    st = json.loads((rig2.ws(lid) / "analysis" / "model_stats.json").read_text(encoding="utf-8"))
    assert (st["gave_up"], st["retries"], st["upstream_timeouts"], st["slowest"]) == (1, 3, 0, None)
