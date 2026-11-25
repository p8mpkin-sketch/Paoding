"""按题读在工作流里的编排（docs/design/fenjue/14-question-led.md）：题面解析 → 领读与追读 → 答题稿 → 回头核对。

`run.Engine` 在识别候选之前调 `read_phase`，在候选清单建好之后调 `answer_phase`；题面没有点名时两处都不进来，
流程与以前逐字节相同。这里的状态都放在工作区的簿记里，不登记成产物（所以不需要新的 Schema）：

- `engine.json` 的 `ql` 键：子问、走哪条路；
- `artifacts/` 里以 `ql:` 起名的几份 JSON（检查点：计划、每一批读了什么、答题稿、核对结果、读数）；
- `facts.jsonl`：只追加的细事实库（答题与核对用；带对方的名字，不给候选、提炼、归位那几步看）；
- `ql.json`：给人和 `trial.py report` 读的汇总（走哪条路、核对读数、读了多少、花了多少）。

三条硬线都在这里守（缺省值取自 2026-11-25 的基线，可由配置改）：模型调用次数、token、时间。任何一条到了就停止扩读，
排了队没读的照实进「没读到」；来不及核对的结论标「未核对」。不追加、不借别的步骤的份额。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import data, dati, shihuo, survey, wenti
from .dan import BudgetExhausted, Dan, Reply

if TYPE_CHECKING:
    from .run import Delivery, Engine

CODE_FORMS = ("code", "docs")
OWN_SID_BASE = 90  # 我们自己那份材料的快照编号从 s91 起，与对方的 s1、s2… 分开


@dataclass(frozen=True)
class Limits:
    """按题读的各条线〔占位〕。token 与调用次数取自 2026-11-25 同一道题五次运行的中位数 × 1.5。"""

    token_cap: int = 590_000  # 整次运行的 token（入 + 出）
    call_cap: int = 85  # 整次运行的模型调用次数
    read_share: float = 0.50  # 领读、追读、读自家实现合计至多占 token 线的这么多
    reads_theirs: int = 20  # 对方仓库至多读这么多部分
    reads_own: int = 4  # 我们自己的实现至多读这么多部分
    category_reads: int = 8  # 通用勘察那一轮留的阅读次数（每个类别至多一段）
    batch: int = 8  # 一批至多读这么多部分
    core_per_question: int = 3  # 每个子问取几个文件作第一批
    reserve_calls: int = 26  # 留给后面各步（候选、提炼、归位、答题、核对）的调用次数
    read_stop_s: float = 480.0  # 时间线：过了这个点不再开新的一批阅读
    verify_stop_s: float = 1200.0  # 时间线：过了这个点不再开新的一轮核对，剩下的标「未核对」


class Meter:
    """数这次运行调了多少次模型（取备忘的也算：它在流程里就是一次调用）。并发时几个线程一起数，所以带锁。"""

    def __init__(self, inner: Dan) -> None:
        self.inner, self.made = inner, 0
        self._lock = threading.Lock()

    def call(self, role: str, key: str, payload: Mapping[str, Any]) -> Reply:
        with self._lock:
            self.made += 1
        return self.inner.call(role, key, payload)

    def __getattr__(self, name: str) -> Any:  # forget 等别的方法照旧找里面那一个
        return getattr(self.inner, name)


def par[T](jobs: Sequence[Callable[[], T]], width: int) -> list[T]:
    """并发跑一组互不相干的调用，按原来的次序交回结果。width ≤ 1 就是顺序执行。
    有一个被预算挡下，等其余的做完再把它抛出去（做完的在调用备忘里，接着做时不再花钱）。
    线程是守护线程：会话被终止时主线程退出，不等它们。"""
    n = max(1, min(int(width), len(jobs)))
    if n == 1:
        return [j() for j in jobs]
    results: list[Any] = [None] * len(jobs)
    errors: list[BaseException | None] = [None] * len(jobs)
    todo = list(range(len(jobs)))
    lock = threading.Lock()

    def work() -> None:
        while True:
            with lock:
                if not todo:
                    return
                i = todo.pop(0)
            try:
                results[i] = jobs[i]()
            except BaseException as e:  # noqa: BLE001  原样带回主线程再抛
                errors[i] = e

    threads = [threading.Thread(target=work, daemon=True) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    bad = [e for e in errors if e is not None]
    if bad:
        raise next((e for e in bad if isinstance(e, BudgetExhausted)), bad[0])
    return results


# ---------------------------------------------------------------- 走哪条路


def decide(eng: Engine) -> list[dict[str, str]]:
    """这道题走哪条路，立项时定一次、记进簿记：题面点名了子问、且有一份代码或文档形态的外部材料 → 按题读。"""
    q = eng.x.get("ql")
    if isinstance(q, dict):
        return list(q.get("questions", []))
    qs = wenti.questions(str(eng.cfg.statement or eng.intake.get("statement") or "")) if eng.cfg.question_led else []
    note = ""
    if qs and not any(s.form in CODE_FORMS for s in eng._snaps.values()):
        qs, note = [], "题面点名了问题，但材料不是代码或文档，没有可按题读的文件"
    eng.x["ql"] = {"questions": qs, **({"note": note} if note else {})}
    return qs


def questions(eng: Engine) -> list[dict[str, str]]:
    q = eng.x.get("ql")
    return list(q.get("questions", [])) if isinstance(q, dict) else []


def route_line(eng: Engine) -> str:
    q = eng.x.get("ql") or {}
    line = dati.route_line(q.get("questions", []))
    return line + (f"（{q['note']}）" if q.get("note") else "")


def _main_snapshot(eng: Engine) -> str:
    return next(sid for sid, s in eng._snaps.items() if s.form in CODE_FORMS)


def _elapsed(eng: Engine) -> float:
    return float(eng._elapsed_base + eng.cfg.clock() - eng._t0)


def tick(eng: Engine) -> None:
    """把调用次数与用时记进簿记（只在按题读的题上记；通用勘察的题簿记不多一个字）。
    接着做时从调用备忘里取回的调用也计一次：偏保守，线只会早到，不会晚到。"""
    q = eng.x.get("ql")
    if isinstance(q, dict) and q.get("questions"):
        q["elapsed_s"] = round(_elapsed(eng), 1)
        q["calls"] = int(eng._calls_base + eng._meter.made)


def _tick(eng: Engine) -> None:
    tick(eng)


def tokens_spent(eng: Engine) -> int:
    return sum(int(a) + int(b) for a, b in eng.state["spent"].get("tokens", {}).values())


def calls_made(eng: Engine) -> int:
    return int(eng._calls_base + eng._meter.made)


# ---------------------------------------------------------------- 细事实库


def facts(eng: Engine) -> dict[str, dict[str, Any]]:
    p = eng.ws / "facts.jsonl"
    out: dict[str, dict[str, Any]] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                f = json.loads(line)
                out.setdefault(f["id"], f)
    return out


def _append_facts(eng: Engine, rows: Sequence[Mapping[str, Any]]) -> int:
    have = facts(eng)
    new = 0
    with (eng.ws / "facts.jsonl").open("a", encoding="utf-8") as f:
        for r in rows:
            if r["id"] not in have:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
                have[r["id"]] = dict(r)
                new += 1
    return new


# ---------------------------------------------------------------- ① 题面解析


def _plan(eng: Engine, qs: list[dict[str, str]], ix: wenti.Index) -> dict[str, Any]:
    lim = eng.cfg.limits
    terms, tin, tout = dati.ask_terms(eng.dan, qs)
    eng._spend("S3", "light", tin, tout)

    def hit_files(qid: str) -> dict[str, dict[str, int]]:
        zh, en = terms.get(qid, ([], []))
        return wenti.search(ix, [*zh, *en])

    zero = [q["id"] for q in qs if not hit_files(q["id"])]
    if zero:  # 没命中的子问：把各词的命中数交回去再要一次词
        fb = []
        for q in qs:
            zh, en = terms.get(q["id"], ([], []))
            n = len(hit_files(q["id"]))
            fb.append(f"{q['id']} 的检索词 {'、'.join([*zh, *en]) or '（空）'} 在对方仓库命中 {n} 个文件")
        fb.append(f"{'、'.join(zero)} 一个文件都没命中：换别的说法、同义词、缩写、词干再给一组")
        again, tin, tout = dati.ask_terms(eng.dan, qs, fb, rnd=2)
        eng._spend("S3", "light", tin, tout)
        for qid in zero:
            if any(again.get(qid, ([], []))):
                terms[qid] = again[qid]
        zero = [q["id"] for q in qs if not hit_files(q["id"])]
    all_terms = [t for q in qs for part in terms.get(q["id"], ([], [])) for t in part]
    vocab = wenti.vocabulary(ix, list(dict.fromkeys(all_terms)))
    picks: dict[str, dict[str, list[str]]] = {}
    if vocab["names"] or vocab["files"]:
        picks, tin, tout = dati.ask_pick(eng.dan, qs, vocab, eng.cfg.nonce)
        eng._spend("S3", "light", tin, tout)
    base: dict[str, float] = {}
    ranked: dict[str, list[tuple[float, str]]] = {}
    for q in qs:
        zh, en = terms.get(q["id"], ([], []))
        pk = picks.get(q["id"], {"names": [], "files": []})
        ranked[q["id"]] = wenti.rank(ix, [*zh, *en], pk["names"], pk["files"])
        for s, p in ranked[q["id"]]:
            base[p] = max(base.get(p, 0.0), s)
    core: list[str] = []
    for i in range(lim.core_per_question):  # 各子问轮流取，题面点名的每一问第一批都有份
        for q in qs:
            rows = ranked[q["id"]]
            if i < len(rows) and rows[i][1] not in core:
                core.append(rows[i][1])
    named = sorted({p for q in qs for _, p in ranked[q["id"]][:12]})
    sigs = data.signatures()
    top = sorted(base, key=lambda p: (-base[p], p))[:300]
    return {
        "v": 1,
        "snapshot": ix.snap.sid,
        "terms": {q["id"]: {"zh": terms.get(q["id"], ([], []))[0], "en": terms.get(q["id"], ([], []))[1]} for q in qs},
        "picks": picks,
        "core": core,
        "base": {p: base[p] for p in top},
        "named": named,
        "zero": zero,
        "slots": {
            q["id"]: wenti.question_slot(
                q["text"], [*terms.get(q["id"], ([], []))[0], *terms.get(q["id"], ([], []))[1]], sigs
            )
            for q in qs
        },
    }


# ---------------------------------------------------------------- ②③ 领读与追读


def _own(eng: Engine) -> tuple[survey.Snapshot, wenti.Index] | None:
    """我们自己那份材料（立项单里出处是我们仓库的那个来源）。没有就返回 None：只对照能力清单。"""
    if eng._own_ix is not None:
        return eng._own_ix
    nos = set(eng.x.get("own_sources", []))
    for i, s in enumerate((s for s in eng.intake["sources"] if s["no"] in nos), 1):
        mat = eng._material(s)
        if mat is None or s["form"] not in CODE_FORMS:
            continue
        snap = survey.load_snapshot(f"s{OWN_SID_BASE + i}", s["form"], mat)
        eng._own_ix = (snap, wenti.Index.build(snap, survey.probe(snap)))
        eng.x["ql"]["own"] = {"snapshot": snap.sid, "source": s["no"], "ref": s.get("ref", "")}
        return eng._own_ix
    return None


def _own_parts(own_ix: wenti.Index, plan: Mapping[str, Any], n: int) -> list[wenti.Part]:
    """我们自己的实现里读哪几部分：用同一组检索词排文件，每个文件取命中最多的那一部分。"""
    terms = [t for row in plan["terms"].values() for t in [*row["zh"], *row["en"]]]
    out: list[wenti.Part] = []
    for _, path in wenti.rank(own_ix, terms, [], [])[: n * 2]:
        ps = wenti.parts(own_ix.snap.sid, path, own_ix.snap.texts[path])
        lines = own_ix.folded[path].splitlines()

        def hits(p: wenti.Part, lines: list[str] = lines) -> int:
            body = "\n".join(lines[p.a - 1 : p.b])
            return sum(body.count(t) for t in terms)

        out.append(max(ps, key=lambda p: (hits(p), -p.a)))
        if len(out) >= n:
            break
    return out


def _frontier(eng: Engine, ix: wenti.Index, plan: Mapping[str, Any]) -> tuple[wenti.Frontier, list[dict[str, Any]]]:
    fr = wenti.Frontier(ix, dict(plan["base"]), list(plan["core"]))
    done: list[dict[str, Any]] = []
    i = 0
    while eng._done(f"ql:batch:{i}"):
        b = eng.get(f"ql:batch:{i}")
        done.append(b)
        for r in b["parts"]:
            if r["side"] == "theirs":
                fr.note(wenti.Part(r["snapshot"], r["path"], r["lines"][0], r["lines"][1]), r["follow"])
        i += 1
    return fr, done


def read_phase(eng: Engine) -> Delivery | None:
    """题面解析、领读、追读。只在识别候选这一步的预算份额用完时交回一次部分交付；别的线到了只是停止扩读。"""
    qs = questions(eng)
    lim = eng.cfg.limits
    sid = _main_snapshot(eng)
    ix = wenti.Index.build(eng._snaps[sid], eng._surveys[sid])
    if not eng._done("ql:plan"):
        if eng._stage_left("S3") <= 0:
            return eng._budget_cut("S3", "ql:plan")
        eng._mark("ql:plan", "S3", "doing")
        plan = _plan(eng, qs, ix)
        _tick(eng)
        sha = eng.put("ql:plan", plan)
        eng._mark(
            "ql:plan",
            "S3",
            "done",
            output=sha,
            summary=f"第一批 {len(plan['core'])} 个文件；没命中的子问 {len(plan['zero'])} 个",
        )
    plan = eng.get("ql:plan")
    if eng._done("ql:read"):
        return None
    eng._mark("ql:read", "S3", "doing")
    fr, done = _frontier(eng, ix, plan)
    own = _own(eng)
    qslot: Mapping[str, str] = plan["slots"]
    stop = ""
    while not stop:
        theirs_n = sum(1 for b in done for r in b["parts"] if r["side"] == "theirs")
        own_done = any(r["side"] == "ours" for b in done for r in b["parts"])
        spent = sum(int(r["tokens_in"]) + int(r["tokens_out"]) for b in done for r in b["parts"])
        reads = sum(len(b["parts"]) for b in done)
        avg = spent // reads if reads else 10_000
        room_tok = int((lim.token_cap * lim.read_share - spent) // max(avg, 1))
        room_calls = lim.call_cap - lim.reserve_calls - lim.category_reads - calls_made(eng)
        theirs_b = [b for b in done if any(r["side"] == "theirs" for r in b["parts"])]
        dry = len(theirs_b) >= 2 and all(not any(r["facts"] for r in b["parts"]) for b in theirs_b[-2:])
        want_own = own is not None and not own_done and (len(theirs_b) >= 2 or theirs_n >= lim.reads_theirs)
        if eng._stage_left("S3") <= 0:
            stop = "识别这一步的预算份额用完"
        elif room_tok <= 0:
            stop = "阅读的 token 份额用完"
        elif room_calls <= 0:
            stop = "调用次数接近上限"
        elif _elapsed(eng) >= lim.read_stop_s and done:
            stop = "到了阅读的时间线"
        if stop:
            break
        n = min(lim.batch, room_tok, room_calls)
        batch: list[tuple[wenti.Part, str, str]] = []
        if want_own and own is not None:
            batch = [(p, "对照我们自己的实现", "ours") for p in _own_parts(own[1], plan, min(n, lim.reads_own))]
        if not batch:
            left = lim.reads_theirs - theirs_n
            if left <= 0:
                stop = "读满了计划的份数"
            elif dry:
                stop = "连续两批没有新的事实"
            else:
                picked = fr.first(min(n, left)) if not done else fr.next(min(n, left))
                if not picked and not done:
                    picked = fr.next(min(n, left))
                batch = [(p, why, "theirs") for p, why in picked]
                if not batch:
                    stop = "没有可追的了"
        if not batch:
            if own is not None and not own_done and stop:  # 对方读完了还没回头读自家：补上这一批再停
                own_parts = _own_parts(own[1], plan, min(max(n, 1), lim.reads_own))
                batch = [(p, "对照我们自己的实现", "ours") for p in own_parts]
                stop = "" if batch else stop
            if not batch:
                break
        i = len(done)
        uid = f"ql:batch:{i}"
        eng._mark(uid, "S3", "doing")

        slots = [
            "" if side == "ours" else wenti.slot_of(eng._surveys[sid], p, [qslot[q["id"]] for q in qs])
            for p, _, side in batch
        ]

        def job(p: wenti.Part, side: str, slot: str) -> Callable[[], dati.PartRead]:
            if side == "ours":
                assert own is not None
                return lambda: dati.read_part(eng.dan, own[1], p, qs, None, side="ours", nonce=eng.cfg.nonce)
            return lambda: dati.read_part(eng.dan, ix, p, qs, slot, nonce=eng.cfg.nonce)

        results = par([job(p, side, slot) for (p, _, side), slot in zip(batch, slots, strict=True)], eng.cfg.parallel)
        rows: list[dict[str, Any]] = []
        for (p, why, side), slot, r in zip(batch, slots, results, strict=True):
            _append_facts(eng, r.facts)
            eng._append_obs(r.observations)
            eng._spend("S3", "light", r.tokens_in, r.tokens_out)
            if side == "theirs":
                fr.note(p, r.follow)
            rows.append(
                {
                    "side": side,
                    "slot": slot,
                    "snapshot": p.sid,
                    "path": p.path,
                    "lines": [p.a, p.b],
                    "why": why,
                    "facts": [f["id"] for f in r.facts],
                    "observations": dict(sorted(r.obs_q.items())),
                    "follow": r.follow,
                    "failed": r.failed,
                    "dropped": r.dropped,
                    "truncated": r.truncated,
                    "tokens_in": r.tokens_in,
                    "tokens_out": r.tokens_out,
                }
            )
        _tick(eng)
        body = {"i": i, "parts": rows}
        sha = eng.put(uid, body)
        nf = sum(len(r["facts"]) for r in rows)
        eng._mark(uid, "S3", "done", output=sha, summary=f"第 {i + 1} 批：读 {len(rows)} 部分，{nf} 条细事实")
        done.append(body)
    parts = [r for b in done for r in b["parts"]]
    summary = {
        "v": 1,
        "stop": stop or "没有可追的了",
        "batches": len(done),
        "theirs": {
            "parts": sum(1 for r in parts if r["side"] == "theirs"),
            "files": len({r["path"] for r in parts if r["side"] == "theirs"}),
            "lines": sum(r["lines"][1] - r["lines"][0] + 1 for r in parts if r["side"] == "theirs"),
        },
        "ours": {
            "parts": sum(1 for r in parts if r["side"] == "ours"),
            "files": len({r["path"] for r in parts if r["side"] == "ours"}),
        },
        "facts": sum(len(r["facts"]) for r in parts),
        "failed": [f"{r['path']}:{r['lines'][0]}-{r['lines'][1]}" for r in parts if r["failed"]],
        "truncated": sum(int(r["truncated"]) for r in parts),
        "dropped": sum(int(r["dropped"]) for r in parts),
        "order": [f"{r['path']}:{r['lines'][0]}-{r['lines'][1]}" for r in parts],
        "queued": fr.left(),
        "tokens": sum(int(r["tokens_in"]) + int(r["tokens_out"]) for r in parts),
    }
    sha = eng.put("ql:read", summary)
    eng._mark("ql:read", "S3", "done", output=sha, summary=f"读了 {len(parts)} 部分；停止：{summary['stop']}")
    return None


def read_paths(eng: Engine) -> set[tuple[str, str]]:
    """按题读已经读过的（文件, 类别）：通用勘察那一轮不再按同一个类别读同一个文件，别的类别照读。"""
    out: set[tuple[str, str]] = set()
    i = 0
    while eng._done(f"ql:batch:{i}"):
        out |= {(r["path"], r["slot"]) for r in eng.get(f"ql:batch:{i}")["parts"] if r["side"] == "theirs"}
        i += 1
    return out


def asked(eng: Engine) -> list[dict[str, Any]]:
    """每个子问和它的观察（给识别候选用）。"""
    by: dict[str, list[str]] = {q["id"]: [] for q in questions(eng)}
    have = eng.observations()
    i = 0
    while eng._done(f"ql:batch:{i}"):
        for r in eng.get(f"ql:batch:{i}")["parts"]:
            for oid, qid in r["observations"].items():
                if oid in have and qid in by and oid not in by[qid]:
                    by[qid].append(oid)
        i += 1
    return [{"id": q["id"], "text": q["text"], "observations": sorted(by[q["id"]])} for q in questions(eng)]


def pick(doc: Mapping[str, Any], asked_rows: Sequence[Mapping[str, Any]], n: int) -> list[str]:
    """预评估自动取哪几个候选：每个子问优先级最高的那个先取，再按优先级补到 n 个。交回的次序按候选编号。"""
    cands = list(doc["candidates"])
    ids: list[str] = []
    for a in asked_rows:
        c = next((c for c in cands if shihuo.covers(c, a)), None)
        if c is not None and c["id"] not in ids:
            ids.append(c["id"])
    ids = ids[:n]
    for c in cands:
        if len(ids) >= n:
            break
        if c["id"] not in ids:
            ids.append(c["id"])
    return [c["id"] for c in cands if c["id"] in ids]


# ---------------------------------------------------------------- ⑦⑧ 答题稿与回头核对


def _snaps(eng: Engine) -> dict[str, survey.Snapshot]:
    out = dict(eng._snaps)
    own = _own(eng)
    if own is not None:
        out[own[0].sid] = own[0]
    return out


def _profile(eng: Engine) -> list[dict[str, Any]]:
    slots = set((eng.get("ql:plan") or {}).get("slots", {}).values())
    return [{k: d[k] for k in ("dim", "meaning", "level")} for d in data.profile()["dims"] if d["slot"] in slots]


def answer_phase(eng: Engine) -> Delivery | None:
    """写答题稿，再对着源码逐条核对。结论最后的标注取核对的结果。只在归位这一步的预算份额用完时交回部分交付。"""
    qs = questions(eng)
    lim = eng.cfg.limits
    fx = facts(eng)
    doc = eng.get("candidates.json")
    if not eng._done("ql:draft"):
        if eng._stage_left("S5") <= 0:
            return eng._budget_cut("S5", "ql:draft")
        eng._mark("ql:draft", "S3", "doing")
        cands = [
            {
                "id": c["id"],
                "title": c["title"],
                "slot": c["slot"],
                **({"registered": c["dedupe"]["bang"]} if c.get("dedupe") else {}),
            }
            for c in doc["candidates"]
        ]
        draft: dict[str, Any] = {}
        problems: list[str] = []
        if any(f["side"] == "theirs" for f in fx.values()):
            draft, problems, tin, tout = dati.draft(eng.dan, qs, fx, cands, _profile(eng), bool(eng.x["ql"].get("own")))
            eng._spend("S5", "heavy", tin, tout)
        else:
            problems = ["没有读到任何可用的事实，没有写回答"]
        _tick(eng)
        sha = eng.put("ql:draft", {"v": 1, "doc": draft, "problems": problems})
        eng._mark("ql:draft", "S3", "done", output=sha, summary=f"答题稿：{len(dati.items_of(draft))} 条待核对")
    if eng._done("ql:answer"):
        return None
    stored = eng.get("ql:draft")
    draft, problems = stored["doc"], list(stored["problems"])
    eng._mark("ql:answer", "S3", "doing")
    items = [{**it, "verdict": "unverified", "note": ""} for it in dati.items_of(draft)]
    snaps = _snaps(eng)
    stops: list[str] = []

    def run_round(todo: list[dict[str, Any]], tag: str) -> None:
        batches = [todo[i : i + dati.VERIFY_BATCH] for i in range(0, len(todo), dati.VERIFY_BATCH)]
        k = 0
        while k < len(batches):
            if _elapsed(eng) >= lim.verify_stop_s:
                stops.append("到了核对的时间线")
                return
            room = lim.call_cap - calls_made(eng)
            if room <= 0:
                stops.append("调用次数到了上限")
                return
            if eng._stage_left("S5") <= 0:
                stops.append("归位这一步的预算份额用完")
                return
            wave = batches[k : k + max(1, min(eng.cfg.parallel, room))]
            jobs = [
                (lambda b=b, j=j: dati.verify(eng.dan, b, fx, snaps, f"{tag}:{j}", eng.cfg.nonce))
                for j, b in enumerate(wave, k)
            ]
            for b, (got, tin, tout) in zip(wave, par(jobs, eng.cfg.parallel), strict=True):
                eng._spend("S5", "mid", tin, tout)
                for it in b:
                    if it["n"] in got:
                        it["verdict"], it["note"] = got[it["n"]]["verdict"], got[it["n"]]["note"]
            k += len(wave)

    run_round(items, "r1")
    partial = [it for it in items if it["verdict"] == "partial"]
    if partial and not stops and calls_made(eng) < lim.call_cap and eng._stage_left("S5") > 0:
        fixed, tin, tout = dati.fix(eng.dan, partial, fx)
        eng._spend("S5", "heavy", tin, tout)
        redo = []
        for it in partial:
            if it["n"] in fixed and fixed[it["n"]] != it["text"]:
                it["text"], it["rewritten"] = fixed[it["n"]], True
                it["verdict"], it["was"] = "unverified", it["note"]  # 改写过的文字还没核过：先按未核对算
                redo.append(it)
        run_round(redo, "r2")
    _tick(eng)
    ans = {
        "v": 1,
        "items": items,
        "not_recommended": draft.get("not_recommended", []),
        "unsure": draft.get("unsure", []),
        "problems": problems,
        "stops": sorted(set(stops)),
    }
    st = dati.stats(ans, fx, (eng.get("ql:plan") or {}).get("named", []))
    eng.put("ql:stats", st)
    sha = eng.put("ql:answer", ans)
    eng._mark(
        "ql:answer",
        "S3",
        "done",
        output=sha,
        summary=f"核对 {st['items']} 条：支持 {st['supported']}，未核对 {st['unverified']}",
    )
    export(eng)
    return None


def _unread(eng: Engine) -> dict[str, Any]:
    plan, rd = eng.get("ql:plan") or {}, eng.get("ql:read") or {}
    ans = eng.get("ql:answer") or {}
    qs = {q["id"]: q["text"] for q in questions(eng)}
    notes = [
        f"{qid}（{qs.get(qid, '')}）：检索词在对方仓库一个文件都没命中，这一问没有读到东西"
        for qid in plan.get("zero", [])
    ]
    if not eng.x["ql"].get("own"):
        notes.append("没有读我们自己的实现（这道题没有带我们仓库的归档），「我们现在怎么做」只对照了能力清单")
    notes += [f"`{w}` 读了但没有读成（输出几次都不合形状）" for w in rd.get("failed", [])]
    if rd.get("truncated"):
        notes.append(f"阅读时有 {rd['truncated']} 次输出被上限截断后重读")
    notes += [f"答题稿里有条目没过检查，已拿掉：{p}"[:300] for p in ans.get("problems", [])[:6]]
    notes += [f"核对提前停下：{s}" for s in ans.get("stops", [])]
    theirs, ours = rd.get("theirs", {}), rd.get("ours", {})
    line = (
        f"对方仓库 {theirs.get('files', 0)} 个文件、{theirs.get('parts', 0)} 部分、{theirs.get('lines', 0)} 行；"
        f"我们自己的实现 {ours.get('parts', 0)} 部分；细事实 {rd.get('facts', 0)} 条；停止原因：{rd.get('stop', '')}。"
    )
    return {"notes": notes, "queued": rd.get("queued", []), "read_line": line}


def section(eng: Engine) -> str:
    """报告里「回答」这一节（没有按题读就是空串）。"""
    qs = questions(eng)
    ans = eng.get("ql:answer")
    if not qs or ans is None:
        return ""
    return dati.render(qs, ans, facts(eng), _unread(eng), eng.get("ql:stats"))


def registered_notes(doc: Mapping[str, Any]) -> list[str]:
    """与已登记的做法重复的候选：只在旁边注一句，不剔除。"""
    rows = [
        f"- {c['id']}（{c['title']}）：已有登记 {c['dedupe']['bang']}" for c in doc["candidates"] if c.get("dedupe")
    ]
    return ["**与已登记的做法重复的（只标注，不因此剔除）**：", *rows] if rows else []


def export(eng: Engine) -> None:
    """`ql.json`：走哪条路与各项读数的汇总，随工作区导出。过线标准的几样直接读它。"""
    q = eng.x.get("ql") or {}
    doc: dict[str, Any] = {
        "v": 1,
        "route": "question_led" if q.get("questions") else "general",
        "route_line": route_line(eng),
        "questions": q.get("questions", []),
    }
    if q.get("questions"):
        _tick(eng)
        st = eng.get("ql:stats") or {}
        doc.update(
            {
                "own": q.get("own"),
                "read": {k: v for k, v in (eng.get("ql:read") or {}).items() if k != "queued"},
                "stats": st,
                "calls": calls_made(eng),
                "tokens": tokens_spent(eng),
                "elapsed_s": q.get("elapsed_s"),
                "limits": {"token_cap": eng.cfg.limits.token_cap, "call_cap": eng.cfg.limits.call_cap},
                # 过线看三样里引擎自己数得出的两样：每个子问都有留下的结论、未核对的不超过两成
                "pass": {
                    "all_answered": bool(st)
                    and all(st.get("answered", {}).get(x["id"], 0) > 0 for x in q["questions"]),
                    "has_recommendation": int(st.get("recommendations", 0)) > 0,
                    "unverified_within_20pct": float(st.get("unverified_share", 1.0)) <= 0.2,
                },
            }
        )
    tmp = eng.ws / ".ql.json.tmp"
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(eng.ws / "ql.json")
