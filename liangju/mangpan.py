"""盲判：同一把尺子判所有臂（现行设计第 5 节）。

对每个题次，盲判拿到的只有四样：题面、这道题的子问清单、交出的回答文本、定版快照（只读）。臂名、过程日志、
引擎内的核对标注、工单、细事实、各臂自己拆的子问，都不在 `BlindItem` 里，提示词里也就不可能出现。

三段：
1. 整理（一次调用）：把回答摘成按子问排的承重结论清单，每条是回答里的逐字片段，由程序核对确实在回答里。
2. 判读（一次调用）：只看题面、子问与清单，判每个子问答到、部分答到、没答到。
3. 回原文抽样核对（每条一次带只读工具的调用）：每个子问抽 2 条、一份回答至多 8 条，对着快照判成立、被原文否定、
   找不到依据。抽哪几条由种子定，种子由计划哈希（没有计划时用题集摘要）与题号派生，跑之前就定死。

每个不利的判断写成一条发现记录（第 7.2 节）。盲判的模型单独登记、必须与各臂的模型不同，并且三份已知答案的自检样本
（`canary/`，两种文风各一份）都判对了才启用。自检记录里记每个题次的用时；没有「全部判对并且在时限内」的自检记录，
`judge` 拒绝启动。时限是试火计划里登记的每题次盲判时限，随批次头带过来；没有计划的批次没有时限。

三段提示词、抽样量与自检样本合起来是这把尺子的版本（`version`）：提示词的版本与抽样量写进试火计划（于是进计划哈希），
启动前拿批次头里登记的那一份与现在磁盘上的核对，对不上就不判。

    python -m liangju.mangpan version
    python -m liangju.mangpan selfcheck --judge judge.json --out <批次目录>/selfcheck.json
    python -m liangju.mangpan judge --batch <批次目录> --questions questions.json --judge judge.json [--jobs 4]
    python -m liangju.mangpan rejudge --batch <批次目录> --questions questions.json --judge judge.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from liangju import tici
from liangju.common import Refused, read_json, sha, write_json
from liangju.model import Client, HttpClient, JudgeModel, Ledger, ModelError, Toolbox, with_tools
from liangju.sousuo import FILE_BYTES

HERE = Path(__file__).resolve().parent
STAGES = ("zhengli", "pandu", "hedui")
PER_SUBQ, PER_ANSWER = 2, 8  # 抽样量（cz 2026-11-27 定）：每个子问 2 条，一份回答至多 8 条
STEPS = 12  # 一条结论至多查阅这么多轮
QUOTE_MAX = 600
SUB_VERDICTS = ("answered", "partial", "missing")
CLAIM_VERDICTS = ("holds", "refuted", "no_basis")
ADVERSE = ("partial", "missing", "refuted", "no_basis", "incomplete")  # 五种不利的判断
MASK = "〔名〕"


def prompts() -> dict[str, str]:
    return {s: (HERE / "prompts" / f"{s}.md").read_text(encoding="utf-8") for s in STAGES}


def prompts_digest() -> str:
    return sha({k: sha(v.encode("utf-8")) for k, v in prompts().items()})


def canary_digest() -> str:
    """自检样本的版本：题面、子问、六份回答、预期与快照，逐个文件的摘要合起来。"""
    root = HERE / "canary"
    files = sorted(p for p in root.rglob("*") if p.is_file())
    return sha({p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in files})


def version() -> dict[str, Any]:
    """这把尺子的版本。`prompts` 与 `sample` 原样写进试火计划的盲判一栏。"""
    return {
        "prompts": prompts_digest(),
        "sample": {"per_sub": PER_SUBQ, "max": PER_ANSWER},
        "canary": canary_digest(),
    }


@dataclass(frozen=True)
class BlindItem:
    """盲判看得到的全部。这里没有臂名，也没有任何一条臂自己的读数。"""

    question: str  # 题号（只用来派生种子与落盘，不进提示词）
    text: str  # 题面
    subquestions: tuple[str, ...]
    answer: str
    snapshot: Path

    @property
    def blind(self) -> str:
        return sha(f"{self.question}\n{self.answer}".encode())[:20]


class JudgeFailed(Exception):
    """盲判自己没做成（端点调不通、两次都没给出合规的 JSON）。不算任何一条臂的错，单独计数。"""


def _json(text: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("没有 JSON 对象")
    doc = json.loads(m.group(0))
    if not isinstance(doc, dict):
        raise ValueError("不是 JSON 对象")
    return doc


def _subqs(item: BlindItem) -> str:
    return "\n".join(f"{i}. {q}" for i, q in enumerate(item.subquestions, 1))


def _rows(doc: dict[str, Any], n: int) -> list[dict[str, Any]]:
    rows = doc.get("subquestions")
    if not isinstance(rows, list) or [r.get("n") if isinstance(r, dict) else None for r in rows] != list(
        range(1, n + 1)
    ):
        raise ValueError("子问编号不全或顺序不对")
    return rows


def _locate(answer: str, quote: str) -> tuple[int, int] | None:
    """逐字片段在回答里的位置。只容许空白上的出入（换行、连续空格）；别的出入一律不认。"""
    i = answer.find(quote)
    if i >= 0:
        return i, i + len(quote)
    parts = [re.escape(p) for p in quote.split()]
    if not parts:
        return None
    m = re.search(r"\s+".join(parts), answer)
    return (m.start(), m.end()) if m else None


def tidy(item: BlindItem, client: Client, ledger: Ledger) -> tuple[list[list[dict[str, Any]]], int]:
    """第一段。回 每个子问的结论（位置与出处）、被丢掉的不逐字的片段数。"""
    user = f"【题面】\n{item.text}\n\n【子问清单】\n{_subqs(item)}\n\n【回答原文】\n{item.answer}"
    err = ""
    for _ in range(2):
        try:
            turn = client.chat(prompts()["zhengli"], [{"role": "user", "text": user + err}])
        except ModelError as e:
            raise JudgeFailed(f"整理：{e}") from None
        ledger.add("zhengli", item.blind, turn)
        try:
            rows = _rows(_json(turn.text), len(item.subquestions))
            out: list[list[dict[str, Any]]] = []
            dropped = 0
            seen: set[tuple[int, int]] = set()
            for r in rows:
                claims = []
                for c in r.get("claims") or []:
                    at = _locate(item.answer, str(c.get("quote", ""))) if isinstance(c, dict) else None
                    if at is None or at[1] - at[0] > QUOTE_MAX or at in seen:
                        dropped += 1  # 不逐字、过长或重复：不认
                        continue
                    seen.add(at)
                    claims.append({"at": list(at), "cite": str(c.get("cite") or "")[:300]})
                out.append(claims)
            return out, dropped
        except (ValueError, TypeError, AttributeError) as e:
            err = f"\n\n（上一次的输出不合要求：{e}。只输出要求的 JSON 对象。）"
    raise JudgeFailed("整理：两次都没有给出合规的输出")


def read(item: BlindItem, claims: list[list[dict[str, Any]]], client: Client, ledger: Ledger) -> list[dict[str, Any]]:
    """第二段。只看题面、子问与清单。"""
    blocks = []
    for i, cs in enumerate(claims, 1):
        lines = [f"  - {item.answer[c['at'][0] : c['at'][1]]}" for c in cs] or ["  （没有摘出结论）"]
        blocks.append(f"子问 {i} 的结论：\n" + "\n".join(lines))
    user = f"【题面】\n{item.text}\n\n【子问清单】\n{_subqs(item)}\n\n【摘出的结论】\n" + "\n\n".join(blocks)
    err = ""
    for _ in range(2):
        try:
            turn = client.chat(prompts()["pandu"], [{"role": "user", "text": user + err}])
        except ModelError as e:
            raise JudgeFailed(f"判读：{e}") from None
        ledger.add("pandu", item.blind, turn)
        try:
            out = []
            for r in _rows(_json(turn.text), len(item.subquestions)):
                if r.get("verdict") not in SUB_VERDICTS:
                    raise ValueError(f"verdict 只取 {SUB_VERDICTS}")
                out.append(
                    {
                        "n": r["n"],
                        "verdict": r["verdict"],
                        "premise_false": bool(r.get("premise_false")) and r["verdict"] == "answered",
                        "reason": str(r.get("reason") or "")[:400],
                        "mechanism": str(r.get("mechanism") or "")[:200],
                    }
                )
            return out
        except (ValueError, TypeError, AttributeError) as e:
            err = f"\n\n（上一次的输出不合要求：{e}。只输出要求的 JSON 对象。）"
    raise JudgeFailed("判读：两次都没有给出合规的输出")


def pick(counts: list[int], seed: str, per_subq: int = PER_SUBQ, per_answer: int = PER_ANSWER) -> list[tuple[int, int]]:
    """抽哪几条：每个子问至多 `per_subq` 条（不足就全查），整份至多 `per_answer` 条。

    每个子问内部的次序由种子定；超过整份上限时一轮一轮地取（每个子问先各取一条，再各取第二条），
    这样子问多的题也是每个子问先有一条。回 (子问序号从 0 起, 该子问内第几条)。"""

    def order(sub: int, n: int) -> list[int]:
        return sorted(range(n), key=lambda i: hashlib.sha256(f"{seed}|{sub}|{i}".encode()).hexdigest())

    chosen = [order(s, n)[:per_subq] for s, n in enumerate(counts)]
    out: list[tuple[int, int]] = []
    for rnd in range(per_subq):
        for s, idx in enumerate(chosen):
            if rnd < len(idx) and len(out) < per_answer:
                out.append((s, idx[rnd]))
    return sorted(out)


def check(
    item: BlindItem, sub: int, claim: dict[str, Any], client: Client, ledger: Ledger, box: Toolbox
) -> dict[str, Any]:
    """第三段：一条结论对着快照核对。"""
    quote = item.answer[claim["at"][0] : claim["at"][1]]
    user = (
        f"【题面】\n{item.text}\n\n【这条结论回答的子问】\n{item.subquestions[sub]}\n\n"
        f"【结论的逐字片段】\n{quote}\n\n【写结论的人给的出处】\n{claim['cite'] or '（没有给）'}"
    )
    err = ""
    for _ in range(2):
        try:
            text, turns = with_tools(client, prompts()["hedui"], user + err, box, STEPS)
        except ModelError as e:
            raise JudgeFailed(f"核对：{e}") from None
        for t in turns:
            ledger.add("hedui", item.blind, t)
        try:
            doc = _json(text)
            if doc.get("verdict") not in CLAIM_VERDICTS:
                raise ValueError(f"verdict 只取 {CLAIM_VERDICTS}")
            lines = doc.get("lines") or [0, 0]
            return {
                "verdict": doc["verdict"],
                "path": str(doc.get("path") or "")[:300],
                "lines": [int(lines[0]), int(lines[1])],
                "mechanism": str(doc.get("mechanism") or "")[:200],
            }
        except (ValueError, TypeError, IndexError) as e:
            err = f"\n\n（上一次的输出不合要求：{e}。查完后只输出要求的 JSON 对象。）"
    raise JudgeFailed("核对：两次都没有给出合规的输出")


def judge(
    item: BlindItem,
    client: Client,
    ledger: Ledger,
    seed_base: str,
    per_subq: int = PER_SUBQ,
    per_answer: int = PER_ANSWER,
) -> dict[str, Any]:
    """一个题次的盲判。输入里没有臂名，所以同一份回答标成哪条臂，结果都逐项相同。"""
    claims, dropped = tidy(item, client, ledger)
    subs = read(item, claims, client, ledger)
    box = Toolbox(item.snapshot)
    sampled = []
    for s, i in pick([len(c) for c in claims], f"{seed_base}|{item.question}", per_subq, per_answer):
        v = check(item, s, claims[s][i], client, ledger, box)
        sampled.append({"n": s + 1, "at": claims[s][i]["at"], **v})
    for row, cs in zip(subs, claims, strict=True):
        row["claims"] = [c["at"] for c in cs]
    return {
        "v": 1,
        "blind": item.blind,
        "question": item.question,
        "prompts": prompts_digest(),
        "sampling": [per_subq, per_answer],
        "subquestions": subs,
        "dropped_quotes": dropped,
        "sampled": sampled,
        "search_timeouts": box.timeouts,
        "answered": all(r["verdict"] == "answered" for r in subs),
        "true": all(c["verdict"] == "holds" for c in sampled),
    }


# ---------------------------------------------------------------- 发现记录


def identifiers(snapshot: Path, *texts: str) -> frozenset[str]:
    """快照的标识符清单（文件名与文本内容里的英文标识符），加上题面里的。全部转小写。"""
    names: set[str] = set()
    pat = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
    for p in sorted(snapshot.rglob("*")):
        if ".git" in p.relative_to(snapshot).parts:
            continue
        names.update(x.lower() for x in pat.findall(p.name))
        if p.is_file() and not p.is_symlink() and p.stat().st_size <= FILE_BYTES:
            names.update(x.lower() for x in pat.findall(p.read_text(encoding="utf-8", errors="ignore")))
    for t in texts:
        names.update(x.lower() for x in pat.findall(t))
    return frozenset(names)


def scrub(sentence: str, names: frozenset[str]) -> tuple[str, bool]:
    """那句自由文字不许带题面与仓库里的专有名词：凡是清单里有的英文标识符，一律换成占位。宁可多换。"""
    hit = False

    def sub(m: re.Match[str]) -> str:
        nonlocal hit
        if any(part.lower() in names for part in re.split(r"[./\-:]", m.group(0)) if part):
            hit = True
            return MASK
        return m.group(0)

    return re.sub(r"[A-Za-z_][A-Za-z0-9_./\-:]*", sub, sentence), hit


def findings(
    batch: str, a: tici.Attempt, verdict: dict[str, Any] | None, names: frozenset[str], cap: int | None = None
) -> list[dict[str, Any]]:
    """一个题次的发现记录。臂名在这里才接上：盲判做完之后。`cap` 是每题上限（毫美元）。"""
    at = {"batch": batch, "arm": a.arm, "question": a.question, "rep": a.rep}
    rows: list[dict[str, Any]] = []

    def add(source: str, verdict_: str, sub: int | None, text: str, evidence: dict[str, Any]) -> None:
        clean, scrubbed = scrub(text, names)
        row = {
            "at": {**at, "subq": sub},
            "source": source,
            "verdict": verdict_,
            "text": clean,
            "scrubbed": scrubbed,
            "evidence": evidence,
        }
        rows.append({**row, "hash": sha(row)})

    if a.status != "finished":
        add("run", "incomplete", None, f"运行没有正常结束：{a.status}", {})
    elif cap is not None and a.cost_usd_milli > cap:
        add("run", "incomplete", None, "运行结束了，花费超出每题上限", {})
    for r in (verdict or {}).get("subquestions", []):
        if r["verdict"] != "answered":
            add("pandu", r["verdict"], r["n"], r["mechanism"], {"answer_at": r["claims"]})
    for c in (verdict or {}).get("sampled", []):
        if c["verdict"] != "holds":
            add(
                "hedui",
                c["verdict"],
                c["n"],
                c["mechanism"],
                {"answer_at": c["at"], "path": c["path"], "lines": c["lines"]},
            )
    return rows


# ---------------------------------------------------------------- 自检样本


def selfcheck(client: Client, ledger: Ledger, clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """三份已知答案的样本（两种文风各一份）。全查不抽样，任何一份判错都不算通过。

    每份样本是一个题次，记它从头判完用了多少秒（没做成的也记到放弃为止）。全查比正式判时的抽样只多不少。"""
    q = read_json(HERE / "canary" / "question.json")
    expected = read_json(HERE / "canary" / "expected.json")["samples"]
    results: dict[str, dict[str, Any]] = {}
    for name, want in sorted(expected.items()):
        item = BlindItem(
            question="canary",
            text=q["text"],
            subquestions=tuple(q["subquestions"]),
            answer=(HERE / "canary" / "answers" / f"{name}.md").read_text(encoding="utf-8"),
            snapshot=HERE / "canary" / "snapshot",
        )
        began = clock()
        try:
            v = judge(item, client, ledger, "selfcheck", per_subq=99, per_answer=99)
        except JudgeFailed as e:
            results[name] = {"ok": False, "why": f"盲判没做成：{e}", "seconds": round(clock() - began, 3)}
            continue
        seconds = round(clock() - began, 3)
        got = {
            "answered": v["answered"],
            "true": v["true"],
            "subq": {str(r["n"]): r["verdict"] for r in v["subquestions"]},
            "premise_false": [r["n"] for r in v["subquestions"] if r["premise_false"]],
        }
        ok = True
        for key, val in want.items():
            if key == "subq":
                ok = ok and all(got["subq"].get(n) == x for n, x in val.items())
            else:
                ok = ok and got[key] == val
        results[name] = {"ok": ok, "got": got, "seconds": seconds}
    return {
        "v": 2,
        **version(),
        "results": results,
        "seconds_max": max(r["seconds"] for r in results.values()),
        "ok": all(r["ok"] for r in results.values()),
    }


# ---------------------------------------------------------------- 整批


def load_questions(path: Path) -> dict[str, dict[str, Any]]:
    doc = read_json(path)
    base = path.parent
    out = {}
    for q in doc["questions"]:
        if not q.get("subquestions"):
            raise Refused(f"题 {q['id']} 没有子问清单：子问随题目一起定，不由任何一条臂拆")
        out[str(q["id"])] = {**q, "snapshot": (base / q["snapshot"]).resolve()}
    return out


def _gate(
    batch_dir: Path, cfg: JudgeModel, attempts: list[tici.Attempt], selfcheck_path: Path | None
) -> dict[str, Any]:
    """启动前的核对：盲判的模型登记全了（`JudgeModel.load` 已查）、与各臂的模型不同、与批次头里从计划带来的盲判
    一栏对得上、自检样本都判对过并且每个题次都在时限内。"""
    batch = read_json(batch_dir / "batch.json")
    arm_models = {str(a.get("model") or "") for a in (batch.get("arms") or {}).values()}
    arm_models |= {m for a in attempts for m in a.models_seen}
    if cfg.name in arm_models:
        raise Refused(f"盲判的模型 {cfg.name} 与某条臂的模型相同：盲判的模型必须与各臂不同")
    limit = _registered(batch, cfg)
    f = selfcheck_path or batch_dir / "selfcheck.json"
    if not f.exists():
        raise Refused(f"没有自检记录（{f}）：先跑 selfcheck，三份样本都判对了才启用")
    sc = read_json(f)
    now = version()
    same = sc.get("model") == cfg.name and sc.get("version") == cfg.version and sc.get("prompts") == now["prompts"]
    if not (sc.get("ok") and same):
        raise Refused("自检记录不是这个模型、这版提示词的，或没有全部判对：这一批盲判不作数")
    if sc.get("canary") != now["canary"] or sc.get("sample") != now["sample"]:
        raise Refused("自检记录不是用现在这套自检样本与抽样量做的：重跑 selfcheck")
    expected = set(read_json(HERE / "canary" / "expected.json")["samples"])
    results = sc.get("results") if isinstance(sc.get("results"), dict) else {}
    took: dict[str, float] = {}
    for k, r in results.items():
        v = r.get("seconds") if isinstance(r, dict) else None
        if not isinstance(v, bool) and isinstance(v, int | float) and v >= 0:
            took[k] = float(v)
    if set(took) != expected or len(took) != len(results):
        raise Refused("自检记录里没有每个题次的用时，或样本不全：重跑 selfcheck")
    if limit is not None:
        over = sorted(k for k, v in took.items() if v > limit)
        if over:
            raise Refused(
                f"自检时 {'、'.join(over)} 的盲判用时超过每题次的盲判时限（{limit} 秒）："
                "这个模型判不完，换下一个候选，不改时限"
            )
    return dict(batch)


def _registered(batch: dict[str, Any], cfg: JudgeModel) -> float | None:
    """批次头里从试火计划带来的盲判一栏，与实际要用的核对。回每题次的盲判时限（秒）；没有计划的批次回 None。"""
    planned = str(batch.get("plan_hash") or "无") != "无"
    reg = batch.get("judge")
    if not planned and reg is None:
        return None
    if not isinstance(reg, dict):
        raise Refused("这一批登记了试火计划，批次头里却没有盲判一栏：用 pici start --plan 登记，时限不能缺")
    if not planned:
        raise Refused("批次头里有盲判一栏却没有计划哈希：这一栏只从试火计划里来，不手填")
    if (reg.get("model"), reg.get("version")) != (cfg.name, cfg.version):
        raise Refused("盲判的模型或版本与试火计划里登记的不同：计划登记之后不改")
    now = version()
    if reg.get("prompts") != now["prompts"]:
        raise Refused("三段提示词的版本与试火计划里登记的不同：提示词是量具，换了版本要另立计划")
    if reg.get("sample") != now["sample"]:
        raise Refused("抽样量与试火计划里登记的不同")
    limit = reg.get("seconds_per_item")
    if isinstance(limit, bool) or not isinstance(limit, int | float) or limit <= 0:
        raise Refused("批次头里没有每题次的盲判时限")
    return float(limit)


def _items(batch_dir: Path, questions: dict[str, dict[str, Any]]) -> tuple[list[tici.Attempt], dict[str, BlindItem]]:
    attempts = tici.load_all(batch_dir)
    items: dict[str, BlindItem] = {}
    for a in attempts:
        if a.answer is None:
            continue
        q = questions.get(a.question)
        if q is None:
            raise Refused(f"题次用的题号 {a.question} 不在题集里")
        it = BlindItem(a.question, q["text"], tuple(q["subquestions"]), a.answer, q["snapshot"])
        items[it.blind] = it
    return attempts, items


def _seed(batch: dict[str, Any], questions_path: Path) -> str:
    plan = str(batch.get("plan_hash") or "")
    return plan if plan and plan != "无" else sha(read_json(questions_path))


def run_judge(a: argparse.Namespace, client: Client | None = None) -> int:
    batch_dir, qpath = Path(a.batch), Path(a.questions)
    cfg = JudgeModel.load(read_json(Path(a.judge)))
    questions = load_questions(qpath)
    attempts, items = _items(batch_dir, questions)
    batch = _gate(batch_dir, cfg, attempts, Path(a.selfcheck) if a.selfcheck else None)
    client = client or HttpClient(cfg)
    ledger = Ledger(batch_dir / "judge_calls.jsonl")
    seed = _seed(batch, qpath)
    failures: dict[str, str] = {}

    def one(it: BlindItem) -> None:
        out = batch_dir / "verdicts" / f"{it.blind}.json"
        if out.exists():
            return  # 接着上次做：判过的不重判
        began = time.monotonic()
        try:
            v = judge(it, client, ledger, seed)
            took = round(time.monotonic() - began, 3)  # 这个题次判了多久：只记，不拿来截断
            write_json(out, {**v, "model": cfg.name, "model_version": cfg.version, "seconds": took})
        except JudgeFailed as e:
            failures[it.blind] = str(e)

    with ThreadPoolExecutor(max_workers=max(1, int(a.jobs))) as pool:
        list(pool.map(one, [items[k] for k in sorted(items)]))

    index, rows = [], []
    names: dict[str, frozenset[str]] = {}
    for att in attempts:
        blind = None
        verdict = None
        if att.answer is not None:
            q = questions[att.question]
            blind = BlindItem(att.question, q["text"], tuple(q["subquestions"]), att.answer, q["snapshot"]).blind
            f = batch_dir / "verdicts" / f"{blind}.json"
            verdict = read_json(f) if f.exists() else None
        index.append({"arm": att.arm, "question": att.question, "rep": att.rep, "blind": blind})
        known = questions.get(att.question)
        if known is not None and att.question not in names:
            names[att.question] = identifiers(known["snapshot"], known["text"], *known["subquestions"])
        plan_cap = (batch.get("caps") or {}).get("per_question_usd_milli")
        cap = plan_cap if plan_cap is not None else att.cap_usd_milli
        rows += findings(str(batch.get("id", "")), att, verdict, names.get(att.question, frozenset()), cap)
    write_json(batch_dir / "index.json", index)
    write_json(batch_dir / "judge_failures.json", failures)
    with (batch_dir / "findings.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"判了 {len(items) - len(failures)} 份回答，盲判没做成 {len(failures)} 份，发现记录 {len(rows)} 条")
    return 0


def run_rejudge(a: argparse.Namespace, client: Client | None = None) -> int:
    """重判一致率：抽五分之一的回答从头再判一遍，比「答到」与「属实」两个结论。"""
    batch_dir, qpath = Path(a.batch), Path(a.questions)
    cfg = JudgeModel.load(read_json(Path(a.judge)))
    attempts, items = _items(batch_dir, load_questions(qpath))
    batch = _gate(batch_dir, cfg, attempts, Path(a.selfcheck) if a.selfcheck else None)
    client = client or HttpClient(cfg)
    ledger = Ledger(batch_dir / "judge_calls.jsonl")
    seed = _seed(batch, qpath)
    done = sorted(k for k in items if (batch_dir / "verdicts" / f"{k}.json").exists())
    chosen = sorted(done, key=lambda k: sha(f"{seed}|rejudge|{k}".encode()))[: math.ceil(len(done) / 5)]
    agree = failed = 0
    for k in chosen:
        first = read_json(batch_dir / "verdicts" / f"{k}.json")
        try:
            again = judge(items[k], client, ledger, seed)
        except JudgeFailed:
            failed += 1
            continue
        agree += int((first["answered"], first["true"]) == (again["answered"], again["true"]))
    write_json(batch_dir / "rejudge.json", {"v": 1, "chosen": len(chosen), "agree": agree, "failed": failed})
    print(f"重判一致率 {agree}/{len(chosen)}：重判 {len(chosen)} 份，两遍结论一致 {agree} 份，没做成 {failed} 份")
    return 0


def run_selfcheck(a: argparse.Namespace, client: Client | None = None) -> int:
    cfg = JudgeModel.load(read_json(Path(a.judge)))
    out = Path(a.out)
    doc = selfcheck(client or HttpClient(cfg), Ledger(out.with_name("selfcheck_calls.jsonl")))
    write_json(out, {**doc, "model": cfg.name, "version": cfg.version})
    for name, r in doc["results"].items():
        print(f"{name}：{'判对' if r['ok'] else '判错'}，用时 {r['seconds']} 秒")
    print(f"最慢的一个题次 {doc['seconds_max']} 秒；启动前拿它们与计划里每题次的盲判时限比")
    print("自检通过" if doc["ok"] else "自检没有通过：这个模型、这版提示词下的盲判不作数")
    return 0 if doc["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="liangju.mangpan")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version", help="这把尺子的版本：提示词与抽样量写进试火计划")
    s = sub.add_parser("selfcheck", help="三份已知答案的样本")
    s.add_argument("--judge", required=True)
    s.add_argument("--out", required=True)
    for name in ("judge", "rejudge"):
        j = sub.add_parser(name)
        j.add_argument("--batch", required=True)
        j.add_argument("--questions", required=True)
        j.add_argument("--judge", required=True)
        j.add_argument("--selfcheck")
        j.add_argument("--jobs", default=1)
    a = ap.parse_args(argv)
    if a.cmd == "version":
        print(json.dumps(version(), ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    try:
        return {"selfcheck": run_selfcheck, "judge": run_judge, "rejudge": run_rejudge}[a.cmd](a)
    except Refused as e:
        print(f"拒绝：{e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
