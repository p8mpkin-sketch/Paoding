"""按题读、答题、回头核对里调模型的那几步（docs/design/fenjue/14-question-led.md §3–§6）。

每一步都是「无工具、一问一答、输出过形状检查」的调用，模型的输出只是提议：

- `ask_terms`、`ask_pick`：把子问换成检索词；再从对方仓库里真实存在的名字里挑词（挑的每个词必须逐字在表里）。
- `read_part`：读一个文件的一部分（带行号）。交回三样：**细事实**（答题用，一条一句、各带行区间、可逐条核对）、
  观察（照旧给识别候选用，形状与片段阅读的相同，出处收窄到它自己的行区间）、值得追的标识符。
- `draft`：只凭细事实写回答——每条结论引用细事实的编号。文件与行由引擎从编号推出，模型不写。
- `verify`、`fix`：把结论与它引用的原文交给另一个隔离的调用判「支持、部分、不支持」；部分支持的改写一次再核。
  结论最后的标注以核对结果为准。

细事实与观察是两套东西：观察照旧不带任何对方的名字，供后面的候选、提炼、归位用（那几步的隔离规则不变）；
细事实允许带对方的名字与数值，只给答题与核对这两步看，留在工作区的簿记里，不登记成产物。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..shapes import digest
from . import data, shihuo, survey, text, wenti
from .dan import Dan, estimate_tokens, new_nonce, reading

ATTEMPTS = 3  # 阅读：首次 + 重来至多 2 次（与片段阅读相同）
DRAFT_ATTEMPTS = 2
MAX_FACTS = 24  # 一次阅读至多交回的细事实〔占位〕
MAX_FOLLOW = 12
FACT_CHARS = 320
FACT_SPAN = 60  # 一条细事实的行区间至多这么宽：窄才核对得动
LCS_MAX = 12  # 与原文的最长公共片段须短于这个数（词元），与现有「不抄写」的门槛同一个数
MAX_POINTS = 16  # 每个子问至多这么多条结论
MAX_RECS = 8
VERIFY_BATCH = 6  # 一次核对调用里的结论条数
VERIFY_FACTS = 3  # 一条结论至多拿它引用的前几条细事实的原文去核
VERIFY_PAD = 3  # 核对时原文区间前后各多给几行
KINDS = ("mechanism", "behavior", "doc_claim", "config", "test_spec")
VERDICTS = ("supported", "partial", "unsupported")
_FILELINE = re.compile(r"[\w./-]+\.[A-Za-z]{1,5}:\d+|第\s*\d+\s*行|\bL\d+\b|\blines?\s*\d+", re.IGNORECASE)


def fact_id(rec: Mapping[str, Any]) -> str:
    body = {k: rec[k] for k in ("snapshot", "path", "lines", "text")}
    return "f" + digest(body)[:12]


def _internal_terms(s: str) -> list[str]:
    return [t for t in data.table("vocab")["internal_terms"] if t in s]


# ---------------------------------------------------------------- 题面 → 检索词


def ask_terms(
    dan: Dan, qs: Sequence[Mapping[str, str]], feedback: Sequence[str] = (), rnd: int = 1
) -> tuple[dict[str, tuple[list[str], list[str]]], int, int]:
    """把每个子问换成中英文检索词。模型此刻没见过对方仓库：只看题面。`feedback` 是上一轮各词的命中数。"""
    errors: list[str] = list(feedback)
    tin = tout = 0
    out: dict[str, tuple[list[str], list[str]]] = {}
    for attempt in range(1, DRAFT_ATTEMPTS + 1):
        key = f"wenti:terms:{rnd}:{attempt}"
        payload: dict[str, Any] = {"template": "wenti/terms/v1", "questions": list(qs), "max_terms": 16}
        if errors:
            payload["errors"] = errors
        r = dan.call("reader", key, payload)
        tin, tout = tin + r.tokens_in, tout + r.tokens_out
        with reading(key):
            rows = r.output.get("terms") if isinstance(r.output, dict) else None
            out = {}
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict) and row.get("q") in {q["id"] for q in qs}:
                    out[str(row["q"])] = wenti.clean_terms(row)
            missing = [q["id"] for q in qs if not any(out.get(q["id"], ([], [])))]
        if not missing:
            break
        errors = [*feedback, f"这几个子问没有给出可用的检索词：{'、'.join(missing)}"]
    return out, tin, tout


def ask_pick(
    dan: Dan, qs: Sequence[Mapping[str, str]], vocab: Mapping[str, Sequence[str]], nonce: Callable[[], str] = new_nonce
) -> tuple[dict[str, dict[str, list[str]]], int, int]:
    """从对方仓库里真实存在的名字里挑词：名字表是外部数据（定界包裹），挑中的必须逐字在表里，否则不收。"""
    names, files = list(vocab["names"]), list(vocab["files"])
    listing = "## 名字\n" + "\n".join(names) + "\n\n## 文件\n" + "\n".join(files)
    errors: list[str] = []
    tin = tout = 0
    out: dict[str, dict[str, list[str]]] = {}
    for attempt in range(1, DRAFT_ATTEMPTS + 1):
        key = f"wenti:pick:{attempt}"
        payload: dict[str, Any] = {
            "template": "wenti/pick/v1",
            "questions": list(qs),
            "max_names": 20,
            "max_files": 6,
            "excerpt": listing,
            "nonce": nonce(),
        }
        if errors:
            payload["errors"] = errors
        r = dan.call("reader", key, payload)
        tin, tout = tin + (r.tokens_in or estimate_tokens(listing) + 800), tout + r.tokens_out
        with reading(key):
            rows = r.output.get("picks") if isinstance(r.output, dict) else None
            out, bad = {}, 0
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict) or row.get("q") not in {q["id"] for q in qs}:
                    continue
                got_n = [n for n in row.get("names") or [] if isinstance(n, str)]
                got_f = [f for f in row.get("files") or [] if isinstance(f, str)]
                bad += sum(1 for n in got_n if n not in names) + sum(1 for f in got_f if f not in files)
                out[str(row["q"])] = {
                    "names": [n for n in dict.fromkeys(got_n) if n in names][:20],
                    "files": [f for f in dict.fromkeys(got_f) if f in files][:6],
                }
        if out and not bad:
            break
        errors = (
            ["输出应为 {picks: [{q, names, files}]}"]
            if not out
            else [f"有 {bad} 个词或文件不在给出的表里：只能逐字从表里挑"]
        )
    return out, tin, tout


# ---------------------------------------------------------------- 阅读一部分


@dataclass
class PartRead:
    part: wenti.Part
    facts: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    obs_q: dict[str, str] = field(default_factory=dict)  # 观察 id → 它回答的子问
    follow: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    failed: bool = False
    dropped: int = 0  # 没过检查被丢掉的细事实条数
    truncated: int = 0  # 被输出上限截断的次数


def _lines_ok(v: Any, part: wenti.Part) -> tuple[int, int] | None:
    if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in v)):
        return None
    a, b = int(v[0]), int(v[1])
    return (a, b) if part.a <= a <= b <= part.b else None


def _parse_part(
    out: Any,
    snap: survey.Snapshot,
    part: wenti.Part,
    qids: Sequence[str],
    slot: str | None,
    side: str,
    flags: Sequence[str],
    nonce: str,
    attempt: int,
    shown: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str], list[str], list[str]]:
    """交回 (细事实, 观察, 观察→子问, 追的标识符, 错误)。形状不对整份重来；个别条目不合规矩的单条丢掉并记一条错误。"""
    if not isinstance(out, dict) or not isinstance(out.get("facts"), list):
        return [], [], {}, [], ["输出应为 {facts: [...], observations: [...], follow: [...]}"]
    errs: list[str] = []
    facts: list[dict[str, Any]] = []
    body_tokens = text.tokens(wenti.raw_range(snap, part.path, part.a, part.b))
    if len(out["facts"]) > MAX_FACTS:
        errs.append(f"细事实至多 {MAX_FACTS} 条，这次给了 {len(out['facts'])} 条：只留与子问最相关的")
    for i, item in enumerate(out["facts"][:MAX_FACTS], 1):
        if not isinstance(item, dict):
            errs.append(f"细事实第 {i} 条不是对象")
            continue
        t = str(item.get("text") or "").strip()
        rng = _lines_ok(item.get("lines"), part)
        why = ""
        if not t or len(t) > FACT_CHARS:
            why = f"text 须是 1–{FACT_CHARS} 字的一句话"
        elif rng is None:
            why = f"lines 须是 [起行, 止行]，落在给你的 {part.a}–{part.b} 行之内"
        elif rng[1] - rng[0] + 1 > FACT_SPAN:
            why = f"行区间太宽（{rng[1] - rng[0] + 1} 行）：一条事实指到它所在的那几行，至多 {FACT_SPAN} 行"
        elif item.get("q") not in qids:
            why = f"q 须是 {'、'.join(qids)} 之一"
        elif item.get("kind") not in KINDS:
            why = f"kind 须是 {'、'.join(KINDS)} 之一"
        elif "```" in t:
            why = "不要用代码围栏"
        elif text.instruction_hits(text.without_hidden(t)):
            why = "写成了指令的口气：只陈述原文做了什么"
        elif text.longest_common_run(text.tokens(t), body_tokens) >= LCS_MAX:
            why = "照抄了原文的一长段：用自己的话说，名字与数值可以保留"
        if why:
            errs.append(f"细事实第 {i} 条：{why}")
            continue
        assert rng is not None
        rec: dict[str, Any] = {
            "side": side,
            "q": item["q"],
            "kind": item["kind"],
            "text": t,
            "snapshot": snap.sid,
            "path": part.path,
            "lines": [rng[0], rng[1]],
            "sha256": survey._sha(wenti.raw_range(snap, part.path, rng[0], rng[1]).encode()),
        }
        sym = wenti.enclosing(snap, part.path, rng[0])
        if sym:
            rec["symbol"] = sym
        if flags:
            rec["flagged"] = True
        rec["id"] = fact_id(rec)
        if rec["id"] not in {f["id"] for f in facts}:
            facts.append(rec)
    observations: list[dict[str, Any]] = []
    obs_q: dict[str, str] = {}
    items = out.get("observations") if slot else []
    for i, item in enumerate(items if isinstance(items, list) else [], 1):
        if i > shihuo.MAX_OBS_PER_READ:
            errs.append(f"观察至多 {shihuo.MAX_OBS_PER_READ} 条")
            break
        if not isinstance(item, dict):
            continue
        rng = _lines_ok(item.get("lines"), part)
        if rng is None:
            errs.append(f"观察第 {i} 条：lines 须落在 {part.a}–{part.b} 行之内")
            continue
        raw = wenti.raw_range(snap, part.path, rng[0], rng[1])
        e = survey.Excerpt(snap.sid, part.path, rng, survey._sha(raw.encode()))
        plain = {k: v for k, v in item.items() if k not in ("lines", "q")}
        recs, bad = shihuo._parse_reader({"observations": [plain]}, str(slot), snap, e, flags, nonce, attempt)
        if bad:
            errs += [f"观察第 {i} 条：{b.partition('：')[2] or b}" for b in bad]
            continue
        observations += recs
        for r in recs:
            obs_q[r["id"]] = str(item.get("q")) if item.get("q") in qids else qids[0]
    raw_follow = out.get("follow")
    follow = [n for n in (raw_follow if isinstance(raw_follow, list) else []) if wenti.follow_ok(n, shown)]
    return facts, observations, obs_q, list(dict.fromkeys(follow))[:MAX_FOLLOW], errs


def read_part(
    dan: Dan,
    ix: wenti.Index,
    part: wenti.Part,
    qs: Sequence[Mapping[str, str]],
    slot: str | None,
    *,
    side: str = "theirs",
    nonce: Callable[[], str] = new_nonce,
) -> PartRead:
    """读一个文件的一部分。`slot` 给了就同时交观察（对方仓库）；不给只交细事实（我们自己的实现）。"""
    snap = ix.snap
    shown = wenti.numbered(snap, part)
    flags = text.injection_hits(wenti.raw_range(snap, part.path, part.a, part.b))
    whole = part.a == 1 and part.b >= ix.lines[part.path]
    res = PartRead(part)
    errors: list[str] = []
    for attempt in range(1, ATTEMPTS + 1):
        n = nonce()
        key = f"qread:{part.key()}:{attempt}"
        payload: dict[str, Any] = {
            "template": "reader/q/v1",
            "side": side,
            "questions": list(qs),
            "path": part.path,
            "lines": [part.a, part.b],
            "whole_file": whole,
            "max_facts": MAX_FACTS,
            "max_observations": shihuo.MAX_OBS_PER_READ if slot else 0,
            "max_follow": MAX_FOLLOW,
            "excerpt": shown
            if whole
            else "## 本文件的定义大纲（行号: 名字）\n"
            + "\n".join(wenti.outline(ix, part.path))
            + "\n\n## 原文\n"
            + shown,
            "nonce": n,
        }
        if slot:
            sig = data.signatures()[slot]
            payload["slot"] = slot
            payload["slot_decides"] = sig["decides"]
            payload["dims"] = [
                {"dim": d["dim"], "meaning": d["meaning"]} for d in data.profile()["dims"] if d["slot"] == slot
            ]
            payload["primitives"] = sorted(data.primitives())
        if errors:
            payload["errors"] = errors
        r = dan.call("reader", key, payload)
        res.tokens_in += r.tokens_in or estimate_tokens(shown) + 1500
        res.tokens_out += r.tokens_out
        if r.output is None and r.stop == "max_tokens":
            res.truncated += 1
            errors = ["上一次的输出被输出上限截断，JSON 不完整：细事实只留最要紧的，思考从简，重新输出完整的 JSON"]
            continue
        with reading(key):
            facts, obs, obs_q, follow, errors = _parse_part(
                r.output, snap, part, [q["id"] for q in qs], slot, side, flags, n, attempt, shown
            )
        shape_bad = not isinstance(r.output, dict) or not isinstance(r.output.get("facts"), list)
        many = len(errors) > max(2, len(facts) // 4)
        if shape_bad or (many and attempt < ATTEMPTS):
            continue  # 形状不对，或不合规矩的条目太多：带着错误重读
        # 个别条目没过：不为它们整份重读，收下合格的，丢掉的条数记下
        res.facts, res.observations, res.obs_q, res.follow = facts, obs, obs_q, follow
        res.dropped = len(errors)
        return res
    res.failed = True
    return res


# ---------------------------------------------------------------- 答题稿


def draft_payload(
    qs: Sequence[Mapping[str, str]],
    facts: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
    profile: Sequence[Mapping[str, Any]],
    own_read: bool,
    errors: Sequence[str],
) -> dict[str, Any]:
    def row(f: Mapping[str, Any]) -> dict[str, Any]:
        r = {"id": f["id"], "q": f["q"], "kind": f["kind"], "text": f["text"], "file": f["path"]}
        if f.get("symbol"):
            r["in"] = f["symbol"]
        if f.get("flagged"):
            r["suspected_injection"] = True
        return r

    p: dict[str, Any] = {
        "template": "dati/v1",
        "questions": list(qs),
        "facts_theirs": [row(f) for f in facts if f["side"] == "theirs"],
        "facts_ours": [row(f) for f in facts if f["side"] == "ours"],
        "ours_read": own_read,
        "ours_profile": list(profile),
        "candidates": list(candidates),
        "max_points": MAX_POINTS,
        "max_recommendations": MAX_RECS,
    }
    if errors:
        p["errors"] = list(errors)
    return p


def _clean_items(
    rows: Any, known: Mapping[str, Mapping[str, Any]], limit: int, where: str, *, need_facts: bool = True
) -> tuple[list[dict[str, Any]], list[str]]:
    out: list[dict[str, Any]] = []
    errs: list[str] = []
    for i, item in enumerate(rows if isinstance(rows, list) else [], 1):
        if len(out) >= limit:
            break
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            errs.append(f"{where} 第 {i} 条没有 text")
            continue
        t = str(item["text"]).strip()[:600]
        ids = [x for x in item.get("facts") or [] if isinstance(x, str)]
        ours = [x for x in item.get("ours") or [] if isinstance(x, str)]
        unknown = [x for x in [*ids, *ours] if x not in known]
        why = ""
        if unknown:
            why = f"引用了不存在的细事实编号 {unknown[:3]}"
        elif need_facts and not ids and not ours:
            why = "没有引用任何细事实：每条都要有出处，写不出出处的放到 unsure"
        elif "```" in t:
            why = "不要用代码围栏"
        elif _FILELINE.search(t):
            why = "不要自己写文件名加行号或行号：引用细事实的编号即可，文件与行由系统补"
        elif _internal_terms(t):
            why = f"出现了内部名词 {_internal_terms(t)[:3]}：改用常规的技术词"
        if why:
            errs.append(f"{where} 第 {i} 条：{why}")
            continue
        row: dict[str, Any] = {"text": t, "facts": list(dict.fromkeys(ids))}
        if ours:
            row["ours"] = list(dict.fromkeys(ours))
        for k in ("title", "priority", "candidate"):
            if isinstance(item.get(k), str) and item[k].strip():
                row[k] = item[k].strip()[:80]
        out.append(row)
    return out, errs


def parse_draft(
    out: Any, qs: Sequence[Mapping[str, str]], facts: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(out, dict) or not isinstance(out.get("answers"), list):
        return {}, ["输出应为 {answers: [{q, points}], recommendations, not_recommended, unsure}"]
    errs: list[str] = []
    answers: list[dict[str, Any]] = []
    for q in qs:
        row = next((a for a in out["answers"] if isinstance(a, dict) and a.get("q") == q["id"]), None)
        pts, e = _clean_items((row or {}).get("points"), facts, MAX_POINTS, f"{q['id']} 的结论")
        errs += e
        has = any(f["q"] == q["id"] and f["side"] == "theirs" for f in facts.values())
        if has and not pts:
            errs.append(f"{q['id']} 有可用的细事实，却没有写出任何结论")
        answers.append({"q": q["id"], "points": pts})
    recs, e1 = _clean_items(out.get("recommendations"), facts, MAX_RECS, "建议")
    nots, e2 = _clean_items(out.get("not_recommended"), facts, MAX_RECS, "不建议", need_facts=False)
    unsure, e3 = _clean_items(out.get("unsure"), facts, MAX_RECS, "拿不准", need_facts=False)
    return {"answers": answers, "recommendations": recs, "not_recommended": nots, "unsure": unsure}, [
        *errs,
        *e1,
        *e2,
        *e3,
    ]


def draft(
    dan: Dan,
    qs: Sequence[Mapping[str, str]],
    facts: Mapping[str, Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
    profile: Sequence[Mapping[str, Any]],
    own_read: bool,
) -> tuple[dict[str, Any], list[str], int, int]:
    """写答题稿。交回 (稿, 仍没过的问题, token 入, token 出)。没过的条目已经从稿里拿掉，问题照实带出去。"""
    errors: list[str] = []
    doc: dict[str, Any] = {}
    tin = tout = 0
    for attempt in range(1, DRAFT_ATTEMPTS + 1):
        key = f"dati:draft:{attempt}"
        r = dan.call("main", key, draft_payload(qs, list(facts.values()), candidates, profile, own_read, errors))
        tin, tout = tin + r.tokens_in, tout + r.tokens_out
        if r.output is None:
            errors = ["上一次没有可用的输出（被截断、拒答或不是 JSON）：重新输出完整的 JSON，思考从简"]
            continue
        with reading(key):
            got, errors = parse_draft(r.output, qs, facts)
        if got:
            doc = got
        if got and not errors:
            break
    return doc, errors, tin, tout


# ---------------------------------------------------------------- 回头核对


def items_of(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    """稿里要核对的条目：各子问的结论与建议（「不建议」「拿不准」本来就不当事实交，不核）。每条给一个稳定的编号。"""
    out: list[dict[str, Any]] = []
    for a in doc.get("answers", []):
        for i, p in enumerate(a["points"], 1):
            out.append({"n": f"{a['q']}.{i}", "kind": "point", "q": a["q"], **p})
    for i, r in enumerate(doc.get("recommendations", []), 1):
        out.append({"n": f"R{i}", "kind": "rec", **r})
    return out


def _excerpt_for(
    item: Mapping[str, Any], facts: Mapping[str, Mapping[str, Any]], snaps: Mapping[str, survey.Snapshot]
) -> str:
    rows = []
    for fid in [*item.get("facts", []), *item.get("ours", [])][:VERIFY_FACTS]:
        f = facts[fid]
        snap = snaps[f["snapshot"]]
        total = len(snap.texts[f["path"]].splitlines())
        a, b = max(1, f["lines"][0] - VERIFY_PAD), min(total, f["lines"][1] + VERIFY_PAD)
        rows.append(f"[{f['path']} {a}-{b}]\n" + wenti.numbered(snap, wenti.Part(f["snapshot"], f["path"], a, b)))
    return "\n\n".join(rows)


def verify(
    dan: Dan,
    batch: Sequence[Mapping[str, Any]],
    facts: Mapping[str, Mapping[str, Any]],
    snaps: Mapping[str, survey.Snapshot],
    tag: str,
    nonce: Callable[[], str] = new_nonce,
) -> tuple[dict[str, dict[str, str]], int, int]:
    """一批结论对着各自引用的原文核一遍。交回 {条目编号: {verdict, note}}；没判到的条目不在里面（算未核对）。"""
    body = "\n\n".join(f"### 条目 {it['n']} 引用的原文\n{_excerpt_for(it, facts, snaps)}" for it in batch)
    errors: list[str] = []
    tin = tout = 0
    out: dict[str, dict[str, str]] = {}
    for attempt in range(1, DRAFT_ATTEMPTS + 1):
        key = f"heyan:{tag}:{attempt}"
        payload: dict[str, Any] = {
            "template": "heyan/v1",
            "items": [{"n": it["n"], "text": it["text"]} for it in batch],
            "excerpt": body,
            "nonce": nonce(),
        }
        if errors:
            payload["errors"] = errors
        r = dan.call("blind", key, payload)
        tin, tout = tin + (r.tokens_in or estimate_tokens(body) + 800), tout + r.tokens_out
        with reading(key):
            rows = r.output.get("verdicts") if isinstance(r.output, dict) else None
            out = {}
            for row in rows if isinstance(rows, list) else []:
                if (
                    isinstance(row, dict)
                    and row.get("verdict") in VERDICTS
                    and any(row.get("n") == it["n"] for it in batch)
                ):
                    out[str(row["n"])] = {"verdict": row["verdict"], "note": str(row.get("note") or "")[:300]}
        if len(out) == len(batch):
            break
        errors = [f"每个条目都要给 verdict（{'、'.join(VERDICTS)} 之一）；这次缺 {len(batch) - len(out)} 条"]
    return out, tin, tout


def fix(
    dan: Dan, partial: Sequence[Mapping[str, Any]], facts: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, str], int, int]:
    """部分支持的结论改写一次：只许删改到原文支持得住的范围，不许新增内容。交回 {条目编号: 新的文字}。"""
    payload = {
        "template": "dati/fix/v1",
        "items": [
            {
                "n": it["n"],
                "text": it["text"],
                "note": it.get("note", ""),
                "facts": [{"id": f, "text": facts[f]["text"]} for f in [*it.get("facts", []), *it.get("ours", [])]],
            }
            for it in partial
        ],
    }
    key = "dati:fix:1"
    r = dan.call("main", key, payload)
    out: dict[str, str] = {}
    with reading(key):
        rows = r.output.get("fixed") if isinstance(r.output, dict) else None
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not isinstance(row.get("text"), str):
                continue
            t = row["text"].strip()[:600]
            if t and "```" not in t and not _FILELINE.search(t) and not _internal_terms(t):
                out[str(row.get("n"))] = t
    return out, r.tokens_in, r.tokens_out


# ---------------------------------------------------------------- 报告

# 结论后面的标注取回头核对的结果，不取答题时模型自己的说法：原文支持 → 确认；只支持一部分（改写一次后再核仍是）→ 推断；
# 不支持 → 不留在回答里，移到「拿不准」；没来得及核 → 未核对，单列，不当事实用。
LABEL_ZH = {
    "supported": "确认",
    "partial": "推断",
    "unsupported": "核对不支持",
    "unverified": "未核对",
}


def cite(f: Mapping[str, Any]) -> str:
    a, b = f["lines"]
    where = f"{f['path']}:{a}" + (f"-{b}" if b != a else "")
    side = "我们 " if f["side"] == "ours" else ""
    return f"`{side}{where}`" + (f"（{f['symbol']}）" if f.get("symbol") else "")


def route_line(qs: Sequence[Mapping[str, str]]) -> str:
    """报告的第一行：这道题走的是哪条路。"""
    if not qs:
        return "> 读法：题面没有点名具体的问题，走通用勘察。"
    said = "；".join(f"{q['id']} {q['text']}" for q in qs)
    return f"> 读法：题面点名了 {len(qs)} 问，按题读。{said}"


def stats(ans: Mapping[str, Any], facts: Mapping[str, Mapping[str, Any]], named: Sequence[str]) -> dict[str, Any]:
    """核对与引用的读数：都由引擎数出来，过线标准直接读它。"""
    items = list(ans.get("items", []))
    by = {v: sum(1 for it in items if it["verdict"] == v) for v in LABEL_ZH}
    kept = [it for it in items if it["verdict"] != "unsupported"]
    cites = [facts[f] for it in kept for f in [*it.get("facts", []), *it.get("ours", [])] if f in facts]
    theirs = [c for c in cites if c["side"] == "theirs"]
    on_named = sum(1 for c in theirs if c["path"] in set(named))
    qids = sorted({it["q"] for it in items if it.get("q")})
    return {
        "items": len(items),
        "kept": len(kept),
        **by,
        "rewritten": sum(1 for it in items if it.get("rewritten")),
        "unverified_share": round(by["unverified"] / len(kept), 4) if kept else 0.0,
        "verified_pass_share": round(by["supported"] / max(1, len(items) - by["unverified"]), 4),
        "citations": len(cites),
        "citations_theirs": len(theirs),
        "citations_on_named": on_named,
        "named_share": round(on_named / len(theirs), 4) if theirs else 0.0,
        "answered": {
            q: sum(1 for it in items if it.get("q") == q and it["verdict"] in ("supported", "partial")) for q in qids
        },
        "recommendations": sum(1 for it in items if it["kind"] == "rec" and it["verdict"] in ("supported", "partial")),
    }


def render(
    qs: Sequence[Mapping[str, str]],
    ans: Mapping[str, Any],
    facts: Mapping[str, Mapping[str, Any]],
    unread: Mapping[str, Any],
    st: Mapping[str, Any],
) -> str:
    """报告里「回答」这一节。结论后面的标注取核对的结果；引用的文件、行、所在定义都由细事实的出处推出。"""

    def line(it: Mapping[str, Any]) -> str:
        refs = "、".join(cite(facts[f]) for f in [*it.get("facts", []), *it.get("ours", [])] if f in facts)
        mark = LABEL_ZH[it["verdict"]] + ("，改写过" if it.get("rewritten") else "")
        note = f"（原文只支持一部分：{it['note']}）" if it["verdict"] == "partial" and it.get("note") else ""
        return f"{it['text']} 〔{mark}〕{note} {refs}".rstrip()

    items = list(ans.get("items", []))
    body = [it for it in items if it["verdict"] in ("supported", "partial")]
    loose = [it for it in items if it["verdict"] == "unverified"]
    gone = [it for it in items if it["verdict"] == "unsupported"]
    lines = ["# 回答", ""]
    for q in qs:
        lines += [f"## {q['id']}：{q['text']}", ""]
        pts = [it for it in body if it.get("q") == q["id"]]
        if pts:
            lines += [f"{i}. {line(it)}" for i, it in enumerate(pts, 1)]
        else:
            lines.append("没有经过核对的结论：见下面的「未核对」与「没读到」。")
        lines.append("")
    recs = [it for it in body if it["kind"] == "rec"]
    lines += ["## 值得集成的做法", ""]
    if recs:
        for i, it in enumerate(recs, 1):
            head = f"**{it['title']}**" if it.get("title") else ""
            pr = f"（{it['priority']}）" if it.get("priority") else ""
            cand = f"，对应候选 {it['candidate']}" if it.get("candidate") else ""
            lines.append(f"{i}. {head}{pr}{cand}{'：' if head else ''}{line(it)}")
    else:
        lines.append("没有经过核对的建议。")
    if ans.get("not_recommended"):
        lines += ["", "## 不建议集成的", ""]
        lines += [f"- {r['text']}" for r in ans["not_recommended"]]
    lines += ["", "## 拿不准的", ""]
    unsure = [f"- {r['text']}" for r in ans.get("unsure", [])]
    unsure += [f"- {it['text']}（核对不支持：{it.get('note') or '引用的原文不支持这个说法'}）" for it in gone]
    lines += unsure or ["- 无"]
    if loose:
        lines += ["", "## 未核对的（时间或预算到线，没有来得及核对；不当事实用）", ""]
        lines += [
            f"- {it['text']} {'、'.join(cite(facts[f]) for f in it.get('facts', []) if f in facts)}" for it in loose
        ]
    lines += ["", "## 没读到的", ""]
    rows = [f"- {r}" for r in unread.get("notes", [])]
    rows += [
        f"- `{r['path']}:{r['lines'][0]}-{r['lines'][1]}`（{r['why']}，排了队没读）" for r in unread.get("queued", [])
    ]
    lines += rows or ["- 排了队的都读了"]
    lines += [
        "",
        "## 核对记录",
        "",
        f"- 结论与建议共 {st['items']} 条：核对后标「确认」{st['supported']}，标「推断」{st['partial']}"
        f"（改写过 {st['rewritten']}），不支持 {st['unsupported']}（已移到「拿不准」），"
        f"未核对 {st['unverified']}（占留下的 {st['unverified_share']:.0%}）。",
        f"- 引用 {st['citations']} 处，其中对方仓库 {st['citations_theirs']} 处、"
        f"指向题面命中文件的 {st['citations_on_named']} 处（{st['named_share']:.0%}）。"
        "行号由系统从阅读记录推出，不由模型书写。",
        f"- 阅读：{unread.get('read_line', '')}",
    ]
    return "\n".join(lines)
