"""外部裁决三期在起草一侧（external-verdict §5.8）：形态目录、external 形态、command 两档警告、平台导入排版。"""

from __future__ import annotations

import json

import pytest

from paoding_qicao.contract import (
    Catalog,
    Form,
    ImportError_,
    Intake,
    Settings,
    batch,
    catalog_of,
    defaults_catalog,
    import_vetted,
    override,
    parse_draft,
    placeholder_priors,
    system,
    vet,
)
from paoding_qicao.draft import SYSTEM
from paoding_qicao.service import KaitiService, heuristic_drafter

INTAKE = Intake.load()
SETTINGS = Settings.from_doc({})
PRIORS = placeholder_priors()
PLAT = Form("external", "ext_receipt", "plat-a", ("plat-a.test", "10.0.0.5:*"), r"T-[0-9]+", "1")
CAT = Catalog((Form("answer", "exact_match"), Form("command", "replay"), PLAT))

REGISTRY = {
    "exact_match": {"form": "answer", "applies_to": ["goal", "intent"], "version": "1"},
    "replay": {"form": "command", "applies_to": ["goal", "intent"], "version": "1"},
    "ext_receipt": {
        "form": "external",
        "applies_to": ["goal"],
        "authority": "external",
        "params": {"connector": "plat-a"},
        "version": "1",
    },
    "panel": {"applies_to": ["goal"], "version": "1"},  # 没标 form：不进目录
}
CONNS = {
    "plat-a": {
        "version": "3",
        "digest": "d",
        "doc": {"match": {"hosts": ["plat-a.test"]}, "task_ref": {"pattern": "T-[0-9]+"}},
    }
}


def _vet(text: str, answer: str | None = None, catalog: Catalog | None = CAT, doc=None, strict: bool = False):
    ext = INTAKE.extract(text)
    d = parse_draft(doc or heuristic_drafter(ext, bool(answer) or bool(ext.answers)), ext, "h")
    return vet(ext, answer, d, INTAKE, SETTINGS, PRIORS, zero_confirm=False, nonce="n", catalog=catalog, strict=strict)


def codes(v):
    return [n.code for n in v.notes]


# ---------------------------------------------------------------- 形态目录


def test_catalog_from_registry():
    cat = catalog_of(REGISTRY, CONNS)
    assert cat.judge("answer") == "exact_match" and cat.judge("command") == "replay"
    (p,) = cat.platforms()
    assert (p.connector, p.hosts, p.task_ref, p.version) == ("plat-a", ("plat-a.test",), "T-[0-9]+", "3")
    assert set(cat.kinds()) == {"answer", "command", "external", "none"} and cat.kinds()[-1] == "none"
    assert catalog_of(REGISTRY, {}).platforms() == ()  # 档案没加载：不进目录
    assert "external" not in catalog_of(REGISTRY, {}).kinds()


def test_prompt_lists_external_only_when_registered():
    assert system(None) == SYSTEM and system(("answer", "command", "none")) == SYSTEM
    s = system(CAT.kinds())
    assert "external" in s and s != SYSTEM


def test_host_matching_with_port_and_glob():
    assert PLAT.matches("plat-a.test") and PLAT.matches("plat-a.test:443") and PLAT.matches("10.0.0.5:8080")
    assert not PLAT.matches("other.test:443")


def test_defaults_catalog_keeps_old_behavior():
    t = "修好构建。完成标准：在仓库根目录跑 `make test` 全部通过。"
    a, b = _vet(t, catalog=None, strict=True), _vet(t, catalog=defaults_catalog(INTAKE.defaults), strict=True)
    assert a.input == b.input and a.input["judges"] == ["replay"]
    # 不选严格判定：命令进开放道当必做自检项（open-lane 裁决 §12 第 2 条）
    c = _vet(t, catalog=None)
    assert c.input["goal"]["self_checks"] == [{"text": "make test", "src": "span"}] and c.input["judges"] == []


# ---------------------------------------------------------------- external 形态


TEXT = "平台任务 T-17（https://plat-a.test/tasks/T-17）：找出服务里的口令，提交给平台，回执通过就算完成。限时 6 小时。"


def test_registered_platform_is_external():
    v = _vet(TEXT)
    assert v.lane == "confirm" and v.external == {"connector": "plat-a", "judge_id": "ext_receipt", "task": "T-17"}
    assert v.input["goal"]["check"] == {"judge_id": "ext_receipt", "binding": {"connector": "plat-a", "task": "T-17"}}
    assert v.input["scope"][0]["resource"] == "workspace"  # 平台地址不进授权
    assert "clipped_wall_s" not in codes(v)  # 平台时限不进花费预算
    assert any(r["field"] == "deadline" for r in v.derivation)
    with pytest.raises(ValueError):  # 起草结果本身不开题：批次由导入时领题生成
        batch(v, lambda b: __import__("hashlib").sha256(b).hexdigest(), None)


def test_submit_example_is_only_material():
    t = TEXT + "提交方式：`curl -X POST https://plat-a.test/api/tasks/T-17/submissions -d '{}'`"
    v = _vet(t)
    assert v.external is not None and v.spec is None and "submit_example_material" in codes(v)


def test_task_ref_must_be_unique_and_present():
    assert "no_task_ref" in codes(_vet("在 https://plat-a.test 上找口令，回执通过算完成。"))
    two = _vet("任务 T-1 或 T-2，在 https://plat-a.test 上，回执通过算完成。")
    assert two.lane == "refuse" and "ambiguous_task" in codes(two)


def test_answer_wins_over_platform():
    v = _vet(TEXT + "答案：PD-ABCDEF")
    assert v.external is None and v.input["judges"] == ["exact_match"]


def test_model_says_external_but_platform_unknown():
    t = "在 https://else.test/t 上提交，回执通过算完成。"
    ext = INTAKE.extract(t)
    url = ext.of("url")[0].id
    doc = {**heuristic_drafter(ext, False), "check": {"form": "external", "spans": [url]}}
    v = _vet(t, doc=doc, strict=True)
    assert v.lane == "refuse" and "platform_unregistered" in codes(v)
    # 不选严格判定：未登记的平台不拒题，进开放道，平台地址不开通路（open-lane 裁决附加条件 2）
    import dataclasses

    on = dataclasses.replace(SETTINGS, grants_runtime=True)  # 开题零出站（settings_hub 的缺省）
    o = vet(ext, None, parse_draft(doc, ext, "h"), INTAKE, on, PRIORS, zero_confirm=False, nonce="n", catalog=CAT)
    assert o.lane == "open" and "platform_unregistered" in codes(o) and o.external is None
    assert o.input["goal"]["accept"] == "open" and o.input["scope"][0]["resource"] == "workspace"
    # 运行时扩权关着时原文地址会在开题时开通：开放道也要人确认这一次
    c = _vet(t, doc=doc)
    assert c.lane == "confirm" and "open_needs_confirm" in codes(c) and c.input["goal"]["accept"] == "open"


def test_two_platforms_refuse():
    cat = Catalog(CAT.forms + (Form("external", "ext_b", "plat-b", ("plat-b.test",), "T-[0-9]+"),))
    v = _vet("T-17 在 https://plat-a.test 和 https://plat-b.test 上都有。", catalog=cat)
    assert v.lane == "refuse" and "ambiguous_platform" in codes(v)


# ---------------------------------------------------------------- command 两档警告


def test_plain_command_warns_but_needs_no_ack():
    v = _vet("修好构建。完成标准：在仓库根目录跑 `make test` 全部通过。", strict=True)
    assert "command_criterion" in codes(v) and "command_outbound" not in codes(v) and v.needs_ack is None


@pytest.mark.parametrize(
    "cmd",
    ["curl -X POST http://q1:8080/x", "curl q1:8080 -d x", "python check.py --data a"],
)
def test_outbound_command_needs_ack(cmd):
    v = _vet(f"完成标准：跑 `{cmd}` 返回 0。", strict=True)
    assert "command_outbound" in codes(v) and v.needs_ack == "command"
    with pytest.raises(ValueError):
        batch(v, lambda b: __import__("hashlib").sha256(b).hexdigest(), None)
    acked = override(v, {"ack_command": True}, SETTINGS)
    assert acked.needs_ack is None
    assert [r["source"] for r in acked.derivation if r["field"] == "goal.check.ack"] == ["human"]
    assert batch(acked, lambda b: __import__("hashlib").sha256(b).hexdigest(), None)
    with pytest.raises(ValueError):
        override(v, {"ack_command": "yes"}, SETTINGS)


@pytest.mark.parametrize("cmd", ["curl -X POST http://q1:8080/x", "python check.py --data a"])
def test_open_lane_outbound_command_is_only_material(cmd):
    """开放道里命令只当自检项；有外发形状的连自检项也不当（智能体“自检”时再提交一次就错了），只留在题面里。"""
    v = _vet(f"完成标准：跑 `{cmd}` 返回 0。")
    assert v.lane == "open" and "self_checks" not in v.input["goal"] and v.needs_ack is None
    assert "command_outbound_material" in codes(v) and v.spec is None and cmd in v.statement


def test_submit_word_in_text_is_outbound():
    v = _vet("把结果提交上去。完成标准：跑 `make check` 通过。", strict=True)
    assert v.needs_ack == "command"
    # 开放道里命令只是自检项，判官不重放它：不需要“只检查、不提交”的勾选
    assert _vet("把结果提交上去。完成标准：跑 `make check` 通过。").needs_ack is None


# ---------------------------------------------------------------- 平台导入


ITEM = {"task": "T-17", "title": "找口令", "time_limit_s": 21600, "max_submissions": 3}
NOTICE = json.dumps({"id": "T-17", "statement": "题面", "instance": "10.9.9.9:31000"}).encode()


def test_import_builds_external_open():
    v = import_vetted(PLAT, ITEM, "题面", NOTICE, INTAKE, SETTINGS, PRIORS, now_ms=1000, nonce="n")
    assert v.lane == "confirm" and not v.eligible
    p = v.input
    assert p["goal"]["check"]["binding"] == {"connector": "plat-a", "task": "T-17", "max_submissions": 3}
    assert p["goal"]["max_attempts"] == 3  # min(模板缺省 5, 平台额度 3)
    assert p["deadline"] == {"source": "external", "bound_by": "$notice", "at": 1000 + 21600 * 1000}
    assert p["budget"]["wall_s"] <= SETTINGS.caps["open_wall_s"] and p["scope"][0]["resource"] == "workspace"
    ops = batch(v, lambda b: __import__("hashlib").sha256(b).hexdigest(), None)
    body = ops[-1]["body"]
    names = [o["body"]["media_type"] for o in ops[:-1]]
    assert "application/json" in names
    assert body["deadline"]["bound_by"] == body["origin"]["materials"][0]  # 公告既是材料，又是截止时刻的出处


def test_import_human_budget_and_errors():
    v = import_vetted(
        PLAT, ITEM, "题面", NOTICE, INTAKE, SETTINGS, PRIORS, now_ms=0, budget={"wall_s": 600, "usd_milli": 900}
    )
    assert v.input["budget"]["wall_s"] == 600 and v.input["budget"]["usd_milli"] == 900
    assert {r["field"]: r["source"] for r in v.derivation}["budget.wall_s"] == "human"
    with pytest.raises(ImportError_):
        import_vetted(PLAT, ITEM, "题面", NOTICE, INTAKE, SETTINGS, PRIORS, now_ms=0, budget={"wall_s": 10**9})
    with pytest.raises(ImportError_):
        import_vetted(PLAT, {**ITEM, "max_submissions": None}, "题面", NOTICE, INTAKE, SETTINGS, PRIORS, now_ms=0)
    with pytest.raises(ImportError_):
        import_vetted(PLAT, ITEM, " ", NOTICE, INTAKE, SETTINGS, PRIORS, now_ms=0)
    nolimit = import_vetted(PLAT, {**ITEM, "time_limit_s": None}, "题面", NOTICE, INTAKE, SETTINGS, PRIORS, now_ms=0)
    assert "at" not in nolimit.input["deadline"] and "no_deadline" in codes(nolimit)


def test_service_views():
    svc = KaitiService(INTAKE, lambda: SETTINGS, PRIORS, heuristic_drafter, "h", CAT)
    out = svc.draft_view({"text": TEXT})
    assert out["external"]["task"] == "T-17" and out["ops"] is None and out["blobs"] == []
    refused = svc.draft_view({"text": "随便做点什么。", "strict": True})
    assert refused["lane"] == "refuse" and refused["ways"] == [
        "open",
        "endpoint",
        "human",
        "advanced",
        "register_platform",
    ]
    opened = svc.draft_view({"text": "随便做点什么。"})
    assert opened["lane"] == "open" and opened["ops"][-1]["body"]["origin"]["draft"]["lane"] == "open"
    imp = svc.import_view(PLAT, ITEM, "题面", NOTICE, now_ms=0, nonce="n")
    assert imp["ops"] and {b["name"] for b in imp["blobs"]} == {"statement", "notice", "derivation"}
