"""题目生成器：留出题有可重复的产生办法（现行设计第 7.4 节）。归量具，在引擎之外。

四步：

1. 取样仓库（`sample`）。候选是一份公开仓库检索结果的清单（`candidates`，每行一个仓库：名字、钉住的提交号、语言、
   大小、许可证）。按预登记的配额沿语言与仓库大小两条轴取，用固定的种子抽：同一格里的候选按「种子与仓库名」的哈希
   排序，取前几个，其余的按同一个顺序当替补。许可证不在配额登记的清单里的、排除清单里的（开发题与回归夹具用过的、
   之前任何一套题用过的），都不取。另外三条轴（问法、前提是否成立、答案在代码还是在配置文档）按配额里各自的题数，
   用同一个种子分到每一个位置上。
2. 出题。一个固定版本的调用带只读工具读快照，按分到的格子交出四样：题面、子问清单、每个子问的答案要点、每条要点
   的证据指针。前提不成立的题另交「确实没有」的证据。
3. 自动校验，五项全过才入库，任何一项不过就丢弃重出（同一个仓库至多出 `ATTEMPTS` 次，再不行换同一格的下一个替补）：
   - `evidence`：证据指针都在快照里、行区间不越界；声称没有的词在快照里确实搜不到（程序判）；
   - `leak`：题面不含文件路径，不含证据所在定义的确切名字（程序对照快照判）；
   - `supported`：一个没看过出题过程的独立调用，只拿着题面与指针指向的原文，判原文是否支持每条要点；
   - `needs_repo`：让模型不给快照直接作答，用第 5 节的盲判来判，必须不过线；
   - `duplicate`：一套题里一个仓库只出一道，用过的仓库不再出。
4. 入库与摘要。题集文件里带着生成器的版本、种子、配额与候选清单的摘要，题集摘要就是这个文件的摘要（与
   `pici digest` 是同一个数）。回传的只有 `receipt.json`：摘要、各格的题数、各项校验丢弃的次数。

    python -m liangju.chuti version
    python -m liangju.chuti candidates --quota quota.json --out candidates.jsonl
    python -m liangju.chuti sample --candidates candidates.jsonl --quota quota.json --seed <种子> \
        [--exclude 清单.json …] --out sample.json
    python -m liangju.chuti selfcheck --setter m.json [--answerer m.json …] --judge judge.json \
        --judge-selfcheck selfcheck.json --out chuti_selfcheck.json
    python -m liangju.chuti generate --sample sample.json --out <题集目录> --used used.json \
        --setter m.json [--answerer m.json …] --judge judge.json --judge-selfcheck selfcheck.json \
        --selfcheck chuti_selfcheck.json
    python -m liangju.chuti spot --set <题集目录> --n 10 --out sheet.json     # 题目质量：抽出要人看的那几道
    python -m liangju.chuti spot --tally sheet.json                           # 报抽检的符合率
    python -m liangju.chuti anchor --anchor <批次目录> --anchor-questions q.json \
        --generated <批次目录> --generated-questions q.json --out anchor.json

留出题在 cz 的机器上生成，题集目录不进会话也不进仓库。联网的只有 `candidates` 与取快照这两处，联网的是生成器，
不是引擎。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from liangju import huizong, mangpan, sousuo
from liangju.common import Refused, read_json, read_jsonl, sha, write_json
from liangju.model import Client, HttpClient, JudgeModel, Ledger, ModelError, Toolbox, with_tools

HERE = Path(__file__).resolve().parent
PROMPTS = ("chuti", "yanti", "zuoda")
AXES: dict[str, tuple[str, ...]] = {
    "ask": ("how", "why", "whether", "difference", "where"),
    "premise": ("holds", "fails"),
    "where": ("code", "doc"),
}
CHECKS = ("evidence", "leak", "supported", "needs_repo", "duplicate")
ATTEMPTS = 3  # 同一个仓库至多出这么多次题，都没过校验就换替补
STEPS = 40  # 出题时至多查阅这么多轮
SPAN = 60  # 一处证据至多这么多行
SUBQS = (2, 4)  # 子问个数的范围
POINTS = 3  # 一个子问至多这么多条答案要点
DOC_SUFFIXES = frozenset(
    ".md .rst .txt .adoc .yaml .yml .toml .ini .cfg .conf .json .xml .properties .env .example".split()
)
GITHUB = "https://api.github.com"
PER_QUERY = 100  # 检索候选时每一格取回的仓库数


class Dropped(Exception):
    """这一道题没有过校验（或没出成）：丢弃。`check` 是哪一项，`why` 是给人看的原因。"""

    def __init__(self, check: str, why: str) -> None:
        super().__init__(why)
        self.check, self.why = check, why


def prompts() -> dict[str, str]:
    return {s: (HERE / "prompts" / f"{s}.md").read_text(encoding="utf-8") for s in PROMPTS}


def canary() -> dict[str, Any]:
    doc: dict[str, Any] = read_json(HERE / "chuti_canary.json")
    return doc


def version() -> dict[str, Any]:
    """生成器的版本：三段提示词、几个定数、故意做坏的那几道题，以及「不读仓库答不出」用的那把尺子。"""
    ruler = mangpan.version()
    return {
        "prompts": sha({k: sha(v.encode("utf-8")) for k, v in prompts().items()}),
        "limits": {"attempts": ATTEMPTS, "steps": STEPS, "span": SPAN, "subqs": list(SUBQS), "points": POINTS},
        "canary": sha(canary()),
        "ruler": {"prompts": ruler["prompts"], "sample": ruler["sample"]},
    }


def version_id() -> str:
    return sha(version())[:16]


# ---------------------------------------------------------------- 第 1 步：取样仓库


def check_quota(quota: Any) -> dict[str, Any]:
    """配额是预登记的：题集代号、允许的许可证、仓库大小怎么分档、语言乘大小每格几道、另外三条轴各取几道。"""
    if not isinstance(quota, dict):
        raise Refused("配额文件不是一个 JSON 对象")
    if not str(quota.get("set") or "").strip():
        raise Refused("配额里没有题集代号（set）")
    licenses = quota.get("licenses")
    if not isinstance(licenses, list) or not licenses or not all(isinstance(x, str) and x for x in licenses):
        raise Refused("配额里没有允许的许可证清单（licenses）：许可证不在清单里的仓库不取")
    sizes = quota.get("sizes")
    if not isinstance(sizes, dict) or not sizes:
        raise Refused("配额里没有仓库大小的分档（sizes：档名到 [下限, 上限] 千字节，上限可以是 null）")
    for name, span in sizes.items():
        ok = isinstance(span, list) and len(span) == 2 and _count(span[0], zero=True)
        if not ok or not (span[1] is None or (_count(span[1]) and span[1] > span[0])):
            raise Refused(f"仓库大小的分档 {name} 写得不对：要 [下限, 上限]，上限大于下限或是 null")
    cells = quota.get("cells")
    if not isinstance(cells, dict) or not cells:
        raise Refused("配额里没有语言乘大小各格的题数（cells：「语言/档名」到题数）")
    for key, n in cells.items():
        lang, _, size = str(key).rpartition("/")
        if not lang or size not in sizes or not _count(n):
            raise Refused(f"配额里的格子 {key} 写得不对：要「语言/档名」，档名在 sizes 里，题数是正整数")
    total = sum(cells.values())
    for axis, values in AXES.items():
        got = quota.get(axis)
        if not isinstance(got, dict) or set(got) - set(values) or not all(_count(n, zero=True) for n in got.values()):
            raise Refused(f"配额里的 {axis} 一栏写得不对：只取 {list(values)}，各是非负整数")
        if sum(got.values()) != total:
            raise Refused(f"配额里 {axis} 一栏合计 {sum(got.values())} 道，语言乘大小各格合计 {total} 道：两边要相等")
    return quota


def _count(x: Any, zero: bool = False) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and (x >= 0 if zero else x > 0)


def _cell(row: dict[str, Any], quota: dict[str, Any]) -> str | None:
    for name, (lo, hi) in quota["sizes"].items():
        if row["size_kb"] >= lo and (hi is None or row["size_kb"] < hi):
            key = f"{row['language']}/{name}"
            return key if key in quota["cells"] else None
    return None


def _candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    repo, commit = str(row.get("repo") or "").strip(), str(row.get("commit") or "").strip().lower()
    size = row.get("size_kb")
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", repo) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        return None  # 没有钉住提交号的不算候选
    if not _count(size, zero=True) or not str(row.get("language") or "").strip():
        return None
    url = str(row.get("url") or f"https://github.com/{repo}.git")
    return {
        "repo": repo,
        "commit": commit,
        "language": str(row["language"]),
        "size_kb": size,
        "license": str(row.get("license") or ""),
        "url": url,
    }


def sample(candidates: list[dict[str, Any]], quota: Any, seed: str, excluded: set[str]) -> dict[str, Any]:
    """按配额与种子取样。同样的候选、配额、种子与排除清单，抽到的仓库与各格的分配相同。"""
    quota = check_quota(quota)
    if not str(seed).strip():
        raise Refused("没有给种子：取样用固定的种子")
    excluded = {x.lower() for x in excluded}
    rows: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    for raw in candidates:
        row = _candidate(raw)
        if row is None:
            counts["malformed"] += 1
        elif row["repo"].lower() not in rows:
            rows[row["repo"].lower()] = row
    pool: dict[str, list[dict[str, Any]]] = {cell: [] for cell in quota["cells"]}
    for key, row in sorted(rows.items()):
        cell = _cell(row, quota)
        if cell is None:
            counts["outside_cells"] += 1
        elif row["license"] not in quota["licenses"]:
            counts["license"] += 1
        elif key in excluded:
            counts["excluded"] += 1
        else:
            counts["eligible"] += 1
            pool[cell].append(row)
    slots: list[dict[str, Any]] = []
    spares: dict[str, list[dict[str, Any]]] = {}
    for cell in sorted(quota["cells"]):
        want = quota["cells"][cell]
        ranked = sorted(pool[cell], key=lambda r: sha(f"{seed}|{r['repo'].lower()}".encode()))
        if len(ranked) < want:
            raise Refused(f"格子 {cell} 要 {want} 个仓库，合格的候选只有 {len(ranked)} 个：配额取不满，不取样")
        lang, _, size = cell.rpartition("/")
        for row in ranked[:want]:
            slots.append({"cell": cell, "axes": {"language": lang, "size": size}, **_pin(row)})
        spares[cell] = [_pin(r) for r in ranked[want:]]
    for axis in AXES:
        values = [v for v in AXES[axis] for _ in range(quota[axis].get(v, 0))]
        ranks = {j: sha(f"{seed}|{axis}|{j}".encode()) for j in range(len(slots))}
        order = sorted(ranks, key=ranks.__getitem__)
        for value, j in zip(values, order, strict=True):
            slots[j]["axes"][axis] = value
    for n, slot in enumerate(slots, 1):
        slot["n"] = n
    return {
        "v": 1,
        "set": quota["set"],
        "seed": str(seed),
        "quota": sha(quota),
        "candidates": sha(sorted(rows.values(), key=lambda r: str(r["repo"]).lower())),
        "excluded": sha(sorted(excluded)),
        "counts": {k: counts[k] for k in ("eligible", "excluded", "license", "outside_cells", "malformed")},
        "slots": slots,
        "spares": spares,
    }


def _pin(row: dict[str, Any]) -> dict[str, Any]:
    return {"repo": row["repo"], "commit": row["commit"], "url": row["url"]}


def load_excluded(paths: list[str]) -> set[str]:
    """排除清单：每个文件是一个仓库名的数组，或者是 `generate` 自己记的用过的仓库（`used.json`）。"""
    out: set[str] = set()
    for p in paths:
        if not Path(p).exists():
            continue
        doc = read_json(Path(p))
        rows = doc.get("repos") if isinstance(doc, dict) else doc
        if not isinstance(rows, list):
            raise Refused(f"排除清单 {p} 不是仓库名的数组")
        out |= {str(r.get("repo") if isinstance(r, dict) else r).lower() for r in rows}
    return out


Get = Callable[[str], Any]


def _github(url: str) -> Any:
    headers = {"accept": "application/vnd.github+json", "user-agent": "liangju-chuti"}
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)  # noqa: S310  固定的公开接口
    try:
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise Refused(f"检索公开仓库没做成（{type(e).__name__}: {e}）") from None


def find_candidates(quota: Any, get: Get = _github) -> list[dict[str, Any]]:
    """候选来自公开仓库的检索结果：每一格检索一次（语言、大小区间、不是分叉、没有归档），每个仓库钉住缺省分支当时的
    提交号。检索结果随时间变，所以取样对着的是存下来的这份清单，清单的摘要记进题集。"""
    quota = check_quota(quota)
    out: list[dict[str, Any]] = []
    for cell in sorted(quota["cells"]):
        lang, _, size = cell.rpartition("/")
        lo, hi = quota["sizes"][size]
        q = f"language:{lang} size:{lo}..{hi - 1 if hi is not None else '*'} fork:false archived:false"
        found = get(f"{GITHUB}/search/repositories?q={urllib.parse.quote(q)}&sort=stars&per_page={PER_QUERY}")
        for item in found.get("items") or []:
            name, branch = str(item.get("full_name") or ""), str(item.get("default_branch") or "")
            if not name or not branch:
                continue
            head = get(f"{GITHUB}/repos/{name}/commits/{urllib.parse.quote(branch)}")
            out.append(
                {
                    "repo": name,
                    "commit": str(head.get("sha") or ""),
                    "language": lang,
                    "size_kb": item.get("size"),
                    "license": str((item.get("license") or {}).get("spdx_id") or ""),
                    "url": str(item.get("clone_url") or f"https://github.com/{name}.git"),
                }
            )
    return out


Fetch = Callable[[dict[str, Any], Path], None]


def git_fetch(row: dict[str, Any], dest: Path) -> None:
    """取钉住的那个提交的快照：只取这一个提交，取完去掉 `.git`。"""
    dest.mkdir(parents=True)

    def git(*args: str) -> None:
        done = subprocess.run(["git", "-C", str(dest), *args], capture_output=True, timeout=1800, check=False)  # noqa: S603, S607
        if done.returncode != 0:
            raise OSError(done.stderr.decode("utf-8", "replace").strip()[-300:])

    git("init", "-q")
    git("fetch", "-q", "--depth", "1", row["url"], row["commit"])
    git("-c", "advice.detachedHead=false", "checkout", "-q", "FETCH_HEAD")
    shutil.rmtree(dest / ".git")


# ---------------------------------------------------------------- 第 2 步：出题


def _pointer(p: Any) -> dict[str, Any]:
    if not isinstance(p, dict) or not isinstance(p.get("path"), str) or not p["path"].strip():
        raise ValueError("证据指针没有路径")
    if not _count(p.get("start")) or not _count(p.get("end")):
        raise ValueError("证据指针的行号不是正整数")
    return {"path": p["path"].strip(), "start": p["start"], "end": p["end"]}


def parse_draft(text: str) -> dict[str, Any]:
    """出题调用交出来的四样（加上前提不成立时的那一份）。形状不对就抛 ValueError。"""
    doc = mangpan._json(text)
    if not isinstance(doc.get("text"), str) or not doc["text"].strip():
        raise ValueError("没有题面")
    subs = doc.get("subquestions")
    if not isinstance(subs, list) or not SUBQS[0] <= len(subs) <= SUBQS[1]:
        raise ValueError(f"子问要 {SUBQS[0]} 到 {SUBQS[1]} 个")
    out_subs = []
    for s in subs:
        if not isinstance(s, dict) or not isinstance(s.get("q"), str) or not s["q"].strip():
            raise ValueError("有一个子问没有文字")
        points = s.get("points")
        if not isinstance(points, list) or not 1 <= len(points) <= POINTS:
            raise ValueError(f"每个子问要 1 到 {POINTS} 条答案要点")
        rows = []
        for p in points:
            if not isinstance(p, dict) or not isinstance(p.get("point"), str) or not p["point"].strip():
                raise ValueError("有一条答案要点没有文字")
            ev = p.get("evidence")
            if not isinstance(ev, list) or not ev:
                raise ValueError("有一条答案要点没有证据指针")
            rows.append({"point": p["point"].strip(), "evidence": [_pointer(e) for e in ev]})
        out_subs.append({"q": s["q"].strip(), "points": rows})
    absent = doc.get("absent")
    if absent is not None:
        if not isinstance(absent, dict) or not _count(absent.get("sub")) or absent["sub"] > len(out_subs):
            raise ValueError("absent 里没有写是第几个子问")
        terms = absent.get("searched")
        if not isinstance(terms, list) or not terms or not all(isinstance(t, str) for t in terms):
            raise ValueError("absent 里没有查过的词")
        if not isinstance(absent.get("actual"), str) or not absent["actual"].strip():
            raise ValueError("absent 里没有写那里实际是什么")
        absent = {
            "sub": absent["sub"],
            "searched": [t.strip() for t in terms],
            "expected_at": _pointer(absent.get("expected_at")),
            "actual": absent["actual"].strip(),
        }
    return {"text": doc["text"].strip(), "subquestions": out_subs, "absent": absent}


def set_one(slot: dict[str, Any], snapshot: Path, attempt: int, client: Client, ledger: Ledger) -> dict[str, Any]:
    """一次出题调用。格子里只有三条轴的取值与语言；仓库名不给。"""
    axes = slot["axes"]
    user = (
        f"【格子】\n问法：{axes['ask']}\n前提：{axes['premise']}\n答案在哪里：{axes['where']}\n"
        f"主要语言：{axes['language']}\n\n【第几次】\n{attempt}"
    )
    if attempt > 1:
        user += "（前几次出的题没有通过校验，已经丢弃；请换一处内容、换一个角度重新出）"
    try:
        text, turns = with_tools(client, prompts()["chuti"], user, Toolbox(snapshot), STEPS)
    except ModelError as e:
        raise Dropped("failed", f"出题调用没做成：{e}") from None
    for t in turns:
        ledger.add("chuti", f"{slot['n']}", t)
    try:
        return parse_draft(text)
    except ValueError as e:
        raise Dropped("malformed", f"出题调用交出来的形状不对：{e}") from None


# ---------------------------------------------------------------- 第 3 步：自动校验


def _lines(snapshot: Path, p: dict[str, Any]) -> list[str]:
    """指针指向的那几行原文。不在快照里、越界、太长，都抛 ValueError。"""
    try:
        f = sousuo.inside(snapshot.resolve(), p["path"])
    except ValueError:
        raise ValueError(f"证据指针指到了快照之外：{p['path']}") from None
    if not f.is_file() or f.is_symlink() or ".git" in Path(p["path"]).parts:
        raise ValueError(f"证据指针指的文件不在快照里：{p['path']}")
    if f.stat().st_size > sousuo.FILE_BYTES:
        raise ValueError(f"证据指针指的文件太大：{p['path']}")
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    if not 1 <= p["start"] <= p["end"] <= len(lines):
        raise ValueError(f"证据指针的行区间越界：{p['path']} 第 {p['start']}–{p['end']} 行，文件共 {len(lines)} 行")
    if p["end"] - p["start"] + 1 > SPAN:
        raise ValueError(f"一处证据超过 {SPAN} 行：{p['path']}")
    return lines[p["start"] - 1 : p["end"]]


def _pointers(draft: dict[str, Any]) -> list[dict[str, Any]]:
    out = [e for s in draft["subquestions"] for p in s["points"] for e in p["evidence"]]
    return out + ([draft["absent"]["expected_at"]] if draft["absent"] else [])


def _texts(snapshot: Path) -> list[tuple[str, str]]:
    root = snapshot.resolve()
    out = []
    for p in sousuo.files(root, root):
        if p.stat().st_size <= sousuo.FILE_BYTES:
            out.append((p.relative_to(root).as_posix(), p.read_text(encoding="utf-8", errors="replace")))
    return out


def check_evidence(draft: dict[str, Any], snapshot: Path, axes: dict[str, str]) -> None:
    """程序判：指针都在快照里、不越界；格子说前提不成立时要有「确实没有」的证据，查过的词在快照里一处都搜不到；
    格子说答案在配置文档（或在代码）时，至少有一处证据落在那一类文件里。"""
    try:
        for p in _pointers(draft):
            _lines(snapshot, p)
    except ValueError as e:
        raise Dropped("evidence", str(e)) from None
    absent = draft["absent"]
    if (axes["premise"] == "fails") != (absent is not None):
        raise Dropped("evidence", "前提标得与格子不符：格子说不成立的要交「确实没有」的证据，说成立的不能交")
    if absent is not None:
        terms = [t for t in absent["searched"] if len(t) >= 2]
        if not terms or len(terms) != len(absent["searched"]):
            raise Dropped("evidence", "「确实没有」的证据里，查过的词是空的或太短")
        texts = _texts(snapshot)
        for t in terms:
            hit = next((rel for rel, body in texts if t.lower() in body.lower() or t.lower() in rel.lower()), None)
            if hit is not None:
                raise Dropped("evidence", f"前提标错了：说没有的词「{t}」在快照里搜得到")
    kinds = {Path(e["path"]).suffix.lower() in DOC_SUFFIXES for s in draft["subquestions"] for p in s["points"]
             for e in p["evidence"]}  # fmt: skip
    if (axes["where"] == "doc") not in kinds:
        raise Dropped("evidence", "答案所在的位置标得与格子不符：没有一处证据落在格子说的那一类文件里")


_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_DEFINES = re.compile(
    rf"\b(?:def|class|func|fn|function|struct|interface|type|enum|trait|impl|const|let|var|val|module|package"
    rf"|namespace|object|record|macro)\s+({_NAME})"
)
_ASSIGNS = re.compile(rf"^\s*(?:export\s+|pub\s+|static\s+|final\s+)*[\"']?({_NAME}(?:[.\-]{_NAME})*)[\"']?\s*[:=]")


def defined_names(lines: list[str]) -> set[str]:
    """一段原文里定义的名字：定义关键字后面的那个名字，以及行首被赋值的名字或配置项的键。全部转小写。"""
    out: set[str] = set()
    for line in lines:
        out.update(m.lower() for m in _DEFINES.findall(line))
        m = _ASSIGNS.match(line)
        if m:
            out.add(m.group(1).lower())
            out.update(part.lower() for part in re.split(r"[.\-]", m.group(1)))
    return {n for n in out if len(n) >= 3}


def check_leak(draft: dict[str, Any], snapshot: Path) -> None:
    """程序判：题面不含文件路径或文件名，不含证据所在定义的确切名字，也不含快照里那种一看就是代码里的名字
    （带下划线或大小写混排的标识符）。宁可多丢。"""
    text = draft["text"]
    low = text.lower()
    root = snapshot.resolve()
    for p in sousuo.files(root, root):
        rel = p.relative_to(root).as_posix()
        if rel.lower() in low or ("." in p.name and len(p.name) >= 4 and p.name.lower() in low):
            raise Dropped("leak", "题面里有文件路径或文件名")
    tokens = set(re.findall(_NAME, text))
    names: set[str] = set()
    for pointer in _pointers(draft):
        names |= defined_names(_lines(snapshot, pointer))
    if {t.lower() for t in tokens} & names:
        raise Dropped("leak", "题面里有证据所在定义的确切名字")
    codey = {t for t in tokens if "_" in t.strip("_") or re.search(r"[a-z][A-Z]", t)}
    if codey and {t.lower() for t in codey} & mangpan.identifiers(snapshot):
        raise Dropped("leak", "题面里有代码里的标识符")


def _excerpt(snapshot: Path, pointers: list[dict[str, Any]]) -> str:
    blocks = []
    for k, p in enumerate(pointers, 1):
        body = "\n".join(f"{i}\t{line}" for i, line in enumerate(_lines(snapshot, p), p["start"]))
        blocks.append(f"原文片段 {k}：\n{body}")
    return "\n\n".join(blocks)


def check_supported(draft: dict[str, Any], snapshot: Path, client: Client, ledger: Ledger, tag: str) -> None:
    """独立的一次调用：没看过出题过程，没有工具，只拿着题面、子问、要点与指针指向的原文。路径不给。"""
    rows: list[str] = []
    for i, s in enumerate(draft["subquestions"], 1):
        absent = draft["absent"] if draft["absent"] and draft["absent"]["sub"] == i else None
        for p in s["points"]:
            n = len(rows) + 1
            head = f"要点 {n}（回答子问 {i}）：{p['point']}"
            pointers = list(p["evidence"])
            if absent is not None:
                head += (
                    f"\n这条要点标着「前提不成立」。出题方说查过这些词都没有：{'、'.join(absent['searched'])}。"
                    f"出题方说本该在的地方实际是：{absent['actual']}（见最后一个原文片段）"
                )
                pointers.append(absent["expected_at"])
            rows.append(f"{head}\n{_excerpt(snapshot, pointers)}")
    subs = "\n".join(f"{i}. {s['q']}" for i, s in enumerate(draft["subquestions"], 1))
    user = f"【题面】\n{draft['text']}\n\n【子问清单】\n{subs}\n\n【答案要点与原文】\n" + "\n\n".join(rows)
    system = prompts()["yanti"]
    messages: list[dict[str, Any]] = [{"role": "user", "text": user}]
    for _ in range(2):
        try:
            turn = client.chat(system, messages)
        except ModelError as e:
            raise Dropped("failed", f"独立校验的调用没做成：{e}") from None
        ledger.add("yanti", tag, turn)
        try:
            got = mangpan._json(turn.text).get("points")
            if not isinstance(got, list) or [r.get("n") if isinstance(r, dict) else None for r in got] != list(
                range(1, len(rows) + 1)
            ):
                raise ValueError("要点的编号不全或顺序不对")
            if not all(isinstance(r.get("supported"), bool) for r in got):
                raise ValueError("supported 不是 true 或 false")
        except ValueError as e:
            messages = [{"role": "user", "text": f"{user}\n\n（上一次的输出不合要求：{e}。只输出那个 JSON 对象。）"}]
            continue
        bad = [r["n"] for r in got if not r["supported"]]
        if bad:
            raise Dropped("supported", f"指针指向的原文不支持第 {bad} 条答案要点")
        return
    raise Dropped("failed", "独立校验两次都没有给出合规的输出")


def check_needs_repo(
    draft: dict[str, Any], snapshot: Path, answerer: Client, judge: Client, ledger: Ledger, tag: str
) -> None:
    """不给快照让模型直接作答，交给第 5 节的盲判（它对着快照核对）。过线了就说明不读仓库也答得出：丢弃。"""
    try:
        turn = answerer.chat(prompts()["zuoda"], [{"role": "user", "text": draft["text"]}])
    except ModelError as e:
        raise Dropped("failed", f"不给快照作答的调用没做成：{e}") from None
    ledger.add("zuoda", tag, turn)
    if not turn.text.strip():
        return  # 什么都没答出来：不过线
    item = mangpan.BlindItem(tag, draft["text"], tuple(s["q"] for s in draft["subquestions"]), turn.text, snapshot)
    try:
        v = mangpan.judge(item, judge, ledger, "chuti")
    except mangpan.JudgeFailed as e:
        raise Dropped("failed", f"盲判没做成：{e}") from None
    if v["answered"] and v["true"]:
        raise Dropped("needs_repo", "不读仓库也答得出：不给快照直接作答，盲判判为过线")


@dataclass
class Models:
    setter: Client  # 出题与独立校验
    answerers: list[Client]  # 不给快照作答：用到的每个模型各做一遍，有一个答得出就丢弃
    judge: Client  # 盲判


def vet(draft: dict[str, Any], snapshot: Path, axes: dict[str, str], m: Models, ledger: Ledger, tag: str) -> None:
    """前四项校验，便宜的先做。任何一项不过就抛 `Dropped`。第五项（不重复）在入库时查。"""
    check_evidence(draft, snapshot, axes)
    check_leak(draft, snapshot)
    check_supported(draft, snapshot, m.setter, ledger, tag)
    for answerer in m.answerers:
        check_needs_repo(draft, snapshot, answerer, m.judge, ledger, tag)


def selfcheck(m: Models, ledger: Ledger) -> dict[str, Any]:
    """校验拦得住坏题：四道故意做坏的题（指针越界、前提标错、题面泄底、不读仓库也能答）都要被丢弃，并且各自是被
    该拦它的那一项拦下的；另有一道做对的题要通过，不然什么都丢的校验也能过这一关。快照用盲判自检的那一份。"""
    files = mangpan.canary_files()
    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="liangju-chuti-") as tmp:
        snapshot = Path(tmp) / "snapshot"
        for rel, src in files.items():
            if rel.startswith("snapshot/"):
                (Path(tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, Path(tmp) / rel)
        for name, case in sorted(canary()["cases"].items()):
            got: str | None = None
            try:
                vet(parse_draft(json.dumps(case["draft"])), snapshot, case["axes"], m, ledger, f"canary-{name}")
            except Dropped as e:
                got = e.check
            results[name] = {"expected": case["caught_by"], "got": got, "ok": got == case["caught_by"]}
    return {"v": 1, "generator": version(), "results": results, "ok": all(r["ok"] for r in results.values())}


# ---------------------------------------------------------------- 第 4 步：整套出题、入库与摘要


def generate(
    plan: dict[str, Any], out: Path, m: Models, fetch: Fetch, ledger: Ledger, used: set[str]
) -> tuple[list[dict[str, Any]], Counter[str], int]:
    """按取样的结果一个位置一个位置出题。回入库的题、各项丢弃的次数、换了几次替补。

    出好的题先存进 `<out>/work/`，中途断了接着做：出好的不重出。一个位置把同一格的替补都用完还没出成，就拒绝，
    整套题不入库（配额是预登记的，不能少出）。"""
    code = plan["set"]
    spares = {cell: list(rows) for cell, rows in plan["spares"].items()}
    taken = {u.lower() for u in used}
    drops: Counter[str] = Counter()
    replaced = 0
    accepted: list[dict[str, Any]] = []
    for slot in plan["slots"]:
        qid = f"{code}-{slot['n']:03d}"
        work, snapshot = out / "work" / f"{qid}.json", out / "snapshots" / qid
        if work.exists() and snapshot.is_dir():
            done = read_json(work)
            taken.add(done["repo"].lower())
            accepted.append(done)
            continue
        first: list[dict[str, Any]] = [_pin(slot)]
        got: dict[str, Any] | None = None
        while got is None:
            if first:
                row = first.pop()
            elif spares[slot["cell"]]:
                row = spares[slot["cell"]].pop(0)  # 替补是同一格共用的：用掉一个少一个
                replaced += 1
            else:
                break
            if row["repo"].lower() in taken:
                drops["duplicate"] += 1  # 这个仓库已经出过题：一套题里一个仓库只出一道，用过的不再出
                continue
            if snapshot.exists():
                shutil.rmtree(snapshot)
            try:
                fetch(row, snapshot)
            except (OSError, subprocess.SubprocessError) as e:
                drops["fetch"] += 1
                print(f"位置 {slot['n']}：快照没取到（{type(e).__name__}），换替补", file=sys.stderr)
                continue
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    draft = set_one(slot, snapshot, attempt, m.setter, ledger)
                    vet(draft, snapshot, slot["axes"], m, ledger, qid)
                except Dropped as e:
                    drops[e.check] += 1
                    continue
                got = {"id": qid, "repo": row["repo"], "commit": row["commit"], "axes": slot["axes"], "draft": draft}
                break
        if got is None:
            shutil.rmtree(snapshot, ignore_errors=True)
            raise Refused(
                f"位置 {slot['n']}（格子 {slot['cell']}）把替补都用完了还没有出成一道过校验的题：整套题不入库。"
                "出好的题留在 work/ 里，补足候选之后要重新取样"
            )
        taken.add(got["repo"].lower())
        write_json(work, got)
        accepted.append(got)
    return accepted, drops, replaced


def admit(
    plan: dict[str, Any], accepted: list[dict[str, Any]], models: dict[str, Any], used: set[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """入库：排成题集文件与答案文件。第五项校验在这里再查一遍：一套题里一个仓库只出一道，用过的仓库不再出。"""
    repos = [a["repo"].lower() for a in accepted]
    again = sorted({r for r in repos if repos.count(r) > 1} | (set(repos) & {u.lower() for u in used}))
    if again:
        raise Refused(f"有 {len(again)} 个仓库出了不止一道题或者以前的题集用过：不入库")
    if len(accepted) != len(plan["slots"]):
        raise Refused(f"配额是 {len(plan['slots'])} 道，出成的只有 {len(accepted)} 道：不入库")
    keys = {
        a["id"]: {
            "repo": a["repo"],
            "commit": a["commit"],
            "subquestions": a["draft"]["subquestions"],
            "absent": a["draft"]["absent"],
        }
        for a in accepted
    }
    questions = {
        "v": 1,
        "generator": {
            "id": version_id(),
            "version": version(),
            "set": plan["set"],
            "seed": plan["seed"],
            "quota": plan["quota"],
            "candidates": plan["candidates"],
            "excluded": plan["excluded"],
            "models": models,
            "keys": sha(keys),
        },
        "questions": [
            {
                "id": a["id"],
                "text": a["draft"]["text"],
                "subquestions": [s["q"] for s in a["draft"]["subquestions"]],
                "snapshot": f"snapshots/{a['id']}",
                "axes": a["axes"],
            }
            for a in accepted
        ],
    }
    return questions, keys


def receipt(questions: dict[str, Any], drops: Counter[str], replaced: int) -> dict[str, Any]:
    """回传的只有这些：摘要、各格的题数、各项校验丢弃的次数。没有题面、仓库名与路径。"""
    rows = questions["questions"]
    g = questions["generator"]
    return {
        "v": 1,
        "set": g["set"],
        "digest": sha(questions),
        "count": len(rows),
        "generator": g["id"],
        "seed": g["seed"],
        "quota": g["quota"],
        "candidates": g["candidates"],
        "cells": {
            axis: dict(sorted(Counter(str(q["axes"][axis]) for q in rows).items()))
            for axis in ("language", "size", *AXES)
        },
        "language_by_size": dict(sorted(Counter(f"{q['axes']['language']}/{q['axes']['size']}" for q in rows).items())),
        "discarded": {k: drops[k] for k in (*CHECKS, "malformed", "failed", "fetch")},
        "replaced_repos": replaced,
    }


# ---------------------------------------------------------------- 题目质量的抽检、与锚题集对一次


def spot_pick(set_dir: Path, n: int) -> dict[str, Any]:
    """题目质量：从一套生成的题里抽 n 道给人看。抽哪几道由题集摘要定。人填两栏，工具只算符合率。"""
    questions = read_json(set_dir / "questions.json")
    digest = sha(questions)
    ids = sorted((q["id"] for q in questions["questions"]), key=lambda i: sha(f"{digest}|{i}".encode()))[: max(1, n)]
    return {
        "v": 1,
        "digest": digest,
        "generator": (questions.get("generator") or {}).get("id"),
        "rows": [{"id": i, "reads_like_a_real_question": None, "points_are_right": None} for i in sorted(ids)],
    }


def spot_tally(sheet: dict[str, Any]) -> dict[str, Any]:
    rows = sheet.get("rows") or []
    keys = ("reads_like_a_real_question", "points_are_right")
    if not rows or not all(isinstance(r.get(k), bool) for r in rows for k in keys):
        raise Refused("抽检表还没有填完：每道题的两栏都要填 true 或 false")
    both = sum(all(r[k] for k in keys) for r in rows)
    return {
        "digest": sheet.get("digest"),
        "generator": sheet.get("generator"),
        "checked": len(rows),
        **{k: sum(r[k] for r in rows) for k in keys},
        "both": both,
        "rate": round(both / len(rows), 4),
    }


def _benhuo(summary: dict[str, Any]) -> tuple[int, int, int | None]:
    rows = [r for r in summary["每条臂一组"] if r["角色"] == huizong.ROLE_ZH["benhuo"]]
    if len(rows) != 1 or not rows[0]["题次数"]:
        raise Refused("批次里没有本火臂的题次（或不止一条本火臂）：对不了")
    pair = summary["成对比较"].get(f"{huizong.ROLE_ZH['benhuo']}对{huizong.ROLE_ZH['tonghuo']}") or {}
    return rows[0]["过线的题次数"], rows[0]["题次数"], pair.get("噪声底 m")


def anchor(anchor_sum: dict[str, Any], anchor_q: Any, gen_sum: dict[str, Any], gen_q: Any) -> dict[str, Any]:
    """与人出的题是不是同一把尺子：本火臂在锚题集与生成的题集上的过线比例之差，要在噪声底之内。

    噪声底是按题次数算的一个数（本火对同火对照的不一致数 d，取 2 倍的 d 的平方根）。这里把它换成比例：每一边的
    噪声底除以那一边的题次数，两边里取大的那个。两边至少有一边要带同火对照，不然没有噪声底可比。"""
    if not isinstance(gen_q, dict) or not isinstance(gen_q.get("generator"), dict):
        raise Refused("生成的那一边给的不是生成器出的题集（题集文件里没有 generator 一栏）")
    if isinstance(anchor_q, dict) and anchor_q.get("generator"):
        raise Refused("锚题集要是人出的那一套：这一份是生成器出的")
    a_pass, a_n, a_m = _benhuo(anchor_sum)
    g_pass, g_n, g_m = _benhuo(gen_sum)
    floors = [m / n for m, n in ((a_m, a_n), (g_m, g_n)) if m is not None]
    if not floors:
        raise Refused("两边都没有同火对照：没有噪声底，对不了")
    gap = abs(a_pass / a_n - g_pass / g_n)
    return {
        "v": 1,
        "generator": gen_q["generator"]["id"],
        "anchor": {"digest": sha(anchor_q), "passed": a_pass, "attempts": a_n, "noise_floor": a_m},
        "generated": {"digest": sha(gen_q), "passed": g_pass, "attempts": g_n, "noise_floor": g_m},
        "gap": round(gap, 4),
        "floor": round(max(floors), 4),
        "ok": gap <= max(floors) + 1e-9,
    }


def anchored(questions: Any, record: Any) -> str | None:
    """一套题能不能用于判定。人出的题集不用对；生成的题集要有一份「对过了并且在噪声底之内」的记录，而且是这一版
    生成器的。回不能用的原因，能用就回 None。"""
    g = questions.get("generator") if isinstance(questions, dict) else None
    if not isinstance(g, dict):
        return None
    if not isinstance(record, dict):
        return "这套题是生成器出的：先与人出的锚题集对一次（chuti anchor），对过了才能用于判定"
    if record.get("generator") != g.get("id"):
        return "与锚题集对过的是另一版生成器：这一版要重新对"
    if not record.get("ok"):
        return "这一版生成器的题与锚题集的过线比例之差超出了噪声底：只能用于旗帜，不能用于判定"
    return None


# ---------------------------------------------------------------- 命令


def _models(a: argparse.Namespace) -> tuple[tuple[JudgeModel, list[JudgeModel], JudgeModel], dict[str, Any]]:
    setter = JudgeModel.load(read_json(Path(a.setter)))
    answerers = [JudgeModel.load(read_json(Path(p))) for p in a.answerer or []] or [setter]
    judge = JudgeModel.load(read_json(Path(a.judge)))
    if any(judge.name == x.name for x in answerers):
        raise Refused("盲判的模型与作答的模型相同：盲判的模型必须与被它判的模型不同")
    sc = Path(a.judge_selfcheck)
    if not sc.exists():
        raise Refused(f"没有盲判的自检记录（{sc}）：先跑 mangpan selfcheck")
    answer = mangpan.qualify(None, judge, read_json(sc))
    if not answer["ok"]:
        raise Refused(answer["reasons"][0])
    names = {
        "setter": [setter.name, setter.version],
        "answerers": [[x.name, x.version] for x in answerers],
        "judge": [judge.name, judge.version],
    }
    return (setter, answerers, judge), names


def _clients(cfgs: tuple[JudgeModel, list[JudgeModel], JudgeModel]) -> Models:
    return Models(HttpClient(cfgs[0]), [HttpClient(x) for x in cfgs[1]], HttpClient(cfgs[2]))


def run_candidates(a: argparse.Namespace, get: Get = _github) -> int:
    rows = find_candidates(read_json(Path(a.quota)), get)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), "utf-8")
    print(f"候选 {len(rows)} 个，写在 {out}")
    return 0


def run_sample(a: argparse.Namespace) -> int:
    doc = sample(read_jsonl(Path(a.candidates)), read_json(Path(a.quota)), a.seed, load_excluded(a.exclude or []))
    write_json(Path(a.out), doc)
    print(f"取了 {len(doc['slots'])} 个仓库，替补 {sum(len(v) for v in doc['spares'].values())} 个")
    return 0


def run_selfcheck(a: argparse.Namespace, m: Models | None = None) -> int:
    cfgs, names = _models(a)
    out = Path(a.out)
    doc = selfcheck(m or _clients(cfgs), Ledger(out.with_name("chuti_selfcheck_calls.jsonl")))
    write_json(out, {**doc, "models": names})
    for name, r in doc["results"].items():
        print(f"{name}：该由 {r['expected'] or '（通过）'} 处置，实际 {r['got'] or '（通过）'}")
    print("生成器的校验合格" if doc["ok"] else "生成器的校验不合格：不启用")
    return 0 if doc["ok"] else 1


def run_generate(a: argparse.Namespace, m: Models | None = None, fetch: Fetch = git_fetch) -> int:
    cfgs, names = _models(a)
    sc = read_json(Path(a.selfcheck)) if Path(a.selfcheck).exists() else {}
    if not (sc.get("ok") and sc.get("generator") == version() and sc.get("models") == names):
        raise Refused("没有这一版生成器、这几个模型的校验记录，或故意做坏的题没有全部拦下：先跑 chuti selfcheck")
    plan = read_json(Path(a.sample))
    out, used_path = Path(a.out), Path(a.used)
    if (out / "questions.json").exists():
        raise Refused(f"{out} 里已经有一套入了库的题：一个目录只放一套")
    used = load_excluded([str(used_path)])
    ledger = Ledger(out / "chuti_calls.jsonl")
    accepted, drops, replaced = generate(plan, out, m or _clients(cfgs), fetch, ledger, used)
    questions, keys = admit(plan, accepted, names, used)
    write_json(out / "keys.json", keys)
    write_json(out / "questions.json", questions)
    doc = receipt(questions, drops, replaced)
    write_json(out / "receipt.json", doc)
    before = read_json(used_path)["repos"] if used_path.exists() else []
    write_json(used_path, {"repos": before + [{"repo": a_["repo"], "set": plan["set"]} for a_ in accepted]})
    print(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True))
    return 0


def run_spot(a: argparse.Namespace) -> int:
    if a.tally:
        print(json.dumps(spot_tally(read_json(Path(a.tally))), ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    if not (a.set and a.out):
        raise Refused("抽题要给 --set 与 --out；算符合率要给 --tally")
    write_json(Path(a.out), spot_pick(Path(a.set), int(a.n)))
    print(f"抽检表写在 {a.out}：每道题填两栏（像不像人会问的、答案要点对不对），填完用 --tally 算符合率")
    return 0


def run_anchor(a: argparse.Namespace) -> int:
    aq, gq = Path(a.anchor_questions), Path(a.generated_questions)
    doc = anchor(huizong.build(Path(a.anchor), aq), read_json(aq), huizong.build(Path(a.generated), gq), read_json(gq))
    write_json(Path(a.out), doc)
    print(f"过线比例之差 {doc['gap']}，噪声底（比例）{doc['floor']}：", end="")
    print(
        "在噪声底之内，这一版生成器的题可以用于判定"
        if doc["ok"]
        else "超出噪声底，只用于旗帜；把差异当作生成器的缺陷去查"
    )
    return 0 if doc["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="liangju.chuti")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version")
    c = sub.add_parser("candidates", help="检索公开仓库，存成候选清单")
    c.add_argument("--quota", required=True)
    c.add_argument("--out", required=True)
    s = sub.add_parser("sample", help="按配额与种子取样")
    for name in ("candidates", "quota", "seed", "out"):
        s.add_argument(f"--{name}", required=True)
    s.add_argument("--exclude", action="append")
    k = sub.add_parser("selfcheck", help="校验拦得住坏题")
    g = sub.add_parser("generate", help="出题、校验、入库")
    for p in (k, g):
        for name in ("setter", "judge", "judge-selfcheck", "out"):
            p.add_argument(f"--{name}", required=True)
        p.add_argument("--answerer", action="append")
    for name in ("sample", "used", "selfcheck"):
        g.add_argument(f"--{name}", required=True)
    t = sub.add_parser("spot", help="题目质量的抽检")
    for name in ("set", "out", "tally"):
        t.add_argument(f"--{name}")
    t.add_argument("--n", default=10)
    n = sub.add_parser("anchor", help="与人出的锚题集对一次")
    for name in ("anchor", "anchor-questions", "generated", "generated-questions", "out"):
        n.add_argument(f"--{name}", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "version":
        print(json.dumps({"id": version_id(), **version()}, ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    runs: dict[str, Callable[[argparse.Namespace], int]] = {
        "candidates": run_candidates,
        "sample": run_sample,
        "selfcheck": run_selfcheck,
        "generate": run_generate,
        "spot": run_spot,
        "anchor": run_anchor,
    }
    try:
        return runs[a.cmd](a)
    except Refused as x:
        print(f"拒绝：{x}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
