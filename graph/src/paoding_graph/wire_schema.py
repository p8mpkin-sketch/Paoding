"""HTTP 绑定的线格式（graph/SPEC.md「HTTP 绑定」，HMI 设计 §11.2、§14）：JSON Schema（2020-12）的唯一事实源。

- 网页前端的类型文件 `web/src/api/types.ts` 由它生成：`uv run python scripts/gen-types.py`（CI 里带 `--check`）。
- 图服务的测试拿它校验真应答（`validate`，严格模式下对象不许有 schema 没列的键），所以 schema、服务、前端三方一致。

写法：`$defs` 里每个名字对应前端的一个导出类型。TypeScript 表达不了而 JSON Schema 也不需要的两样，用 `x-ts-` 前缀的
注记交给生成器，校验时忽略：类型参数（`x-ts-params`、`x-ts-param`、`x-ts-args`）。`description` 生成为注释。

本模块只描述形状，不做 IO，不进内核。
"""

from __future__ import annotations

from typing import Any

Schema = dict[str, Any]  # 一个 JSON Schema 片段

# ---------- 写法 ----------

STR: Schema = {"type": "string"}
INT: Schema = {"type": "integer"}
NUM: Schema = {"type": "number"}
BOOL: Schema = {"type": "boolean"}
ANY: Schema = {}  # 任意 JSON 值（TS 的 unknown）
OBJ: Schema = {"type": "object"}  # 任意对象（TS 的 Record<string, unknown>）


def ref(name: str, *args: str) -> Schema:
    d: Schema = {"$ref": f"#/$defs/{name}"}
    if args:
        d["x-ts-args"] = list(args)
    return d


def lit(*values: Any) -> Schema:
    return {"const": values[0]} if len(values) == 1 else {"enum": list(values)}


def arr(item: Schema) -> Schema:
    return {"type": "array", "items": item}


def null(s: Schema) -> Schema:
    return {"anyOf": [s, {"type": "null"}]}


def one(*xs: Schema, doc: str | None = None) -> Schema:
    d: Schema = {"anyOf": list(xs)}
    if doc:
        d["description"] = doc
    return d


def both(*xs: Schema, doc: str | None = None) -> Schema:
    d: Schema = {"allOf": list(xs)}
    if doc:
        d["description"] = doc
    return d


def rec(value: Schema, keys: Schema | None = None) -> Schema:
    d: Schema = {"type": "object", "additionalProperties": value}
    if keys:
        d["propertyNames"] = keys
    return d


def param(name: str) -> Schema:
    return {"x-ts-param": name}


def doc(s: Schema, text: str) -> Schema:
    return {**s, "description": text}


def obj(req: Schema | None = None, opt: Schema | None = None, *, doc: str | None = None) -> Schema:
    props = {**(req or {}), **(opt or {})}
    d: Schema = {"type": "object", "properties": props, "required": list(req or {})}
    if doc:
        d["description"] = doc
    return d


def env(body: Schema, doc: str | None = None) -> Schema:
    """视图端点的统一外壳加视图本身。"""
    return both(ref("Envelope"), body, doc=doc)


# ---------- 定义（次序即生成文件里的次序） ----------

D: dict[str, Schema] = {}
_SECTIONS: list[tuple[str, str]] = []  # (第一个定义名, 小节标题)


def section(title: str) -> None:
    _SECTIONS.append((f"__next__{len(_SECTIONS)}", title))


def define(name: str, schema: Schema) -> None:
    if _SECTIONS and _SECTIONS[-1][0].startswith("__next__"):
        _SECTIONS[-1] = (name, _SECTIONS[-1][1])
    D[name] = schema


RESULT = lit("pass", "fail", "inconclusive")

section("规格已定（§3.1.2、§3.2.2、§3.5.2）")
define("ArtifactId", STR)
define("Risk", lit("r0", "r1", "r2"))
define("Level", lit("E0", "E1", "E2", "E3d", "E3", "X"))
define("Terminal", lit("solved", "accepted", "unsolved"))
define("Grade", lit("decisive", "consistent", "advisory"))
define("ActorKind", lit("human", "sinan", "adapter", "judge", "executor", "watchdog", "graph"))
define("Actor", obj({"kind": ref("ActorKind"), "id": STR}, {"session": STR, "role": STR}))
define(
    "Event",
    obj(
        {
            "v": lit(1),
            "seq": INT,
            "problem_id": STR,
            "ts": INT,
            "actor": ref("Actor"),
            "kind": STR,
            "body": OBJ,
            "idem_key": STR,
            "prev_hash": STR,
            "hash": STR,
        }
    ),
)
define(
    "Profile",
    obj(
        {
            "info": lit("complete", "partial"),
            "judge": lit("hard", "costly", "deferred", "none"),
            "reversibility": ref("Risk"),
        }
    ),
)
define("ProfileAxis", lit("info", "judge", "reversibility"))
define("Budget", obj({"usd_milli": INT, "wall_s": INT}, {"tokens": INT}))
define("VaultRef", obj({"vault": STR, "digest": STR}))
define("Control", obj({"inputs": arr(ref("ArtifactId"))}, doc="对照判据（§3.3.3）：同规格、异输入，只用于观察类论断。"))
define(
    "Check",
    obj(
        {"judge_id": STR},
        {"spec_ref": ref("ArtifactId"), "expect": OBJ, "sealed": arr(ref("VaultRef")), "control": ref("Control")},
    ),
)
define(
    "ScopeRule",
    obj(
        {"resource": STR, "pattern": STR, "actions": arr(STR), "risk": ref("Risk")},
        {"granted": obj({"seq": INT, "by": STR, "request": STR}), "revoked": INT},
        doc="运行时扩权追加的规则带 granted（谁在哪个序号按哪条申请批的）；撤销的规则留在原位、带 revoked 序号。",
    ),
)
define(
    "DraftRef",
    obj(
        {"record": ref("ArtifactId"), "lane": lit("practice", "confirm")},
        {"policy": obj({"version": INT, "digest": STR})},
        doc="一句话开题的出处账引用与道别（增量 13）；policy 只在练习道，由图服务从信封抄入。",
    ),
)
define(
    "Origin",
    obj({"statement_ref": ref("ArtifactId"), "materials": arr(ref("ArtifactId"))}, {"draft": ref("DraftRef")}),
)
define("Env", obj({"base": STR, "baseline_ref": STR}))
define(
    "ProblemInput",
    obj(
        {
            "title": STR,
            "origin": ref("Origin"),
            "goal": obj(
                {"statement": STR, "check": ref("Check"), "max_attempts": INT, "accept": lit("judge", "human")}
            ),
            "scope": arr(ref("ScopeRule")),
            "budget": both(ref("Budget"), obj({"verify_share": NUM, "bootstrap_share": NUM})),
            "env": ref("Env"),
            "judges": arr(STR),
        },
        doc="open_problem 的事件体。没有 profile 字段：画像是派生量，提交时不接受（HMI §3.2 强制点）。"
        "题目 id 在批次外层。",
    ),
)
define("ArtifactClass", lit("exec", "judge", "input", "authored"))
define(
    "ExecRecord",
    obj(
        {
            "sandbox_id": STR,
            "base": STR,
            "baseline_ref": STR,
            "tool": STR,
            "command": STR,
            "cwd": STR,
            "exit_code": null(INT),
            "touched": arr(STR),
            "started_at": INT,
            "ended_at": INT,
            "truncated": BOOL,
        },
        {"killed": null(STR), "stdout_ref": null(STR), "stderr_ref": null(STR)},
    ),
)

section("读端点")
define("RegisterName", lit("证据", "叙述", "人", "估"))
D_TAGGED = {
    **obj(
        {"src": STR, "register": ref("RegisterName"), "value": param("T")},
        doc="凡文字内容都是这个形状。语域由服务端按出处类别查表给出；渲染只认 register，不看内容。",
    ),
    "x-ts-params": ["T = string"],
}
define("Tagged", D_TAGGED)
define(
    "Envelope",
    obj(
        {"as_of": INT, "head": INT, "view_hash": STR},
        {"state_hash": STR},
        doc="视图端点的统一外壳。as_of 是这份投影对应的序号（全局 seq）；view_hash = sha256(JCS(视图))。",
    ),
)
define(
    "Badge", obj({"judge_id": STR, "version": null(STR), "grade": null(ref("Grade")), "kind": null(STR), "label": STR})
)
define(
    "VerdictRow",
    obj(
        {
            "seq": INT,
            "result": RESULT,
            "judge": STR,
            "version": STR,
            "grade": null(ref("Grade")),
            "candidate": null(ref("ArtifactId")),
            "request": STR,
            "evidence": arr(ref("ArtifactId")),
        }
    ),
)
define(
    "Predicate",
    both(
        ref("Badge"),
        obj(
            {
                "target": STR,
                "spec_ref": null(ref("ArtifactId")),
                "spec_hash": null(STR),
                "expect": OBJ,
                "sealed": arr(ref("VaultRef")),
                "max_attempts": null(INT),
                "attempts_used": null(INT),
                "level": null(ref("Level")),
                "level_word": null(STR),
                "fail_means": lit("refuted", "not_yet"),
                "verdicts": arr(ref("VerdictRow")),
            }
        ),
        doc="判据卡：Goal、带判据的 Intent、观察类论断同形。",
    ),
)
define("IntentState", lit("open", "blocked", "leased", "done", "achieved", "needs_human", "abandoned"))
define("Decision", obj({"decision": lit("approve", "deny"), "by": STR, "seq": INT, "reason": ref("Tagged")}))
define(
    "FactBase",
    obj(
        {
            "id": STR,
            "type": lit("fact"),
            "seq": INT,
            "claim_type": lit("observation", "inference"),
            "level": ref("Level"),
            "level_word": STR,
            "unstable": BOOL,
            "disputed": BOOL,
            "stale": BOOL,
            "title": ref("Tagged"),
            "summary": ref("Tagged"),
            "premises": arr(STR),
            "yielded_by": null(STR),
            "session": null(STR),
            "predicate": null(ref("Predicate")),
        },
        doc="论断的公共部分；grounds 的形状随层而变。",
    ),
)
define("FactNode", both(ref("FactBase"), obj({"grounds": arr(ref("ArtifactId"))})))
define(
    "IntentNode",
    obj(
        {
            "id": STR,
            "type": lit("intent"),
            "seq": INT,
            "status": ref("IntentState"),
            "risk": ref("Risk"),
            "level": null(ref("Level")),
            "level_word": null(STR),
            "title": ref("Tagged"),
            "summary": ref("Tagged"),
            "premises": arr(STR),
            "budget": ref("Budget"),
            "session": null(STR),
            "needs_scope": arr(ref("ScopeRule")),
            "gate": BOOL,
            "approvals": arr(ANY),
            "attempts": INT,
            "predicate": null(ref("Predicate")),
            "decision": null(ref("Decision")),
            "expected_gain": null(ref("Tagged", "number")),
        },
        {"leases": arr(STR)},
    ),
)
define(
    "HintNode",
    obj(
        {
            "id": STR,
            "type": lit("hint"),
            "seq": INT,
            "ts": doc(null(INT), "Hint 事件的 ts（裁决 005-7）"),
            "author": STR,
            "closed": BOOL,
            "about": null(STR),
            "text": ref("Tagged"),
        }
    ),
)
define("GraphNode", one(ref("FactNode"), ref("IntentNode")))
define(
    "GroundRef",
    obj(
        {
            "id": ref("ArtifactId"),
            "class": ref("ArtifactClass"),
            "src": STR,
            "register": ref("RegisterName"),
            "hash": STR,
            "size": INT,
        }
    ),
)
NO_ROOT = doc(BOOL, "整条前提链上的“无证据根”（H6，裁决 005-4），由图服务算。")
define(
    "FactEvidence",
    both(
        ref("FactBase"),
        obj(
            {
                "problem_id": STR,
                "grounds": arr(ref("GroundRef")),
                "no_evidence_root": NO_ROOT,
                "body_ref": null(ref("ArtifactId")),
            }
        ),
    ),
)
define(
    "IntentEvidence", both(ref("IntentNode"), obj({"problem_id": STR, "leases": arr(STR), "no_evidence_root": NO_ROOT}))
)
define("HintEvidence", both(ref("HintNode"), obj({"problem_id": STR})))
define("NodeEvidence", both(ref("Envelope"), one(ref("FactEvidence"), ref("IntentEvidence"), ref("HintEvidence"))))
define(
    "LeaseRow",
    obj(
        {
            "id": STR,
            "kind": STR,
            "holder": STR,
            "reserve": ref("Budget"),
            "issued_seq": INT,
            "expires_at": INT,
            "active": BOOL,
        },
        {"target": STR, "outcome": STR, "ended_seq": INT, "transcript_ref": null(STR), "reflect": BOOL},
    ),
)
define(
    "ProblemHead",
    obj(
        {
            "id": STR,
            "title": ref("Tagged"),
            "closed": BOOL,
            "terminal": null(ref("Terminal")),
            "terminal_badge": ref("Badge"),
            "opened_seq": INT,
            "opened_ts": INT,
            "closed_seq": null(INT),
            "profile": ref("Profile"),
        }
    ),
)
define(
    "ProfileOverride",
    obj(
        {"axis": ref("ProfileAxis"), "value": STR, "derived": null(STR), "by": STR, "seq": INT, "reason": ref("Tagged")}
    ),
)
define(
    "JudgeRequestRow",
    obj(
        {
            "id": STR,
            "seq": INT,
            "target": STR,
            "judge_id": STR,
            "candidate": null(ref("ArtifactId")),
            "verdict_seq": null(INT),
        }
    ),
)
define(
    "StatusView",
    env(
        obj(
            {
                "problem": both(
                    ref("ProblemHead"),
                    obj(
                        {
                            "now_ts": INT,
                            "derived_profile": ref("Profile"),
                            "profile_overrides": arr(ref("ProfileOverride")),
                            "scope": arr(ref("ScopeRule")),
                            "env": ref("Env"),
                            "judges": arr(STR),
                            "origin": ref("Origin"),
                        }
                    ),
                ),
                "goal": obj(
                    {"statement": ref("Tagged"), "accept": lit("judge", "human"), "predicate": ref("Predicate")}
                ),
                "facts": arr(ref("FactNode")),
                "intents": arr(ref("IntentNode")),
                "hints": arr(ref("HintNode")),
                "leases": arr(ref("LeaseRow")),
                "requests": arr(ref("JudgeRequestRow")),
                "review": BOOL,
                "closeout": arr(ANY),
            }
        )
    ),
)
define(
    "HumanWorkItem",
    obj(
        {"kind": lit("human"), "target": STR, "why": STR},
        doc="why：needs_human（待审批的 Intent）、stalled（停滞，target 为题目 id）；M1 起还有续期门等。",
    ),
)
define(
    "WorkItem",
    one(
        obj({"kind": lit("bootstrap", "recall")}),
        obj({"kind": lit("reason")}, {"reflect": BOOL}),
        obj({"kind": lit("explore", "judge"), "target": STR}),
        obj(
            {"kind": lit("rejudge"), "target": STR, "judge": STR, "version": STR, "candidate": null(ref("ArtifactId"))}
        ),
        ref("HumanWorkItem"),
    ),
)
define("WorkView", env(obj({"items": arr(ref("WorkItem"))})))
define(
    "Frontier",
    obj(
        {
            "hints": arr(STR),
            "human": arr(ref("HumanWorkItem")),
            "disputed": arr(STR),
            "intents": arr(STR),
            "premises": arr(STR),
            "facts": arr(STR),
        }
    ),
)
define(
    "GraphView",
    env(obj({"layer": STR, "items": arr(ANY), "next_after_seq": null(INT), "total": INT, "frontier": ref("Frontier")})),
)
define("BudgetCap", obj(None, {"usd_milli": INT, "tokens": INT, "wall_s": INT}, doc="题预算上限；没设的轴不出现。"))
define(
    "BudgetResponse",
    env(
        obj(
            {
                "cap": ref("BudgetCap"),
                "spent": ref("Budget"),
                "reserved": ref("Budget"),
                "by_kind": rec(ref("Budget")),
                "verify_spent": ref("Budget"),
                "marks": arr(INT),
                "percent": obj({"spent": NUM, "committed": NUM}),
                "mark_lines": arr(INT),
                "mark_seqs": arr(INT),
                "verify_share": NUM,
                "bootstrap_share": NUM,
                "wall": obj({"cap_s": INT, "elapsed_s": INT}),
                "review": BOOL,
            }
        )
    ),
)
define(
    "ArtifactView",
    env(
        obj(
            {
                "id": ref("ArtifactId"),
                "problem_id": STR,
                "hash": STR,
                "size": INT,
                "media_type": STR,
                "class": ref("ArtifactClass"),
                "parents": arr(ref("ArtifactId")),
                "producer": obj({"actor": STR}, {"session": STR}),
                "seq": INT,
                "src": STR,
                "register": ref("RegisterName"),
                "exec": null(ref("ExecRecord")),
            }
        )
    ),
)
define("CardKind", lit("approval", "closeout", "extension", "dispute", "scope"))
define(
    "CardResponse",
    {
        **env(
            obj(
                {
                    "card": doc(
                        obj({"kind": ref("CardKind"), "target": STR, "fields": param("F")}),
                        "进 card_hash 的部分：只含与这一个决定有关的字段（参考模型的投影）。",
                    ),
                    "card_hash": STR,
                    "display": doc(param("D"), "排版用的附带信息，不进 card_hash；估值只在这里（I8）。"),
                }
            )
        ),
        "x-ts-params": ["F = Record<string, unknown>", "D = Record<string, unknown>"],
    },
)
define(
    "ApprovalPremise",
    obj(
        {
            "id": STR,
            "level": ref("Level"),
            "disputed": BOOL,
            "unstable": BOOL,
            "stale": BOOL,
            "controlled": BOOL,
            "waived": BOOL,
        }
    ),
)
define(
    "ApprovalFields",
    obj(
        {
            "risk": ref("Risk"),
            "budget": ANY,
            "done": ANY,
            "tests": arr(STR),
            "needs_scope": ANY,
            "rollback": ANY,
            "premises": arr(ref("ApprovalPremise")),
        }
    ),
)
define(
    "DisplayPremise",
    obj(
        {
            "id": STR,
            "type": lit("fact", "intent"),
            "level": null(ref("Level")),
            "level_word": null(STR),
            "title": ref("Tagged"),
        }
    ),
)
define(
    "ApprovalDisplay",
    obj(
        {
            "status": ref("IntentState"),
            "title": ref("Tagged"),
            "summary": ref("Tagged"),
            "reserve": ref("Budget"),
            "lease_note": STR,
            "rollback": null(ref("Tagged")),
            "predicate": null(ref("Predicate")),
            "premises": arr(ref("DisplayPremise")),
            "disputes": arr(ANY),
            "needs_scope": arr(ref("ScopeRule")),
            "scope": arr(ref("ScopeRule")),
            "expected_gain": null(ref("Tagged", "number")),
            "rollback_declared": BOOL,
            "approve_enabled": BOOL,
            "decision": null(ref("Decision")),
        }
    ),
)
define(
    "ScopeCardFields",
    obj(
        {
            "rules": arr(ref("ScopeRule")),
            "why": STR,
            "status": lit("pending", "granted", "denied"),
            "auto": BOOL,
            "scope": arr(ref("ScopeRule")),
            "closed": BOOL,
        },
        doc="扩权卡进 card_hash 的部分（runtime-grants §7.1）：申请的规则（风险已查表）、理由、现有有效范围。",
    ),
)
define(
    "ScopeDecision",
    obj(
        {
            "decision": lit("approve", "deny"),
            "by": null(STR),
            "seq": null(INT),
            "via": null(lit("auto", "approval")),
            "policy_version": null(INT),
            "reason": ref("Tagged"),
        }
    ),
)
define(
    "ScopeDisplay",
    obj(
        {
            "status": lit("pending", "granted", "denied"),
            "why": ref("Tagged"),
            "by": STR,
            "session": null(STR),
            "role": null(STR),
            "intent": null(STR),
            "auto": BOOL,
            "blockers": arr(STR),
            "risk_rows": doc(
                null(arr(null(INT))), "逐条：风险表命中的行号（从 1 起），null 即未命中、按缺省 r2；旧事件整项为 null。"
            ),
            "profile": doc(
                null(obj({"before": ref("Profile"), "after": ref("Profile"), "overridden": arr(STR)})),
                "批准前后的画像（与开题同一个推导函数）；已决定的申请为 null。",
            ),
            "risk_choices": arr(ref("Risk")),
            "approve_enabled": BOOL,
            "decision": null(ref("ScopeDecision")),
        }
    ),
)
define(
    "ExtensionFields",
    obj(
        {"progress_since_50": arr(STR), "spent_usd_milli": INT, "cap_usd_milli": INT},
        doc="续期卡随 M1 落地（真图服务现在返回 not_enabled）；字段形状是 F1 的暂行约定。",
    ),
)
define(
    "HintTrace",
    env(
        obj(
            {
                "hint": ref("HintNode"),
                "closed_seq": null(INT),
                "note": STR,
                "temporal": obj({"added": arr(STR), "abandoned": arr(STR)}),
                "exposure": null(obj({"sessions": arr(STR), "added": arr(STR), "abandoned": arr(STR)})),
            }
        )
    ),
)
define(
    "ProfilePreview",
    obj(
        {
            "profile": ref("Profile"),
            "basis": doc(
                obj({"info": OBJ, "judge": OBJ, "reversibility": OBJ}),
                "每轴的推导依据：rule 加若干指针字段（scope_index、judge_id…），按键值原样列出。",
            ),
        }
    ),
)
define("JudgeEntry", obj({"judge_id": STR, "version": STR, "grade": ref("Grade"), "kind": STR, "max_cost": NUM}))
define("JudgesResponse", obj({"items": arr(ref("JudgeEntry")), "external_resources": arr(STR)}))
define("CatalogItem", obj({"name": STR, "hash": STR, "size": INT, "signature": null(STR), "data": ANY, "text": STR}))
define("Catalog", obj({"items": arr(ref("CatalogItem"))}))
define(
    "ProblemItem",
    both(
        ref("ProblemHead"),
        obj(
            {
                "spent_usd_milli": INT,
                "cap_usd_milli": null(INT),
                "closed_ts": null(INT),
                "goal_level": null(ref("Level")),
                "active": arr(obj({"kind": STR}, {"target": STR})),
                "human_todo": INT,
                "wall": obj({"cap_s": INT, "elapsed_s": INT}),
            },
            doc="题目列表的一行。closed_ts 是关题事件的 ts；active 是在途租约的种类与目标（不推断“阶段”）。",
        ),
    ),
)
define(
    "ProblemsView",
    env(
        obj(
            {
                "items": arr(ref("ProblemItem")),
                "totals": obj(
                    {"problems": INT, "solved": INT, "spent_usd_milli": INT, "cost_per_solve_usd_milli": null(INT)}
                ),
            }
        )
    ),
)
define("EventsResponse", obj({"events": arr(ref("Event")), "head": INT, "next_after": INT}))
define("HealthResponse", obj({"ok": BOOL, "head": INT, "api": STR}))

section("合并读与刻度（P2-1）")
define("SnapshotPart", lit("status", "view", "budget", "work"))
define(
    "PartsHash",
    obj(
        {"status": STR, "view": STR, "budget": STR, "work": STR},
        doc="四份投影各自的 view_hash。事件流的 view 帧与 snapshot 应答都带它。",
    ),
)
define(
    "SnapshotResponse",
    obj(
        {"as_of": INT, "head": INT, "view_hash": STR, "parts_hash": ref("PartsHash")},
        {
            "status": ref("StatusView"),
            "view": ref("GraphView"),
            "budget": ref("BudgetResponse"),
            "work": ref("WorkView"),
        },
        doc="GET /v1/problems/{pid}/snapshot：四份投影与单独的端点同形；`parts=` 只要其中几份。",
    ),
)
define(
    "WireTick",
    obj(
        {"seq": INT, "ts": INT, "kind": STR},
        {"result": RESULT, "mark": INT, "decision": STR, "via": STR, "policy_version": INT},
        doc="时间轴的一格：每条事件只有 seq、ts、种类；判官裁决另带 result，预算标记另带 mark；"
        "扩权的批准与拒绝（grant_scope）另带 decision，图服务批准时带 via，自动批准带信封版本 policy_version。",
    ),
)
define(
    "TicksResponse",
    obj({"as_of": INT, "head": INT, "ticks": arr(ref("WireTick")), "last_seq": INT, "head_hash": null(STR)}),
)
define("ViewFrame", obj({"as_of": INT, "parts_hash": ref("PartsHash")}, doc="事件流里一批事件之后的具名帧。"))

section("写")
define(
    "HumanOpKind",
    {
        **lit(
            "open_problem",
            "register_artifact",
            "hint",
            "approve",
            "profile_override",
            "abandon_intent",
            "close_problem",
            "add_intent",
            "extend",
            "budget_add",
            "pause",
            "resume",
            "rule",
            "accept",
            "judge_revoke",
            "intent_done",
            "grant_scope",
            "revoke_scope",
        ),
        "description": "add_intent 之后的几种随后续里程碑启用（规格 3.1.9）；M0 的图服务以 schema_error 拒绝。",
    },
)
define("Op", obj({"op": ref("HumanOpKind"), "body": OBJ}))
define("Seen", obj({"seq": INT, "card_hash": STR}))
define(
    "OpResult",
    one(
        obj({"ok": lit(True), "id": null(STR), "seq": INT}),
        obj({"ok": lit(False), "code": STR}, {"detail": STR, "card": ANY, "as_of": INT}),
    ),
)
define("ProposalResponse", obj({"ok": BOOL, "results": arr(ref("OpResult"))}, {"id": STR}))
define("ErrorBody", obj({"ok": lit(False), "code": STR}, {"detail": STR}))

SCHEMA: Schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://paoding.local/schema/wire.json",
    "title": "庖丁图服务 HTTP 绑定的线格式",
    "$defs": D,
}
SECTIONS: dict[str, str] = dict(_SECTIONS)  # 定义名 → 它前面的小节标题


# ---------- 校验（测试用；只认上面用到的那几种关键字） ----------


def validate(name: str, value: Any, *, strict: bool = True) -> list[str]:
    """按 $defs[name] 校验 value，返回错误清单（空即通过）。strict：对象不许有 schema 没列出的键
    （跨 allOf 合并后再看），用来发现服务端多出、而前端类型不知道的字段。"""
    errs: list[str] = []
    _check(ref(name), value, "$", errs, strict, frozenset())
    return errs


_PY: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
    "array": list,
    "object": dict,
}


def _resolve(s: Schema) -> Schema:
    while "$ref" in s:
        s = D[s["$ref"].rsplit("/", 1)[1]]
    return s


def _keys(s: Schema) -> set[str] | None:
    """一个 schema 认得的对象键；None 表示说不准（含 anyOf、任意对象、Record、类型参数）。"""
    s = _resolve(s)
    if "allOf" in s:
        out: set[str] = set()
        for x in s["allOf"]:
            k = _keys(x)
            if k is None:
                return None
            out |= k
        return out
    if "properties" in s and "additionalProperties" not in s:
        return set(s["properties"])
    return None


def _ok(s: Schema, v: Any, strict: bool, outer: frozenset[str] | None) -> bool:
    e: list[str] = []
    _check(s, v, "", e, strict, outer)
    return not e


def _check(s: Schema, v: Any, at: str, errs: list[str], strict: bool, outer: frozenset[str] | None) -> None:
    """outer：外层 allOf 的兄弟分支认得的键，这一层也不算多出；None 表示多出的键由外层统一判。"""
    s = _resolve(s)
    if not s or "x-ts-param" in s:
        return
    if "allOf" in s:
        ks = _keys(s)
        if ks is not None:  # 全部分支的键都确定：合并后一次判多出
            for x in s["allOf"]:
                _check(x, v, at, errs, strict, None)
            if strict and outer is not None and isinstance(v, dict):
                extra = set(v) - ks - outer
                if extra:
                    errs.append(f"{at}: 多出的键 {sorted(extra)}")
            return
        known = [_keys(x) for x in s["allOf"]]  # 含 anyOf 的：把兄弟的键传给它
        for i, x in enumerate(s["allOf"]):
            sib = frozenset().union(*(k for j, k in enumerate(known) if j != i and k is not None))
            sub = None if outer is None or known[i] is not None else outer | sib
            _check(x, v, at, errs, strict, sub)  # 键确定的分支只校形状，多出的键归含 anyOf 的那支判
        return
    if "anyOf" in s:
        if not any(_ok(x, v, strict, outer) for x in s["anyOf"]):
            best: list[str] = []
            for x in s["anyOf"]:
                e: list[str] = []
                _check(x, v, at, e, strict, outer)
                if not best or len(e) < len(best):
                    best = e
            errs.append(f"{at}: 哪一支都不符（最接近的一支：{best[:3]}）")
        return
    if "const" in s:
        if v != s["const"] or type(v) is not type(s["const"]):
            errs.append(f"{at}: 应为 {s['const']!r}，是 {v!r}")
        return
    if "enum" in s:
        if v not in s["enum"]:
            errs.append(f"{at}: {v!r} 不在 {s['enum']}")
        return
    t = s.get("type")
    py: type | tuple[type, ...] | None = _PY.get(t) if isinstance(t, str) else None
    if py is not None and (not isinstance(v, py) or (t in ("integer", "number") and isinstance(v, bool))):
        errs.append(f"{at}: 应为 {t}，是 {type(v).__name__}")
        return
    if t == "array":
        for i, x in enumerate(v):
            _check(s["items"], x, f"{at}[{i}]", errs, strict, frozenset())
    elif t == "object":
        props = s.get("properties", {})
        for k in s.get("required", []):
            if k not in v:
                errs.append(f"{at}: 缺键 {k}")
        for k, x in v.items():
            if k in props:
                _check(props[k], x, f"{at}.{k}", errs, strict, frozenset())
            elif "additionalProperties" in s:
                _check(s["additionalProperties"], x, f"{at}.{k}", errs, strict, frozenset())
            elif strict and "properties" in s and outer is not None and k not in outer:
                errs.append(f"{at}: 多出的键 {k}")
