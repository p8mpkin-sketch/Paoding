"""校验（设计 §2 第③层）：确定性纯函数。不读时钟、不做 IO、不调模型。

vet(抽取结果, 答案栏, 草案, 模板数据, 设置快照, 先验源) → Vetted
- 出处：每个进入提交体的字段都有一行出处（摘 span / 表 table / 估 prior / 起草 model），见 derivation。
- 答案：只走专用栏或标签行；题面、题名、目标句、材料、检查命令里出现答案即拒绝（answer_leak）。
- 判据：有答案 → exact_match（sealed，保密库）；认出已登记平台 → 外部裁决；人给了验收清单 → 人工验收；
  其余进开放道（docs/design/open-lane/ §3.1）：不登记判据，原文里的检查命令变成必做自检项。
  严格判定（strict）或设置里关了开放道（lanes.open=false）时，回到判据先行：命令 → replay，都没有 → 拒绝。
  模型不能改变"有没有答案"，也不能写检查命令。
- 授权：只认草案标为 entry 的地址区间；风险查设置层的风险表，未命中按 r2。没有入口 → 只有 workspace（r0）。
- 预算：原文写的数 > 先验源（按档位）> 模板缺省；被单题硬顶裁剪，裁过即不得零确认。
- 分道：refuse | confirm | practice | open。practice 只在零确认开关打开且全部条件满足时给出；开关关着时记 eligible。
  open 不出确认卡（开题零出站时）：confirm 一档的提示只作说明，不压道别。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any

from .catalog import Catalog, Form, defaults_catalog
from .draft import Draft
from .extract import Extraction, norm
from .policy import RISK_RANK, Intake, PriorSource, Settings

ANSWER_SLOT = "$answer"  # 提交前由调用方换成保密库的 VaultRef


@dataclass(frozen=True)
class Note:
    code: str
    field: str
    text: str
    lane: str  # 它把道别压到哪一档：refuse | confirm（开放道里 confirm 一档只作说明）


@dataclass
class Vetted:
    lane: str  # practice | confirm | refuse | open
    eligible: bool  # 练习道候选（零确认开关打开时即直开）
    notes: list[Note]
    derivation: list[dict[str, Any]]
    input: dict[str, Any] | None  # ProblemInput（不含 profile；Origin 与 spec_ref 用批内引用，见 ops.batch）
    statement: str  # 题面 = 剪去答案的原文
    references: list[str] = field(default_factory=list)  # 参考地址，作为文字材料（text/uri-list，不抓取）
    spec: str | None = None  # replay 的检查命令，逐字取自原文代码块
    secret: str | None = field(default=None, repr=False)  # 答案；只交给保密库，不序列化
    pid: str = ""
    priors_version: str = ""
    # 运行时扩权开着时：原文里起草指认的入口地址，只作展示（确认卡上的原文高亮），不生成规则、不影响道别
    mentions: list[dict[str, Any]] = field(default_factory=list)
    external: dict[str, Any] | None = None  # 外部裁决：{connector, judge_id, task}；批次由导入时领题生成（§5.8）
    needs_ack: str | None = None  # "command"：命令有外发的形状，人勾“只检查、不提交”之前不给批次
    notice: bytes | None = None  # 资源公告（导入时领题的说明全文）；有它时 deadline.bound_by 指向它

    def public(self) -> dict[str, Any]:
        """可登记、可打印的部分（不含答案）。"""
        return {
            "lane": self.lane,
            "eligible": self.eligible,
            "notes": [n.__dict__ for n in self.notes],
            "derivation": self.derivation,
            "input": self.input,
            "priors": self.priors_version,
            **({"mentions": self.mentions} if self.mentions else {}),
            "external": self.external,
            "needs_ack": self.needs_ack,
        }


def _src(field_: str, value: Any, source: str, spans: list[str] | None = None, note: str = "") -> dict[str, Any]:
    d: dict[str, Any] = {"field": field_, "value": value, "source": source}
    if spans:
        d["spans"] = spans
    if note:
        d["note"] = note
    return d


def vet(
    ext: Extraction,
    answer_field: str | None,
    d: Draft | None,
    intake: Intake,
    settings: Settings,
    priors: PriorSource,
    *,
    zero_confirm: bool | None = None,
    nonce: str = "",
    draft_error: str = "",
    catalog: Catalog | None = None,
    acceptance: list[Mapping[str, Any]] | None = None,
    strict: bool = False,
) -> Vetted:
    """acceptance：人选了“人工验收”（宪章 D3、02 §3.3）后给的验收清单，
    每项 {span: 区间 id} 或 {text: 人写的陈述}，可带 needs。模型不写条目：草案里没有这一栏。
    strict：人选了“严格判定”。没有可判定的终点就拒绝，不进开放道。"""
    notes: list[Note] = []
    der: list[dict[str, Any]] = []
    dfl = intake.defaults
    open_ok = settings.lanes_open and not strict  # 回滚开关 lanes.open（open-lane §11）

    def note(code: str, f: str, text: str, lane: str = "confirm") -> None:
        notes.append(Note(code, f, text, lane))

    # ---------- 原文与答案 ----------
    if not ext.text.strip():
        note("empty_text", "statement", "原文是空的", "refuse")
    answers = [a for a in ext.answers if a]
    secret: str | None = None
    if answer_field is not None and answer_field.strip():
        secret = answer_field.strip()
        if answers and any(norm(a) != norm(secret) for a in answers):
            note("answer_conflict", "goal.check", "答案栏与原文里的答案行不一致", "refuse")
    elif len(answers) > 1:
        note("multiple_answers", "goal.check", "原文里有不止一个答案行", "refuse")
    elif answers:
        secret = answers[0]
    cat = catalog or defaults_catalog(dfl)
    raw = False  # 起草不可用、按原话直开开放道（地图 Q38，D14；体质修炼 004）
    if d is None:
        why = draft_error or "没有草案"
        d = _raw_draft(ext) if _raw_ok(ext, secret, acceptance, open_ok, cat) and not notes else None
        if d is None:
            note("bad_draft", "draft", f"起草结果不可用：{why}", "refuse")
            return _done(notes, der, None, ext, secret, [], None, nonce, priors, False, intake, zero_confirm)
        raw = True
        note(
            "draft_unavailable",
            "draft",
            f"起草不可用（{why}），按原话开题：题面与目标就是原话，题名取原话开头；原文里的地址只当材料、"
            "金额与时长不认，用默认预算；"
            + ("执行时要访问外部地址会按需申请" if settings.grants_runtime else "这次不开任何出站"),
        )

    # ---------- 目标 ----------
    goal_text = "".join(ext.span(s).value for s in d.goal_sentence)  # type: ignore[union-attr]
    der.append(_src("goal.statement", goal_text, "span", list(d.goal_sentence)))
    if raw:
        der.append(_src("title", d.title, "span", [d.goal_sentence[0]], "起草不可用：取原话开头"))
    else:
        der.append(_src("title", d.title, "model"))

    # ---------- 判据（形态目录由注册表驱动，见 catalog.py） ----------
    judges: list[str]
    check: dict[str, Any]
    accept, items = "judge", []
    spec: str | None = None
    needs_ack: str | None = None
    external: dict[str, Any] | None = None
    max_attempts = int(dfl["max_attempts"])
    plats: dict[str, tuple[Form, list[str]]] = {}  # 查表认出的平台：连接器 → (形态, 命中的地址区间)
    for psp in ext.of("url") + ext.of("addr") + ext.of("host"):
        for pf in cat.platform_of(str(psp.value)):
            plats.setdefault(pf.connector, (pf, []))[1].append(psp.id)
    plat_spans = {sid for _, ids in plats.values() for sid in ids}
    if d.check_form == "external" and not set(d.check_spans) & plat_spans:
        if open_ok:  # 未登记的平台不再拒题（open-lane 裁决附加条件 2）：进开放道，地址只作材料
            note(
                "platform_unregistered",
                "goal.check",
                "起草认为判定权在外部平台，但原文里的地址不是已登记的平台：按开放道去做，平台的结果不当判定。"
                "要让平台说了算，先去设置页登记这个平台，再从平台导入",
            )
        else:
            note(
                "platform_unregistered",
                "goal.check",
                "起草认为判定权在外部平台，但原文里的地址不是已登记的平台：先去设置页登记这个平台，再从平台导入",
                "refuse",
            )
    if secret is None and len(plats) > 1:
        note(
            "ambiguous_platform", "goal.check", f"原文里认出不止一个已登记的平台：{'、'.join(sorted(plats))}", "refuse"
        )
    if secret is None and len(plats) == 1:
        ((f, hit_ids),) = plats.values()
        tasks = cat.task_refs(f, ext.text)
        task = tasks[0] if len(tasks) == 1 else ""
        if not tasks:
            note("no_task_ref", "goal.check", f"认出平台 {f.connector}，但原文里没有它的任务号", "refuse")
        elif len(tasks) > 1:
            note("ambiguous_task", "goal.check", f"原文里有不止一个任务号：{'、'.join(tasks)}", "refuse")
        judges = [f.judge_id]
        check = {"judge_id": f.judge_id, "binding": {"connector": f.connector, "task": task}}
        external = {"connector": f.connector, "judge_id": f.judge_id, "task": task}
        der.append(
            _src("goal.check", f"{f.judge_id} · 平台 {f.connector} 的回执", "table", hit_ids, "地址查连接器档案")
        )
        der.append(_src("goal.binding.task", task, "span", note="按档案的任务号形状，逐字取自原文"))
        note(
            "external_platform",
            "goal.check",
            f"判定权在平台 {f.connector}：创建时由连接器领题（平台此刻开始计时），候选由判官代为提交，"
            "按平台回执判定；外部判定的任务都要你确认",
        )
        if d.check_form == "command" or ext.of("code"):
            note("submit_example_material", "goal.check", "原文里的命令没有当成检查命令：判定权在平台，它只作材料")
    elif secret is not None:
        if d.check_form == "command":
            note("command_ignored", "goal.check", "有标准答案，忽略起草指认的检查命令，按答案匹配")
        jid = str(cat.judge("answer") or dfl["answer_judge"])
        judges, check = [jid], {"judge_id": jid, "sealed": [ANSWER_SLOT]}
        der.append(_src("goal.check", f"{jid} · 答案在保密库", "table", note="答案由人给出，起草模型看不到"))
        deliverable = ext.span(d.deliverable).value if d.deliverable else str(dfl["deliverable"])  # type: ignore[union-attr]
        der.append(
            _src(
                "deliverable",
                deliverable,
                "span" if d.deliverable else "table",
                [d.deliverable] if d.deliverable else None,
            )
        )
    elif d.check_form == "command" and d.check_spans and not open_ok:
        sp = ext.span(d.check_spans[0])
        assert sp is not None
        spec = str(sp.value)
        jid = str(cat.judge("command") or dfl["command_judge"])
        judges = [jid]
        check = {"judge_id": jid, "spec_ref": "$spec", "expect": dict(dfl["command_expect"])}
        der.append(_src("goal.check", f"{jid} · {spec}", "span", [sp.id], "“这条命令就是完成标准”由起草模型指认"))
        note(
            "command_criterion",
            "goal.check",
            "判官会在洁净容器里重放这条命令，按退出码判定；开题后不能改。如果它是向外部平台提交，它就不是检查："
            "重放会再提交一次，或者因为出不去网被判失败。外部平台说了算的任务，请先登记这个平台，再从平台导入",
        )
        outw = _outbound(spec, ext, intake.outbound)
        if outw:
            needs_ack = "command"
            note(
                "command_outbound",
                "goal.check",
                f"这条命令有外发的形状（{'、'.join(outw)}）：勾选“我确认这条命令只检查、不提交”之后才能创建",
            )
    elif acceptance:
        jid = str(cat.judge("human") or dfl.get("human_judge", "structure_check"))
        judges, check = [jid], {"judge_id": jid}
        accept, items = "human", _acceptance(ext, acceptance, der, note)
        der.append(_src("goal.check", f"{jid} · 只看交付物的形状，只给读数", "table", note="人工验收：由你逐条判"))
        note(
            "human_acceptance",
            "goal.check",
            "人工验收：交付后由你按清单逐条判，终态最多为“已验收”，不写“已证明”；清单创建后不能改",
        )
    elif open_ok:
        # 开放道（open-lane §3.1）：不登记判据、不设候选次数；智能体从原话出发自己找答案，交付时带证据
        judges, check, accept = [], {}, "open"
        if d.check_form == "answer":
            note("answer_missing", "goal.check", "起草认为有标准答案，但答案栏与原文里都没有答案行：按开放道去找它")
        for sid in d.check_spans if d.check_form == "command" else []:
            sp = ext.span(sid)
            assert sp is not None
            outw = _outbound(str(sp.value), ext, intake.outbound)
            if outw:  # 有外发形状的命令（多半是向平台提交）不当自检项：让智能体“自检”时再提交一次就错了
                der.append(_src("goal.check", sp.value, "span", [sid], "有外发的形状，只留在题面里，不当自检项"))
                note(
                    "command_outbound_material",
                    "goal.check",
                    f"原文里的命令有外发的形状（{'、'.join(outw)}）：不当自检项，只留在题面里。"
                    "执行时要访问外部地址，会按需申请，由你批准",
                )
                continue
            items.append({"text": str(sp.value), "src": "span"})
            der.append(
                _src(f"goal.self_checks[{len(items) - 1}]", sp.value, "span", [sid], "交付前必须自己跑，如实报告")
            )
        if items:
            note(
                "command_self_check",
                "goal.check",
                "原文里的命令作为必做的自检项：智能体交付前自己跑、如实报告结果；判官不重放它。"
                "要按它的退出码判定，请选“严格判定”",
            )
        der.append(_src("goal.check", "开放道 · 不登记判据", "table", note="交付带证据，未经独立判定"))
    else:
        if d.check_form == "answer":
            note("answer_missing", "goal.check", "起草认为有标准答案，但答案栏与原文里都没有答案行", "refuse")
        why = "你选了严格判定，但" if strict else ""
        note("no_criterion", "goal.check", f"{why}没有标准答案，也没有能跑的检查命令：现有判定方式判不了它", "refuse")
        judges, check = [], {}
    if acceptance and accept == "judge":
        note("acceptance_ignored", "goal.check", "已有可判定的终点，验收清单没有用上：按判定器判定")
    if accept != "open":
        der.append(_src("goal.max_attempts", max_attempts, "table"))

    # ---------- 授权 ----------
    scope: list[dict[str, Any]] = []
    refs: list[str] = []
    mentions: list[dict[str, Any]] = []
    for sid, role in d.entries:
        sp = ext.span(sid)
        assert sp is not None
        if sid in plat_spans and external is not None:
            refs.append(sp.text)
            der.append(_src("materials", sp.text, "span", [sid], "平台地址：连接器经档案的固定通道访问，不进授权"))
            continue
        if role == "reference":
            refs.append(sp.text)
            der.append(_src("materials", sp.text, "span", [sid], "参考资料，只当文字，不开通路"))
            continue
        if settings.grants_runtime:
            # 开题零出站（runtime-grants §3.1）：入口只作原文高亮，执行时智能体按需申请，人或练习道白名单批
            mentions.append({"value": str(sp.value), "span": sid})
            der.append(_src("scope.mention", sp.value, "span", [sid], "执行时如需访问，会按需申请"))
            continue
        risk, row = settings.risk_of("net", str(sp.value), ["connect"])
        rule = {"resource": "net", "pattern": str(sp.value), "actions": ["connect"], "risk": risk}
        scope.append(rule)
        der.append(_src(f"scope[{len(scope) - 1}].pattern", sp.value, "span", [sid]))
        der.append(
            _src(
                f"scope[{len(scope) - 1}].risk",
                risk,
                "table",
                note=f"风险表第 {row + 1} 行" if row is not None else "未命中风险表，按规格缺省 r2",
            )
        )
        if row is None:
            note("risk_unmatched", f"scope[{len(scope) - 1}]", f"{sp.value} 不在风险表里，按 r2：每次用到都要你批准")
    claimed = {s for s, _ in d.entries}
    for sp in ext.of("addr") + ext.of("url"):
        if sp.id not in claimed:
            refs.append(sp.text)
            der.append(_src("materials", sp.text, "span", [sp.id], "起草没有指认的地址：只当文字，不开通路"))
    if not scope:
        scope.append({"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"})
        why = "开题零出站，执行时按需申请" if settings.grants_runtime else "原文里没有入口"
        der.append(_src("scope[0]", "workspace（不开任何出站）", "table", note=why))

    # ---------- 预算 ----------
    caps = settings.caps
    eligible_shape = secret is not None and _in_envelope(scope, intake.envelope)
    tier_src = "table"
    if eligible_shape:
        tier = "easy"
    elif d.tier_guess:
        tier, tier_src = d.tier_guess, "model"
    else:
        tier = str(dfl["tier"])
    prior = priors.lookup(tier, None)
    fb = dfl["fallback_budget"]
    usd = wall = 0
    if external is not None and d.deadline is not None:
        sp = ext.span(d.deadline)
        assert sp is not None
        der.append(_src("deadline", sp.text, "span", [d.deadline], "平台时限进截止时刻（领题时换算），不进花费预算"))
    for key, span_id, cap_key in (
        ("usd_milli", d.spend, "open_usd_milli"),
        ("wall_s", None if external is not None else d.deadline, "open_wall_s"),
    ):
        if span_id is not None:
            sp = ext.span(span_id)
            assert sp is not None
            val, src, spans_, why = int(sp.value), "span", [span_id], ""
        elif prior is not None:
            val, src, spans_, why = (
                int(getattr(prior, key)),
                "prior",
                None,
                f"档位 {tier}（{tier_src}）· {priors.version()}",
            )
        else:
            val, src, spans_, why = int(fb[key]), "table", None, "先验源查不到，用模板缺省"
        cap = int(caps[cap_key])
        if val > cap:
            note(f"clipped_{key}", f"budget.{key}", f"原值 {val} 超过单题硬顶 {cap}，已裁到 {cap}")
            why = (why + "；" if why else "") + f"裁到单题硬顶 {cap}"
            val = cap
        der.append(_src(f"budget.{key}", val, src, spans_, why))
        if key == "usd_milli":
            usd = val
        else:
            wall = val
    for sp_kind, chosen, label in (("money", d.spend, "金额"), ("duration", d.deadline, "时长")):
        if chosen is None and ext.of(sp_kind) and not raw and not (external is not None and sp_kind == "duration"):
            note(f"unclaimed_{sp_kind}", "budget", f"原文里有{label}，起草没有指认它；用的是默认值")
    if tier_src == "model":
        note("model_tier", "budget", f"档位 {tier} 是起草模型猜的")
    vs, bs = float(dfl["verify_share"]), float(dfl["bootstrap_share"])
    if prior is not None and prior.bootstrap_share is not None and not eligible_shape:
        bs = prior.bootstrap_share
    der.append(_src("budget.shares", {"verify_share": vs, "bootstrap_share": bs}, "table"))

    problem: dict[str, Any] | None = None
    if accept == "open":
        problem = {
            "title": d.title,
            "origin": {"statement_ref": "$statement", "materials": ["$references"] if refs else []},
            "goal": {"statement": goal_text, "accept": "open", **({"self_checks": items} if items else {})},
            "scope": scope,
            "budget": {"usd_milli": usd, "wall_s": wall, "verify_share": vs, "bootstrap_share": bs},
            "env": dict(dfl["env"]),
            "judges": [],
        }
    elif judges:
        problem = {
            "title": d.title,
            "origin": {"statement_ref": "$statement", "materials": ["$references"] if refs else []},
            "goal": {
                "statement": goal_text,
                "check": check,
                "max_attempts": max_attempts,
                "accept": accept,
                **({"acceptance": items} if items else {}),
            },
            "scope": scope,
            "budget": {"usd_milli": usd, "wall_s": wall, "verify_share": vs, "bootstrap_share": bs},
            "env": dict(dfl["env"]),
            "judges": judges,
        }

    # ---------- 外泄 ----------
    if secret is not None:
        s = norm(secret)
        leaks = [
            name
            for name, text in (
                ("题面", ext.text),
                ("题名", d.title),
                ("目标句", goal_text),
                ("材料", "\n".join(refs)),
                ("检查命令", spec or ""),
            )
            if s and s in norm(text)
        ]
        if leaks:
            note("answer_leak", "statement", f"答案出现在{'、'.join(leaks)}里：原文其它地方也写了答案", "refuse")

    # ---------- 练习道条件 ----------
    caps_ok = usd <= int(caps["practice_usd_milli"]) and wall <= int(caps["practice_wall_s"])
    narrowed = any(n.code.startswith("clipped_") for n in notes)
    guessed = any(n.code in ("model_tier", "unclaimed_money", "unclaimed_duration", "command_ignored") for n in notes)
    eligible = (
        eligible_shape
        and caps_ok
        and not narrowed
        and not guessed
        and max_attempts <= int(intake.envelope.get("goal", {}).get("max_attempts_max", max_attempts))
    )
    if accept == "open":
        pass  # 开放道不走零确认的练习道条件：它本来就不出确认卡
    elif secret is None:
        note("no_answer", "goal.check", "没有标准答案：不能零确认")
    elif not eligible_shape:
        note("outside_envelope", "scope", "授权不全在练习道信封里（只读、白名单地址）")
    elif not caps_ok:
        note("over_practice_cap", "budget", "预算超过练习上限")
    v = _done(notes, der, problem, ext, secret, refs, spec, nonce, priors, eligible, intake, zero_confirm, d)
    v.mentions = mentions
    if v.lane != "refuse":
        v.external, v.needs_ack = external, needs_ack
    return v


RAW_TITLE_MAX = 40  # 与草案 title 的上限相同（draft.parse_draft）


def _raw_ok(
    ext: Extraction, secret: str | None, acceptance: list[Mapping[str, Any]] | None, open_ok: bool, cat: Catalog
) -> bool:
    """起草不可用时能不能按原话直开（D14）：只在会进开放道的题上。人给了答案（要判官比对）、给了验收清单、
    选了严格判定或关了开放道、原文里认出已登记的平台（判定权在平台）时，都要草案里的结构，照旧拒绝。"""
    if not open_ok or secret is not None or acceptance or not ext.of("sentence"):
        return False
    return not any(cat.platform_of(str(sp.value)) for sp in ext.of("url") + ext.of("addr") + ext.of("host"))


def _raw_draft(ext: Extraction) -> Draft:
    """按原话的草案：目标是原文的全部句子，题名取第一句的开头；不指认入口、交付物、检查命令、金额、时长与档位。
    确定性代码，不调模型：同一段原文恒得同一份。"""
    sents = ext.of("sentence")
    first = " ".join(str(sents[0].value).split())
    title = first if len(first) <= RAW_TITLE_MAX else first[: RAW_TITLE_MAX - 1] + "…"
    return Draft(title=title or "按原话开题", goal_sentence=tuple(sp.id for sp in sents))


ACCEPTANCE_MAX, ACCEPTANCE_TEXT_MAX = 32, 200  # 与内核 goal.acceptance 的上限相同


def _acceptance(
    ext: Extraction, given: list[Mapping[str, Any]], der: list[dict[str, Any]], note: Any
) -> list[dict[str, Any]]:
    """把人给的清单变成 goal.acceptance 的提交形态：区间取原文（出处“摘”），其余是人写的（出处“人”）。
    不合格的条目让这张卡落到拒绝道，不替人改写。"""
    out: list[dict[str, Any]] = []
    if len(given) > ACCEPTANCE_MAX:
        note("acceptance_bad", "goal.acceptance", f"验收清单至多 {ACCEPTANCE_MAX} 条", "refuse")
        return out
    for k, a in enumerate(given):
        sid, text = a.get("span"), a.get("text")
        sp = ext.span(sid) if isinstance(sid, str) else None
        if sp is not None:
            body, src, spans = sp.text.strip(), "span", [sp.id]
        elif sid is None and isinstance(text, str):
            body, src, spans = text.strip(), "human", None
        else:
            note("acceptance_bad", "goal.acceptance", f"第 {k + 1} 条不是原文区间，也不是你写的陈述", "refuse")
            continue
        if not body or len(body) > ACCEPTANCE_TEXT_MAX:
            note("acceptance_bad", "goal.acceptance", f"第 {k + 1} 条须为 1 到 {ACCEPTANCE_TEXT_MAX} 字", "refuse")
            continue
        item = {"text": body, "src": src}
        if a.get("needs") in ("artifact", "note"):
            item["needs"] = a["needs"]
        out.append(item)
        der.append(_src(f"goal.acceptance[{len(out) - 1}]", body, "span" if spans else "human", spans))
    return out


def _outbound(spec: str, ext: Extraction, words: Mapping[str, Any]) -> list[str]:
    """命令有没有外发的形状（§5.8 加重警告）：含地址区间、写方法的 HTTP 动词、原文里有“提交”一类词。
    词表在 intake.yaml。"""
    why: list[str] = []
    if any(sp.text in spec for sp in ext.of("url") + ext.of("addr") + ext.of("host")):
        why.append("命令里有地址")
    verbs = [v for v in words.get("verbs", []) if re.search(r"(?<!\S)" + re.escape(str(v)) + r"(?!\S)", spec, re.I)]
    if verbs:
        why.append("写方法 " + "、".join(str(v) for v in verbs))
    hits = [w for w in words.get("words", []) if str(w).lower() in ext.text.lower()]
    if hits:
        why.append("原文有“" + "、".join(str(w) for w in hits) + "”")
    return why


def _in_envelope(scope: list[dict[str, Any]], env: Mapping[str, Any]) -> bool:
    allow = env.get("allow", {})
    max_risk = RISK_RANK[str(allow.get("max_risk", "r0"))]
    for r in scope:
        if r["resource"] not in allow.get("resources", []) or RISK_RANK[r["risk"]] > max_risk:
            return False
        if r["resource"] == "net" and not any(fnmatchcase(r["pattern"], p) for p in allow.get("net_patterns", [])):
            return False
    return True


def _done(
    notes: list[Note],
    der: list[dict[str, Any]],
    problem: dict[str, Any] | None,
    ext: Extraction,
    secret: str | None,
    refs: list[str],
    spec: str | None,
    nonce: str,
    priors: PriorSource,
    eligible: bool,
    intake: Intake,
    zero_confirm: bool | None,
    d: Draft | None = None,
) -> Vetted:
    zc = intake.zero_confirm if zero_confirm is None else zero_confirm
    if any(n.lane == "refuse" for n in notes) or problem is None:
        lane, eligible = "refuse", False
    elif problem["goal"].get("accept") == "open":
        lane, eligible = "open", False
        if any(r["resource"] != "workspace" for r in problem["scope"]):
            # 运行时扩权关着时原文里的入口会在开题时开通：这时不能零确认（open-lane §3.1 第 3 点的前提）
            lane = "confirm"
            notes.append(
                Note("open_needs_confirm", "scope", "运行时扩权关着，开题就会开通原文里的地址：请确认", "confirm")
            )
    elif eligible and zc:
        lane = "practice"
    else:
        lane = "confirm"
        if eligible:
            notes.append(Note("zero_confirm_off", "lane", "练习道候选；零确认尚未放行，请确认", "confirm"))
    if d is not None and d.model:
        der.append(_src("draft.model", d.model, "table", note="起草模型档案"))
    pid = "kt-" + hashlib.sha256((ext.text + "\x00" + nonce).encode()).hexdigest()[:12]
    return Vetted(lane, eligible, notes, der, problem, ext.text, refs, spec, secret, pid, priors.version())


def derivation_bytes(v: Vetted) -> bytes:
    """出处账的登记形态（input 类 Artifact 的正文）：规范化 JSON，不含答案。"""
    return json.dumps({"pid": v.pid, **v.public()}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


KNOWLEDGE_MODES = ("auto", "pick", "off")


def _knowledge_pref(raw: Any) -> dict[str, Any] | None:
    """知识选项 → prefs.knowledge；auto（缺省）返回 None，不写。资料 id 是否存在由书库在检索时认。"""
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) - {"mode", "pick"} or raw.get("mode") not in KNOWLEDGE_MODES:
        raise ValueError(f"knowledge 是 {{mode, pick?}}，mode 取 {'、'.join(KNOWLEDGE_MODES)}")
    pick = raw.get("pick") or []
    if not isinstance(pick, list) or not all(isinstance(x, str) and x for x in pick):
        raise ValueError("knowledge.pick 是资料 id 的列表")
    if raw["mode"] == "pick" and not pick:
        raise ValueError("选“指定”时至少勾一份资料")
    if raw["mode"] == "auto":
        return None
    return {"mode": "pick", "pick": list(dict.fromkeys(pick))} if raw["mode"] == "pick" else {"mode": "off"}


def override(v: Vetted, ov: Mapping[str, Any], settings: Settings) -> Vetted:
    """确认卡上人能改的两类（设计 §7.3）：每条授权规则的风险（三选一）与预算的金额、时限。纯函数。

    ov = {"risk": {"<规则下标>": "r0|r1|r2"}, "usd_milli": int, "wall_s": int, "model": 档案名,
          "knowledge": {mode: auto|pick|off, pick?: [资料 id]}}，都可省。
    model 是任务级模型偏好（宪章 03 §3.1），只能取设置页已登记的档案名，写进 open_problem 的 prefs.model。
    knowledge 是任务的知识选项（资料库第二期，K3）：auto 是缺省，不写进事件；pick / off 写进 prefs.knowledge。
    改过的字段出处记"人"；只要改过一项，这道题就不再是练习道候选（零确认只给没人碰过的草案）。
    超过单题硬顶、风险取值不合法、下标越界一律 ValueError，不裁剪：人写的数不替人改。
    """
    if v.input is None or v.lane == "refuse":
        raise ValueError("拒绝道没有可改的字段")
    keys = {"risk", "usd_milli", "wall_s", "ack_command", "model", "knowledge"}
    if set(ov) - keys:
        raise ValueError(
            f"只能改 risk、usd_milli、wall_s、ack_command、model、knowledge，不能改 {sorted(set(ov) - keys)}"
        )
    inp = json.loads(json.dumps(v.input))
    der = [dict(x) for x in v.derivation]
    touched: list[str] = []

    def mark(field_: str, value: Any) -> None:
        for row in der:
            if row["field"] == field_:
                if row["value"] == value:
                    return
                row.update(value=value, source="human", note="人在确认卡上改")
                row.pop("spans", None)
                touched.append(field_)
                return
        raise ValueError(f"出处账里没有 {field_}")

    risk = ov.get("risk") or {}
    if not isinstance(risk, Mapping):
        raise ValueError("risk 须是 {规则下标: 风险}")
    for k, r in risk.items():
        i = int(k)
        if not 0 <= i < len(inp["scope"]) or inp["scope"][i]["resource"] == "workspace":
            raise ValueError(f"没有可改风险的第 {i} 条规则")
        if r not in RISK_RANK:
            raise ValueError(f"风险只能取 r0/r1/r2，不是 {r!r}")
        if inp["scope"][i]["risk"] != r:
            inp["scope"][i]["risk"] = r
            mark(f"scope[{i}].risk", r)
    for key, cap_key in (("usd_milli", "open_usd_milli"), ("wall_s", "open_wall_s")):
        if key not in ov:
            continue
        val = ov[key]
        if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
            raise ValueError(f"{key} 须为正整数")
        cap = int(settings.caps[cap_key])
        if val > cap:
            raise ValueError(f"{key} = {val} 超过单题硬顶 {cap}")
        if inp["budget"][key] != val:
            inp["budget"][key] = val
            mark(f"budget.{key}", val)
    model = ov.get("model")
    if model is not None:
        names = [p.get("name") for p in (settings.models or {}).get("profiles") or []]
        if not isinstance(model, str) or model not in names:
            raise ValueError(
                f"模型档案 {model!r} 未登记：只能从设置页的档案里选（{'、'.join(map(str, names)) or '无'}）"
            )
        if (inp.get("prefs") or {}).get("model") != model:
            inp["prefs"] = {**(inp.get("prefs") or {}), "model": model}
            der = [r for r in der if r["field"] != "prefs.model"]
            der.append(_src("prefs.model", model, "human", note="人在确认卡上选的执行模型档案"))
            touched.append("prefs.model")
    kn = _knowledge_pref(ov.get("knowledge"))
    if kn is not None and (inp.get("prefs") or {}).get("knowledge") != kn:
        inp["prefs"] = {**(inp.get("prefs") or {}), "knowledge": kn}
        der = [r for r in der if r["field"] != "prefs.knowledge"]
        der.append(_src("prefs.knowledge", kn, "human", note="人在新建时选的知识选项"))
        touched.append("prefs.knowledge")
    ack = ov.get("ack_command")
    if ack is not None and not isinstance(ack, bool):
        raise ValueError("ack_command 须是 true 或 false")
    needs_ack = v.needs_ack
    if ack and v.needs_ack == "command":
        needs_ack = None
        der.append(_src("goal.check.ack", "我确认这条命令只检查、不提交", "human", note="人在确认卡上勾选"))
        touched.append("goal.check.ack")
    if not touched:
        return v
    gone = {"zero_confirm_off"} | {"clipped_" + f.split(".", 1)[1] for f in touched if f.startswith("budget.")}
    notes = [n for n in v.notes if n.code not in gone]
    notes.append(Note("human_edit", "lane", f"你在卡上改了 {'、'.join(touched)}", "confirm"))
    lane = "open" if v.lane == "open" else "confirm"  # 开放道改了预算仍是开放道：人改过的数本来就是人定的
    out = Vetted(lane, False, notes, der, inp, v.statement, v.references, v.spec, v.secret, v.pid, v.priors_version)
    out.external, out.needs_ack, out.notice = v.external, needs_ack, v.notice
    return out
