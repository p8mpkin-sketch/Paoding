"""内核：validate 与 apply（规格 §3.1.2）。I1：两者都是纯函数，不读时钟、不做 IO、不调用模型。

- `validate(state, actor, kind, body, cfg)` → `Ok(body')` 或 `Reject(code, detail)`。
  body' 是将要写进事件的规范化事件体，含图服务派生的字段（画像、判官快照、producer）。
  cfg 是只读配置（判官注册表、资源插件、配额）；它的取值在 validate 时写进事件体，所以重放不依赖它。
- `apply(state, event)` → 新状态。新对象的 id 由事件的 seq 派生：a_<seq>、f_<seq>、i_<seq>、j_<seq>。
- 等级不在状态里（I3）。需要等级时经 levels.py 调用从参考模型搬运来的函数重算。

异常只在解析层接：提议体经 parse.Obj 读取，形状不对抛 BadBody，validate 把它（以及事件体不可规范化的
JCSError）转成 schema_error。校验函数里其余的异常是内核自己的缺陷，原样抛出，不伪装成输入错误。
状态与事件的类型在 state.py。

按事件族分成子模块，每个子模块里校验（`_v_*`）与应用（`_a_*`）分开写：
`problem`（开题、登记、画像覆盖）、`fact`（论断）、`intent`（Intent、审批、Hint）、`judge`（判官请求与裁决）、
`lease`（租约四操作与用量）、`close`（关题与预算标记）、`grants`（运行时扩权）；共用的结果类型、配置与解析在 `common`。
本模块只做分派：谁能提交什么、题目与令牌的前置检查、异常到 schema_error 的转换。
IO 前置条件不在这里：Blob 是否存在、哈希是否相符由服务层在调用 validate 之前检查。
"""

from __future__ import annotations

from typing import cast

from .. import work as wk  # noqa: F401  —— 测试经 reducer.wk 替换内核函数，确认内核缺陷原样抛出
from ..jcs import JCSError, canonicalize
from ..parse import BadBody, Obj
from ..state import Actor, Body, Event, State
from . import close, fact, grants, intent, judge, lease, problem, recall
from .common import Applier, Config, Ok, Reject, TimedValidator, Validator, empty_state
from .fact import content_key

__all__ = [
    "AFTER_CLOSE",
    "KINDS",
    "Config",
    "Ok",
    "Reject",
    "apply",
    "content_key",
    "empty_state",
    "result_id",
    "validate",
]

# ---------- 谁可以提交什么（§3.1.2 操作表） ----------


def _who(actor: Actor, kind: str) -> bool:
    k, role = actor["kind"], actor.get("role")
    if kind == "open_problem":
        return k == "human"
    if kind == "register_artifact":
        return k in ("executor", "adapter", "judge", "human")  # 类别与令牌的匹配另查
    if kind == "add_fact":
        return k == "adapter" and role in ("bootstrap", "explore", "reason", "recall")  # recall 另有白名单
    if kind == "add_intent":
        return (k == "adapter" and role == "reason") or k == "human"
    if kind == "request_judge":
        return k in ("adapter", "sinan", "human")
    if kind == "judge_verdict":
        return k == "judge"
    if kind == "lease":
        return k in ("sinan", "judge")  # 租约种类与身份的匹配另查
    if kind in ("renew", "release"):
        return k in ("sinan", "judge", "adapter")  # 限持有者，另查
    if kind == "expire_lease":
        return k == "watchdog"
    if kind == "abandon_intent":
        return (k == "adapter" and role == "reason") or k == "human"
    if kind in ("hint", "approve", "profile_override"):
        return k == "human"
    if kind == "cost":
        return k in ("adapter", "judge")
    if kind == "close_problem":
        return k in ("graph", "watchdog", "human")
    if kind == "budget_mark":
        return k == "graph"
    if kind == "request_scope":  # 申请不是授权；图服务只替带 needs_scope 的 Intent 申请（另查）
        return (k == "adapter" and role in grants.REQUEST_ROLES) or k in ("human", "graph")
    if kind == "grant_scope":  # 人；或图服务按确定性判定（另查，判定在 validate 里重算）
        return k in ("human", "graph")
    if kind == "revoke_scope":
        return k == "human"
    return False


KINDS = (
    "open_problem",
    "register_artifact",
    "add_fact",
    "add_intent",
    "request_judge",
    "judge_verdict",
    "lease",
    "renew",
    "release",
    "expire_lease",
    "abandon_intent",
    "hint",
    "approve",
    "cost",
    "close_problem",
    "budget_mark",
    "profile_override",
    "request_scope",
    "grant_scope",
    "revoke_scope",
)
AFTER_CLOSE = ("cost", "release")  # 关题后在途任务仍可交回用量与释放租约


def _handback(state: State, actor: Actor, pid: str, kind: str, body: Body) -> bool:
    """关题那一刻还在途的会话，可以把自己的留档（authored 类）登记进来再释放租约。

    题目常常是被会话自己提交的候选关掉的：判官一通过，图服务立刻关题，而会话还没来得及交回留档。
    只认"令牌的会话是本题一条仍在途的租约"；authored 类永不入 grounds（I2），不影响任何等级。"""
    if kind != "register_artifact" or body.get("class") != "authored":
        return False
    held = state["leases"].get(actor.get("session") or "")
    return held is not None and held["problem_id"] == pid and held["active"]


_TIMED: dict[str, TimedValidator] = {
    "lease": lease._v_lease,
    "renew": lease._v_renew,
    "release": lease._v_release,
    "expire_lease": lease._v_expire_lease,
}

_VALIDATORS: dict[str, Validator] = {
    "open_problem": problem._v_open_problem,
    "register_artifact": problem._v_register_artifact,
    "profile_override": problem._v_profile_override,
    "add_fact": fact._v_add_fact,
    "add_intent": intent._v_add_intent,
    "abandon_intent": intent._v_abandon_intent,
    "approve": intent._v_approve,
    "hint": intent._v_hint,
    "request_judge": judge._v_request_judge,
    "judge_verdict": judge._v_judge_verdict,
    "cost": lease._v_cost,
    "close_problem": close._v_close_problem,
    "budget_mark": close._v_budget_mark,
    "request_scope": grants._v_request_scope,
    "grant_scope": grants._v_grant_scope,
    "revoke_scope": grants._v_revoke_scope,
}

_APPLIERS: dict[str, Applier] = {
    "open_problem": problem._a_open_problem,
    "register_artifact": problem._a_register_artifact,
    "profile_override": problem._a_profile_override,
    "add_fact": fact._a_add_fact,
    "add_intent": intent._a_add_intent,
    "abandon_intent": intent._a_abandon_intent,
    "approve": intent._a_approve,
    "hint": intent._a_hint,
    "request_judge": judge._a_request_judge,
    "judge_verdict": judge._a_judge_verdict,
    "lease": lease._a_lease,
    "renew": lease._a_renew,
    "release": lease._a_end_lease,
    "expire_lease": lease._a_end_lease,
    "cost": lease._a_cost,
    "close_problem": close._a_close_problem,
    "budget_mark": close._a_budget_mark,
    "request_scope": grants._a_request_scope,
    "grant_scope": grants._a_grant_scope,
    "revoke_scope": grants._a_revoke_scope,
}
assert set(_VALIDATORS) | set(_TIMED) == set(KINDS) == set(_APPLIERS)


def validate(
    state: State, actor: Actor, pid: str, kind: str, body: Body, cfg: Config, ts: int | None = None
) -> Ok | Reject:
    """ts：这条事件将被赋予的时间戳（服务层的时钟，作为参数传入）；缺省取 state["now"]。"""
    if kind not in KINDS:
        return Reject("schema_error", f"未知操作 {kind}")
    if not isinstance(body, dict):
        return Reject("schema_error", "body 必须是对象")
    if not _who(actor, kind):
        return Reject("forbidden_op", f"{actor['kind']}/{actor.get('role')} 不能提交 {kind}")
    if kind != "open_problem" and not (kind == "register_artifact" and body.get("class") == "input"):
        p = state["problems"].get(pid)
        if p is None:
            return Reject("unknown_ref", f"题目 {pid} 未开")
        if p["closed"] and kind not in AFTER_CLOSE and not _handback(state, actor, pid, kind, body):
            return Reject("schema_error", "题目已关闭")
        held = state["leases"].get(actor.get("session") or "")
        if held is not None and held["problem_id"] != pid:  # 任务令牌随租约签发，只在租约所属的题内有效
            return Reject("scope_mismatch", f"令牌的会话 {held['id']} 属于别题")
    narrowed = recall.whitelist(state, actor, pid, kind, body)  # 增量 8：recall 角色的操作白名单
    if narrowed is not None:
        return narrowed
    try:  # 只接解析层的异常：提议体形状不对，或其中有不可规范化的值
        b = Obj(body)
        if kind in _TIMED:
            out = _TIMED[kind](state, actor, pid, b, cfg, state["now"] if ts is None else ts)
        else:
            out = _VALIDATORS[kind](state, actor, pid, b, cfg)
        if isinstance(out, Ok):
            canonicalize(out.body)  # 事件体要进哈希链与状态哈希，必须是可规范化的 JSON 值
        return out
    except BadBody as e:
        return Reject("schema_error", str(e))
    except JCSError as e:  # 只可能来自提议体里的值（超出双精度的整数、NaN 等）
        return Reject("schema_error", f"提议体不可规范化：{e}")


# ---------- apply ----------


def apply(state: State, ev: Event) -> State:
    """纯函数：返回新状态，不修改入参。只复制被改动的集合（各族的 _a_* 在浅副本上替换集合）。"""
    s = cast(State, dict(state))
    s["now"] = ev["ts"]
    s["seq"] = ev["seq"]
    applier = _APPLIERS.get(ev["kind"])
    if applier is None:
        raise ValueError(f"apply：未知事件 {ev['kind']}")
    applier(s, ev)
    return s


def result_id(ev: Event) -> str | None:
    """一条事件给提议方的返回 id。"""
    prefix = {
        "register_artifact": "a",
        "add_fact": "f",
        "add_intent": "i",
        "request_judge": "j",
        "lease": "l",
        "request_scope": "r",
    }.get(ev["kind"])
    if ev["kind"] == "hint" and "close" not in ev["body"]:
        prefix = "h"
    if ev["kind"] == "add_fact" and ev["body"].get("merge_into"):
        return str(ev["body"]["merge_into"])
    return f"{prefix}_{ev['seq']}" if prefix else None
