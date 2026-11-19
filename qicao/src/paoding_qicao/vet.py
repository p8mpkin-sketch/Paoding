"""校验（设计 §2 第③层）：确定性纯函数。不读时钟、不做 IO、不调模型。

vet(抽取结果, 答案栏, 草案, 模板数据, 设置快照, 先验源) → Vetted
- 出处：每个进入提交体的字段都有一行出处（摘 span / 表 table / 估 prior / 起草 model），见 derivation。
- 答案：只走专用栏或标签行；题面、题名、目标句、材料、检查命令里出现答案即拒绝（answer_leak）。
- 判据：有答案 → exact_match（sealed，保密库）；无答案而草案指认了原文代码块 → replay；都没有 → 拒绝。
  模型不能改变"有没有答案"，也不能写检查命令。
- 授权：只认草案标为 entry 的地址区间；风险查设置层的风险表，未命中按 r2。没有入口 → 只有 workspace（r0）。
- 预算：原文写的数 > 先验源（按档位）> 模板缺省；被单题硬顶裁剪，裁过即不得零确认。
- 分道：refuse | confirm | practice。practice 只在零确认开关打开且全部条件满足时给出；开关关着时记 eligible。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any

from .draft import Draft
from .extract import Extraction, norm
from .policy import RISK_RANK, Intake, PriorSource, Settings

ANSWER_SLOT = "$answer"  # 提交前由调用方换成保密库的 VaultRef


@dataclass(frozen=True)
class Note:
    code: str
    field: str
    text: str
    lane: str  # 它把道别压到哪一档：refuse | confirm


@dataclass
class Vetted:
    lane: str  # practice | confirm | refuse
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
) -> Vetted:
    notes: list[Note] = []
    der: list[dict[str, Any]] = []
    dfl = intake.defaults

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
    if d is None:
        note("bad_draft", "draft", f"起草结果不可用：{draft_error or '没有草案'}", "refuse")
        return _done(notes, der, None, ext, secret, [], None, nonce, priors, False, intake, zero_confirm)

    # ---------- 目标 ----------
    goal_text = "".join(ext.span(s).value for s in d.goal_sentence)  # type: ignore[union-attr]
    der.append(_src("goal.statement", goal_text, "span", list(d.goal_sentence)))
    der.append(_src("title", d.title, "model"))

    # ---------- 判据 ----------
    judges: list[str]
    check: dict[str, Any]
    spec: str | None = None
    max_attempts = int(dfl["max_attempts"])
    if secret is not None:
        if d.check_form == "command":
            note("command_ignored", "goal.check", "有标准答案，忽略起草指认的检查命令，按答案匹配")
        jid = str(dfl["answer_judge"])
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
    elif d.check_form == "command" and d.check_spans:
        sp = ext.span(d.check_spans[0])
        assert sp is not None
        spec = str(sp.value)
        jid = str(dfl["command_judge"])
        judges = [jid]
        check = {"judge_id": jid, "spec_ref": "$spec", "expect": dict(dfl["command_expect"])}
        der.append(_src("goal.check", f"{jid} · {spec}", "span", [sp.id], "“这条命令就是完成标准”由起草模型指认"))
        note("command_criterion", "goal.check", "没有标准答案，完成标准是原文里的一条命令；开题后不能改")
    else:
        if d.check_form == "answer":
            note("answer_missing", "goal.check", "起草认为有标准答案，但答案栏与原文里都没有答案行", "refuse")
        note("no_criterion", "goal.check", "没有标准答案，也没有能跑的检查命令：现有判定方式判不了它", "refuse")
        judges, check = [], {}
    der.append(_src("goal.max_attempts", max_attempts, "table"))

    # ---------- 授权 ----------
    scope: list[dict[str, Any]] = []
    refs: list[str] = []
    mentions: list[dict[str, Any]] = []
    for sid, role in d.entries:
        sp = ext.span(sid)
        assert sp is not None
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
    for key, span_id, cap_key in (
        ("usd_milli", d.spend, "open_usd_milli"),
        ("wall_s", d.deadline, "open_wall_s"),
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
        if chosen is None and ext.of(sp_kind):
            note(f"unclaimed_{sp_kind}", "budget", f"原文里有{label}，起草没有指认它；用的是默认值")
    if tier_src == "model":
        note("model_tier", "budget", f"档位 {tier} 是起草模型猜的")
    vs, bs = float(dfl["verify_share"]), float(dfl["bootstrap_share"])
    if prior is not None and prior.bootstrap_share is not None and not eligible_shape:
        bs = prior.bootstrap_share
    der.append(_src("budget.shares", {"verify_share": vs, "bootstrap_share": bs}, "table"))

    problem: dict[str, Any] | None = None
    if judges:
        problem = {
            "title": d.title,
            "origin": {"statement_ref": "$statement", "materials": ["$references"] if refs else []},
            "goal": {"statement": goal_text, "check": check, "max_attempts": max_attempts, "accept": "judge"},
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
    if secret is None:
        note("no_answer", "goal.check", "没有标准答案：不能零确认")
    elif not eligible_shape:
        note("outside_envelope", "scope", "授权不全在练习道信封里（只读、白名单地址）")
    elif not caps_ok:
        note("over_practice_cap", "budget", "预算超过练习上限")
    out = _done(notes, der, problem, ext, secret, refs, spec, nonce, priors, eligible, intake, zero_confirm, d)
    out.mentions = mentions
    return out


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


def override(v: Vetted, ov: Mapping[str, Any], settings: Settings) -> Vetted:
    """确认卡上人能改的两类（设计 §7.3）：每条授权规则的风险（三选一）与预算的金额、时限。纯函数。

    ov = {"risk": {"<规则下标>": "r0|r1|r2"}, "usd_milli": int, "wall_s": int}，都可省。
    改过的字段出处记"人"；只要改过一项，这道题就不再是练习道候选（零确认只给没人碰过的草案）。
    超过单题硬顶、风险取值不合法、下标越界一律 ValueError，不裁剪：人写的数不替人改。
    """
    if v.input is None or v.lane == "refuse":
        raise ValueError("拒绝道没有可改的字段")
    if set(ov) - {"risk", "usd_milli", "wall_s"}:
        raise ValueError(f"只能改 risk、usd_milli、wall_s，不能改 {sorted(set(ov) - {'risk', 'usd_milli', 'wall_s'})}")
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
    if not touched:
        return v
    gone = {"zero_confirm_off"} | {"clipped_" + f.split(".", 1)[1] for f in touched if f.startswith("budget.")}
    notes = [n for n in v.notes if n.code not in gone]
    notes.append(Note("human_edit", "lane", f"你在卡上改了 {'、'.join(touched)}", "confirm"))
    return Vetted(
        "confirm", False, notes, der, inp, v.statement, v.references, v.spec, v.secret, v.pid, v.priors_version
    )
