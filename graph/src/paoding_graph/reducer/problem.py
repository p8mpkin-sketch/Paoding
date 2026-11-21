"""开题族：open_problem、register_artifact、profile_override（画像的推导与事后覆盖）。"""

from __future__ import annotations

from typing import cast

from .. import refmodel as rm
from ..parse import Obj
from ..practice import LANES, violations
from ..state import Actor, Artifact, Body, Check, Event, JudgeEntry, Problem, Profile, ScopeRule, State
from . import knowledge, recall
from .common import _HEX64, RISK_RANK, RISKS, WALL_MODES, Config, Ok, Reject, _check, _reason, _ref, _rule

# ---------- 校验 ----------


def _derive_profile(scope: list[ScopeRule], goal_judge: JudgeEntry | None, cfg: Config) -> Profile:
    """画像推导（§3.1.2）。人不填写；只在开题、范围修订与人工覆盖时重算，结果写进事件体。
    goal_judge 为 None：开放道的题没有 Goal 判官（docs/design/open-lane/ §8），判定轴为 none。"""
    reversibility = max((r["risk"] for r in scope), key=RISK_RANK.__getitem__)
    if goal_judge is None or goal_judge["grade"] == "advisory":
        judge = "none"
    elif goal_judge["kind"] == "deferred" or goal_judge["grade"] == "consistent":
        judge = "deferred"
    elif goal_judge["max_cost"] <= cfg.cheap_judge_max_cost:
        judge = "hard"
    else:
        judge = "costly"
    info = "partial" if any(r["resource"] in cfg.external_resources for r in scope) else "complete"
    return {"info": info, "judge": judge, "reversibility": reversibility}


AUTHORITIES = ("local", "external", "human", "self")
DEADLINE_SOURCES = ("local", "external")


def authority_of(goal_judge: JudgeEntry | None, accept: str) -> str:
    """判定来源（external-verdict §4.2）：由 Goal 判官快照与 goal.accept 推出，不由提交方声明。

    与 `_derive_profile` 同为开题时的派生量，放在一处：#93 的扩权随 scope 重算画像，判定来源不随 scope 变，
    所以扩权路径只调 `_derive_profile`，开题路径两者都调。accept=human（宪章 D3）落地之前，内核只会推出 local
    或 external。开放道（accept=open，docs/design/open-lane/ §5）没有判官，结论只是智能体的自述：self。"""
    if accept == "open" or goal_judge is None:
        return "self"
    if accept == "human":
        return "human"
    return "external" if goal_judge.get("authority") == "external" else "local"


ACCEPTS = ("judge", "human", "open")
SELF_CHECK_MAX = 16  # 开放道的必做自检项上限（原文里出现的检查命令，open-lane §4.2、裁决 §12 第 2 条）
SELF_CHECK_TEXT_MAX = 2000
ACCEPTANCE_MAX = 32  # 验收清单条目上限
ACCEPTANCE_TEXT_MAX = 200  # 每条陈述的字数上限（宪章 02 §3.3）
ACCEPTANCE_SRC = ("span", "human")  # 只许原文区间或人写（裁决附加 1）；模型起草的条目不进清单
ACCEPTANCE_NEEDS = ("artifact", "note")


def _acceptance(g: Obj, accept: str) -> list[Body] | Reject:
    """验收清单（宪章 D3、02 §3.3）：accept=human 的题必带，开题时登记、之后不可改；编号 a1、a2… 由图服务分配。
    accept=judge 的题不接受清单：A 道与 B1 没有 accept 操作，终态只有 solved 与 unsolved。"""
    if accept == "judge":
        return Reject("schema_error", "只有 accept=human 的题带验收清单") if "acceptance" in g else []
    items = g.children("acceptance", None) if "acceptance" in g else None
    if not items:
        return Reject("schema_error", "accept=human 的题须带非空的验收清单 goal.acceptance[]")
    if len(items) > ACCEPTANCE_MAX:
        return Reject("schema_error", f"验收清单至多 {ACCEPTANCE_MAX} 条")
    out: list[Body] = []
    for i, it in enumerate(items, start=1):
        if not {"text", "src"} <= it.keys() <= {"text", "src", "needs"}:
            return Reject("schema_error", "验收条目须为 {text, src, needs?}；编号由图服务分配，提交时不接受")
        text = it.text("text").strip()
        if not text or len(text) > ACCEPTANCE_TEXT_MAX:
            return Reject("schema_error", f"验收条目 {i} 的陈述须非空、不超过 {ACCEPTANCE_TEXT_MAX} 字")
        if it.get("src") not in ACCEPTANCE_SRC:
            return Reject("schema_error", f"验收条目的来源只许 {ACCEPTANCE_SRC}：模型起草的条目不进清单")
        if "needs" in it and it.get("needs") not in ACCEPTANCE_NEEDS:
            return Reject("schema_error", f"验收条目的 needs 取 {ACCEPTANCE_NEEDS}")
        out.append(
            {
                "id": f"a{i}",
                "text": text,
                "src": it.string("src"),
                **({"needs": it.string("needs")} if "needs" in it else {}),
            }
        )
    return out


def _open_goal(g: Obj, judges: list[str]) -> Body | Reject:
    """开放道的 Goal（docs/design/open-lane/ §3、§8）：只有陈述，不登记判据、不设候选次数、不带验收清单。
    原文里的检查命令进 self_checks：会话交付前必须自己跑、如实报告，判官不重放它，终态也不因它而变。"""
    if not g.keys() <= {"statement", "accept", "self_checks"}:
        extra = sorted(g.keys() - {"statement", "accept", "self_checks"})
        return Reject("schema_error", f"开放道的 Goal 只有 statement、accept，可选 self_checks；不接受 {extra}")
    if judges:
        return Reject("schema_error", "开放道不启用判官：judges 须为空")
    statement = g.text("statement").strip()
    if not statement:
        return Reject("schema_error", "开放道的 Goal 须有非空的陈述")
    out: Body = {"statement": g.text("statement"), "accept": "open"}
    if "self_checks" in g:
        items = g.children("self_checks")
        if not 1 <= len(items) <= SELF_CHECK_MAX:
            return Reject("schema_error", f"self_checks 须为 1 到 {SELF_CHECK_MAX} 条")
        checks: list[Body] = []
        for i, it in enumerate(items, start=1):
            if it.keys() != {"text", "src"} or it.get("src") not in ACCEPTANCE_SRC:
                return Reject("schema_error", f"自检项须为 {{text, src: {'|'.join(ACCEPTANCE_SRC)}}}；编号由图服务分配")
            text = it.text("text").strip()
            if not text or len(text) > SELF_CHECK_TEXT_MAX:
                return Reject("schema_error", f"自检项 {i} 须非空、不超过 {SELF_CHECK_TEXT_MAX} 字")
            checks.append({"id": f"c{i}", "text": text, "src": it.string("src")})
        out["self_checks"] = checks
    return out


def _deadline(state: State, pid: str, d: Obj) -> Body | Reject:
    """时限（§5.6）：local 开题即给绝对时刻；external 开题时给（附出处）或留待 bind_deadline 绑定一次。"""
    if not d.keys() <= {"source", "at", "bound_by"} or d.get("source") not in DEADLINE_SOURCES:
        return Reject("schema_error", "deadline 须为 {source: local|external, at?, bound_by?}")
    out: Body = {"source": d.string("source")}
    if "at" in d:
        at = d.get("at")
        if type(at) is not int or at <= 0:
            return Reject("schema_error", "deadline.at 须为正整数（毫秒）")
        out["at"] = at
    if out["source"] == "local":
        if "at" not in out or "bound_by" in d:
            return Reject("schema_error", "source=local 的 deadline 须给 at，不带 bound_by")
    elif ("at" in out) != ("bound_by" in d):
        return Reject(
            "schema_error", "source=external 的 deadline：at 与 bound_by 同给（开题时领题）或都不给（运行时绑定）"
        )
    if "bound_by" in d:
        ref = d.string("bound_by")
        err = _ref(state, pid, ref, "deadline.bound_by")
        if err:
            return err
        if state["artifacts"][ref]["class"] != "input":
            return Reject("inadmissible_class", "开题时的 deadline.bound_by 只接受 input 类（资源公告）")
        out["bound_by"] = ref
    return out


def _prefs(pr: Obj, cfg: Config) -> Body | Reject:
    """任务级偏好（宪章 03 §3.1）：model，一个已登记的模型档案名（端点与密钥不能在任务里填）；
    knowledge 见 knowledge.prefs（资料库第二期，K3）。"""
    if not pr.keys() <= {"model", "knowledge"}:
        return Reject("schema_error", "prefs 只有 model 与 knowledge 两项：端点、密钥等只能在设置页改")
    out: Body = {}
    if "knowledge" in pr:
        kp = knowledge.prefs(pr.child("knowledge"))
        if isinstance(kp, Reject):
            return kp
        out["knowledge"] = kp
    if "model" in pr:
        name = pr.text("model")
        if name not in cfg.model_profiles:
            known = "、".join(sorted(cfg.model_profiles)) or "无"
            return Reject("unknown_ref", f"模型档案 {name!r} 未登记（已登记：{known}）：任务级只能从设置页的档案里选")
        out["model"] = name
    return out


def _v_open_problem(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    if pid in state["problems"]:
        return Reject("schema_error", "题目已存在")
    if "profile" in body:
        return Reject("schema_error", "profile 是派生字段，提交时不接受")
    allowed = {"title", "origin", "goal", "scope", "budget", "env", "judges"}
    # v1.5 增量 9、10；external-verdict §5.6；prefs 为任务级偏好（宪章 03 §3.1、地图 Q12）：可选，缺省时事件体与旧版相同
    optional = {"labels", "recall", "deadline", "prefs"}
    if not allowed <= body.keys() <= allowed | optional:
        return Reject("schema_error", f"字段应为 {sorted(allowed)}，可选 {sorted(optional)}")
    judges = body.strings("judges")
    for j in judges:
        if j not in cfg.judges:
            return Reject("unknown_ref", f"判官 {j} 未注册")
    g = body.child("goal")
    if "authority" in g:
        return Reject("schema_error", "goal.authority 是派生字段，提交时不接受")
    accept = g.get("accept")
    if accept not in ACCEPTS:
        return Reject("schema_error", f"goal.accept 取 {ACCEPTS}")
    check: Check | None = None
    max_attempts: int | None = None
    if accept == "open":  # 开放道（open-lane §8）：Goal 没有判官，结论随交付附证据，不由判官判定
        opened = _open_goal(g, judges)
        if isinstance(opened, Reject):
            return opened
        goal: Body = opened
    else:
        check = _check(g.child("check"), goal=True)
        if check["judge_id"] not in judges:
            return Reject("unknown_ref", "Goal 判官不在本题启用的判官里")
        acceptance = _acceptance(g, accept)
        if isinstance(acceptance, Reject):
            return acceptance
        ma = g.get("max_attempts")
        if type(ma) is not int or ma < 1:
            return Reject("schema_error", "goal.max_attempts 必须是正整数")
        max_attempts = ma
        if "self_checks" in g:
            return Reject("schema_error", "self_checks 只用于开放道：判定道的完成标准是登记的判据")
        goal = {**g.raw, "check": check, **({"acceptance": acceptance} if acceptance else {})}
    scope = [_rule(r) for r in body.children("scope")]
    if not scope:
        return Reject("schema_error", "scope 必填且非空")
    b = body.child("budget")
    budget: Body = {k: b.number(k) for k in ("usd_milli", "wall_s", "verify_share", "bootstrap_share")}
    if "tokens" in b:
        budget["tokens"] = b.number("tokens")
    if not (
        budget["usd_milli"] > 0
        and budget["wall_s"] > 0
        and 0 <= budget["verify_share"] <= 1
        and 0 <= budget["bootstrap_share"] <= 1
        and budget.get("tokens", 1) > 0
    ):
        return Reject("schema_error", "预算必须为正，份额在 [0,1]")
    for key, cap, unit in (("usd_milli", cfg.open_cap_usd_milli, "毫美元"), ("wall_s", cfg.open_cap_wall_s, "秒")):
        if cap is not None and budget[key] > cap:
            return Reject("over_budget", f"budget.{key}={budget[key]} 超过单题硬顶 {cap} {unit}")
    o = body.child("origin")
    if not {"statement_ref", "materials"} <= o.keys() <= {"statement_ref", "materials", "draft"}:
        return Reject("schema_error", "origin 字段应为 statement_ref、materials，可选 draft")
    statement_ref, materials = o.string("statement_ref"), o.strings("materials")
    draft: Body | None = None
    if "draft" in o:
        # 一句话开题（增量 13）：出处账的引用与道别。policy 由图服务从已加载的信封抄入，提交时不接受
        d = o.child("draft")
        if d.keys() != {"record", "lane"} or d.get("lane") not in LANES:
            return Reject("schema_error", f"origin.draft 须为 {{record, lane: {'|'.join(LANES)}}}")
        draft = {"record": d.string("record"), "lane": d.string("lane")}
        if (draft["lane"] == "open") != (accept == "open"):  # 道别与 Goal 的形态一一对应，不许错配
            return Reject("schema_error", "lane=open 当且仅当 goal.accept=open")
    for ref in [statement_ref, *materials, *([draft["record"]] if draft else [])]:
        err = _ref(state, pid, ref, "Origin 引用")
        if err:
            return err
        if state["artifacts"][ref]["class"] != "input":
            return Reject("inadmissible_class", "Origin 只接受 input 类")
    if draft is not None and draft["lane"] == "practice":
        # 练习道信封（增量 15）：零确认没有人在回路里，"它最多能做什么"只在这里、由唯一写入者检查
        if cfg.practice is None:
            return Reject("forbidden_op", "本部署没有加载练习道信封，不接受练习道开题")
        assert check is not None and max_attempts is not None  # 练习道 ⇒ 不是开放道（上面已查错配）
        bad = violations(cfg.practice, list(scope), check, budget, max_attempts)
        if bad:
            return Reject("forbidden_op", "练习道信封不许：" + "；".join(bad))
        draft["policy"] = cfg.practice.stamp()
    snapshot = {j: cfg.judges[j] for j in judges}
    gj = snapshot[check["judge_id"]] if check is not None else None
    authority = authority_of(gj, g.string("accept"))
    # 外部裁决的开题三条检查（external-verdict §5.2）：只认结构，不读档案内容（红线 3）
    if authority == "human" and gj is not None and gj.get("authority") == "external":
        return Reject("schema_error", "判定权在外部平台的题不接受 accept=human：终态由平台回执定")
    if authority == "external" and gj is not None and check is not None and max_attempts is not None:
        conn = gj.get("connector")
        if conn is None:
            return Reject("unknown_ref", f"判官 {check['judge_id']} 的连接器档案没有加载，不接受外部裁决开题")
        binding = check.get("binding")
        if binding is None:
            return Reject("schema_error", "外部裁决的 Goal 判据须带 binding {connector, task, max_submissions}")
        if binding["connector"] != conn["id"]:
            return Reject(
                "schema_error", f"binding.connector={binding['connector']} 与判官快照的连接器 {conn['id']} 不符"
            )
        if max_attempts > binding["max_submissions"]:
            return Reject(
                "schema_error", f"goal.max_attempts={max_attempts} 超过平台提交额度 {binding['max_submissions']}"
            )
    elif check is not None and "binding" in check:
        return Reject("schema_error", "只有外部裁决的判官接受 binding")
    deadline: Body | None = None
    if "deadline" in body:
        dl = _deadline(state, pid, body.child("deadline"))
        if isinstance(dl, Reject):
            return dl
        deadline = dl
    if cfg.wall_mode not in WALL_MODES:
        raise ValueError(f"Config.wall_mode 只取 {WALL_MODES}")  # 组装根的缺陷，不是输入错误
    prefs: Body | None = None
    if "prefs" in body:
        pr = _prefs(body.child("prefs"), cfg)
        if isinstance(pr, Reject):
            return pr
        prefs = pr
    extras = recall.open_extras(state, pid, body, judges)
    if isinstance(extras, Reject):
        return extras
    return Ok(
        {
            "title": body.text("title"),
            "origin": {
                "statement_ref": statement_ref,
                "materials": materials,
                **({"draft": draft} if draft is not None else {}),
            },
            "goal": {**goal, **({"authority": authority} if authority != "local" else {})},
            "scope": scope,
            "budget": budget,
            "env": body.child("env").raw,
            "judges": judges,
            "judge_snapshot": {j: dict(e) for j, e in snapshot.items()},
            "profile": _derive_profile(scope, gj, cfg),
            **extras,
            **({"deadline": deadline} if deadline is not None else {}),
            # 任务级模型偏好（工作台设计 C13）：只记名字，不进等级、消费门与画像；会话开起时按它解析一次
            **({"prefs": prefs} if prefs is not None else {}),
            # 时限语义开关（§5.6）：缺省 elapsed 时事件体与旧版相同；spend 时连同最长存活一起抄入
            **({"wall_mode": "spend", "life_s": cfg.life_s} if cfg.wall_mode == "spend" else {}),
            # 开放道交付后闲置自动关的时长（地图 Q33）：开题时抄入，在途题不随设置变
            **({"idle_close_s": cfg.idle_close_s} if accept == "open" and cfg.idle_close_s is not None else {}),
            # 开放道交付后复核（地图 Q34）：开题时抄入，在途题不随设置变；没抄入的题不复核
            **({"review": True} if accept == "open" and cfg.review_open else {}),
            # 宪章 D5：开在哪一版设置之下。由图服务抄入，提交体里不接受；不进等级、消费门与画像
            **({"settings": {"version": cfg.settings[0], "digest": cfg.settings[1]}} if cfg.settings else {}),
            # 焚决 F3：开在哪一套功法之下。同 settings：由图服务抄入，提交体里不接受；不进等级、消费门与画像。
            # 旧事件没有这个字段，读端把它读作第 0 阶（旧法）
            **({"gongfa": {"jie": cfg.gongfa[0], "digest": cfg.gongfa[1]}} if cfg.gongfa else {}),
        }
    )


_EXEC_FIELDS = {
    "sandbox_id",
    "base",
    "baseline_ref",
    "tool",
    "command",
    "cwd",
    "exit_code",
    "touched",
    "started_at",
    "ended_at",
    "truncated",
}


def _v_register_artifact(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    cls = body.string("class")
    kn: Body | None = None
    if cls == "knowledge":
        r = knowledge.artifact(actor, pid, body, state)
        if isinstance(r, Reject):
            return r
        kn = r
    elif "knowledge" in body:
        return Reject("schema_error", "只有 knowledge 类带 knowledge 出处字段")
    elif cls not in rm.REGISTRAR:
        return Reject("schema_error", f"未知类别 {cls}")
    elif rm.validate_register(actor["kind"], cls) != "ok":
        return Reject("forbidden_op", f"{actor['kind']} 的令牌不能登记 {cls} 类")
    if pid not in state["problems"] and actor["kind"] != "human":
        return Reject("unknown_ref", f"题目 {pid} 未开")
    if "producer" in body:
        return Reject("schema_error", "producer 由令牌决定，提交时不接受")
    size = body.req("size")
    if not _HEX64.match(body.string("hash")) or type(size) is not int or size < 0:
        return Reject("schema_error", "hash 须为 sha256，size 须为非负整数")
    ex: Body | None = None
    if cls in ("exec", "judge"):
        if "exec" not in body or body.child("exec").keys() != _EXEC_FIELDS:
            return Reject("schema_error", f"{cls} 类必须带完整的 exec 出处字段")
        ex = dict(body.child("exec").raw)
    elif "exec" in body:
        return Reject("schema_error", "只有 exec 与 judge 类带 exec 出处字段")
    parents = body.strings("parents", [])
    for p in parents:
        err = _ref(state, pid, p, "parent")
        if err:
            return err
    producer = {"actor": actor["id"], **({"session": actor["session"]} if "session" in actor else {})}
    return Ok(
        {
            "hash": body.string("hash"),
            "size": size,
            "media_type": body.text("media_type"),
            "class": cls,
            "parents": parents,
            "producer": producer,
            **({"exec": ex} if ex is not None else {}),
            **({"knowledge": kn} if kn is not None else {}),
        }
    )


PROFILE_AXES: dict[str, tuple[str, ...]] = {
    "info": ("complete", "partial"),
    "judge": ("hard", "costly", "deferred", "none"),
    "reversibility": RISKS,
}


def _v_profile_override(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    """画像只能事后覆盖并留痕（裁决 A7）：逐轴覆盖，理由必填，推出值与覆盖值都留在事件体里。"""
    axis, value = body.string("axis"), body.string("value")
    if axis not in PROFILE_AXES:
        return Reject("schema_error", f"轴只取 {sorted(PROFILE_AXES)}")
    if value not in PROFILE_AXES[axis]:
        return Reject("schema_error", f"{axis} 只取 {PROFILE_AXES[axis]}")
    reason = _reason(body)
    if not reason:
        return Reject("schema_error", "覆盖须写理由")
    p = state["problems"][pid]
    derived = cast(dict[str, str], p.get("derived_profile", p["profile"]))
    return Ok({"axis": axis, "value": value, "reason": reason, "derived": derived[axis]})


def _v_bind_deadline(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    """运行时领题的外部时限（external-verdict §5.6）：判官令牌提交，只绑定一次，证据是本题的 judge 类回执。"""
    if body.keys() != {"at", "evidence"}:
        return Reject("schema_error", "bind_deadline 须为 {at, evidence}")
    dl = state["problems"][pid].get("deadline")
    if dl is None or dl["source"] != "external":
        return Reject("forbidden_op", "本题没有待绑定的外部时限")
    if "at" in dl:
        return Reject("forbidden_op", "外部时限已绑定，之后不可改")
    at = body.get("at")
    if type(at) is not int or at <= 0:
        return Reject("schema_error", "at 须为正整数（毫秒）")
    ref = body.string("evidence")
    err = _ref(state, pid, ref, "evidence")
    if err:
        return err
    if state["artifacts"][ref]["class"] != "judge":
        return Reject("inadmissible_class", "外部时限的证据须是判官运行器登记的 judge 类回执")
    return Ok({"at": at, "evidence": ref})


# ---------- 应用 ----------


def _a_open_problem(s: State, ev: Event) -> None:
    pid = ev["problem_id"]
    opened = cast(Problem, {**ev["body"], "id": pid, "closed": False, "opened_seq": ev["seq"], "opened_ts": ev["ts"]})
    s["problems"] = {**s["problems"], pid: opened}


def _a_register_artifact(s: State, ev: Event) -> None:
    aid = f"a_{ev['seq']}"
    s["artifacts"] = {**s["artifacts"], aid: cast(Artifact, {**ev["body"], "id": aid, "problem_id": ev["problem_id"]})}


def _a_profile_override(s: State, ev: Event) -> None:
    body, pid = ev["body"], ev["problem_id"]
    p = s["problems"][pid]
    s["problems"] = {
        **s["problems"],
        pid: {
            **p,
            "derived_profile": p.get("derived_profile", p["profile"]),
            "profile": cast(Profile, {**p["profile"], body["axis"]: body["value"]}),
            "profile_overrides": p.get("profile_overrides", [])
            + [
                {
                    "axis": body["axis"],
                    "value": body["value"],
                    "reason": body["reason"],
                    "derived": body["derived"],
                    "seq": ev["seq"],
                    "by": ev["actor"]["id"],
                }
            ],
        },
    }


def _a_bind_deadline(s: State, ev: Event) -> None:
    pid = ev["problem_id"]
    p = s["problems"][pid]
    bound: Problem = {**p, "deadline": {**p["deadline"], "at": ev["body"]["at"], "bound_by": ev["body"]["evidence"]}}
    s["problems"] = {**s["problems"], pid: bound}
