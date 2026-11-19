"""记忆召回在内核里的两处（规格 v1.5 增量 8、9、10；4.3 的"记忆条目与投影资产"）。

- 开题：`Problem.labels`、`Problem.recall` 两个可选字段的校验。召回清单随开题事件登记，之后不可改（I4 同族）；
  它不进等级函数、消费门与画像。召回判据的 spec 与对照输入必须是同批登记的 input 类 Artifact。
- 角色 `recall` 的操作白名单：只能提交召回清单里的判据作观察（标题带"[忆] "、无前提、grounds 只有该判据的
  spec），以及对它们 `request_judge`。等级照旧由本题判官的裁决决定（I7：记忆不携带等级过界）。

两个字段都缺省时，开题事件与旧日志逐字节相同。
"""

from __future__ import annotations

from ..jcs import canonicalize
from ..parse import Obj
from ..state import Actor, Body, Check, State
from .common import _HEX64, Reject, _check, _ref

MAX_RECALL = 8  # 每题至多 8 条事实（规格 2.3 结构清单）
MAX_NOTES = 16
PREFIX = "[忆] "
NOTE_KINDS = ("env_fact", "excluded", "spend_profile")
MODES = ("verify", "noverify")  # noverify 是消融臂：召回但不复核，事实只作叙述


def _labels(body: Obj) -> Body | Reject:
    lab = body.child("labels")
    if not lab.keys() <= {"tags", "env"}:
        return Reject("schema_error", f"labels 多余字段 {sorted(lab.keys() - {'tags', 'env'})}")
    tags = lab.strings("tags", [])
    out: Body = {"tags": sorted(set(tags))}
    if "env" in lab:
        env = lab.string("env")
        if not env or len(env) > 200:
            return Reject("schema_error", "labels.env 须为 1 到 200 字符")
        out["env"] = env
    return out


def _recall(state: State, pid: str, body: Obj, judges: list[str]) -> Body | Reject:
    r = body.child("recall")
    allowed = {"items", "excluded_by_human", "match_digest", "mode", "notes"}
    if not r.keys() <= allowed or not {"items", "match_digest"} <= r.keys():
        return Reject("schema_error", f"recall 须有 items、match_digest，可选 {sorted(allowed)}")
    mode = r.string("mode", "verify")
    if mode not in MODES:
        return Reject("schema_error", f"recall.mode 只取 {MODES}")
    if not _HEX64.match(r.string("match_digest")):
        return Reject("schema_error", "match_digest 须为 sha256")
    raw = r.children("items")
    if len(raw) > MAX_RECALL:
        return Reject("schema_error", f"召回至多 {MAX_RECALL} 条")
    if mode == "noverify" and raw:
        return Reject("schema_error", "noverify 不复核：事实只放 notes，items 须为空")
    items: list[Body] = []
    seen: set[str] = set()
    for it in raw:
        if it.keys() != {"mem", "title", "check"}:
            return Reject("schema_error", "召回条目只有 mem、title、check")
        mem, title = it.string("mem"), it.string("title")
        if not _HEX64.match(mem) or mem in seen:
            return Reject("schema_error", "召回条目的 mem 须为互不相同的 sha256")
        if not title or len(PREFIX + title) > 120:
            return Reject("schema_error", "召回条目的标题加前缀后不超过 120 字符")
        check = _check(it.child("check"), observation=True)
        if check["judge_id"] not in judges:
            return Reject("unknown_ref", f"召回判据的判官 {check['judge_id']} 不在本题启用的判官里")
        if "spec_ref" not in check or check.get("sealed"):
            return Reject("schema_error", "召回判据须带 spec_ref，且不得引用保密库")
        refs = [check["spec_ref"], *(check["control"]["inputs"] if "control" in check else [])]
        for ref in refs:
            err = _ref(state, pid, ref, "召回判据的引用")
            if err:
                return err
            if state["artifacts"][ref]["class"] != "input":
                return Reject("inadmissible_class", "召回判据的 spec 与对照输入只接受同批登记的 input 类")
        seen.add(mem)
        items.append({"mem": mem, "title": title, "check": check})
    notes: list[Body] = []
    for n in r.children("notes", []):
        if not n.keys() <= {"mem", "kind", "title", "body"} or not {"mem", "kind", "title"} <= n.keys():
            return Reject("schema_error", "notes 条目有 mem、kind、title，可选 body")
        if n.string("kind") not in NOTE_KINDS:
            return Reject("schema_error", f"notes.kind 只取 {NOTE_KINDS}")
        notes.append({k: n.raw[k] for k in ("mem", "kind", "title", "body") if k in n})
    if len(notes) > MAX_NOTES:
        return Reject("schema_error", f"notes 至多 {MAX_NOTES} 条")
    return {
        "items": items,
        "excluded_by_human": sorted(set(r.strings("excluded_by_human", []))),
        "match_digest": r.string("match_digest"),
        **({"mode": mode} if mode != "verify" else {}),
        **({"notes": notes} if notes else {}),
    }


def open_extras(state: State, pid: str, body: Obj, judges: list[str]) -> Body | Reject:
    """open_problem 的 v1.5 可选字段。缺省时返回空体，事件体与旧版逐字节相同。"""
    out: Body = {}
    if "labels" in body:
        lab = _labels(body)
        if isinstance(lab, Reject):
            return lab
        out["labels"] = lab
    if "recall" in body:
        rec = _recall(state, pid, body, judges)
        if isinstance(rec, Reject):
            return rec
        out["recall"] = rec
    return out


# ---------- 角色 recall 的白名单（增量 8） ----------


def _same(a: Check, b: Body) -> bool:
    return canonicalize(a) == canonicalize(b)


def whitelist(state: State, actor: Actor, pid: str, kind: str, body: Body) -> Reject | None:
    """recall 会话只许做两件事：把召回清单里的判据原样提交为观察，对它们请求判定。"""
    if actor.get("role") != "recall":
        return None
    if kind == "release":
        return None
    if kind not in ("add_fact", "request_judge"):
        return Reject("forbidden_op", f"recall 角色不能提交 {kind}")
    p = state["problems"].get(pid)
    items = (p.get("recall") or {}).get("items", []) if p else []
    if kind == "request_judge":
        f = state["facts"].get(str(body.get("target")))
        if f is None or f["problem_id"] != pid or f["session"] != actor.get("session"):
            return Reject("forbidden_op", "recall 角色只能对本次召回提交的观察请求判定")
        return None
    check, title = body.get("check"), body.get("title")
    ok = (
        body.get("claim_type") == "observation"
        and not body.get("premises")
        and isinstance(check, dict)
        and any(
            _same(it["check"], check)
            and title == PREFIX + it["title"]
            and body.get("grounds") == [it["check"]["spec_ref"]]
            for it in items
        )
    )
    if not ok:
        return Reject("forbidden_op", "recall 角色只能原样提交召回清单里的判据（带前缀、无前提、grounds 为其 spec）")
    return None
