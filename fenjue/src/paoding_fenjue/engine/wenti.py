"""按题读的确定性部分（docs/design/fenjue/14-question-led.md §2–§4）：题面拆问、按词检索、切分文件、排下一批。

题目原话在这里第一次进流程。模型只在三处出场，都在 `dati.py`：把问句换成检索词、从对方仓库的真实名字里挑词、
读一段原文。这里全是纯函数：同一份快照、同一组词，排出来的阅读顺序逐字节相同。

- `questions`：题面里有没有点名。有「怎么、如何、怎样」引出的问句才算点名；没有就返回空列表，流程走原路径。
- `search`、`vocabulary`、`overview`、`rank`：检索词在路径、符号、标题、正文里的命中，加一份不靠检索词的目录概览
  （对方仓库自己的叫法不在检索词里时，挑词那一步靠它找到实现所在的目录）→ 每个子问的文件排序。
- `parts`：把一个文件切成整段可读的部分（不超过 PART_LINES 行；过长的在顶层定义处下刀）。
- `Frontier`：排每一批读什么。次序是定死的：要追的名字的定义最先；其余按这一部分自己的命中排；各子问轮流取；
  一个文件读到上限就让位给别的文件。它也数得出「要追的名字里，定义读到了几个」。
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
    _defs_in: dict[str, list[str]] | None = None
    _refs: dict[str, int] | None = None
    _sites: dict[str, list[tuple[str, int]]] = field(default_factory=dict)

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

    def refs(self) -> dict[str, int]:
        """每个标识符在几个文件里出现过（概览里按它挑各目录最常被用到的名字）。"""
        if self._refs is None:
            out: dict[str, int] = {}
            for p in self.files:
                for n in self.idents[p]:
                    out[n] = out.get(n, 0) + 1
            self._refs = out
        return self._refs

    def sites(self, name: str) -> list[tuple[str, int]]:
        """这个名字定义在哪：[(文件, 行)]，只看非测试文件，每个文件取第一处。找不到定义的那一行就不算。"""
        if name in self._sites:
            return self._sites[name]
        if self._defs_in is None:
            inv: dict[str, list[str]] = {}
            for p in self.files:
                if not self.is_test(p):
                    for sym in self.defines(p):
                        inv.setdefault(sym, []).append(p)
            self._defs_in = inv
        pat = re.compile(
            rf"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:def|class|function|const|let|var|type|interface|enum)\s+"
            rf"{re.escape(name)}\b|^{re.escape(name)}\s*[:=]"
        )
        out: list[tuple[str, int]] = []
        for p in sorted(self._defs_in.get(name, [])):
            for i, ln in enumerate(self.snap.texts[p].splitlines(), 1):
                if pat.match(ln):
                    out.append((p, i))
                    break
        self._sites[name] = out
        return out


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


def dir_of(path: str) -> str:
    return path.rsplit("/", 1)[0] + "/" if "/" in path else "./"


def overview(ix: Index, max_dirs: int = 300, per_dir: int = 6) -> list[dict[str, Any]]:
    """对方仓库的目录概览，**不靠检索词**：每个有源码的目录一行——几个文件、多少行、这里定义的名字里最常被别处用到的几个。
    盲出的检索词里没有对方仓库自己的叫法时，名字表里挑不到实现；挑词那一步看这份概览，按目录把它找出来。
    测试、示例、构建产物一类的目录不列。目录太多时留代码行数最多的 max_dirs 个。"""
    refs = ix.refs()
    by: dict[str, dict[str, Any]] = {}
    for p in ix.files:
        if ix.is_test(p) or ix.is_doc(p) or survey._noise(p):
            continue
        row = by.setdefault(dir_of(p), {"files": 0, "lines": 0, "syms": set()})
        row["files"] += 1
        row["lines"] += ix.lines[p]
        row["syms"] |= {s for s in ix.defines(p) if len(s) >= 4 and not s.startswith("_")}
    keep = sorted(by, key=lambda d: (-by[d]["lines"], d))[:max_dirs]
    out: list[dict[str, Any]] = []
    for d in sorted(keep):
        syms = sorted(by[d]["syms"], key=lambda s: (-refs.get(s, 0), not s[:1].isupper(), s))[:per_dir]
        out.append({"dir": d, "files": by[d]["files"], "lines": by[d]["lines"], "names": syms})
    return out


def rank(
    ix: Index,
    terms: Sequence[str],
    names: Sequence[str],
    picked_files: Sequence[str],
    picked_dirs: Sequence[str] = (),
) -> list[tuple[float, str]]:
    """一个子问的文件排序：挑中的文件最前，挑中的目录里的文件其次；其余按挑中的名字是否在这里定义、路径与正文的
    命中算分。正文的命中按文件长度折算（折成每 PART_LINES 行多少次）：大文件不因为行数多就排到前面。
    测试、示例一类往后放（它们在追读时当规格读）。"""
    fold_names = [text.fold(n) for n in names if n.isascii()]
    words = list(dict.fromkeys([*terms, *fold_names]))
    hits = search(ix, words)
    dirs = tuple(picked_dirs)
    pool = set(hits) | {p for p in picked_files if p in ix.folded}
    if dirs:
        pool |= {p for p in ix.files if dir_of(p) in dirs}
    want = set(names)
    out: list[tuple[float, str]] = []
    for p in pool:
        row = hits.get(p, {"path": 0, "symbol": 0, "text": 0})
        defined = len(ix.defines(p) & want)
        s = 6.0 * (p in picked_files) + 4.0 * (dir_of(p) in dirs) + 3.0 * min(defined, 3) + 2.0 * min(row["path"], 3)
        dense = row["text"] * min(1.0, PART_LINES / max(1, ix.lines[p]))
        s += min(3.0, math.log1p(dense)) + 1.0 * min(row["symbol"], 3)
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

AMBIGUOUS = 3  # 一个名字定义在多于这么多个文件里，就不当「追得到的定义」（多半是通用的方法名）
PICK_VOTE, FOLLOW_VOTE = 1, 2  # 读过原文之后说值得追的，比只看名字表挑的更靠前


@dataclass
class Frontier:
    """读到哪了、接下来读什么。全部状态都能从检查点重建：读过的部分、要追的名字（谁为哪个子问提的）。

    一批怎么排（确定的，同样的状态排出同样的一批）：

    1. 每个子问各有一队。队里**要追的名字的定义**（还没读到的）排最前；其余按这一部分自己的分排——文件的题面分、
       这一部分正文里的命中、用到要追的名字。同一个文件每多读一部分，它剩下的部分就降一档。
    2. 各子问轮流从自己的队里取，读得少的子问先取：题面点名的每一问都轮得到。
    3. 一个文件读满 `file_cap` 部分就让位：只有别的都排完了，才回头接着读它，而且每批只多读一部分。
       大文件不会先把额度用完。
    """

    ix: Index
    base: dict[str, float]  # 文件 → 题面检索的分（各子问取最高）
    core: list[str]  # 各子问排在最前的几个文件（找对应的测试时用）
    qbase: dict[str, dict[str, float]] = field(default_factory=dict)  # 子问 → 文件 → 分
    words: dict[str, list[str]] = field(default_factory=dict)  # 子问 → 折叠后的检索词与挑中的名字
    file_cap: int = 3
    read: set[str] = field(default_factory=set)  # 读过的部分的 key
    chase: dict[str, dict[str, int]] = field(default_factory=dict)  # 要追的名字 → 子问 → 票数
    picked: set[str] = field(default_factory=set)  # 挑词那一步挑的名字
    followed: set[str] = field(default_factory=set)  # 读原文时说值得追的名字
    tests_read: int = 0
    per_file: dict[str, int] = field(default_factory=dict)
    per_q: dict[str, int] = field(default_factory=dict)
    _pc: dict[str, list[Part]] = field(default_factory=dict)
    _wc: dict[str, list[Part]] = field(default_factory=dict)
    _lc: dict[str, tuple[dict[str, int], set[str]]] = field(default_factory=dict)

    @property
    def qids(self) -> list[str]:
        return list(self.words) or sorted(self.qbase) or ["Q1"]

    def _parts(self, path: str) -> list[Part]:
        if path not in self._pc:
            self._pc[path] = parts(self.ix.snap.sid, path, self.ix.snap.texts[path])
        return self._pc[path]

    def pick(self, names: Iterable[str], q: str) -> None:
        for nm in names:
            self.picked.add(nm)
            row = self.chase.setdefault(nm, {})
            row[q] = row.get(q, 0) + PICK_VOTE

    def note(self, part: Part, follow: Mapping[str, str], q: str = "") -> None:
        """读完了一部分：`follow` 是它说值得追的名字 → 为哪个子问追；`q` 是这一部分算在哪个子问名下。"""
        self.read.add(part.key())
        self.per_file[part.path] = self.per_file.get(part.path, 0) + 1
        if q:
            self.per_q[q] = self.per_q.get(q, 0) + 1
        if self.ix.is_test(part.path):
            self.tests_read += 1
        for nm, qid in follow.items():
            self.followed.add(nm)
            row = self.chase.setdefault(nm, {})
            row[qid] = row.get(qid, 0) + FOLLOW_VOTE

    def where(self, name: str) -> list[Part]:
        """这个名字的定义落在哪几个部分里。仓库里没有定义、或定义散在太多文件里的，交回空。"""
        if name not in self._wc:
            sites = self.ix.sites(name)
            out: list[Part] = []
            if sites and len(sites) <= AMBIGUOUS:
                for path, line in sites:
                    out += [p for p in self._parts(path) if p.a <= line <= p.b][:1]
            self._wc[name] = out
        return self._wc[name]

    def def_read(self, name: str) -> bool:
        return any(p.key() in self.read for p in self.where(name))

    def _local(self, part: Part) -> tuple[dict[str, int], set[str]]:
        k = part.key()
        if k not in self._lc:
            raw = self.ix.snap.texts[part.path].splitlines()[part.a - 1 : part.b]
            body = text.fold("\n".join(raw))
            hits = {q: sum(_count(body, w) for w in ws) for q, ws in self.words.items()}
            self._lc[k] = (hits, set(_IDENT.findall("\n".join(raw))))
        return self._lc[k]

    def _score(self, part: Part) -> tuple[str, float, str]:
        """一个不含待追定义的部分：算在哪个子问名下、值不值得读、为什么。"""
        ix, path = self.ix, part.path
        hits, here = self._local(part)
        uses = [n for n in self.chase if n in here]
        votes: dict[str, float] = {}
        for q in self.qids:
            v = self.qbase.get(q, {}).get(path, 0.0) + min(3.0, math.log1p(hits.get(q, 0)))
            votes[q] = v + sum(1.0 for n in uses if q in self.chase[n])
        q = max(self.qids, key=lambda x: votes[x])
        s = 0.5 * self.base.get(path, 0.0)
        if ix.is_test(path):
            stems = {c.rsplit("/", 1)[-1].rsplit(".", 1)[0] for c in self.core}
            rel = len(uses) + sum(1 for st in stems if st and st in path)
            if not rel:
                return q, 0.0, ""
            return q, s + (3.0 if self.tests_read < 2 else 0.5) + min(3, rel), "对应的测试"
        why = "题面命中" if s > 0 else ""
        # 这一部分自己的命中，加上它在本文件各部分里的相对密度：大文件里先读命中最密的那几段，不从第一行顺着读
        top = max((self._local(p)[0].get(q, 0) for p in self._parts(path)), default=0)
        s += min(3.0, math.log1p(hits.get(q, 0))) + (4.0 * hits.get(q, 0) / top if top else 0.0)
        if uses:
            s += min(3.0, 1.0 * len(uses))
            why = why or "用到要追的名字"
        seen = self.per_file.get(path, 0)
        if seen:
            s -= 1.5 * seen
            why = "同一个文件的后续部分"
        if ix.is_doc(path):
            s -= 1.0
        return q, s, why

    def _queue(self, floor: float) -> list[tuple[str, int, float, Part, str]]:
        """所有还值得读的部分：(子问, 档, 分, 部分, 为什么)。档 0 是待追的定义，档 1 是其余。"""
        open_defs: dict[str, tuple[Part, list[str]]] = {}
        for name in sorted(self.chase):
            ps = self.where(name)
            if ps and not any(p.key() in self.read for p in ps):
                for p in ps:
                    open_defs.setdefault(p.key(), (p, []))[1].append(name)
        out: list[tuple[str, int, float, Part, str]] = []
        for key in sorted(open_defs):
            part, names = open_defs[key]
            votes: dict[str, int] = {}
            for n in names:
                for q, c in self.chase[n].items():
                    votes[q] = votes.get(q, 0) + c
            q = max(sorted(votes), key=lambda x: votes[x])
            s = 6.0 + 2.0 * min(3, sum(votes.values()) - 1) + 0.5 * self.base.get(part.path, 0.0)
            why = "追到的定义" if any(n in self.followed for n in names) else "挑中的名字的定义"
            out.append((q, 0, s, part, why))
        chased = set(self.chase)
        for path in self.ix.files:
            if self.base.get(path, 0.0) <= 0 and not (self.ix.idents[path] & chased):
                continue
            for part in self._parts(path):
                if part.key() in self.read or part.key() in open_defs:
                    continue
                q, s, why = self._score(part)
                if s >= floor:
                    out.append((q, 1, s, part, why))
        return out

    def next(self, n: int, floor: float = 1.5) -> list[tuple[Part, str, str]]:
        """下一批：[(部分, 为什么, 算在哪个子问名下)]。平分按路径与行号定序。"""

        def order(t: tuple[str, int, float, Part, str]) -> tuple[int, float, str, int]:
            return (t[1], -round(t[2], 4), t[3].path, t[3].a)

        by: dict[str, list[tuple[str, int, float, Part, str]]] = {q: [] for q in self.qids}
        for c in self._queue(floor):
            by.setdefault(c[0], []).append(c)
        for q in by:
            by[q].sort(key=order)
        turn = sorted(by, key=lambda q: (self.per_q.get(q, 0), q))
        at = dict.fromkeys(by, 0)
        taken: dict[str, int] = {}
        out: list[tuple[str, int, float, Part, str]] = []
        held: list[tuple[str, int, float, Part, str]] = []
        moved = True
        while len(out) < n and moved:
            moved = False
            for q in turn:
                if len(out) >= n:
                    break
                while at[q] < len(by[q]):
                    c = by[q][at[q]]
                    at[q] += 1
                    path = c[3].path
                    if self.per_file.get(path, 0) + taken.get(path, 0) >= self.file_cap:
                        held.append(c)  # 这个文件读满了：先让别的
                        continue
                    out.append(c)
                    taken[path] = taken.get(path, 0) + 1
                    moved = True
                    break
        # 别的都排完了，读满了的文件才接着读，而且每批每个文件只多读一部分：大文件一批批慢慢读，不一口气吃掉额度
        for c in sorted(held, key=order):
            if len(out) < n and c[3].path not in taken:
                out.append(c)
                taken[c[3].path] = 1
        return [(c[3], c[4], c[0]) for c in out]

    def left(self, n: int = 15) -> list[dict[str, Any]]:
        """排了队但没读的（交付里的「没读到」）：下一批本来会读的前 n 个。"""
        return [{"path": p.path, "lines": [p.a, p.b], "why": why, "q": q} for p, why, q in self.next(n)]

    def chase_report(self) -> dict[str, dict[str, Any]]:
        """每个子问要追的名字里，定义读到了几个。分两栏：读原文时说值得追的（`followed`）、挑词那一步挑的（`picked`）。
        分母只数仓库里找得到定义的名字（外部库里的、散在太多文件里的不算）；读没读到看那一部分是否真的读过。"""

        def row(names: list[str]) -> dict[str, Any]:
            defined = [n for n in names if self.where(n)]
            got = [n for n in defined if self.def_read(n)]
            return {
                "names": len(names),
                "defined": len(defined),
                "read": len(got),
                "share": round(len(got) / len(defined), 4) if defined else None,
                "unread": [n for n in defined if n not in got][:12],
            }

        out: dict[str, dict[str, Any]] = {}
        for q in self.qids:
            mine = sorted(n for n, v in self.chase.items() if q in v)
            out[q] = {
                "followed": row([n for n in mine if n in self.followed]),
                "picked": row([n for n in mine if n in self.picked]),
            }
        return out


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
