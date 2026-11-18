"""内核：validate 与 apply（规格 §3.1.2）。I1：两者都是纯函数，不读时钟、不做 IO、不调用模型。

- `validate(state, actor, kind, body, cfg)` → `Ok(body')` 或 `Reject(code, detail)`。
  body' 是将要写进事件的规范化事件体，含图服务派生的字段（画像、判官快照、producer）。
  cfg 是只读配置（判官注册表、资源插件、配额）；它的取值在 validate 时写进事件体，所以重放不依赖它。
- `apply(state, event)` → 新状态。新对象的 id 由事件的 seq 派生：a_<seq>、f_<seq>、i_<seq>、j_<seq>。
- 等级不在状态里（I3）。需要等级时经 levels.py 调用从参考模型搬运来的函数重算。

异常只在解析层接：提议体经 parse.Obj 读取，形状不对抛 BadBody，validate 把它（以及事件体不可规范化的
JCSError）转成 schema_error。校验函数里其余的异常是内核自己的缺陷，原样抛出，不伪装成输入错误。
状态与事件的类型在 state.py。
IO 前置条件不在这里：Blob 是否存在、哈希是否相符由服务层在调用 validate 之前检查。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, cast

from . import cards
from . import levels as lv
from . import refmodel as rm
from . import work as wk
from .envelope import sha256_hex
from .jcs import JCSError, canonicalize
from .parse import BadBody, Obj
from .resources import external_resources
from .state import (Actor, Amount, Artifact, Body, Check, Cost, Done, Event, Fact, Hint, Intent, JudgeEntry, Lease,
                    Problem, Profile, Request, ScopeRule, State, Verdict)

RISKS = ("r0", "r1", "r2")
RISK_RANK = {r: i for i, r in enumerate(RISKS)}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Ok:
    body: Body


@dataclass(frozen=True)
class Reject:
    code: str
    detail: str = ""
    card: tuple[str, str] | None = None   # stale_view 时所指的卡 (kind, target)；服务层据此附上链头的最新卡片


@dataclass(frozen=True)
class Config:
    judges: dict[str, JudgeEntry] = field(default_factory=dict)      # judge_id → {version, grade, kind, max_cost}
    external_resources: frozenset[str] = field(default_factory=external_resources)  # 取自 resources.py 登记表
    cheap_judge_max_cost: float = 0.05                # "廉价判官"阈值（美元），配置项
    fact_quota: int = 20                              # 每个任务（会话）的写入配额
    intent_quota: int = 8
    intent_budget_usd_milli: tuple[int, int] = (1, 10_000_000)  # add_intent 预算区间


def empty_state() -> State:
    return {"problems": {}, "artifacts": {}, "facts": {}, "intents": {}, "requests": {},
            "verdicts": [], "content_keys": {}, "revoked": [], "approvals": {}, "lease_seqs": {},
            "abandoned": [], "leases": {}, "hints": {}, "costs": [], "now": 0, "seq": 0}


# ---------- 谁可以提交什么（§3.1.2 操作表） ----------

def _who(actor: Actor, kind: str) -> bool:
    k, role = actor["kind"], actor.get("role")
    if kind == "open_problem":
        return k == "human"
    if kind == "register_artifact":
        return k in ("executor", "adapter", "judge", "human")      # 类别与令牌的匹配另查
    if kind == "add_fact":
        return k == "adapter" and role in ("bootstrap", "explore", "reason")
    if kind == "add_intent":
        return (k == "adapter" and role == "reason") or k == "human"
    if kind == "request_judge":
        return k in ("adapter", "sinan", "human")
    if kind == "judge_verdict":
        return k == "judge"
    if kind == "lease":
        return k in ("sinan", "judge")                              # 租约种类与身份的匹配另查
    if kind in ("renew", "release"):
        return k in ("sinan", "judge", "adapter")                   # 限持有者，另查
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
    return False


KINDS = ("open_problem", "register_artifact", "add_fact", "add_intent", "request_judge", "judge_verdict",
         "lease", "renew", "release", "expire_lease", "abandon_intent", "hint", "approve", "cost",
         "close_problem", "budget_mark", "profile_override")
AFTER_CLOSE = ("cost", "release")                  # 关题后在途任务仍可交回用量与释放租约


def _handback(state: State, actor: Actor, pid: str, kind: str, body: Body) -> bool:
    """关题那一刻还在途的会话，可以把自己的留档（authored 类）登记进来再释放租约。

    题目常常是被会话自己提交的候选关掉的：判官一通过，图服务立刻关题，而会话还没来得及交回留档。
    只认"令牌的会话是本题一条仍在途的租约"；authored 类永不入 grounds（I2），不影响任何等级。"""
    if kind != "register_artifact" or body.get("class") != "authored":
        return False
    held = state["leases"].get(actor.get("session") or "")
    return held is not None and held["problem_id"] == pid and held["active"]


def validate(state: State, actor: Actor, pid: str, kind: str, body: Body, cfg: Config,
             ts: int | None = None) -> Ok | Reject:
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
        if held is not None and held["problem_id"] != pid:      # 任务令牌随租约签发，只在租约所属的题内有效
            return Reject("scope_mismatch", f"令牌的会话 {held['id']} 属于别题")
    try:                                    # 只接解析层的异常：提议体形状不对，或其中有不可规范化的值
        b = Obj(body)
        if kind in _TIMED:
            out = _TIMED[kind](state, actor, pid, b, cfg, state["now"] if ts is None else ts)
        else:
            out = _VALIDATORS[kind](state, actor, pid, b, cfg)
        if isinstance(out, Ok):
            canonicalize(out.body)          # 事件体要进哈希链与状态哈希，必须是可规范化的 JSON 值
        return out
    except BadBody as e:
        return Reject("schema_error", str(e))
    except JCSError as e:                   # 只可能来自提议体里的值（超出双精度的整数、NaN 等）
        return Reject("schema_error", f"提议体不可规范化：{e}")


# ---------- 解析：提议体里反复出现的几种形状 ----------

def _rule(r: Obj) -> ScopeRule:
    risk = r.string("risk", "r2")                     # 缺省 r2
    if risk not in RISKS:
        raise BadBody(f"risk 非法：{risk}")
    return {"resource": r.text("resource"), "pattern": r.text("pattern"), "actions": r.texts("actions"),
            "risk": risk}


def _check(c: Obj) -> Check:
    extra = c.keys() - {"judge_id", "spec_ref", "expect", "sealed", "control"}
    if extra:
        raise BadBody(f"check 多余字段 {sorted(extra)}")
    if "control" in c:
        raise BadBody("check.control 是 M1 的对照判据，M0 未启用")
    out: Check = {"judge_id": c.string("judge_id")}
    if "spec_ref" in c:
        out["spec_ref"] = c.string("spec_ref")
    if "expect" in c:
        out["expect"] = c.get("expect")
    if "sealed" in c:
        out["sealed"] = []
        for v in c.children("sealed"):
            if v.keys() != {"vault", "digest"} or not _HEX64.match(v.string("digest")):
                raise BadBody("sealed 必须是 VaultRef{vault, digest}")
            out["sealed"].append({"vault": v.text("vault"), "digest": v.string("digest")})
    return out


def _amount(b: Obj) -> Amount:
    """租约的预留：三条轨都取整，不能为负。"""
    out: Amount = {"usd_milli": b.integer("usd_milli"), "wall_s": b.integer("wall_s", 0)}
    if b.get("tokens") is not None:
        out["tokens"] = b.integer("tokens")
    if out["usd_milli"] < 0 or out["wall_s"] < 0 or out.get("tokens", 0) < 0:
        raise BadBody("预算不能为负")
    return out


def _ref(state: State, pid: str, ref: str, what: str) -> Reject | None:
    """引用的 Artifact 必须存在且属于本题。"""
    a = state["artifacts"].get(ref)
    if a is None:
        return Reject("unknown_ref", f"{what} {ref} 不存在")
    if a["problem_id"] != pid:
        return Reject("scope_mismatch", f"{what} {ref} 属于别题")
    return None


def _node(state: State, node_id: str) -> Fact | Intent | None:
    return state["facts"].get(node_id) or state["intents"].get(node_id)


# ---------- open_problem ----------

def _derive_profile(scope: list[ScopeRule], goal_judge: JudgeEntry, cfg: Config) -> Profile:
    """画像推导（§3.1.2）。人不填写；只在开题、范围修订与人工覆盖时重算，结果写进事件体。"""
    reversibility = max((r["risk"] for r in scope), key=RISK_RANK.__getitem__)
    if goal_judge["grade"] == "advisory":
        judge = "none"
    elif goal_judge["kind"] == "deferred" or goal_judge["grade"] == "consistent":
        judge = "deferred"
    elif goal_judge["max_cost"] <= cfg.cheap_judge_max_cost:
        judge = "hard"
    else:
        judge = "costly"
    info = "partial" if any(r["resource"] in cfg.external_resources for r in scope) else "complete"
    return {"info": info, "judge": judge, "reversibility": reversibility}


def _v_open_problem(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    if pid in state["problems"]:
        return Reject("schema_error", "题目已存在")
    if "profile" in body:
        return Reject("schema_error", "profile 是派生字段，提交时不接受")
    allowed = {"title", "origin", "goal", "scope", "budget", "env", "judges"}
    if body.keys() != allowed:
        return Reject("schema_error", f"字段应为 {sorted(allowed)}")
    judges = body.strings("judges")
    for j in judges:
        if j not in cfg.judges:
            return Reject("unknown_ref", f"判官 {j} 未注册")
    g = body.child("goal")
    check = _check(g.child("check"))
    if check["judge_id"] not in judges:
        return Reject("unknown_ref", "Goal 判官不在本题启用的判官里")
    if g.get("accept") != "judge":
        return Reject("schema_error", "M0 只实现 accept=judge")
    max_attempts = g.get("max_attempts")
    if type(max_attempts) is not int or max_attempts < 1:
        return Reject("schema_error", "goal.max_attempts 必须是正整数")
    goal = {**g.raw, "check": check}
    scope = [_rule(r) for r in body.children("scope")]
    if not scope:
        return Reject("schema_error", "scope 必填且非空")
    b = body.child("budget")
    budget: Body = {k: b.number(k) for k in ("usd_milli", "wall_s", "verify_share", "bootstrap_share")}
    if "tokens" in b:
        budget["tokens"] = b.number("tokens")
    if not (budget["usd_milli"] > 0 and budget["wall_s"] > 0 and 0 <= budget["verify_share"] <= 1
            and 0 <= budget["bootstrap_share"] <= 1 and budget.get("tokens", 1) > 0):
        return Reject("schema_error", "预算必须为正，份额在 [0,1]")
    o = body.child("origin")
    statement_ref, materials = o.string("statement_ref"), o.strings("materials")
    for ref in [statement_ref, *materials]:
        err = _ref(state, pid, ref, "Origin 引用")
        if err:
            return err
        if state["artifacts"][ref]["class"] != "input":
            return Reject("inadmissible_class", "Origin 只接受 input 类")
    snapshot = {j: cfg.judges[j] for j in judges}
    return Ok({"title": body.text("title"), "origin": {"statement_ref": statement_ref, "materials": materials},
               "goal": goal, "scope": scope, "budget": budget,
               "env": body.child("env").raw, "judges": judges,
               "judge_snapshot": {j: dict(e) for j, e in snapshot.items()},
               "profile": _derive_profile(scope, snapshot[check["judge_id"]], cfg)})


# ---------- register_artifact ----------

_EXEC_FIELDS = {"sandbox_id", "base", "baseline_ref", "tool", "command", "cwd", "exit_code",
                "touched", "started_at", "ended_at", "truncated"}


def _v_register_artifact(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    cls = body.string("class")
    if cls not in rm.REGISTRAR:
        return Reject("schema_error", f"未知类别 {cls}")
    if rm.validate_register(actor["kind"], cls) != "ok":
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
    return Ok({"hash": body.string("hash"), "size": size, "media_type": body.text("media_type"),
               "class": cls, "parents": parents, "producer": producer,
               **({"exec": ex} if ex is not None else {})})


# ---------- add_fact ----------

def _ref_artifacts(state: State) -> dict[str, Any]:
    return {aid: rm.Artifact(aid, a["class"], a["problem_id"]) for aid, a in state["artifacts"].items()}


def content_key(state: State, f: Body) -> str:
    """内容键（§3.1.2）：观察类取 check 的规范化哈希（spec_ref 按 Blob 哈希代入）；推断类取 title 与排序后的 premises。"""
    if f["claim_type"] == "observation":
        c = dict(f["check"])
        if "spec_ref" in c:
            c["spec_ref"] = state["artifacts"][c["spec_ref"]]["hash"]
        return "o:" + sha256_hex(canonicalize(c))
    return "i:" + sha256_hex(canonicalize([f["title"], sorted(f["premises"])]))


def _session_count(nodes: dict[str, Fact] | dict[str, Intent], session: str | None) -> int:
    return sum(1 for x in nodes.values() if session and x["session"] == session)


def _v_add_fact(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    allowed = {"title", "summary", "body_ref", "claim_type", "check", "premises", "grounds"}
    if "yielded_by" in body:
        return Reject("schema_error", "yielded_by 由租约推出，不由提议方填写")
    if not body.keys() <= allowed:
        return Reject("schema_error", f"多余字段 {sorted(body.keys() - allowed)}")
    claim_type, title, summary = body.string("claim_type"), body.string("title"), body.string("summary", "")
    if claim_type not in ("observation", "inference"):
        return Reject("schema_error", "claim_type 非法")
    if len(title) > 120 or len(summary) > 600:
        return Reject("schema_error", "title ≤120、summary ≤600 字符")
    premises, grounds = body.strings("premises", []), body.strings("grounds", [])
    check = _check(body.child("check")) if body.get("check") is not None else None
    body_ref = body.opt_string("body_ref")
    for ref in [body_ref, check.get("spec_ref") if check else None]:
        if ref is None:
            continue
        err = _ref(state, pid, ref, "引用")
        if err:
            return err
    # 等级不出题（I7）：前提指向别题的节点一律 scope_mismatch
    for p in premises:
        node = _node(state, p)
        if node is not None and node["problem_id"] != pid:
            return Reject("scope_mismatch", f"前提 {p} 属于别题")
    lvls = lv.levels(state, pid)
    code = str(rm.validate_add_fact(_ref_artifacts(state), lvls, pid, claim_type, check is not None,
                                    tuple(premises), tuple(grounds)))
    if code != "ok":
        return Reject(code)
    if _session_count(state["facts"], actor.get("session")) >= cfg.fact_quota:
        return Reject("quota_exceeded", f"本任务已写 {cfg.fact_quota} 条论断")
    out: Body = {"title": title, "summary": summary, "claim_type": claim_type,
                 "premises": premises, "grounds": grounds,
                 **({"check": check} if check else {}),
                 **({"body_ref": body_ref} if body_ref else {})}
    key = content_key(state, out)
    existing = state["content_keys"].get(pid, {}).get(key)
    return Ok({**out, "content_key": key, **({"merge_into": existing} if existing else {})})


# ---------- add_intent ----------

def _v_add_intent(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    later = {"follows", "executor", "rollback", "delegate"} & body.keys()
    if later:
        return Reject("schema_error", f"{sorted(later)} 属于后续里程碑，M0 未启用")
    allowed = {"title", "summary", "premises", "risk", "budget", "done", "needs_scope", "expected_gain"}
    if not body.keys() <= allowed:
        return Reject("schema_error", f"多余字段 {sorted(body.keys() - allowed)}")
    prob = state["problems"][pid]
    risk = body.string("risk")
    if risk not in RISKS:
        return Reject("schema_error", "risk 非法")
    needs = [_rule(r) for r in body.children("needs_scope", None)]
    ceiling = max((r["risk"] for r in prob["scope"] + needs), key=RISK_RANK.__getitem__)
    if RISK_RANK[risk] > RISK_RANK[ceiling]:
        return Reject("scope_mismatch", f"risk {risk} 高于授权范围的最高风险 {ceiling}")
    premises = body.strings("premises", [])
    lvls = lv.levels(state, pid)
    for p in premises:
        node = _node(state, p)
        if node is not None and node["problem_id"] != pid:
            return Reject("scope_mismatch", f"前提 {p} 属于别题")
        if p not in lvls:
            return Reject("unknown_ref", f"前提 {p} 不存在或不是带判据的 Intent")
        if lvls[p] == rm.X:
            return Reject("stale_premise", f"前提 {p} 已被证伪")
    done: Done | None = None
    if body.get("done") is not None:
        d = body.child("done")
        if "tests" in d:
            return Reject("schema_error", "done.tests 属于完整版")
        rest = Obj({k: v for k, v in d.raw.items() if k != "max_attempts"}, d.where)
        done = cast(Done, {**_check(rest), "max_attempts": d.integer("max_attempts")})
        if done["judge_id"] not in prob["judges"]:
            return Reject("unknown_ref", "done 的判官不在本题启用的判官里")
    bud = body.child("budget")
    budget: Body = {k: bud.number(k) for k in ("usd_milli", "wall_s", "tokens") if k in bud or k == "usd_milli"}
    lo, hi = cfg.intent_budget_usd_milli
    if not (lo <= budget["usd_milli"] <= hi) or any(v < 0 for v in budget.values()):
        return Reject("schema_error", f"预算须在 [{lo}, {hi}] 毫美元，各轨不能为负")
    if actor["kind"] == "adapter" and _session_count(state["intents"], actor.get("session")) >= cfg.intent_quota:
        return Reject("quota_exceeded", f"本任务已加 {cfg.intent_quota} 条 Intent")
    out: Body = {"title": body.string("title"), "summary": body.string("summary", ""), "premises": premises,
                 "risk": risk, "budget": budget, **({"done": done} if done else {}),
                 **({"needs_scope": needs} if needs else {})}
    if "expected_gain" in body:                       # 估值，只供司南排序（I8）
        out["expected_gain"] = float(body.number("expected_gain"))
    return Ok(out)


# ---------- request_judge 与 judge_verdict ----------

def _registered_check(state: State, pid: str, target: str) -> tuple[Check | None, int | None]:
    """目标登记过的判据与次数上限。判据先行（I4）：判官只能是创建时登记的那一个。"""
    if target == "goal":
        g = state["problems"][pid]["goal"]
        return g["check"], g["max_attempts"]
    f = state["facts"].get(target)
    if f is not None and f["problem_id"] == pid:
        return f.get("check"), None
    i = state["intents"].get(target)
    if i is not None and i["problem_id"] == pid and "done" in i:
        return i["done"], i["done"]["max_attempts"]
    return None, None


def _v_request_judge(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    target, judge = body.string("target"), body.string("judge_id")
    node = _node(state, target)
    if node is not None and node["problem_id"] != pid:
        return Reject("scope_mismatch", f"{target} 属于别题")
    check, max_attempts = _registered_check(state, pid, target)
    if check is None:
        return Reject("unknown_ref", f"{target} 不是本题带判据的对象")
    if judge not in state["problems"][pid]["judges"]:
        return Reject("unknown_ref", f"判官 {judge} 未在本题启用")
    if judge != check["judge_id"]:
        return Reject("schema_error", "判官必须是登记判据时的那一个（判据先行）")
    candidate = body.opt_string("candidate")
    if max_attempts is not None:
        if candidate is None:
            return Reject("schema_error", "Goal 与带判据的 Intent 须给候选")
        err = _ref(state, pid, candidate, "候选")
        if err:
            return err
        tried = {r["candidate"] for r in state["requests"].values()
                 if r["problem_id"] == pid and r["target"] == target}     # 每题都有名为 goal 的目标，须按题计数
        if candidate not in tried and len(tried) >= max_attempts:
            return Reject("quota_exceeded", f"{target} 已用满 {max_attempts} 个候选")
    elif candidate is not None:
        return Reject("schema_error", "论断的判定没有候选")
    return Ok({"target": target, "judge_id": judge, "candidate": candidate})


INCONCLUSIVE_REASONS = ("timeout", "env_error", "unsupported", "untouched")   # §3.3.2 reason_code 的无结论各项


def _v_judge_verdict(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    rid, result = body.string("request"), body.string("result")
    req = state["requests"].get(rid)
    if req is None or req["problem_id"] != pid:
        return Reject("unknown_ref", "判官请求不存在")
    if "verdict_seq" in req:
        return Reject("schema_error", "该请求已裁决")
    if result not in ("pass", "fail", "flaky", "inconclusive"):
        return Reject("schema_error", "result 只取 pass、fail、flaky、inconclusive")
    reason = body.text("reason") if "reason" in body else None
    if result == "inconclusive" and reason not in INCONCLUSIVE_REASONS:
        return Reject("schema_error", f"inconclusive 须带原因码 {INCONCLUSIVE_REASONS}")
    evidence = body.strings("evidence", [])
    for ref in evidence:
        err = _ref(state, pid, ref, "evidence")
        if err:
            return err
        if state["artifacts"][ref]["class"] != "judge":
            return Reject("inadmissible_class", "evidence 必须是 judge 类")
    snap = state["problems"][pid]["judge_snapshot"][req["judge_id"]]
    return Ok({"request": rid, "result": result, "version": body.text("version"),
               "grade": snap["grade"], "evidence": evidence,
               **({"reason": reason} if reason is not None else {})})


# ---------- 租约（§3.1.2、§3.5.2） ----------

def _v_lease(state: State, actor: Actor, pid: str, body: Obj, cfg: Config, ts: int) -> Ok | Reject:
    kind, target = body.string("kind"), body.opt_string("target")
    if kind not in ("bootstrap", "reason", "explore", "judge"):
        return Reject("schema_error", f"租约种类 {kind} 非法")
    if (kind == "judge") != (actor["kind"] == "judge"):
        return Reject("forbidden_op", "judge 租约只由判官运行器申请；任务租约只由司南申请")
    reserve, ttl, holder = _amount(body.child("reserve")), body.integer("ttl_s"), body.text("holder")
    if ttl <= 0:
        return Reject("schema_error", "ttl_s 必须为正")
    if wk.in_flight(state, pid, kind, target) is not None:
        return Reject("conflict_leased", "目标上已有在途租约")
    item = {"kind": kind, **({"target": target} if target is not None else {})}
    offered = [{k: v for k, v in w.items() if k in ("kind", "target")} for w in wk.work(state, pid)]
    if item not in offered:
        return Reject("forbidden_op", "目标不在 /work 内")
    view = wk.budget_view(state, pid)
    prob = state["problems"][pid]
    if kind == "bootstrap" and reserve["usd_milli"] > prob["budget"]["bootstrap_share"] * view["cap"]["usd_milli"]:
        return Reject("over_budget", "Bootstrap 的预留不超过 bootstrap_share × cap")
    pool_res = wk.zero()
    for l in wk.active_leases(state, pid):
        if l["kind"] == "judge":
            pool_res = wk.add(pool_res, l["reserve"])
    ok = wk.fits(view, reserve, prob["budget"]["verify_share"], view["verify_spent"], pool_res) \
        if kind == "judge" else wk.fits(view, reserve)
    if not ok:
        return Reject("over_budget", "spent + reserved + reserve 超过上限")
    attempt = 1 + sum(1 for l in wk.leases_of(state, pid) if l["kind"] == kind and l.get("target") == target)
    return Ok({"kind": kind, **({"target": target} if target is not None else {}),
               "holder": holder, "reserve": reserve, "ttl_s": ttl, "attempt": attempt,
               **({"reflect": True} if kind == "reason" and wk.in_review(state, pid) else {})})


def _own_lease(state: State, actor: Actor, pid: str, body: Obj) -> Lease | Reject:
    """续租与释放的共同前置：租约存在、属于提交所指的这道题、提交方是持有者、租约在途。

    四条在关题前后都查（关题只放宽 outcome 的取值，不放宽归属）。判官运行器的令牌不带会话，
    按身份种类放行，但只限 judge 租约。"""
    l = state["leases"].get(body.string("lease"))
    if l is None:
        return Reject("unknown_ref", "租约不存在")
    if l["problem_id"] != pid:
        return Reject("scope_mismatch", f"租约 {l['id']} 属于别题")
    by_judge = actor["kind"] == "judge" and l["kind"] == "judge"
    if not by_judge and actor["id"] != l["holder"] and actor.get("session") != l["id"]:
        return Reject("forbidden_op", "续租与释放限持有者")
    if not l["active"]:
        return Reject("schema_error", "租约已结束")
    return l


def _v_renew(state: State, actor: Actor, pid: str, body: Obj, cfg: Config, ts: int) -> Ok | Reject:
    l = _own_lease(state, actor, pid, body)
    if isinstance(l, Reject):
        return l
    if ts >= l["expires_at"]:
        return Reject("schema_error", "租约已过期，等待 expire_lease")
    ttl = body.integer("ttl_s", l["ttl_s"])
    if ttl <= 0:
        return Reject("schema_error", "ttl_s 必须为正")
    return Ok({"lease": l["id"], "ttl_s": ttl})


RELEASE_OUTCOMES = ("done", "failed", "nothing", "budget_exhausted")


def _v_release(state: State, actor: Actor, pid: str, body: Obj, cfg: Config, ts: int) -> Ok | Reject:
    l = _own_lease(state, actor, pid, body)
    if isinstance(l, Reject):
        return l
    tr = body.opt_string("transcript_ref")
    if state["problems"][pid]["closed"]:               # 关题后在途任务交回租约：结局一律记 closed
        keep = tr is not None and tr in state["artifacts"] and state["artifacts"][tr]["problem_id"] == pid
        return Ok({"lease": l["id"], "outcome": "closed", "after_close": True,
                   **({"transcript_ref": tr} if keep else {})})     # 交回的留档照样挂到租约上
    outcome = body.string("outcome")
    if outcome not in RELEASE_OUTCOMES:
        return Reject("schema_error", f"outcome 只取 {RELEASE_OUTCOMES}")
    if tr is not None and (tr not in state["artifacts"] or state["artifacts"][tr]["problem_id"] != pid):
        return Reject("unknown_ref", "transcript_ref 不存在或属于别题")
    suggestions = body.texts("suggestions", None)
    return Ok({"lease": l["id"], "outcome": outcome,
               **({"transcript_ref": tr} if tr else {}),
               **({"suggestions": suggestions} if suggestions else {})})


def _v_expire_lease(state: State, actor: Actor, pid: str, body: Obj, cfg: Config, ts: int) -> Ok | Reject:
    l = state["leases"].get(body.string("lease"))
    if l is None or l["problem_id"] != pid or not l["active"]:
        return Reject("unknown_ref", "没有这条在途租约")
    if ts < l["expires_at"]:
        return Reject("schema_error", "ts < expires_at，租约未到期")
    return Ok({"lease": l["id"]})


# ---------- 人的决定绑定所见（§3.1.9、HMI H2） ----------

def _seen(state: State, pid: str, kind: str, target: str, body: Obj) -> Body | Reject:
    """决策操作带 seen {seq, card_hash}：在当前状态（链头）重算这张卡的投影哈希，不等即 stale_view。

    seq 只留作审计，不参与比较；哈希按卡片范围计算，与这张卡无关的事件不会让它过期。"""
    seen = body.get("seen")
    if not (isinstance(seen, dict) and set(seen) == {"seq", "card_hash"} and isinstance(seen["card_hash"], str)
            and _HEX64.match(seen["card_hash"]) and type(seen["seq"]) is int and seen["seq"] >= 0):
        return Reject("schema_error", "决策操作须带 seen {seq, card_hash}")
    card = cards.card_object(state, pid, kind, target)
    if card is None:
        return Reject("unknown_ref", f"没有 {kind} 卡 {target}")
    if rm.validate_decision(seen["card_hash"], card) != "ok":
        return Reject("stale_view", f"{kind} 卡 {target} 在你查看之后已变化", (kind, target))
    return {"seq": seen["seq"], "card_hash": seen["card_hash"]}


def _reason(body: Obj) -> str:
    return body.text("reason").strip() if body.get("reason") is not None else ""


# ---------- Intent 的放弃与审批、Hint、用量、关题 ----------

def _v_abandon_intent(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    iid = body.string("intent")
    i = state["intents"].get(iid)
    if i is None or i["problem_id"] != pid:
        return Reject("unknown_ref", "Intent 不存在")
    status = wk.intent_status(state, pid, iid)
    if status in ("achieved", "abandoned", "done"):
        return Reject("schema_error", f"Intent 已是终态 {status}")
    if status == "leased":
        return Reject("conflict_leased", "Intent 有在途租约")
    return Ok({"intent": iid, "reason": body.text("reason", "")})


def _v_approve(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    iid, decision = body.string("intent"), body.string("decision")
    i = state["intents"].get(iid)
    if i is None or i["problem_id"] != pid:
        return Reject("unknown_ref", "Intent 不存在")
    if decision not in ("approve", "deny"):
        return Reject("schema_error", "decision 只取 approve、deny")
    seen = _seen(state, pid, "approval", iid, body)          # 先于状态检查：卡片变了，人要先看到新卡
    if isinstance(seen, Reject):
        return seen
    if wk.intent_status(state, pid, iid) != "needs_human":
        return Reject("schema_error", "只有 needs_human 的 Intent 待审批")
    reason = _reason(body)
    if decision == "deny" and not reason:
        return Reject("schema_error", "拒绝须写理由（§3.2 pd deny --reason）")
    return Ok({"intent": iid, "decision": decision, "seen": seen, **({"reason": reason} if reason else {})})


PROFILE_AXES: dict[str, tuple[str, ...]] = {
    "info": ("complete", "partial"), "judge": ("hard", "costly", "deferred", "none"), "reversibility": RISKS}


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


def _v_hint(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    if "close" in body:
        h = state["hints"].get(body.string("close"))
        if h is None or h["problem_id"] != pid:
            return Reject("unknown_ref", "Hint 不存在")
        return Ok({"close": h["id"]})
    about = body.opt_string("about")
    if about is not None and about != "goal":
        node = _node(state, about)
        if node is None:
            return Reject("unknown_ref", "about 所指节点不存在")
        if node["problem_id"] != pid:
            return Reject("scope_mismatch", f"about 所指节点 {about} 属于别题")
    return Ok({"text": body.text("text"), **({"about": about} if about else {})})


def _v_cost(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    l = state["leases"].get(body.string("task_id"))
    if l is None or l["problem_id"] != pid:
        return Reject("unknown_ref", "任务不存在")
    source = body.string("source")
    if source not in ("proxy", "judge", "cli_reported"):
        return Reject("schema_error", "source 非法")
    nums = {k: body.integer(k) if body.get(k) else 0
            for k in ("tokens_in", "tokens_cached", "tokens_out", "usd_milli", "wall_s")}
    if any(v < 0 for v in nums.values()):
        return Reject("schema_error", "用量不能为负")
    return Ok({"task_id": l["id"], "source": source, **nums,
               "price_table": body.text("price_table"), **({"model": body.text("model")} if body.get("model") else {}),
               **({"tokens_cached_unknown": True} if body.get("tokens_cached") is None else {})})


def _v_close_problem(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    if "terminal" in body and actor["kind"] != "graph":
        return Reject("schema_error", "terminal 是派生量，由图服务按三值算出")
    term = wk.terminal(state, pid)
    if actor["kind"] == "graph" and term != "solved":
        return Reject("schema_error", "图服务只在 Goal 到 E3 时自动关题")
    if wk.closeout_items(state, pid) and actor["kind"] == "graph":
        return Reject("schema_error", "四顾清单非空，需人确认")
    seen: Body | None = None
    if actor["kind"] == "human":
        if "card_hash" in body:
            return Reject("schema_error", "card_hash 不单独接受：所见的收尾清单经 seen {seq, card_hash} 给出并校验")
        if "seen" in body:                              # 人关题时所见的四顾清单；带了就必须与链头相符
            checked = _seen(state, pid, "closeout", pid, body)
            if isinstance(checked, Reject):
                return checked
            seen = checked
    return Ok({"terminal": term, "by": actor["kind"], "card_hash": seen["card_hash"] if seen else None,
               **({"seen": seen} if seen else {}),
               **({"reason": body.text("reason")} if "reason" in body else {})})


def _v_budget_mark(state: State, actor: Actor, pid: str, body: Obj, cfg: Config) -> Ok | Reject:
    return Ok({"mark": body.integer("mark"), "axis": body.text("axis")})


Validator = Callable[[State, Actor, str, Obj, Config], "Ok | Reject"]
TimedValidator = Callable[[State, Actor, str, Obj, Config, int], "Ok | Reject"]

_TIMED: dict[str, TimedValidator] = {
    "lease": _v_lease, "renew": _v_renew, "release": _v_release, "expire_lease": _v_expire_lease}

_VALIDATORS: dict[str, Validator] = {
    "abandon_intent": _v_abandon_intent, "approve": _v_approve, "hint": _v_hint,
    "cost": _v_cost, "close_problem": _v_close_problem, "budget_mark": _v_budget_mark,
    "profile_override": _v_profile_override,
    "open_problem": _v_open_problem, "register_artifact": _v_register_artifact,
    "add_fact": _v_add_fact, "add_intent": _v_add_intent,
    "request_judge": _v_request_judge, "judge_verdict": _v_judge_verdict}


# ---------- apply ----------

def apply(state: State, ev: Event) -> State:
    """纯函数：返回新状态，不修改入参。只复制被改动的集合。"""
    s = cast(State, dict(state))
    s["now"] = ev["ts"]
    s["seq"] = ev["seq"]
    kind, body, pid, seq = ev["kind"], ev["body"], ev["problem_id"], ev["seq"]
    session = ev["actor"].get("session")
    if kind == "open_problem":
        opened = cast(Problem, {**body, "id": pid, "closed": False, "opened_seq": seq, "opened_ts": ev["ts"]})
        s["problems"] = {**s["problems"], pid: opened}
    elif kind == "register_artifact":
        s["artifacts"] = {**s["artifacts"], f"a_{seq}": cast(Artifact, {**body, "id": f"a_{seq}", "problem_id": pid})}
    elif kind == "add_fact":
        target = body.get("merge_into")
        if target:                                   # 内容键相同：幂等合并，grounds 并入
            old = s["facts"][target]
            merged = old["grounds"] + [g for g in body["grounds"] if g not in old["grounds"]]
            s["facts"] = {**s["facts"], target: {**old, "grounds": merged}}
        else:
            fid = f"f_{seq}"
            rec = {k: v for k, v in body.items() if k != "content_key"}
            lease = s["leases"].get(session) if session else None
            if lease and lease["kind"] == "explore":     # yields 边由租约推出，不由模型填写
                rec["yielded_by"] = lease["target"]
            s["facts"] = {**s["facts"], fid: cast(Fact, {**rec, "id": fid, "problem_id": pid, "session": session})}
            s["content_keys"] = {**s["content_keys"],
                                 pid: {**s["content_keys"].get(pid, {}), body["content_key"]: fid}}
    elif kind == "add_intent":
        iid = f"i_{seq}"
        s["intents"] = {**s["intents"], iid: cast(Intent, {**body, "id": iid, "problem_id": pid, "session": session})}
    elif kind == "request_judge":
        rid = f"j_{seq}"
        s["requests"] = {**s["requests"], rid: cast(Request, {**body, "id": rid, "problem_id": pid})}
    elif kind == "judge_verdict":
        req = s["requests"][body["request"]]
        judged: Request = {**req, "verdict_seq": seq}
        if body["result"] == "inconclusive":
            judged["inconclusive"] = body["reason"]
        s["requests"] = {**s["requests"], req["id"]: judged}
        if body["result"] != "inconclusive":      # 抖动以外的无结论裁决不进裁决序列（§3.1.2），等级不变
            verdict: Verdict = {
                "seq": seq, "problem_id": pid, "target": req["target"], "judge": req["judge_id"],
                "version": body["version"], "grade": body["grade"], "result": body["result"],
                "candidate": req["candidate"], "request": req["id"], "evidence": body["evidence"]}
            s["verdicts"] = s["verdicts"] + [verdict]
    elif kind == "lease":
        lid = f"l_{seq}"
        issued = cast(Lease, {**body, "id": lid, "problem_id": pid, "issued_seq": seq, "active": True,
                              "expires_at": ev["ts"] + body["ttl_s"] * 1000})
        s["leases"] = {**s["leases"], lid: issued}
        if body["kind"] == "explore":
            s["lease_seqs"] = {**s["lease_seqs"], body["target"]: s["lease_seqs"].get(body["target"], []) + [seq]}
    elif kind == "renew":
        l = s["leases"][body["lease"]]
        s["leases"] = {**s["leases"], l["id"]: {**l, "expires_at": ev["ts"] + body["ttl_s"] * 1000}}
    elif kind in ("release", "expire_lease"):
        l = s["leases"][body["lease"]]
        ended: Lease = {**l, "active": False, "ended_seq": seq,
                        "outcome": "expired" if kind == "expire_lease" else body["outcome"]}
        if body.get("transcript_ref"):
            ended["transcript_ref"] = body["transcript_ref"]
        s["leases"] = {**s["leases"], l["id"]: ended}
    elif kind == "abandon_intent":
        s["abandoned"] = s["abandoned"] + [body["intent"]]
    elif kind == "profile_override":
        p = s["problems"][pid]
        s["problems"] = {**s["problems"], pid: {
            **p, "derived_profile": p.get("derived_profile", p["profile"]),
            "profile": cast(Profile, {**p["profile"], body["axis"]: body["value"]}),
            "profile_overrides": p.get("profile_overrides", []) + [
                {"axis": body["axis"], "value": body["value"], "reason": body["reason"],
                 "derived": body["derived"], "seq": seq, "by": ev["actor"]["id"]}]}}
    elif kind == "approve":
        if body.get("reason"):
            s["decision_reasons"] = {**s.get("decision_reasons", {}), body["intent"]: {
                "decision": body["decision"], "reason": body["reason"], "by": ev["actor"]["id"], "seq": seq}}
        if body["decision"] == "approve":
            s["approvals"] = {**s["approvals"], body["intent"]: s["approvals"].get(body["intent"], []) + [seq]}
        else:
            s["abandoned"] = s["abandoned"] + [body["intent"]]
    elif kind == "hint":
        if "close" in body:
            h = s["hints"][body["close"]]
            s["hints"] = {**s["hints"], h["id"]: {**h, "closed": True}}
        else:
            hid = f"h_{seq}"
            s["hints"] = {**s["hints"], hid: cast(Hint, {**body, "id": hid, "problem_id": pid, "seq": seq,
                                                         "author": ev["actor"]["id"], "closed": False})}
    elif kind == "cost":
        lk = s["leases"][body["task_id"]]["kind"]
        s["costs"] = s["costs"] + [cast(Cost, {**body, "problem_id": pid, "seq": seq, "lease_kind": lk})]
    elif kind == "close_problem":
        p = s["problems"][pid]
        s["problems"] = {**s["problems"], pid: {**p, "closed": True, "terminal": body["terminal"],
                                                "closed_seq": seq}}
    elif kind == "budget_mark":
        p = s["problems"][pid]
        s["problems"] = {**s["problems"], pid: {**p, "marks": p.get("marks", []) + [body["mark"]],
                                                "mark_seqs": p.get("mark_seqs", []) + [seq]}}
    else:
        raise ValueError(f"apply：未知事件 {kind}")
    return s


def result_id(ev: Event) -> str | None:
    """一条事件给提议方的返回 id。"""
    prefix = {"register_artifact": "a", "add_fact": "f", "add_intent": "i", "request_judge": "j",
              "lease": "l"}.get(ev["kind"])
    if ev["kind"] == "hint" and "close" not in ev["body"]:
        prefix = "h"
    if ev["kind"] == "add_fact" and ev["body"].get("merge_into"):
        return str(ev["body"]["merge_into"])
    return f"{prefix}_{ev['seq']}" if prefix else None
