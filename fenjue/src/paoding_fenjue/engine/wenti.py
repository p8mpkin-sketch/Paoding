"""按题读的确定性部分（docs/design/fenjue/14-question-led.md §2–§4）：题面拆问、按词检索、切分文件、排下一批。

题目原话在这里第一次进流程。模型只在三处出场，都在 `dati.py`：把问句换成检索词、从对方仓库的真实名字里挑词、
读一段原文。这里全是纯函数：同一份快照、同一组词，排出来的阅读顺序逐字节相同。

- `questions`：题面里有没有点名。有「怎么、如何、怎样」引出的问句才算点名；没有就返回空列表，流程走原路径。
- `search`、`vocabulary`、`rank`：检索词在路径、符号、标题、正文里的命中 → 每个子问的文件排序。
- `parts`：把一个文件切成整段可读的部分（不超过 PART_LINES 行；过长的在顶层定义处下刀）。
- `Frontier`：读完一批之后排下一批——追的标识符的定义、用到它们的地方、对应的测试、核心文件剩下的部分。
"""

from __future__ import annotations

import keyword
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import survey, text

ASK = ("怎么", "如何", "怎样", "how ", "how to")  # 问句的标志（按折叠后的小写比对）
_SPLIT = re.compile(r"[、，,；;。？?\n]+")
_LEAD = re.compile(
    r"^(?:请|帮我|麻烦)?(?:看看|看一下|看下|分析一下|分析|研究一下|研究)?(?:这个|该|此)?(?:仓库|项目|系统|代码库|框架)?(?:里面|里|中)?(?:的)?"
)
_LEAD2 = re.compile(r"^[\s:：—-]*(?:(?:它|其|他们)的?|and\s+|also\s+)?", re.IGNORECASE)
MAX_QUESTIONS = 4
PART_LINES = 300  # 一次阅读给模型的行数上限〔占位〕：约 4 千 token，留得出交回细事实的输出空间
PART_MIN = 40  # 切出来的尾巴短于这个数就并进前一部分
_TOP_DEF = re.compile(r"^(?:async\s+def|def|class|function|export\s|const\s|func\s|impl\s|pub\s|type\s|interface\s)")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
_EN_TERM = re.compile(r"[a-z][a-z0-9_ .-]{2,39}")
READABLE = ("python", "javascript", "typescript", "markdown", "toml", "yaml", "json", "ini", "shell", "text")


# ---------------------------------------------------------------- 题面


def questions(statement: str) -> list[dict[str, str]]:
    """题面里点名的子问。规则（确定的，不调模型）：按顿号、逗号、分号切开；带问句标志的一段起一个子问，
    它后面不带标志的段是它的补充，并进去；从「有什么…」起的收尾问（值得集成什么）不算子问——那一问每道题都有。
    一个标志都没有 → 空列表：题面没有点名，走通用勘察。"""
    clauses = [c.strip() for c in _SPLIT.split(statement) if c.strip()]
    out: list[str] = []
    for c in clauses:
        f = text.fold(c)
        if f.startswith(("有什么", "有哪些", "what ")) or "值得我们" in f or "值得集成" in f:
            break
        if any(a in f for a in ASK):
            out.append(c)
        elif out:
            out[-1] = f"{out[-1]}、{c}"
    cleaned = []
    for q in out[:MAX_QUESTIONS]:
        q = _LEAD.sub("", q, count=1).strip() or q
        q = _LEAD2.sub("", q, count=1).strip() or q  # 「分析这个仓库：它的……」剩下的冒号与代词
        cleaned.append(q[:200])
    return [{"id": f"Q{i}", "text": q} for i, q in enumerate(cleaned, 1)]


def clean_terms(raw: Any, limit: int = 16) -> tuple[list[str], list[str]]:
    """模型给的检索词收一遍：英文取小写的词或词干（3–40 个字符），中文 2–8 个字；去重、限量。交回（中文，英文）。"""
    zh: list[str] = []
    en: list[str] = []
    for kind, bucket in (("zh", zh), ("en", en)):
        vals = raw.get(kind) if isinstance(raw, Mapping) else None
        for v in vals if isinstance(vals, list) else []:
            if not isinstance(v, str):
                continue
            t = text.fold(v).strip()
            ok = (2 <= len(t) <= 8 and not t.isascii()) if kind == "zh" else bool(_EN_TERM.fullmatch(t))
            if ok and t not in bucket:
                bucket.append(t)
    return zh[:limit], en[:limit]


# ---------------------------------------------------------------- 检索


@dataclass
class Index:
    """一份快照的检索底：每个可读文件折叠后的正文、标识符集合、定义的符号、是否是测试一类。"""

    snap: survey.Snapshot
    sv: survey.Survey
    files: list[str] = field(default_factory=list)
    folded: dict[str, str] = field(default_factory=dict)
    idents: dict[str, set[str]] = field(default_factory=dict)
    lines: dict[str, int] = field(default_factory=dict)

    @classmethod
    def build(cls, snap: survey.Snapshot, sv: survey.Survey) -> Index:
        ix = cls(snap, sv)
        for f in snap.files:
            if f["lang"] not in READABLE or f["lines"] == 0:
                continue
            p = f["path"]
            body = snap.texts[p]
            ix.files.append(p)
            ix.folded[p] = text.fold(body)
            ix.idents[p] = set(_IDENT.findall(body))
            ix.lines[p] = int(f["lines"])
        return ix

    def is_test(self, path: str) -> bool:
        return bool(re.search(r"(^|/)(tests?|__tests__|spec)(/|_)|(^|/)test_[^/]+$|_test\.[a-z]+$", path.lower()))

    def is_doc(self, path: str) -> bool:
        return path.lower().endswith((".md", ".txt", ".rst"))

    def defines(self, path: str) -> set[str]:
        return set(self.sv.symbols.get(path, []))


def _count(hay: str, needle: str) -> int:
    return hay.count(needle) if needle else 0


def search(ix: Index, terms: Sequence[str]) -> dict[str, dict[str, int]]:
    """每个词在每个文件里的命中：路径里、定义的符号里、正文里各记一类。只留有命中的文件。"""
    out: dict[str, dict[str, int]] = {}
    for p in ix.files:
        fp = text.fold(p)
        syms = [text.fold(s) for s in ix.defines(p)]
        row = {"path": 0, "symbol": 0, "text": 0}
        for t in terms:
            if t in fp:
                row["path"] += 1
            row["symbol"] += sum(1 for s in syms if t in s)
            row["text"] += _count(ix.folded[p], t)
        if any(row.values()):
            out[p] = row
    return out


def vocabulary(ix: Index, terms: Sequence[str], limit: int = 240) -> dict[str, list[str]]:
    """对方仓库里含这些词的真实名字（符号、文件、文档标题），按命中多少排，限量。给「挑词」那一步看的就是它。"""
    hits = search(ix, terms)
    ranked = sorted(hits, key=lambda p: (-(hits[p]["path"] * 5 + hits[p]["symbol"] * 3 + min(hits[p]["text"], 20)), p))
    names: dict[str, int] = {}
    for p in ranked[:120]:
        for s in ix.defines(p):
            if any(t in text.fold(s) for t in terms):
                names[s] = names.get(s, 0) + 1
    for hs in ix.sv.headings.values():
        for h in hs:
            if any(t in text.fold(h) for t in terms) and len(h) <= 80:
                names.setdefault(h, 1)
    top = sorted(names, key=lambda n: (-names[n], n))[:limit]
    return {"names": top, "files": ranked[:60]}


def rank(ix: Index, terms: Sequence[str], names: Sequence[str], picked_files: Sequence[str]) -> list[tuple[float, str]]:
    """一个子问的文件排序：挑中的文件最前；其余按挑中的名字是否在这里定义、路径与正文的命中算分；
    测试、示例一类往后放（它们在追读时当规格读）。"""
    fold_names = [text.fold(n) for n in names if n.isascii()]
    words = list(dict.fromkeys([*terms, *fold_names]))
    hits = search(ix, words)
    out: list[tuple[float, str]] = []
    for p, row in hits.items():
        defined = sum(1 for s in ix.defines(p) if s in names)
        s = 6.0 * (p in picked_files) + 3.0 * min(defined, 3) + 2.0 * min(row["path"], 3)
        s += min(3.0, math.log1p(row["text"])) + 1.0 * min(row["symbol"], 3)
        if ix.is_test(p) or survey._noise(p):
            s -= 3.0
        if ix.is_doc(p):
            s -= 1.0
        if s > 0:
            out.append((round(s, 4), p))
    out.sort(key=lambda t: (-t[0], t[1]))
    return out


# ---------------------------------------------------------------- 切分


@dataclass(frozen=True)
class Part:
    """一个文件里连续的一部分：整文件，或大文件在顶层定义处切出来的一段。"""

    sid: str
    path: str
    a: int
    b: int

    def key(self) -> str:
        return f"{self.sid}:{self.path}:{self.a}-{self.b}"


def parts(sid: str, path: str, body: str) -> list[Part]:
    lines = body.splitlines()
    n = len(lines)
    if n <= PART_LINES:
        return [Part(sid, path, 1, max(n, 1))]
    cuts = [i for i, ln in enumerate(lines) if i and _TOP_DEF.match(ln)]
    out: list[Part] = []
    start = 0
    while n - start > PART_LINES:
        lim = start + PART_LINES
        ok = [c for c in cuts if start + PART_MIN <= c <= lim]
        cut = ok[-1] if ok else lim
        out.append(Part(sid, path, start + 1, cut))
        start = cut
    if n - start < PART_MIN and out:
        last = out.pop()
        out.append(Part(sid, path, last.a, n))
    else:
        out.append(Part(sid, path, start + 1, n))
    return out


def numbered(snap: survey.Snapshot, p: Part) -> str:
    """给模型看的原文：每行前面是它在文件里的行号（模型据此交回行区间）。"""
    lines = snap.texts[p.path].splitlines()
    width = len(str(p.b))
    return "\n".join(f"{i:>{width}}| {lines[i - 1]}" for i in range(p.a, min(p.b, len(lines)) + 1))


def raw_range(snap: survey.Snapshot, path: str, a: int, b: int) -> str:
    return "".join(snap.texts[path].splitlines(keepends=True)[a - 1 : b])


def outline(ix: Index, path: str, limit: int = 60) -> list[str]:
    """本文件的定义大纲（名字与所在行），读大文件的某一部分时一并给，免得那一段没头没尾。"""
    rows: list[str] = []
    wanted = ix.defines(path)
    if not wanted:
        return rows
    for i, ln in enumerate(ix.snap.texts[path].splitlines(), 1):
        m = re.match(r"\s*(?:async\s+)?(?:def|class|function)\s+([A-Za-z_]\w*)", ln)
        if m and m.group(1) in wanted:
            rows.append(f"{i}: {m.group(1)}")
            if len(rows) >= limit:
                break
    return rows


def enclosing(snap: survey.Snapshot, path: str, line: int) -> str:
    """某一行所在的定义名（往上找最近的 def / class）；引用旁边标它，方便人对着源码找。确定的，不由模型写。"""
    lines = snap.texts[path].splitlines()
    best = ""
    indent = 10**6
    for i in range(min(line, len(lines)) - 1, -1, -1):
        m = re.match(r"(\s*)(?:async\s+)?(?:def|class|function)\s+([A-Za-z_]\w*)", lines[i])
        if not m:
            continue
        ind = len(m.group(1))
        if ind < indent:
            best = m.group(2) if not best else f"{m.group(2)}.{best}"
            indent = ind
            if ind == 0:
                break
    return best


def follow_ok(name: Any, shown: str) -> bool:
    """模型说值得追的标识符：必须是标识符的形状、在给它看的原文里逐字出现、不是语言关键字。"""
    return (
        isinstance(name, str)
        and bool(_IDENT.fullmatch(name))
        and len(name) <= 80
        and not keyword.iskeyword(name)
        and re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", shown) is not None
    )


# ---------------------------------------------------------------- 排下一批


@dataclass
class Frontier:
    """读到哪了、接下来读什么。全部状态都能从检查点重建：读过的部分、追的标识符、核心文件。"""

    ix: Index
    base: dict[str, float]  # 文件 → 题面检索的分（各子问取最高）
    core: list[str]  # 第一批的文件：整文件读完
    read: set[str] = field(default_factory=set)  # 读过的部分的 key
    follow: dict[str, int] = field(default_factory=dict)  # 标识符 → 被几个部分提名
    tests_read: int = 0

    def _parts(self, path: str) -> list[Part]:
        return parts(self.ix.snap.sid, path, self.ix.snap.texts[path])

    def first(self, n: int) -> list[tuple[Part, str]]:
        out: list[tuple[Part, str]] = []
        for p in self.core:
            for part in self._parts(p):
                if part.key() not in self.read and len(out) < n:
                    out.append((part, "题面命中"))
        return out

    def note(self, part: Part, names: Iterable[str]) -> None:
        self.read.add(part.key())
        if self.ix.is_test(part.path):
            self.tests_read += 1
        for nm in names:
            self.follow[nm] = self.follow.get(nm, 0) + 1

    def score(self, part: Part) -> tuple[float, str]:
        """一个没读过的部分值不值得读、为什么。"""
        ix = self.ix
        path = part.path
        s = 0.5 * self.base.get(path, 0.0)
        why = "题面命中" if s > 0 else ""
        if path in self.core:
            return s + 5.0, "核心文件的后续部分"
        body = "\n".join(ix.snap.texts[path].splitlines()[part.a - 1 : part.b])
        here = set(_IDENT.findall(body))
        defs = [
            n
            for n in self.follow
            if n in ix.defines(path)
            and re.search(rf"(?:def|class|function)\s+{re.escape(n)}\b|^{re.escape(n)}\s*=", body, re.M)
        ]
        uses = [n for n in self.follow if n in here and n not in defs]
        if ix.is_test(path):
            stems = {c.rsplit("/", 1)[-1].rsplit(".", 1)[0] for c in self.core}
            rel = len(uses) + sum(1 for st in stems if st and st in path)
            if rel:
                bonus = 3.0 if self.tests_read < 2 else 0.5
                return s + bonus + min(3, rel), "对应的测试"
            return 0.0, ""
        if defs:
            s += 4.0 + min(2, len(defs) - 1)
            why = "追到的定义"
        if uses:
            s += min(3.0, 1.0 * len(uses))
            why = why or "用到追读的名字"
        if ix.is_doc(path):
            s -= 1.0
        return s, why

    def next(self, n: int, floor: float = 1.5) -> list[tuple[Part, str]]:
        """下一批：所有没读过的部分里分最高的 n 个（低于 floor 的不读）。平分按路径与行号定序。"""
        scored: list[tuple[float, str, int, Part, str]] = []
        for path in self.ix.files:
            if self.base.get(path, 0.0) <= 0 and not (self.ix.idents[path] & set(self.follow)):
                continue
            for part in self._parts(path):
                if part.key() in self.read:
                    continue
                s, why = self.score(part)
                if s >= floor:
                    scored.append((-round(s, 4), path, part.a, part, why))
        scored.sort(key=lambda t: t[:3])
        return [(t[3], t[4]) for t in scored[:n]]

    def left(self, n: int = 15) -> list[dict[str, Any]]:
        """排了队但没读的（交付里的「没读到」）：分最高的前 n 个。"""
        return [{"path": p.path, "lines": [p.a, p.b], "why": why} for p, why in self.next(n)]


def slot_of(sv: survey.Survey, part: Part, prefer: Sequence[str]) -> str:
    """这一部分的观察记在哪个类别下：子问的类别在这一部分有线索分就用它（按子问的先后，分高的先）；
    否则取与它重叠的勘察分段里分最高的类别；都没有分就用第一个子问的类别。"""
    got: dict[str, float] = {}
    for e in sv.excerpts:
        if e.path != part.path or e.lines[1] < part.a or e.lines[0] > part.b:
            continue
        for slot, s in sv.scores[e.key()].items():
            got[slot] = max(got.get(slot, 0.0), float(s))
    asked = [s for s in dict.fromkeys(prefer) if got.get(s, 0.0) > 0]
    if asked:
        return max(asked, key=lambda s: got[s])
    live = sorted((s for s in got if got[s] > 0), key=lambda s: (-got[s], s))
    return live[0] if live else (prefer[0] if prefer else "H1")


def question_slot(q: str, terms: Sequence[str], signatures: Mapping[str, Mapping[str, Any]]) -> str:
    """子问归哪个类别：题面与检索词在各类别词面线索上的命中，最多的那个；都没有命中取 H1。"""
    hay = text.fold(q + " " + " ".join(terms))
    best, top = "H1", 0
    for slot in sorted(signatures):
        n = sum(1 for w in signatures[slot]["lex"] if text.fold(w) in hay)
        if n > top:
            best, top = slot, n
    return best
