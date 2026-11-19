"""从平台导入（external-verdict §5.8 的主入口）：把连接器领回的一道题变成一张确认卡与一次开题批次。确定性纯函数。

领题（调平台的 brief 端点）是调用方的事（组装根的 connector_hub、pd connector import）：平台从领题那一刻开始计时，
服务地址此刻分配。这里只拿领回来的东西排版：

- 题面取说明全文里档案 fields.statement 指的那一段；说明全文（含服务地址）作资源公告，input 类材料（§5.5）。
- 判据 = 注册表里指向这个连接器的外部判官；绑定单 {connector, task, max_submissions}，次数取清单给的平台额度。
- 截止时刻 = 领题时刻 + 平台时限，bound_by 指向资源公告（§5.6）；花费预算照先验与单题硬顶，不放宽。
- 授权只有 workspace：服务地址在公告里，智能体要用照 #91 申请。连接器自己的出站不进 scope。
- 永远走确认道：交付是对外动作，会消耗平台额度。没有起草模型，出处只有“表”（档案、清单、说明）与“人”。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from .catalog import Form
from .policy import Intake, PriorSource, Settings
from .vet import Note, Vetted, _src


class ImportError_(ValueError):  # noqa: N801  （不与内建 ImportError 同名）
    pass


def import_vetted(
    form: Form,
    item: Mapping[str, Any],
    statement: str,
    notice: bytes,
    intake: Intake,
    settings: Settings,
    priors: PriorSource,
    *,
    now_ms: int,
    nonce: str = "",
    budget: Mapping[str, Any] | None = None,
) -> Vetted:
    """item：清单里的这一条，{task, title, time_limit_s, max_submissions}（按档案 items 指针取出）。
    budget：人在卡上改过的 {usd_milli?, wall_s?}；超过单题硬顶即 ImportError_，不替人裁。"""
    dfl, caps = intake.defaults, settings.caps
    task, title = str(item.get("task") or ""), str(item.get("title") or item.get("task") or "")
    limit, quota = item.get("time_limit_s"), item.get("max_submissions")
    if not task or not statement.strip():
        raise ImportError_("平台的清单或说明里缺任务号或题面")
    if not (isinstance(quota, int) and quota > 0):
        raise ImportError_("平台没有给提交次数上限（档案 items.max_submissions）：次数由内核计，必须先知道平台额度")
    notes: list[Note] = [
        Note(
            "external_platform",
            "goal.check",
            f"判定权在平台 {form.connector}：已领题（平台从此刻开始计时），候选由判官代为提交，按平台回执判定；"
            "外部判定的任务都要你确认",
            "confirm",
        )
    ]
    der: list[dict[str, Any]] = [
        _src("title", title[:40], "table", note="平台清单"),
        _src("goal.statement", "平台回执为通过", "table"),
        _src("goal.check", f"{form.judge_id} · 平台 {form.connector} 的回执", "table", note="连接器档案"),
        _src("goal.binding.task", task, "table", note="平台清单"),
    ]
    attempts = min(int(dfl["max_attempts"]), quota)
    der.append(_src("goal.max_attempts", attempts, "table", note=f"平台额度 {quota} 次，取较小者"))
    deadline: dict[str, Any] = {"source": "external", "bound_by": "$notice"}
    if isinstance(limit, int) and limit > 0:
        deadline["at"] = now_ms + limit * 1000
        der.append(_src("deadline", f"领题后 {limit} 秒", "table", note="平台时限进截止时刻，不进花费预算"))
    else:
        notes.append(
            Note("no_deadline", "deadline", "平台没有给时限：截止时刻留空，只受花费预算与最长存活约束", "confirm")
        )
    tier = str(dfl["tier"])
    prior = priors.lookup(tier, None)
    fb = dfl["fallback_budget"]
    vals: dict[str, int] = {}
    for key, cap_key in (("usd_milli", "open_usd_milli"), ("wall_s", "open_wall_s")):
        cap = int(caps[cap_key])
        human = (budget or {}).get(key)
        if human is not None:
            if not isinstance(human, int) or isinstance(human, bool) or human <= 0:
                raise ImportError_(f"{key} 须为正整数")
            if human > cap:
                raise ImportError_(f"{key} = {human} 超过单题硬顶 {cap}")
            vals[key] = human
            der.append(_src(f"budget.{key}", human, "human", note="人在确认卡上改"))
            continue
        val, src, why = (
            (int(getattr(prior, key)), "prior", f"档位 {tier}（table）· {priors.version()}")
            if prior is not None
            else (int(fb[key]), "table", "先验源查不到，用模板缺省")
        )
        if val > cap:
            why += f"；裁到单题硬顶 {cap}"
            val = cap
        vals[key] = val
        der.append(_src(f"budget.{key}", val, src, note=why))
    vs, bs = float(dfl["verify_share"]), float(dfl["bootstrap_share"])
    if prior is not None and prior.bootstrap_share is not None:
        bs = prior.bootstrap_share
    der.append(_src("budget.shares", {"verify_share": vs, "bootstrap_share": bs}, "table"))
    der.append(
        _src("scope[0]", "workspace（不开任何出站）", "table", note="服务地址在资源公告里；要用照运行时扩权申请")
    )
    problem = {
        "title": title[:40],
        "origin": {"statement_ref": "$statement", "materials": ["$notice"]},
        "goal": {
            "statement": "平台回执为通过",
            "check": {
                "judge_id": form.judge_id,
                "binding": {"connector": form.connector, "task": task, "max_submissions": quota},
            },
            "max_attempts": attempts,
            "accept": "judge",
        },
        "scope": [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}],
        "budget": {**vals, "verify_share": vs, "bootstrap_share": bs},
        "env": dict(dfl["env"]),
        "judges": [form.judge_id],
        "deadline": deadline,
    }
    pid = "kt-" + hashlib.sha256(f"{form.connector}\x00{task}\x00{nonce}".encode()).hexdigest()[:12]
    v = Vetted("confirm", False, notes, der, problem, statement, [], None, None, pid, priors.version())
    v.external = {"connector": form.connector, "judge_id": form.judge_id, "task": task}
    v.notice = notice
    return v
