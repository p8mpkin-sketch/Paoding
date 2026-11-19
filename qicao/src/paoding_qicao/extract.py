"""前置抽取（设计 docs/design/kaiti §2 第①层）：确定性，不调模型。

人贴的原文 → 剪去答案的原文 + 区间表。区间是起草模型唯一能"指"的东西：
授权地址、时限、金额、检查命令、交付文件，值都来自这里，模型写不出原文里没有的值。

- 答案：以登记的标签（数据，见 kaiti.d/intake.yaml）开头的那一段，整段剪出；剪出的答案不进区间表，
  起草模型看不到。标签后跟冒号（`答案：X`、`Answer: X`）时取到行尾；跟"是/为"（`答案是X`）时取到
  中文句读或行尾，答案是疑问（`答案是什么？`）的不算。答案末尾的中文句号不算答案。
- 按 #91 抽取器降为展示：只有答案行仍决定练习道资格与保密库；金额与时长抽到才作预算缺省；
  地址、网址、域名只供确认卡高亮与对原文段号。
- 偏移是剪过答案之后的文本里的 Unicode 码位下标（Python 字符串下标）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

KINDS = ("code", "url", "addr", "host", "money", "duration", "file", "sentence")


@dataclass(frozen=True)
class Span:
    id: str
    start: int
    end: int
    kind: str
    text: str
    # addr/url → "host:port"；host（没写端口的域名，纯展示）→ 主机名；duration → 秒；money → 毫美元；
    # code → 代码正文；file → 文件名；sentence → 文本
    value: Any


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


_BOUND = r"(?:^|(?<=[\s。；;，,.!?！？]))"
_ASK = re.compile(r"[?？]\s*$|什么|多少|哪|几|啥|怎么|如何|吗|否")


def _answer_re(labels: list[str]) -> re.Pattern[str]:
    alt = "|".join(re.escape(x) for x in sorted(labels, key=len, reverse=True))
    # 标签在行首，或跟在句读之后。两种连接：冒号（全角半角）→ 取到行尾；"是/为"（可再跟冒号）→ 取到中文句读
    return re.compile(
        rf"{_BOUND}(?:{alt})"
        r"(?:\s*[:：]\s*(?P<ans>[^\n]*)"
        r"|\s*(?:是|为)\s*[:：]?\s*(?P<ans2>[^\n。；，！？]*)[。；，！？]?)",
        re.IGNORECASE | re.MULTILINE,
    )


def _answer_of(m: re.Match[str]) -> str | None:
    if m.group("ans") is not None:
        return m.group("ans").strip().rstrip("。").strip()
    a = m.group("ans2").strip()
    return None if not a or _ASK.search(a) else a


def cut_answers(raw: str, labels: list[str]) -> tuple[str, list[str]]:
    if not labels:
        return raw, []
    pat = _answer_re(labels)
    answers: list[str] = []

    def cut(m: re.Match[str]) -> str:
        a = _answer_of(m)
        if a is None:  # "答案是什么？"这类疑问不是答案行，原样留在题面
            return m.group(0)
        if a:
            answers.append(a)
        return ""

    text = pat.sub(cut, raw)
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
    + r"\s*个?\s*(?P<half>半)?\s*"  # "一个半小时"：个之后的半加在数上
    + r"(?P<u>秒钟|分钟|小时|钟头|秒|天|seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|hr|h|s|d)(?![A-Za-z])",
    re.IGNORECASE,
)
_MONEY = re.compile(
    r"(?:\$\s?(?P<a>\d+(?:\.\d+)?))"
    r"|(?:(?P<b>\d+(?:\.\d+)?)\s*(?:美元|美金|刀|usd)(?![A-Za-z]))"
    r"|(?:(?P<c>\d+(?:\.\d+)?)\s*(?:元|块钱|人民币|rmb|cny)(?![A-Za-z组素件次]))",
    re.IGNORECASE,
)
_HOST = r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?"
# 边界只看 ASCII：中文字紧贴着地址（"连接到q1:8080"、"q1:8080里"）照样认
_EDGE = r"(?<![A-Za-z0-9_./:@-])"
_AFTER = r"(?![A-Za-z0-9_])"
_PATH = r"(?:/[^\s，。；、：！？（）()\[\]「」『』【】〔〕《》〈〉\"'<>]*)?"
_URL = re.compile(
    rf"(?<![A-Za-z0-9_])(?P<scheme>https?)://(?P<host>{_HOST})(?::(?P<port>\d{{1,5}}))?(?:[/?#][^\s，。；、！？（）()\[\]「」『』【】〔〕《》〈〉\"'<>]*)?"
)
_ADDR = re.compile(rf"{_EDGE}(?P<host>{_HOST}):(?P<port>\d{{1,5}}){_AFTER}{_PATH}")
# 指令前导词后跟"主机 端口"（`nc q1 31337`、`telnet 10.0.0.5 23`），中间可夹短选项
_LEAD = re.compile(
    rf"(?<![A-Za-z0-9_-])(?:nc|ncat|netcat|telnet)(?:\s+-[A-Za-z]+)*\s+(?P<host>{_HOST})\s+(?P<port>\d{{1,5}})(?![A-Za-z0-9_.:])"
)
# 没写协议也没写端口的域名，可带路径；顶级域查表（数据，见 kaiti.d/intake.yaml），免得把 main.py 当域名
_BARE = re.compile(
    rf"{_EDGE}(?P<host>(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+(?P<tld>[A-Za-z]{{2,}}))"
    rf"(?![A-Za-z0-9_-]|\.[A-Za-z0-9]|:\d){_PATH}"
)
_TRAIL = ".,;:!?"
_FENCE = re.compile(r"```[^\n]*\n(?P<c>.*?)```", re.DOTALL)
_INLINE = re.compile(r"`(?P<c>[^`\n]+)`")
_FILE = re.compile(r"(?<![\w/.:-])(?P<f>[\w-]+(?:/[\w.-]+)*\.[A-Za-z][A-Za-z0-9]{0,5})(?![\w])")
_SENT = re.compile(r"[^。！？!?\n]+[。！？!?]?")


def _valid_host(h: str) -> bool:
    return bool(re.search(r"[A-Za-z]", h)) or bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", h))


DEFAULT_RATES = {"usd": 1.0}
DEFAULT_TLDS = ("com", "net", "org", "io", "dev", "app", "cn", "example", "test", "local", "internal")


def extract(
    raw: str,
    labels: list[str],
    url_ports: dict[str, int] | None = None,
    *,
    money_rates: dict[str, float] | None = None,
    host_tlds: list[str] | tuple[str, ...] | None = None,
) -> Extraction:
    """money_rates：每单位折多少美元（usd 恒为 1；cny 缺席时"N元"不当金额）；host_tlds：认作域名的顶级域。"""
    url_ports = url_ports or {"http": 80, "https": 443}
    rates = {"usd": 1.0, **(money_rates or DEFAULT_RATES)}
    tlds = {t.lower() for t in (host_tlds if host_tlds is not None else DEFAULT_TLDS)}
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

    def tail(a: int, b: int) -> int:  # 网址末尾的英文标点算句读，不算网址
        while b > a and text[b - 1] in _TRAIL:
            b -= 1
        return b

    for m in _FENCE.finditer(text):
        take(m.start(), m.end(), "code", m.group("c").rstrip("\n"))
    for m in _LEAD.finditer(text):  # 先于行内代码：`nc q1 31337` 是地址，不是检查命令
        lp = int(m.group("port"))
        if 0 < lp < 65536 and _valid_host(m.group("host")):
            take(m.start(), m.end(), "addr", f"{m.group('host')}:{lp}")
    for m in _INLINE.finditer(text):
        take(m.start(), m.end(), "code", m.group("c"))
    for m in _URL.finditer(text):
        port = m.group("port")
        p = int(port) if port else url_ports.get(m.group("scheme").lower())
        if p and 0 < p < 65536:
            take(m.start(), tail(m.start(), m.end()), "url", f"{m.group('host')}:{p}")
    for m in _ADDR.finditer(text):
        p = int(m.group("port"))
        if 0 < p < 65536 and _valid_host(m.group("host")):
            take(m.start(), tail(m.start(), m.end()), "addr", f"{m.group('host')}:{p}")
    for m in _BARE.finditer(text):
        if m.group("tld").lower() in tlds:
            take(m.start(), tail(m.start(), m.end()), "host", m.group("host"))
    for m in _MONEY.finditer(text):
        if m.group("c") is not None:
            if "cny" not in rates:
                continue
            usd = float(m.group("c")) * rates["cny"]
        else:
            usd = float(m.group("a") or m.group("b"))
        take(m.start(), m.end(), "money", int(round(usd * 1000)))
    for m in _DUR.finditer(text):
        n = cn_number(m.group("n"))
        unit = _UNIT_S.get(m.group("u").lower())
        if n is not None and m.group("half"):
            n = None if m.group("n").endswith("半") else n + 0.5
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
