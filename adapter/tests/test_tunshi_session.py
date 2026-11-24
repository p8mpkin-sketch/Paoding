"""方案分析接进内核（docs/design/fenjue/13-kernel.md）：一道开放道的题、每一轮一个求解会话、固定流程的驱动程序。

走的是真的那条链：真图服务（事件账）、真端点代理（计量与预算）、真工具端点、驱动程序起成宿主子进程；
模型换成按调用键回放录音的假上游。执行层是进程内替身（抓取的测试见 test_tunshi_fetch.py）。
"""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from pathlib import Path

import pytest
from tunshi_rig import MODELS, PRICES, cases, engine_gongfa, fixture_tar, trig  # noqa: F401

from paoding_adapter import tunshi

_PKG = importlib.util.find_spec("paoding_fenjue")  # 只取包的目录读表，不 import 内部模块（跨组件只经契约）
assert _PKG is not None and _PKG.submodule_search_locations
TERMS = json.loads(
    (Path(next(iter(_PKG.submodule_search_locations))) / "engine/tables/vocab.json").read_text(encoding="utf-8")
)["internal_terms"]
UPLOAD = [{"no": 1, "form": "code", "via": "upload", "artifact": "$material"}]


def intake(fx: str = "alpha", **kw):
    return {**cases.intake(fx, "code"), "sources": UPLOAD, **kw}


def opened(trig, fx: str = "alpha", **kw):  # noqa: F811
    rig = trig(cases.recording(fx, "code"))
    rig.open(intake=intake(fx), material=fixture_tar(fx), **kw)
    return rig


def candidates(rig, lid):
    run = rig.run_units(lid)
    sha = run["artifacts"]["candidates.json"]
    return json.loads((rig.ws(lid) / "analysis" / "artifacts" / f"{sha}.json").read_text(encoding="utf-8"))


def kinds(rec, kind):
    return [e for e in rec.events if e.get("type") == kind]


# ---------------------------------------------------------------- 整条链：开题 → 三次确认 → 交接包


def test_an_analysis_runs_from_opening_to_handoff_across_four_sessions(trig):  # noqa: F811
    rig = opened(trig)
    g = rig.graph
    lid, rec = rig.session()
    assert rec.status == "released" and rec.release["outcome"] == "done" and rec.exit_codes == [0], rig.stderr(lid)
    lease = g.state["leases"][lid]
    assert lease["form"] == "h1.tunshi@1"  # 形态由图服务按分析实例的功法抄进租约（F3）
    assert rig.executor.calls == []  # 上传的材料不用抓取：沙箱里一条命令也没跑
    d1 = rig.deliveries()[-1]
    assert d1["outcome"] == "partial" and "第 1 次确认" in d1["needs"][-1]
    # 主张只有“分析依据的是哪份定版材料”，依据是材料本身（input 类）；分析结论是提议，不写成主张
    mat = g.state["problems"]["p1"]["origin"]["materials"][0]
    assert [c["refs"] for c in d1["claims"]] == [[mat]] and "Apache-2.0" in d1["claims"][0]["text"]
    # 每一步用的是它那一档的模型，请求不带采样参数与思考配置，系统提示是登记过的那份
    by_model = {b["model"] for b in rig.replay.requests}
    assert by_model == {MODELS["light"], MODELS["heavy"]}
    for b in rig.replay.requests:
        assert set(b) == {"model", "max_tokens", "system", "messages"} and b["system"].strip()
        assert len(b["messages"]) == 1 and b["messages"][0]["role"] == "user"
    reads = [b for b in rig.replay.requests if b["model"] == MODELS["light"]]
    assert reads and all('<external-data nonce="' in b["messages"][0]["content"] for b in reads)

    blocks = [cases.g1_block(candidates(rig, lid)), cases.g2_block(["C1"]), cases.g3_block(["C1"], "alpha")]
    for blk in blocks:
        rig.follow_up(blk)
        lid, rec = rig.session()
        assert rec.release["outcome"] == "done", rig.stderr(lid)
    ds = rig.deliveries()
    assert [d["outcome"] for d in ds] == ["partial", "partial", "answered", "answered"]
    assert rig.replay.misses == []
    # 结构化产物都经 check 登记（authored 类、产物的媒体类型）；交付末尾的对照表写的是内核给的编号
    arts = g.state["artifacts"]
    products = [a for a in arts.values() if a.get("media_type") == tunshi.PRODUCT_MEDIA]
    assert products and all(a["class"] == "authored" for a in products)
    last = rig.answer(ds[-1])
    assert "handoff.json" in last and "local:" not in last
    row = next(x for x in last.splitlines() if x.startswith("| handoff.json"))
    assert arts[row.split("|")[2].strip()]["media_type"] == tunshi.PRODUCT_MEDIA
    # 给人看的待办里没有内部名词
    for d in ds:
        for n in d["needs"]:
            assert not [t for t in TERMS if t in n], n
    # 后三步是确定性代码：第三次确认之后的会话一次模型都没调
    assert kinds(rec, "assistant") and not [e for e in rec.events if e.get("message", {}).get("usage")]
    # 工作区导出给界面的读端点
    exported = rig.cfg.analysis_export / "p1"
    assert json.loads((exported / "run.json").read_text(encoding="utf-8"))["step"] == "done"
    assert (exported / "engine.json").exists() and not list(exported.glob(".*.tmp"))
    # 花费由端点代理计量进事件账，引擎自己不记账
    assert g.budget("p1")["spent"]["usd_milli"] > 0

    # 结束之后再追问：把最后一次的结果原样再交一次，不重做
    rig.follow_up("谢谢，再发我一次")
    n = len(rig.replay.calls)
    lid, rec = rig.session()
    again = rig.deliveries()[-1]
    assert again["outcome"] == "answered" and "已经结束" in again["needs"][0] and len(rig.replay.calls) == n


def test_activity_shows_steps_but_never_external_text_or_model_output(trig):  # noqa: F811
    rig = opened(trig)
    lid, rec = rig.session()
    says = [c["text"] for e in kinds(rec, "assistant") for c in e["message"].get("content", []) if c["type"] == "text"]
    assert any(s.startswith("阅读片段：s1:README.md") for s in says) and any("识别候选" in s for s in says)
    blob = json.dumps(rec.events, ensure_ascii=False)
    readme = (cases.HERE / "alpha" / "code" / "README.md").read_text(encoding="utf-8")
    line = max(readme.splitlines(), key=len)
    assert len(line) > 30 and line not in blob  # 外部原文不进事件流
    said = json.dumps(rig.replay.entries["shihuo:patterns:1"]["output"], ensure_ascii=False)[:60]
    assert said not in blob  # 模型的输出也不进（它只是提议，进产物之前要过校验）
    for t in TERMS:
        assert not [s for s in says if t in s], t
    # 每次模型调用一条带用量的事件；工具调用成对
    turns = [e for e in kinds(rec, "assistant") if e["message"].get("usage")]
    assert len(turns) == len(rig.replay.calls) and all(e["message"]["model"] for e in turns)
    calls = [c for e in kinds(rec, "assistant") for c in e["message"].get("content", []) if c["type"] == "tool_use"]
    results = [c for e in kinds(rec, "user") for c in e["message"]["content"]]
    assert [c["name"].rsplit("__", 1)[-1] for c in calls] == ["intake", "check", "deliver"]
    assert [r["tool_use_id"] for r in results] == [c["id"] for c in calls]
    brief = json.loads(results[0]["content"])
    assert brief["materials"] == 1 and "statement" not in brief  # 简报在事件里只留计数
    view = rig.runner.activity(lid)
    assert view["status"] == "released" and any(x["kind"] == "turn" for x in view["items"])


def test_the_session_has_only_its_four_tools_and_no_shell(trig):  # noqa: F811
    rig = opened(trig)
    lid, rec = rig.session()
    init = next(e for e in rec.events if e.get("subtype") == "init")
    assert init["tools"] == [f"mcp__paoding__{t}" for t in ("deliver", "intake", "fetch", "check")]
    assert init["driver"] == "tunshi"
    pkg = json.loads(rig.blobs.get(rig.graph.state["artifacts"][rec.package_ref]["hash"]))
    assert "方案分析" in json.dumps(pkg, ensure_ascii=False)


# ---------------------------------------------------------------- 立项单：缺省、不合用、拒收


def test_without_an_intake_sheet_one_is_derived_from_the_materials(trig):  # noqa: F811
    rig = trig(cases.recording("alpha", "code"))
    rig.open(material=fixture_tar("alpha"))
    lid, rec = rig.session()
    doc = json.loads((rig.ws(lid) / "analysis" / "intake.json").read_text(encoding="utf-8"))
    mat = rig.graph.state["problems"]["p1"]["origin"]["materials"][0]
    assert doc["sources"] == [{"no": 1, "form": "code", "via": "upload", "artifact": mat}] and doc["mode"] == "formal"
    assert doc["date"] == "1970-01-01"  # 取开题事件的时间（测试台的钟从 1000 毫秒起），不取墙钟：同一道题每次相同
    assert rig.deliveries()[-1]["outcome"] == "partial"


def test_a_statement_alone_is_a_description_source(trig):  # noqa: F811
    rig = trig(cases.recording("alpha", "description"))
    st = (cases.HERE / "alpha" / "description" / "statement.txt").read_text(encoding="utf-8")
    rig.open(statement=st)
    lid, rec = rig.session()
    assert rec.release["outcome"] == "done", rig.stderr(lid)
    d = rig.deliveries()[-1]
    sref = rig.graph.state["problems"]["p1"]["origin"]["statement_ref"]
    assert d["outcome"] == "partial" and [c["refs"] for c in d["claims"]] == [[sref]]
    assert (rig.ws(lid) / "materials" / "s1" / "statement.txt").read_text(encoding="utf-8") == st


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"sources": [{"no": 1, "form": "code", "via": "upload", "artifact": "a_999"}]}, "不在这道题的材料里"),
        ({"mode": "nonsense"}, "不合 Schema"),
        ({"sources": [{"no": 1, "form": "code", "via": "repo_url", "url": "https://git.example/x/y"}]}, "ref"),
        ({"sources": [{"no": 1, "form": "service", "via": "service_url", "url": "https://svc.example"}]}, "探测计划"),
        ({"sources": UPLOAD + UPLOAD}, "编号有重复"),
    ],
)
def test_an_unusable_intake_sheet_blocks_before_anything_is_read(trig, change, said):  # noqa: F811
    rig = trig(cases.recording("alpha", "code"))
    rig.open(intake=intake(**change), material=fixture_tar("alpha"))
    lid, rec = rig.session()
    d = rig.deliveries()[-1]
    assert d["outcome"] == "blocked" and said in " ".join(d["needs"]), d["needs"]
    assert rig.replay.calls == [] and not (rig.ws(lid) / "analysis" / "run.json").exists()
    assert rig.requests() == []


def test_a_refused_source_is_never_fetched_and_never_requested(trig):  # noqa: F811
    """硬规则：本机题库、校准目录一类的来源在立项时就拒收，不解包、不抓取、不发访问申请。"""
    rig = trig(cases.recording("alpha", "code"))
    src = {"no": 1, "form": "code", "via": "repo_url", "url": "https://git.example/cz/paoding-bank", "ref": "v1"}
    rig.open(intake=intake(sources=[src]), material=fixture_tar("alpha"))
    lid, rec = rig.session()
    d = rig.deliveries()[-1]
    assert "立项没有成" in rig.answer(d) and rig.replay.calls == []
    assert rig.requests() == [] and rig.executor.calls == []
    fetches = [c for c in json.dumps(rec.events).split('"name": "mcp__paoding__fetch"')[1:]]
    assert fetches == []


# ---------------------------------------------------------------- 追问：决定块之外的话、不在确认点上的决定


def test_a_follow_up_without_a_decision_redelivers_the_same_gate(trig):  # noqa: F811
    rig = opened(trig)
    rig.session()
    n = len(rig.replay.calls)
    rig.follow_up("这些候选看着都不错，你觉得呢？")
    lid, rec = rig.session()
    d = rig.deliveries()[-1]
    assert d["outcome"] == "partial" and "决定" in d["needs"][0] and len(rig.replay.calls) == n
    rig.follow_up(cases.g2_block(["C1"]))  # 写错了确认点
    lid, rec = rig.session()
    d = rig.deliveries()[-1]
    assert "现在等的是" in d["needs"][0] and rig.run_units(lid)["step"] == "G1"
    rig.follow_up(cases.g1_block(candidates(rig, lid)))
    lid, rec = rig.session()
    assert rig.run_units(lid)["step"] == "G2"


# ---------------------------------------------------------------- 预算：预留用完接力、题预算用完交付、软线收尾


def test_when_only_the_session_reserve_runs_out_the_next_session_resumes_for_free(trig):  # noqa: F811
    """这个会话的预留用完而题里还有钱：不打扰人，下一个会话从检查点接着做；问过的调用取备忘，不再付钱。"""
    rig = opened(trig)
    lid, rec = rig.session(reserve=1)
    assert rig.deliveries() == [] and rec.release["outcome"] == "budget_exhausted"
    first = list(rig.replay.calls)
    assert 0 < len(first) < 12
    run = rig.run_units(lid)
    assert run["step"] == "paused_budget"
    lid2, rec2 = rig.session()
    assert rec2.release["outcome"] == "done", rig.stderr(lid2)
    assert rig.deliveries()[-1]["outcome"] == "partial" and rig.run_units(lid2)["step"] == "G1"
    assert len(set(rig.replay.calls)) == len(rig.replay.calls) == 12  # 没有一问是付了两次钱的
    assert rig.replay.calls[: len(first)] == first


def test_when_a_steps_share_of_the_budget_runs_out_it_stops_and_topping_up_resumes(trig):  # noqa: F811
    """每一步有自己的预算份额（引擎按宿主给的单价自己算）：份额用完就停在当前单元，交出已有的。"""
    rig = opened(trig, usd_milli=2)
    lid, rec = rig.session()
    d = rig.deliveries()[-1]
    assert d["outcome"] == "partial" and "识别候选" in d["needs"][0] and "预算份额用完" in d["needs"][0]
    assert not [t for t in TERMS if t in " ".join(d["needs"])]
    n = len(rig.replay.calls)
    rig.follow_up("继续", add=400_000)
    lid2, rec2 = rig.session()
    assert rig.run_units(lid2)["step"] == "G1" and rig.deliveries()[-1]["outcome"] == "partial"
    assert len(rig.replay.calls) == 12 and len(set(rig.replay.calls)) == 12 and n < 12
    x = json.loads((rig.ws(lid2) / "analysis" / "engine.json").read_text(encoding="utf-8"))
    assert x["budget_usd_milli"] == 400_002  # 这次运行的预算就是题的预算：追问里追加的也算进来


def test_when_the_endpoint_proxy_says_the_money_is_gone_what_exists_is_delivered(trig):  # noqa: F811
    """整题一级的预算归端点代理（T3）：它拒了（429），而题里也没剩多少，就把已有的交给人，请人追加；
    不靠引擎自己的估算（这里把引擎看到的单价设成 0，它以为一分钱没花）。"""
    rig = opened(trig, usd_milli=3)
    rig.profile["prices"] = {"light": [0, 0], "mid": [0, 0], "heavy": [0, 0]}
    lid, rec = rig.session(reserve=1)
    d = rig.deliveries()[-1]
    assert d["outcome"] == "partial" and "预留预算用完" in d["needs"][0] and "追加预算" in d["needs"][-1]
    assert rig.run_units(lid)["step"] == "paused_budget" and 0 < len(rig.replay.calls) < 12
    rig.follow_up("继续", add=400_000)
    rig.profile["prices"] = dict(PRICES)
    lid2, rec2 = rig.session()
    assert rig.run_units(lid2)["step"] == "G1"
    assert len(set(rig.replay.calls)) == len(rig.replay.calls) == 12


def test_the_soft_line_stops_at_the_current_unit_and_delivers(trig):  # noqa: F811
    """哮天犬在预算或墙钟到 90% 时叫会话收尾：停在当前单元，收尾轮不调模型，把已有的连同检查点交付。"""
    rig = opened(trig)
    gate = threading.Event()

    def slow(key, body):
        gate.set()
        time.sleep(5)
        return None

    rig.replay.override["shihuo:patterns:1"] = slow
    lid = rig.lease()
    t = threading.Thread(target=lambda: (gate.wait(20), time.sleep(0.2), rig.runner.soft_line(lid)), daemon=True)
    t.start()
    t0 = time.monotonic()
    rec = rig.run(lid)
    assert time.monotonic() - t0 < 5 and rec.rounds == 2 and rec.exit_codes == [130, 0], rig.stderr(lid)
    d = rig.deliveries()[-1]
    assert d["outcome"] == "partial" and "接近上限" in d["needs"][0]
    assert rig.run_units(lid)["step"] == "paused_budget"
    closing = [e for e in rec.events if e["round"] == 2]
    assert not [e for e in closing if e.get("message", {}).get("usage")]  # 收尾轮没有模型调用
    del rig.replay.override["shihuo:patterns:1"]
    rig.follow_up("继续")
    lid2, rec2 = rig.session()
    assert rig.run_units(lid2)["step"] == "G1"
    reads = [k for k in rig.replay.calls if k.startswith("read:")]
    assert len(reads) == len(set(reads))  # 读过的片段没有重读


def test_a_killed_session_leaves_a_usable_checkpoint(trig):  # noqa: F811
    """硬顶、停机会直接终止进程：检查点是先写旁边再改名的，下一个会话照样接得上。"""
    rig = opened(trig)
    gate = threading.Event()

    def slow(key, body):
        gate.set()
        time.sleep(5)
        return None

    rig.replay.override["shihuo:patterns:1"] = slow
    lid = rig.lease()
    threading.Thread(target=lambda: (gate.wait(20), rig.runner.kill(lid, "shutdown")), daemon=True).start()
    rec = rig.run(lid)
    assert rec.status == "killed(shutdown)" and rig.deliveries() == []
    json.loads((rig.ws(lid) / "analysis" / "run.json").read_text(encoding="utf-8"))
    del rig.replay.override["shihuo:patterns:1"]
    lid2, rec2 = rig.session()
    assert rig.run_units(lid2)["step"] == "G1" and rig.deliveries()[-1]["outcome"] == "partial"


# ---------------------------------------------------------------- 模型端点：暂时调不通、配置错误、不成形的输出


def test_a_flaky_endpoint_is_retried_and_a_dead_one_hands_over_without_bothering_anyone(trig):  # noqa: F811
    rig = opened(trig)
    seen = {"n": 0}

    def flaky(key, body):
        seen["n"] += 1
        return (
            {"status": 529, "body": {"type": "error", "error": {"type": "overloaded_error"}}}
            if seen["n"] == 1
            else None
        )

    rig.replay.override["shihuo:patterns:1"] = flaky
    lid, rec = rig.session()
    assert rig.deliveries()[-1]["outcome"] == "partial" and seen["n"] == 2  # 重试一次就过了

    rig2 = trig(cases.recording("alpha", "code"))
    rig2.open(pid="p2", intake=intake(), material=fixture_tar("alpha"))
    rig2.replay.override["*"] = {"status": 503, "body": {"error": "upstream down"}}
    lid, rec = rig2.session("p2")
    assert rig2.deliveries("p2") == [] and rec.release["outcome"] == "nothing"  # 没交付：司南会再派一个会话接力
    assert len(rig2.replay.calls) == 3  # 一问试了三次（两次等待）就放手，不空转
    assert "relay" in next(e for e in rec.events if e.get("type") == "result")["result"]
    rig2.replay.override.clear()
    lid, rec = rig2.session("p2")
    assert rig2.deliveries("p2")[-1]["outcome"] == "partial"


def test_when_relays_are_used_up_a_dead_endpoint_is_reported_to_the_person(trig):  # noqa: F811
    rig = opened(trig)
    rig.replay.override["*"] = {"status": 503, "body": {"error": "upstream down"}}
    for _ in range(tunshi.OPEN_RELAYS - 1):
        lid, rec = rig.session()
        assert rig.deliveries() == []
    lid, rec = rig.session()  # 这一轮的最后一个会话：再不说就没人知道了
    d = rig.deliveries()[-1]
    assert d["outcome"] == "blocked" and "调不通" in d["needs"][0] and "继续" in d["needs"][0]


def test_a_request_the_endpoint_rejects_outright_is_reported_not_retried(trig):  # noqa: F811
    rig = opened(trig)
    rig.replay.override["*"] = {"status": 404, "body": {"type": "error", "error": {"type": "not_found_error"}}}
    lid, rec = rig.session()
    d = rig.deliveries()[-1]
    assert d["outcome"] == "blocked" and "模型与端点配置" in d["needs"][0] and len(rig.replay.calls) == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"text": "我不能输出 JSON，抱歉。"},
        {"text": '{"observations": [', "stop_reason": "max_tokens"},
        {"content": [], "stop_reason": "refusal"},
        {"content": [{"type": "thinking", "thinking": '{"observations": []}'}]},
    ],
)
def test_output_that_is_not_a_json_object_is_asked_again_with_the_reason(trig, bad):  # noqa: F811
    """拒答、截断、只有思考没有正文、不是 JSON：都不当结果用，带着说明重问；思考块里的东西不算输出。"""
    rig = opened(trig)
    key = "read:s1:README.md:1-14:H1:1"
    asked = []

    def once(k, body):
        asked.append(body["messages"][0]["content"])
        return {**bad, "usage": {"input_tokens": 10, "output_tokens": 5}}

    rig.replay.override[key] = once
    again = cases.recording("alpha", "code")
    e = json.loads(again.read_text(encoding="utf-8"))["entries"]
    good = next(x for x in e if x["key"] == key)
    rig.replay.entries[key.rsplit(":", 1)[0] + ":2"] = good
    lid, rec = rig.session()
    assert rig.deliveries()[-1]["outcome"] == "partial", rig.stderr(lid)
    assert len(asked) == 1 and key.rsplit(":", 1)[0] + ":2" in rig.replay.calls
    retry = next(b for b in rig.replay.requests if b["messages"][0]["content"].startswith("# 调用 " + key[:-1] + "2"))
    assert "上一次的输出没有通过检查" in retry["messages"][0]["content"]


def test_the_driver_hands_the_stop_reason_to_the_engine():
    """被输出上限截断的回答：引擎要凭停止原因认出截断（trial-b-3），不能只看到“没有 JSON”。"""
    from paoding_adapter import tunshi_cli

    dan = tunshi_cli.ModelDan("http://x", "t", "h1.tunshi@1", {}, "m", tunshi_cli.Events("s"))
    cut = {
        "content": [{"type": "text", "text": '{"atoms": ['}],
        "stop_reason": "max_tokens",
        "usage": {"output_tokens": 12000},
    }
    r = dan._reply("m", cut)
    assert r.output is None and r.stop == "max_tokens" and r.tokens_out == 12000
    ok = {"content": [{"type": "text", "text": '{"a": 1}'}], "stop_reason": "end_turn", "usage": {}}
    assert dan._reply("m", ok).output == {"a": 1}
