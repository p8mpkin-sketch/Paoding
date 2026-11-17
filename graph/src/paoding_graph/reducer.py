"""内核：validate 与 apply（规格 §3.1.2）。I1：两者都是纯函数，不读时钟、不做 IO、不调用模型。

- `validate(state, actor, kind, body, cfg)` → `Ok(body')` 或 `Reject(code, detail)`。
  body' 是将要写进事件的规范化事件体，含图服务派生的字段（画像、判官快照、producer）。
  cfg 是只读配置（判官注册表、资源插件、配额）；它的取值在 validate 时写进事件体，所以重放不依赖它。
- `apply(state, event)` → 新状态。新对象的 id 由事件的 seq 派生：a_<seq>、f_<seq>、i_<seq>、j_<seq>。
- 等级不在状态里（I3）。需要等级时经 levels.py 调用从参考模型搬运来的函数重算。

D2 范围：开题、Artifact 登记与可采信检查、论断、Intent、判官请求与裁决。
租约、消费门对 /work 的作用、关题、人的通道在 D8–D10 补上。
IO 前置条件不在这里：Blob 是否存在、哈希是否相符由服务层在调用 validate 之前检查。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import levels as lv
from . import refmodel as rm
from . import work as wk
from .envelope import sha256_hex
from .jcs import canonicalize

RISKS = ("r0", "r1", "r2")
RISK_RANK = {r: i for i, r in enumerate(RISKS)}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Ok:
    body: dict


@dataclass(frozen=True)
class Reject:
    code: str
    detail: str = ""


@dataclass(frozen=True)
class Config:
    judges: dict = field(default_factory=dict)       # judge_id → {version, grade, kind, max_cost}
    external_resources: frozenset = frozenset()       # 资源插件登记为 external 的资源名
    cheap_judge_max_cost: float = 0.05                # "廉价判官"阈值（美元），配置项
    fact_quota: int = 20                              # 每个任务（会话）的写入配额
    intent_quota: int = 8
    intent_budget_usd_milli: tuple = (1, 10_000_000)  # add_intent 预算区间


def empty_state() -> dict[str, Any]:
    return {"problems": {}, "artifacts": {}, "facts": {}, "intents": {}, "requests": {},
            "verdicts": [], "content_keys": {}, "revoked": [], "approvals": {}, "lease_seqs": {},
            "abandoned": [], "leases": {}, "hints": {}, "costs": [], "now": 0, "seq": 0}


# ---------- 谁可以提交什么（§3.1.2 操作表） ----------

def _who(actor: dict, kind: str) -> bool:
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
    if kind in ("hint", "approve"):
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
         "close_problem", "budget_mark")
AFTER_CLOSE = ("cost", "release")                  # 关题后在途任务仍可交回用量与释放租约


def validate(state: dict, actor: dict, pid: str, kind: str, body: dict, cfg: Config,
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
        if p.get("closed") and kind not in AFTER_CLOSE:
            return Reject("schema_error", "题目已关闭")
    try:
        if kind in _TIMED:
            return _TIMED[kind](state, actor, pid, body, cfg, state["now"] if ts is None else ts)
        return _VALIDATORS[kind](state, actor, pid, body, cfg)
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        return Reject("schema_error", f"{type(e).__name__}: {e}")


# ---------- open_problem ----------

def _derive_profile(scope: list, goal_judge: dict, cfg: Config) -> dict:
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


def _check(c: Any, judges: list | None = None) -> dict:
    if not isinstance(c, dict) or not isinstance(c.get("judge_id"), str):
        raise ValueError("check.judge_id 必填")
    extra = set(c) - {"judge_id", "spec_ref", "expect", "sealed", "control"}
    if extra:
        raise ValueError(f"check 多余字段 {sorted(extra)}")
    if "control" in c:
        raise ValueError("check.control 是 M1 的对照判据，M0 未启用")
    for v in c.get("sealed", []):
        if set(v) != {"vault", "digest"} or not _HEX64.match(v["digest"]):
            raise ValueError("sealed 必须是 VaultRef{vault, digest}")
    return dict(c)


def _v_open_problem(state, actor, pid, body, cfg):
    if pid in state["problems"]:
        return Reject("schema_error", "题目已存在")
    if "profile" in body:
        return Reject("schema_error", "profile 是派生字段，提交时不接受")
    allowed = {"title", "origin", "goal", "scope", "budget", "env", "judges"}
    if set(body) != allowed:
        return Reject("schema_error", f"字段应为 {sorted(allowed)}")
    judges = list(body["judges"])
    for j in judges:
        if j not in cfg.judges:
            return Reject("unknown_ref", f"判官 {j} 未注册")
    goal = dict(body["goal"])
    goal["check"] = _check(goal["check"])
    if goal["check"]["judge_id"] not in judges:
        return Reject("unknown_ref", "Goal 判官不在本题启用的判官里")
    if goal.get("accept") != "judge":
        return Reject("schema_error", "M0 只实现 accept=judge")
    if not (isinstance(goal.get("max_attempts"), int) and goal["max_attempts"] >= 1):
        return Reject("schema_error", "goal.max_attempts 必须是正整数")
    scope = []
    for r in body["scope"]:
        rule = {"resource": str(r["resource"]), "pattern": str(r["pattern"]),
                "actions": [str(a) for a in r["actions"]], "risk": r.get("risk", "r2")}  # 缺省 r2
        if rule["risk"] not in RISKS:
            return Reject("schema_error", f"risk 非法：{rule['risk']}")
        scope.append(rule)
    if not scope:
        return Reject("schema_error", "scope 必填且非空")
    b = body["budget"]
    if not (b["usd_milli"] > 0 and b["wall_s"] > 0 and 0 <= b["verify_share"] <= 1
            and 0 <= b["bootstrap_share"] <= 1):
        return Reject("schema_error", "预算必须为正，份额在 [0,1]")
    origin = body["origin"]
    for ref in [origin["statement_ref"], *origin["materials"]]:
        a = state["artifacts"].get(ref)
        if a is None:
            return Reject("unknown_ref", f"Origin 引用 {ref} 不存在")
        if a["problem_id"] != pid:
            return Reject("scope_mismatch", f"Origin 引用 {ref} 属于别题")
        if a["class"] != "input":
            return Reject("inadmissible_class", "Origin 只接受 input 类")
    snapshot = {j: dict(cfg.judges[j]) for j in judges}
    out = {**body, "goal": goal, "scope": scope, "judges": judges, "judge_snapshot": snapshot,
           "profile": _derive_profile(scope, snapshot[goal["check"]["judge_id"]], cfg)}
    return Ok(out)


# ---------- register_artifact ----------

_EXEC_FIELDS = {"sandbox_id", "base", "baseline_ref", "tool", "command", "cwd", "exit_code",
                "touched", "started_at", "ended_at", "truncated"}


def _v_register_artifact(state, actor, pid, body, cfg):
    cls = body["class"]
    if cls not in rm.REGISTRAR:
        return Reject("schema_error", f"未知类别 {cls}")
    if rm.validate_register(actor["kind"], cls) != "ok":
        return Reject("forbidden_op", f"{actor['kind']} 的令牌不能登记 {cls} 类")
    if pid not in state["problems"] and actor["kind"] != "human":
        return Reject("unknown_ref", f"题目 {pid} 未开")
    if "producer" in body:
        return Reject("schema_error", "producer 由令牌决定，提交时不接受")
    if not _HEX64.match(body["hash"]) or not (isinstance(body["size"], int) and body["size"] >= 0):
        return Reject("schema_error", "hash 须为 sha256，size 须为非负整数")
    if cls in ("exec", "judge"):
        ex = body.get("exec")
        if not isinstance(ex, dict) or set(ex) != _EXEC_FIELDS:
            return Reject("schema_error", f"{cls} 类必须带完整的 exec 出处字段")
    elif "exec" in body:
        return Reject("schema_error", "只有 exec 与 judge 类带 exec 出处字段")
    for p in body.get("parents", []):
        a = state["artifacts"].get(p)
        if a is None:
            return Reject("unknown_ref", f"parent {p} 不存在")
        if a["problem_id"] != pid:
            return Reject("scope_mismatch", f"parent {p} 属于别题")
    producer = {"actor": actor["id"], **({"session": actor["session"]} if "session" in actor else {})}
    return Ok({"hash": body["hash"], "size": body["size"], "media_type": str(body["media_type"]),
               "class": cls, "parents": list(body.get("parents", [])), "producer": producer,
               **({"exec": dict(body["exec"])} if "exec" in body else {})})


# ---------- add_fact ----------

def _ref_artifacts(state: dict) -> dict:
    return {aid: rm.Artifact(aid, a["class"], a["problem_id"]) for aid, a in state["artifacts"].items()}


def content_key(state: dict, f: dict) -> str:
    """内容键（§3.1.2）：观察类取 check 的规范化哈希（spec_ref 按 Blob 哈希代入）；推断类取 title 与排序后的 premises。"""
    if f["claim_type"] == "observation":
        c = dict(f["check"])
        if "spec_ref" in c:
            c["spec_ref"] = state["artifacts"][c["spec_ref"]]["hash"]
        return "o:" + sha256_hex(canonicalize(c))
    return "i:" + sha256_hex(canonicalize([f["title"], sorted(f["premises"])]))


def _session_count(state: dict, coll: str, session: str | None) -> int:
    return sum(1 for x in state[coll].values() if session and x.get("session") == session)


def _v_add_fact(state, actor, pid, body, cfg):
    allowed = {"title", "summary", "body_ref", "claim_type", "check", "premises", "grounds"}
    if "yielded_by" in body:
        return Reject("schema_error", "yielded_by 由租约推出，不由提议方填写")
    if not set(body) <= allowed:
        return Reject("schema_error", f"多余字段 {sorted(set(body) - allowed)}")
    if body["claim_type"] not in ("observation", "inference"):
        return Reject("schema_error", "claim_type 非法")
    if len(body["title"]) > 120 or len(body.get("summary", "")) > 600:
        return Reject("schema_error", "title ≤120、summary ≤600 字符")
    premises, grounds = list(body.get("premises", [])), list(body.get("grounds", []))
    check = _check(body["check"]) if body.get("check") is not None else None
    for ref in [body.get("body_ref"), (check or {}).get("spec_ref")]:
        if ref is None:
            continue
        a = state["artifacts"].get(ref)
        if a is None:
            return Reject("unknown_ref", f"{ref} 不存在")
        if a["problem_id"] != pid:
            return Reject("scope_mismatch", f"{ref} 属于别题")
    # 等级不出题（I7）：前提指向别题的节点一律 scope_mismatch
    for p in premises:
        node = state["facts"].get(p) or state["intents"].get(p)
        if node is not None and node["problem_id"] != pid:
            return Reject("scope_mismatch", f"前提 {p} 属于别题")
    lvls = lv.levels(state, pid)
    code = rm.validate_add_fact(_ref_artifacts(state), lvls, pid, body["claim_type"], check is not None,
                                tuple(premises), tuple(grounds))
    if code != "ok":
        return Reject(code)
    if _session_count(state, "facts", actor.get("session")) >= cfg.fact_quota:
        return Reject("quota_exceeded", f"本任务已写 {cfg.fact_quota} 条论断")
    out = {"title": body["title"], "summary": body.get("summary", ""), "claim_type": body["claim_type"],
           "premises": premises, "grounds": grounds,
           **({"check": check} if check else {}),
           **({"body_ref": body["body_ref"]} if body.get("body_ref") else {})}
    key = content_key(state, out)
    existing = state["content_keys"].get(pid, {}).get(key)
    return Ok({**out, "content_key": key, **({"merge_into": existing} if existing else {})})


# ---------- add_intent ----------

def _v_add_intent(state, actor, pid, body, cfg):
    later = {"follows", "executor", "rollback", "delegate"} & set(body)
    if later:
        return Reject("schema_error", f"{sorted(later)} 属于后续里程碑，M0 未启用")
    allowed = {"title", "summary", "premises", "risk", "budget", "done", "needs_scope", "expected_gain"}
    if not set(body) <= allowed:
        return Reject("schema_error", f"多余字段 {sorted(set(body) - allowed)}")
    prob = state["problems"][pid]
    risk = body["risk"]
    if risk not in RISKS:
        return Reject("schema_error", "risk 非法")
    needs = [{"resource": str(r["resource"]), "pattern": str(r["pattern"]),
              "actions": [str(a) for a in r["actions"]], "risk": r.get("risk", "r2")}
             for r in body.get("needs_scope") or []]
    ceiling = max((r["risk"] for r in prob["scope"] + needs), key=RISK_RANK.__getitem__)
    if RISK_RANK[risk] > RISK_RANK[ceiling]:
        return Reject("scope_mismatch", f"risk {risk} 高于授权范围的最高风险 {ceiling}")
    premises = list(body.get("premises", []))
    lvls = lv.levels(state, pid)
    for p in premises:
        node = state["facts"].get(p) or state["intents"].get(p)
        if node is not None and node["problem_id"] != pid:
            return Reject("scope_mismatch", f"前提 {p} 属于别题")
        if p not in lvls:
            return Reject("unknown_ref", f"前提 {p} 不存在或不是带判据的 Intent")
        if lvls[p] == rm.X:
            return Reject("stale_premise", f"前提 {p} 已被证伪")
    done = None
    if body.get("done") is not None:
        d = dict(body["done"])
        max_attempts = d.pop("max_attempts")
        if "tests" in d:
            return Reject("schema_error", "done.tests 属于完整版")
        done = {**_check(d), "max_attempts": int(max_attempts)}
        if done["judge_id"] not in prob["judges"]:
            return Reject("unknown_ref", "done 的判官不在本题启用的判官里")
    bud = body["budget"]
    lo, hi = cfg.intent_budget_usd_milli
    if not (lo <= bud["usd_milli"] <= hi):
        return Reject("schema_error", f"预算须在 [{lo}, {hi}] 毫美元")
    if actor["kind"] == "adapter" and _session_count(state, "intents", actor.get("session")) >= cfg.intent_quota:
        return Reject("quota_exceeded", f"本任务已加 {cfg.intent_quota} 条 Intent")
    out = {"title": body["title"], "summary": body.get("summary", ""), "premises": premises, "risk": risk,
           "budget": dict(bud), **({"done": done} if done else {}), **({"needs_scope": needs} if needs else {})}
    if "expected_gain" in body:                       # 估值，只供司南排序（I8）
        out["expected_gain"] = float(body["expected_gain"])
    return Ok(out)


# ---------- request_judge 与 judge_verdict ----------

def _registered_check(state: dict, pid: str, target: str) -> tuple[dict | None, int | None]:
    """目标登记过的判据与次数上限。判据先行（I4）：判官只能是创建时登记的那一个。"""
    if target == "goal":
        g = state["problems"][pid]["goal"]
        return g["check"], g["max_attempts"]
    f = state["facts"].get(target)
    if f is not None and f["problem_id"] == pid:
        return f.get("check"), None
    i = state["intents"].get(target)
    if i is not None and i["problem_id"] == pid and i.get("done"):
        return i["done"], i["done"]["max_attempts"]
    return None, None


def _v_request_judge(state, actor, pid, body, cfg):
    target, judge = body["target"], body["judge_id"]
    for coll in ("facts", "intents"):
        node = state[coll].get(target)
        if node is not None and node["problem_id"] != pid:
            return Reject("scope_mismatch", f"{target} 属于别题")
    check, max_attempts = _registered_check(state, pid, target)
    if check is None:
        return Reject("unknown_ref", f"{target} 不是本题带判据的对象")
    if judge not in state["problems"][pid]["judges"]:
        return Reject("unknown_ref", f"判官 {judge} 未在本题启用")
    if judge != check["judge_id"]:
        return Reject("schema_error", "判官必须是登记判据时的那一个（判据先行）")
    candidate = body.get("candidate")
    if max_attempts is not None:
        if candidate is None:
            return Reject("schema_error", "Goal 与带判据的 Intent 须给候选")
        a = state["artifacts"].get(candidate)
        if a is None:
            return Reject("unknown_ref", f"候选 {candidate} 不存在")
        if a["problem_id"] != pid:
            return Reject("scope_mismatch", "候选属于别题")
        tried = {r["candidate"] for r in state["requests"].values() if r["target"] == target}
        if candidate not in tried and len(tried) >= max_attempts:
            return Reject("quota_exceeded", f"{target} 已用满 {max_attempts} 个候选")
    elif candidate is not None:
        return Reject("schema_error", "论断的判定没有候选")
    return Ok({"target": target, "judge_id": judge, "candidate": candidate})


def _v_judge_verdict(state, actor, pid, body, cfg):
    req = state["requests"].get(body["request"])
    if req is None or req["problem_id"] != pid:
        return Reject("unknown_ref", "判官请求不存在")
    if req.get("verdict_seq") is not None:
        return Reject("schema_error", "该请求已裁决")
    if body["result"] not in ("pass", "fail", "flaky"):
        return Reject("schema_error", "result 只取 pass、fail、flaky")
    for ref in body.get("evidence", []):
        a = state["artifacts"].get(ref)
        if a is None:
            return Reject("unknown_ref", f"evidence {ref} 不存在")
        if a["problem_id"] != pid:
            return Reject("scope_mismatch", "evidence 属于别题")
        if a["class"] != "judge":
            return Reject("inadmissible_class", "evidence 必须是 judge 类")
    snap = state["problems"][pid]["judge_snapshot"][req["judge_id"]]
    return Ok({"request": body["request"], "result": body["result"], "version": str(body["version"]),
               "grade": snap["grade"], "evidence": list(body.get("evidence", [])),
               **({"reason": str(body["reason"])} if "reason" in body else {})})


# ---------- 租约（§3.1.2、§3.5.2） ----------

def _budget(b: Any) -> dict:
    out = {"usd_milli": int(b["usd_milli"]), "wall_s": int(b.get("wall_s", 0))}
    if b.get("tokens") is not None:
        out["tokens"] = int(b["tokens"])
    if out["usd_milli"] < 0 or out["wall_s"] < 0 or out.get("tokens", 0) < 0:
        raise ValueError("预算不能为负")
    return out


def _v_lease(state, actor, pid, body, cfg, ts):
    kind, target = body["kind"], body.get("target")
    if kind not in ("bootstrap", "reason", "explore", "judge"):
        return Reject("schema_error", f"租约种类 {kind} 非法")
    if (kind == "judge") != (actor["kind"] == "judge"):
        return Reject("forbidden_op", "judge 租约只由判官运行器申请；任务租约只由司南申请")
    reserve, ttl = _budget(body["reserve"]), int(body["ttl_s"])
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
    pool_res = wk._zero()
    for l in wk.active_leases(state, pid):
        if l["kind"] == "judge":
            pool_res = wk._add(pool_res, l["reserve"])
    ok = wk.fits(view, reserve, prob["budget"]["verify_share"], view["verify_spent"], pool_res) \
        if kind == "judge" else wk.fits(view, reserve)
    if not ok:
        return Reject("over_budget", "spent + reserved + reserve 超过上限")
    attempt = 1 + sum(1 for l in wk.leases_of(state, pid) if l["kind"] == kind and l.get("target") == target)
    return Ok({"kind": kind, **({"target": target} if target is not None else {}),
               "holder": str(body["holder"]), "reserve": reserve, "ttl_s": ttl, "attempt": attempt,
               **({"reflect": True} if kind == "reason" and wk.in_review(state, pid) else {})})


def _own_lease(state, actor, pid, body):
    l = state["leases"].get(body["lease"])
    if l is None or l["problem_id"] != pid:
        return None, Reject("unknown_ref", "租约不存在")
    if actor["kind"] != "judge" and actor["id"] != l["holder"] and actor.get("session") != l["id"]:
        return None, Reject("forbidden_op", "续租与释放限持有者")
    if not l["active"]:
        return None, Reject("schema_error", "租约已结束")
    return l, None


def _v_renew(state, actor, pid, body, cfg, ts):
    l, err = _own_lease(state, actor, pid, body)
    if err:
        return err
    if ts >= l["expires_at"]:
        return Reject("schema_error", "租约已过期，等待 expire_lease")
    return Ok({"lease": l["id"], "ttl_s": int(body.get("ttl_s", l["ttl_s"]))})


RELEASE_OUTCOMES = ("done", "failed", "nothing", "budget_exhausted")


def _v_release(state, actor, pid, body, cfg, ts):
    if state["problems"][pid].get("closed") and body["lease"] in state["leases"]:
        return Ok({"lease": body["lease"], "outcome": "closed", "after_close": True})
    l, err = _own_lease(state, actor, pid, body)
    if err:
        return err
    if body["outcome"] not in RELEASE_OUTCOMES:
        return Reject("schema_error", f"outcome 只取 {RELEASE_OUTCOMES}")
    tr = body.get("transcript_ref")
    if tr is not None and (tr not in state["artifacts"] or state["artifacts"][tr]["problem_id"] != pid):
        return Reject("unknown_ref", "transcript_ref 不存在或属于别题")
    return Ok({"lease": l["id"], "outcome": body["outcome"],
               **({"transcript_ref": tr} if tr else {}),
               **({"suggestions": [str(x) for x in body["suggestions"]]} if body.get("suggestions") else {})})


def _v_expire_lease(state, actor, pid, body, cfg, ts):
    l = state["leases"].get(body["lease"])
    if l is None or l["problem_id"] != pid or not l["active"]:
        return Reject("unknown_ref", "没有这条在途租约")
    if ts < l["expires_at"]:
        return Reject("schema_error", "ts < expires_at，租约未到期")
    return Ok({"lease": l["id"]})


# ---------- Intent 的放弃与审批、Hint、用量、关题 ----------

def _v_abandon_intent(state, actor, pid, body, cfg):
    iid = body["intent"]
    i = state["intents"].get(iid)
    if i is None or i["problem_id"] != pid:
        return Reject("unknown_ref", "Intent 不存在")
    status = wk.intent_status(state, pid, iid)
    if status in ("achieved", "abandoned", "done"):
        return Reject("schema_error", f"Intent 已是终态 {status}")
    if status == "leased":
        return Reject("conflict_leased", "Intent 有在途租约")
    return Ok({"intent": iid, "reason": str(body.get("reason", ""))})


def _v_approve(state, actor, pid, body, cfg):
    iid = body["intent"]
    i = state["intents"].get(iid)
    if i is None or i["problem_id"] != pid:
        return Reject("unknown_ref", "Intent 不存在")
    if body["decision"] not in ("approve", "deny"):
        return Reject("schema_error", "decision 只取 approve、deny")
    if wk.intent_status(state, pid, iid) != "needs_human":
        return Reject("schema_error", "只有 needs_human 的 Intent 待审批")
    return Ok({"intent": iid, "decision": body["decision"]})


def _v_hint(state, actor, pid, body, cfg):
    if "close" in body:
        h = state["hints"].get(body["close"])
        if h is None or h["problem_id"] != pid:
            return Reject("unknown_ref", "Hint 不存在")
        return Ok({"close": h["id"]})
    about = body.get("about")
    if about is not None and about not in state["facts"] and about not in state["intents"] and about != "goal":
        return Reject("unknown_ref", "about 所指节点不存在")
    return Ok({"text": str(body["text"]), **({"about": about} if about else {})})


def _v_cost(state, actor, pid, body, cfg):
    l = state["leases"].get(body["task_id"])
    if l is None or l["problem_id"] != pid:
        return Reject("unknown_ref", "任务不存在")
    if body["source"] not in ("proxy", "judge", "cli_reported"):
        return Reject("schema_error", "source 非法")
    nums = {k: int(body.get(k) or 0) for k in ("tokens_in", "tokens_cached", "tokens_out", "usd_milli", "wall_s")}
    if any(v < 0 for v in nums.values()):
        return Reject("schema_error", "用量不能为负")
    return Ok({"task_id": l["id"], "source": body["source"], **nums,
               "price_table": str(body["price_table"]), **({"model": str(body["model"])} if body.get("model") else {}),
               **({"tokens_cached_unknown": True} if body.get("tokens_cached") is None else {})})


def _v_close_problem(state, actor, pid, body, cfg):
    if "terminal" in body and actor["kind"] != "graph":
        return Reject("schema_error", "terminal 是派生量，由图服务按三值算出")
    term = wk.terminal(state, pid)
    if actor["kind"] == "graph" and term != "solved":
        return Reject("schema_error", "图服务只在 Goal 到 E3 时自动关题")
    if wk.closeout_items(state, pid) and actor["kind"] == "graph":
        return Reject("schema_error", "四顾清单非空，需人确认")
    return Ok({"terminal": term, "by": actor["kind"], "card_hash": body.get("card_hash"),
               **({"reason": str(body["reason"])} if "reason" in body else {})})


def _v_budget_mark(state, actor, pid, body, cfg):
    return Ok({"mark": int(body["mark"]), "axis": str(body["axis"])})


_TIMED = {"lease": _v_lease, "renew": _v_renew, "release": _v_release, "expire_lease": _v_expire_lease}

_VALIDATORS = {"abandon_intent": _v_abandon_intent, "approve": _v_approve, "hint": _v_hint,
               "cost": _v_cost, "close_problem": _v_close_problem, "budget_mark": _v_budget_mark,
               "open_problem": _v_open_problem, "register_artifact": _v_register_artifact,
               "add_fact": _v_add_fact, "add_intent": _v_add_intent,
               "request_judge": _v_request_judge, "judge_verdict": _v_judge_verdict}


# ---------- apply ----------

def apply(state: dict, ev: dict) -> dict:
    """纯函数：返回新状态，不修改入参。只复制被改动的集合。"""
    s = dict(state)
    s["now"] = ev["ts"]
    s["seq"] = ev["seq"]
    kind, body, pid, seq = ev["kind"], ev["body"], ev["problem_id"], ev["seq"]
    session = ev["actor"].get("session")
    if kind == "open_problem":
        s["problems"] = {**s["problems"], pid: {**body, "id": pid, "closed": False, "opened_seq": seq,
                                                "opened_ts": ev["ts"]}}
    elif kind == "register_artifact":
        s["artifacts"] = {**s["artifacts"], f"a_{seq}": {**body, "id": f"a_{seq}", "problem_id": pid}}
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
            s["facts"] = {**s["facts"], fid: {**rec, "id": fid, "problem_id": pid, "session": session}}
            s["content_keys"] = {**s["content_keys"],
                                 pid: {**s["content_keys"].get(pid, {}), body["content_key"]: fid}}
    elif kind == "add_intent":
        iid = f"i_{seq}"
        s["intents"] = {**s["intents"], iid: {**body, "id": iid, "problem_id": pid, "session": session}}
    elif kind == "request_judge":
        rid = f"j_{seq}"
        s["requests"] = {**s["requests"], rid: {**body, "id": rid, "problem_id": pid}}
    elif kind == "judge_verdict":
        req = s["requests"][body["request"]]
        s["requests"] = {**s["requests"], req["id"]: {**req, "verdict_seq": seq}}
        s["verdicts"] = s["verdicts"] + [{
            "seq": seq, "problem_id": pid, "target": req["target"], "judge": req["judge_id"],
            "version": body["version"], "grade": body["grade"], "result": body["result"],
            "candidate": req["candidate"], "request": req["id"], "evidence": body["evidence"]}]
    elif kind == "lease":
        lid = f"l_{seq}"
        rec = {**body, "id": lid, "problem_id": pid, "issued_seq": seq, "active": True,
               "expires_at": ev["ts"] + body["ttl_s"] * 1000}
        s["leases"] = {**s["leases"], lid: rec}
        if body["kind"] == "explore":
            s["lease_seqs"] = {**s["lease_seqs"], body["target"]: s["lease_seqs"].get(body["target"], []) + [seq]}
    elif kind == "renew":
        l = s["leases"][body["lease"]]
        s["leases"] = {**s["leases"], l["id"]: {**l, "expires_at": ev["ts"] + body["ttl_s"] * 1000}}
    elif kind in ("release", "expire_lease"):
        l = s["leases"][body["lease"]]
        outcome = "expired" if kind == "expire_lease" else body["outcome"]
        s["leases"] = {**s["leases"], l["id"]: {**l, "active": False, "outcome": outcome, "ended_seq": seq,
                                                **({"transcript_ref": body["transcript_ref"]}
                                                   if body.get("transcript_ref") else {})}}
    elif kind == "abandon_intent":
        s["abandoned"] = s["abandoned"] + [body["intent"]]
    elif kind == "approve":
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
            s["hints"] = {**s["hints"], hid: {**body, "id": hid, "problem_id": pid, "seq": seq,
                                              "author": ev["actor"]["id"], "closed": False}}
    elif kind == "cost":
        lk = s["leases"][body["task_id"]]["kind"]
        s["costs"] = s["costs"] + [{**body, "problem_id": pid, "seq": seq, "lease_kind": lk}]
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


def result_id(ev: dict) -> str | None:
    """一条事件给提议方的返回 id。"""
    prefix = {"register_artifact": "a", "add_fact": "f", "add_intent": "i", "request_judge": "j",
              "lease": "l"}.get(ev["kind"])
    if ev["kind"] == "hint" and "close" not in ev["body"]:
        prefix = "h"
    if ev["kind"] == "add_fact" and ev["body"].get("merge_into"):
        return ev["body"]["merge_into"]
    return f"{prefix}_{ev['seq']}" if prefix else None
