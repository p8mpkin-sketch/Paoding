"""一句话开题二期：起草服务（POST /v1/drafts 的实现）与确认卡上的人改（override）。"""

from __future__ import annotations

import hashlib
import json

import pytest

from paoding_qicao.contract import (
    ANSWER_SLOT,
    BadRequest,
    Intake,
    KaitiService,
    Settings,
    heuristic_drafter,
    model_drafter,
    placeholder_priors,
)

INTAKE = Intake.load()
SETTINGS = Settings.from_doc(
    {
        "settings": {
            "caps": {
                "open_usd_milli": 20_000,
                "open_wall_s": 14_400,
                "practice_usd_milli": 500,
                "practice_wall_s": 1800,
            },
            "risk": [{"resource": "net", "pattern": "q*:*", "actions": ["connect"], "risk": "r0"}],
        }
    }
)
T1 = "目标在 q1:8080，登录后页面会显示一个答案串，交出来。半小时内搞定。答案：PD-7Q2M9XKD"
T2 = "修好构建。完成标准：跑 `make test` 全部通过。"
T3 = "帮我调研一下主流框架，写一份对比。"


def svc(drafter=heuristic_drafter):
    return KaitiService(INTAKE, lambda: SETTINGS, placeholder_priors(), drafter, "heuristic")


def test_extract_view_hides_answer_and_counts_it():
    out = svc().extract_view({"text": T1})
    assert "PD-7Q2M9XKD" not in json.dumps(out, ensure_ascii=False)
    assert out["answers"] == 1
    kinds = {s["kind"] for s in out["spans"]}
    assert {"addr", "duration", "sentence"} <= kinds


def test_utf16_offsets_slice_the_same_text():
    text = "😀 目标在 q1:8080，交出来。答案：x"
    out = svc().extract_view({"text": text})
    u16 = out["text"].encode("utf-16-le")
    for s in out["spans"]:
        assert u16[2 * s["start"] : 2 * s["end"]].decode("utf-16-le") == s["text"]


def test_confirm_lane_batch_and_blobs():
    out = svc().draft_view({"text": T1})
    assert out["lane"] == "confirm" and out["eligible"] and out["zero_confirm"] is False
    assert any(n["code"] == "zero_confirm_off" for n in out["notes"])
    assert out["secret"] == "PD-7Q2M9XKD"  # 来自原文答案行：回传一次供写保密库
    ops = out["ops"]
    assert ops[-1]["op"] == "open_problem"
    assert ops[-1]["body"]["goal"]["check"]["sealed"] == [ANSWER_SLOT]
    for b, op in zip(out["blobs"], ops[:-1], strict=True):
        data = b["text"].encode()
        assert hashlib.sha256(data).hexdigest() == b["hash"] == op["body"]["hash"] and len(data) == b["size"]
        assert "PD-7Q2M9XKD" not in b["text"]


def test_answer_field_is_not_echoed():
    out = svc().draft_view({"text": T1.split("答案：")[0], "answer": "PD-7Q2M9XKD"})
    assert out["has_answer"] and "secret" not in out
    assert "PD-7Q2M9XKD" not in json.dumps(out, ensure_ascii=False)


def test_command_and_refuse():
    out = svc().draft_view({"text": T2, "strict": True})
    assert out["lane"] == "confirm" and out["input"]["goal"]["check"]["judge_id"] == "replay"
    out = svc().draft_view({"text": T3, "strict": True})
    assert out["lane"] == "refuse" and out["ops"] is None and out["blobs"] == []
    assert any(n["code"] == "no_criterion" for n in out["notes"]) and out["ways"][0] == "open"
    with pytest.raises(BadRequest):
        svc().draft_view({"text": T3, "strict": "yes"})


def test_open_lane_by_default():
    """open-lane §3.1：判不了的进开放道，批次直接给出（前端不出确认卡就提交）；命令变成必做自检项。"""
    out = svc().draft_view({"text": T3})
    assert out["lane"] == "open" and out["ops"] and "ways" not in out
    body = out["ops"][-1]["body"]
    assert body["goal"]["accept"] == "open" and body["judges"] == [] and body["origin"]["draft"]["lane"] == "open"
    out = svc().draft_view({"text": T2})
    assert out["lane"] == "open" and out["ops"][-1]["body"]["goal"]["self_checks"] == [
        {"text": "make test", "src": "span"}
    ]
    assert {b["name"] for b in out["blobs"]} == {"statement", "derivation"}  # 命令不登记成检查规格


def test_no_drafter_refuses():
    out = svc(None).draft_view({"text": T1})
    assert out["lane"] == "refuse" and "没有配置起草模型" in out["notes"][0]["text"]


def test_draft_passthrough_does_not_call_model():
    calls = []

    def drafter(ext, has):
        calls.append(1)
        return heuristic_drafter(ext, has)

    s = svc(drafter)
    first = s.draft_view({"text": T1})
    again = s.draft_view({"text": T1, "draft": first["draft"], "nonce": first["nonce"], "model": first["model"]})
    assert len(calls) == 1 and again["pid"] == first["pid"] and again["input"] == first["input"]


def test_overrides_mark_human_and_drop_candidate():
    s = svc()
    first = s.draft_view({"text": T1})
    body = {"text": T1, "draft": first["draft"], "nonce": first["nonce"]}
    out = s.draft_view({**body, "overrides": {"risk": {"0": "r2"}, "usd_milli": 900}})
    assert out["lane"] == "confirm" and not out["eligible"]
    assert out["input"]["scope"][0]["risk"] == "r2" and out["input"]["budget"]["usd_milli"] == 900
    rows = {r["field"]: r for r in out["derivation"]}
    assert rows["scope[0].risk"]["source"] == "human" and rows["budget.usd_milli"]["source"] == "human"
    assert any(n["code"] == "human_edit" for n in out["notes"])
    assert not any(n["code"] == "zero_confirm_off" for n in out["notes"])
    # 出处账 Blob 随改动更新
    der = next(b for b in out["blobs"] if b["name"] == "derivation")
    assert '"source":"human"' in der["text"]
    # 改成原值：等于没改
    same = s.draft_view({**body, "overrides": {"usd_milli": first["input"]["budget"]["usd_milli"]}})
    assert same["eligible"]


def test_run_profile_override_goes_into_prefs():
    """确认卡“执行用”另选档案（宪章 03 §3.1、地图 Q12）：只认设置页登记过的名字，写进 open_problem 的 prefs.model。"""
    import dataclasses

    prof = [{"name": "default", "model": ""}, {"name": "light", "model": "light-1"}]
    st = dataclasses.replace(SETTINGS, models={"profiles": prof, "routes": {}})
    s = KaitiService(INTAKE, lambda: st, placeholder_priors(), heuristic_drafter, "heuristic")
    first = s.draft_view({"text": T1})
    assert "prefs" not in first["input"]
    body = {"text": T1, "draft": first["draft"], "nonce": first["nonce"]}
    out = s.draft_view({**body, "overrides": {"model": "light"}})
    assert out["input"]["prefs"] == {"model": "light"}
    row = next(r for r in out["derivation"] if r["field"] == "prefs.model")
    assert row["source"] == "human" and row["value"] == "light"
    batch = next(o for o in out["ops"] if o["op"] == "open_problem")
    assert batch["body"]["prefs"] == {"model": "light"}
    for bad in ("custom", 3, ""):
        with pytest.raises(BadRequest):
            s.draft_view({**body, "overrides": {"model": bad}})


def test_knowledge_option_goes_into_prefs():
    """新建任务的知识选项（资料库第二期，K3）：自动是缺省、不写；指定与不用写进 prefs.knowledge，与执行模型并存。"""
    import dataclasses

    prof = [{"name": "default", "model": ""}, {"name": "light", "model": "light-1"}]
    st = dataclasses.replace(SETTINGS, models={"profiles": prof, "routes": {}})
    s = KaitiService(INTAKE, lambda: st, placeholder_priors(), heuristic_drafter, "heuristic")
    first = s.draft_view({"text": T1})
    body = {"text": T1, "draft": first["draft"], "nonce": first["nonce"]}
    auto = s.draft_view({**body, "overrides": {"knowledge": {"mode": "auto"}}})
    assert "prefs" not in auto["input"]
    out = s.draft_view({**body, "overrides": {"knowledge": {"mode": "pick", "pick": ["s_abc123"]}, "model": "light"}})
    assert out["input"]["prefs"] == {"model": "light", "knowledge": {"mode": "pick", "pick": ["s_abc123"]}}
    row = next(r for r in out["derivation"] if r["field"] == "prefs.knowledge")
    assert row["source"] == "human"
    off = s.draft_view({**body, "overrides": {"knowledge": {"mode": "off"}}})
    batch = next(o for o in off["ops"] if o["op"] == "open_problem")
    assert batch["body"]["prefs"] == {"knowledge": {"mode": "off"}}
    for bad in ({"mode": "all"}, {"mode": "pick"}, {"mode": "pick", "pick": [3]}, "auto", {"mode": "off", "x": 1}):
        with pytest.raises(BadRequest):
            s.draft_view({**body, "overrides": {"knowledge": bad}})


@pytest.mark.parametrize(
    "ov",
    [
        {"usd_milli": 20_001},
        {"wall_s": 0},
        {"risk": {"0": "r9"}},
        {"risk": {"5": "r0"}},
        {"title": "x"},
        {"usd_milli": True},
    ],
)
def test_bad_overrides_rejected(ov):
    s = svc()
    first = s.draft_view({"text": T1})
    with pytest.raises(BadRequest):
        s.draft_view({"text": T1, "draft": first["draft"], "nonce": first["nonce"], "overrides": ov})


def test_bad_bodies():
    for b in (None, {"text": 1}, {"text": "x" * (64 * 1024 + 1)}):
        with pytest.raises(BadRequest):
            svc().draft_view(b)
    with pytest.raises(BadRequest):
        svc().draft_view({"text": T1, "answer": 3})


def test_bad_model_output_and_tampered_draft_refuse():
    class M:
        def complete(self, system, user, max_tokens):
            return '{"title": "x", "scope": ["evil:1"]}'

    out = svc(model_drafter(M())).draft_view({"text": T1})
    assert out["lane"] == "refuse" and any(n["code"] == "bad_draft" for n in out["notes"])
    first = svc().draft_view({"text": T1})
    bad = {**first["draft"], "entries": [{"span": "nope", "role": "entry"}]}
    out = svc().draft_view({"text": T1, "draft": bad})
    assert out["lane"] == "refuse"


def test_refuse_way_02_human_acceptance():
    """拒绝页第 02 条路（宪章 D3、02 §3.3）：人给验收清单（原文区间或自己写），任务改为人工验收。"""
    s = svc()
    refused = s.draft_view({"text": T3, "strict": True})
    assert refused["lane"] == "refuse" and "human" in refused["ways"]
    sent = next(x for x in refused["spans"] if x["kind"] == "sentence")
    body = {"text": T3, "draft": refused["draft"], "nonce": refused["nonce"]}
    out = s.draft_view({**body, "acceptance": [{"span": sent["id"]}, {"text": "附上对比表", "needs": "artifact"}]})
    assert out["lane"] == "confirm" and not out["eligible"]
    goal = out["input"]["goal"]
    assert goal["accept"] == "human" and goal["check"] == {"judge_id": "structure_check"}
    assert goal["acceptance"] == [
        {"text": sent["text"].strip(), "src": "span"},
        {"text": "附上对比表", "src": "human", "needs": "artifact"},
    ]
    rows = {r["field"]: r for r in out["derivation"]}
    assert rows["goal.acceptance[0]"]["source"] == "span" and rows["goal.acceptance[1]"]["source"] == "human"
    assert any(n["code"] == "human_acceptance" for n in out["notes"])
    assert out["ops"][-1]["body"]["goal"]["acceptance"] == goal["acceptance"]
    bad = s.draft_view({**body, "acceptance": [{"span": "nope"}]})
    assert bad["lane"] == "refuse" and any(n["code"] == "acceptance_bad" for n in bad["notes"])
    with pytest.raises(BadRequest):
        s.draft_view({**body, "acceptance": [{"text": "x", "src": "model"}]})  # 不收出处字段：模型起草的不进
    judged = s.draft_view({"text": T2, "acceptance": [{"text": "x"}], "strict": True})
    assert judged["input"]["goal"]["accept"] == "judge"
    assert any(n["code"] == "acceptance_ignored" for n in judged["notes"])
