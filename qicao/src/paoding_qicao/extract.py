"""前置抽取（设计 docs/design/kaiti §2 第①层）：确定性，不调模型。

人贴的原文 → 剪去答案的原文 + 区间表。区间是起草模型唯一能"指"的东西：
授权地址、时限、金额、检查命令、交付文件，值都来自这里，模型写不出原文里没有的值。

- 答案：以登记的标签（数据，见 kaiti.d/intake.yaml）开头的那一段，到行尾为止，整段剪出；
  剪出的答案不进区间表，起草模型看不到。
- 偏移是剪过答案之后的文本里的 Unicode 码位下标（Python 字符串下标）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

KINDS = ("code", "url", "addr", "money", "duration", "file", "sentence")


@dataclass(frozen=True)
class Span:
    id: str
    start: int
    end: int
    kind: str
    text: str
    value: Any  # addr/url → "host:port"；duration → 秒；money → 毫美元；code → 代码正文；file → 文件名；sentence → 文本


@dataclass(frozen=True)
class Extraction:
    raw_len: int
    text: str  # 剪去答案之后的原文：就是题面
    answers: tuple[str, ...]  # 标签行剪出的答案（可能多个，多个时校验层拒绝）
    spans: tuple[Span, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def span(self, sid: str) -> Span | None:
        return next((s for s in self.spans if s.id == sid), None)

    def of(self, kind: str) -> list[Span]:
        return [s for s in self.spans if s.kind == kind]


# ---------- 答案 ----------


def _answer_re(labels: list[str]) -> re.Pattern[str]:
    alt = "|".join(re.escape(x) for x in sorted(labels, key=len, reverse=True))
    # 标签在行首，或跟在句读之后；冒号全角半角都认；答案取到行尾
    return re.compile(
        rf"(?:^|(?<=[\s。；;，,.!?！？]))(?:{alt})\s*[:：]\s*(?P<ans>[^\n]*)", re.IGNORECASE | re.MULTILINE
    )


def cut_answers(raw: str, labels: list[str]) -> tuple[str, list[str]]:
    if not labels:
        return raw, []
    pat = _answer_re(labels)
    answers = [m.group("ans").strip() for m in pat.finditer(raw) if m.group("ans").strip()]
    text = pat.sub("", raw)
    text = re.sub(r"[ \t]+\n", "\n", text).rstrip()
    return text, answers


# ---------- 数值 ----------

_CN = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn_number(s: str) -> float | None:
    """阿拉伯数字，或一到九十九的中文数字，或"半"。"""
    s = s.strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return float(s)
    if s == "半":
        return 0.5
    if s.endswith("半") and len(s) > 1:
        head = cn_number(s[:-1])
        return None if head is None else head + 0.5
    if "十" in s:
        a, _, b = s.partition("十")
        if (a and a not in _CN) or (b and b not in _CN):
            return None
        return float((_CN[a] if a else 1) * 10 + (_CN[b] if b else 0))
    if len(s) == 1 and s in _CN:
        return float(_CN[s])
    return None


_UNIT_S = {
    "秒": 1, "秒钟": 1, "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "分钟": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "小时": 3600, "钟头": 3600, "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "天": 86400, "d": 86400, "day": 86400, "days": 86400,
}  # fmt: skip
_NUM = r"(?<![A-Za-z0-9_.])(?P<n>\d+(?:\.\d+)?|[零一二两三四五六七八九十]{1,3}半?|半)"
_DUR = re.compile(
    _NUM
    + r"\s*个?\s*(?P<u>秒钟|分钟|小时|钟头|秒|天|seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|hr|h|s|d)(?![A-Za-z])",
    re.IGNORECASE,
)
_MONEY = re.compile(
    r"(?:\$\s?(?P<a>\d+(?:\.\d+)?))|(?:(?P<b>\d+(?:\.\d+)?)\s*(?:美元|美金|刀|usd)(?![A-Za-z]))", re.IGNORECASE
)
_URL = re.compile(
    r"\b(?P<scheme>https?)://(?P<host>[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)(?::(?P<port>\d{1,5}))?[^\s，。；、）)\]]*"
)
_ADDR = re.compile(r"(?<![\w./:@-])(?P<host>[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?):(?P<port>\d{1,5})(?![\w])")
_FENCE = re.compile(r"```[^\n]*\n(?P<c>.*?)```", re.DOTALL)
_INLINE = re.compile(r"`(?P<c>[^`\n]+)`")
_FILE = re.compile(r"(?<![\w/.:-])(?P<f>[\w-]+(?:/[\w.-]+)*\.[A-Za-z][A-Za-z0-9]{0,5})(?![\w])")
_SENT = re.compile(r"[^。！？!?\n]+[。！？!?]?")


def _valid_host(h: str) -> bool:
    return bool(re.search(r"[A-Za-z]", h)) or bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", h))


def extract(raw: str, labels: list[str], url_ports: dict[str, int] | None = None) -> Extraction:
    url_ports = url_ports or {"http": 80, "https": 443}
    text, answers = cut_answers(raw, labels)
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, int, str, str, Any]] = []
    notes: list[str] = []

    def free(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in taken)

    def take(a: int, b: int, kind: str, value: Any) -> None:
        if free(a, b):
            taken.append((a, b))
            found.append((a, b, kind, text[a:b], value))

    for m in _FENCE.finditer(text):
        take(m.start(), m.end(), "code", m.group("c").rstrip("\n"))
    for m in _INLINE.finditer(text):
        take(m.start(), m.end(), "code", m.group("c"))
    for m in _URL.finditer(text):
        port = m.group("port")
        p = int(port) if port else url_ports.get(m.group("scheme").lower())
        if p and 0 < p < 65536:
            take(m.start(), m.end(), "url", f"{m.group('host')}:{p}")
    for m in _ADDR.finditer(text):
        p = int(m.group("port"))
        if 0 < p < 65536 and _valid_host(m.group("host")):
            take(m.start(), m.end(), "addr", f"{m.group('host')}:{p}")
    for m in _MONEY.finditer(text):
        amount = float(m.group("a") or m.group("b"))
        take(m.start(), m.end(), "money", int(round(amount * 1000)))
    for m in _DUR.finditer(text):
        n = cn_number(m.group("n"))
        unit = _UNIT_S.get(m.group("u").lower())
        if n is not None and unit is not None and n > 0:
            take(m.start(), m.end(), "duration", int(round(n * unit)))
    for m in _FILE.finditer(text):
        take(m.start("f"), m.end("f"), "file", m.group("f"))

    found.sort(key=lambda t: (t[0], t[1]))
    spans = [Span(f"s{i + 1}", a, b, k, t, v) for i, (a, b, k, t, v) in enumerate(found)]
    n = len(spans)
    for m in _SENT.finditer(text):
        s = m.group(0).strip()
        if s:
            a = m.start() + (len(m.group(0)) - len(m.group(0).lstrip()))
            n += 1
            spans.append(Span(f"s{n}", a, a + len(s), "sentence", s, s))
    if len(answers) > 1:
        notes.append("multiple_answers")
    return Extraction(len(raw), text, tuple(answers), tuple(spans), tuple(notes))


def norm(s: str) -> str:
    """外泄比较用：去掉全部空白，大小写折叠。"""
    return re.sub(r"\s+", "", s).casefold()
