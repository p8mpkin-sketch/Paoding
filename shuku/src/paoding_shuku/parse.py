"""解析（五阶段的第二步）：字节 → 纯文本，按媒体类型或文件名选解析器。

第一期支持文字类：md、txt、源码、html、json、csv、yaml、xml。pdf、docx 在第三期，现在明确拒绝（Unsupported），
不假装解析。解析只依赖标准库，结果确定：同样的字节得到同样的文本。
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

MAX_BYTES = 200 * 1024 * 1024  # 单个文件上限 200 MB

TEXT_EXT = {
    ".md", ".markdown", ".txt", ".rst", ".log", ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".ini", ".xml",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs",
    ".rb", ".php", ".sh", ".sql", ".swift", ".scala", ".lua", ".r", ".m", ".css", ".scss",
}  # fmt: skip
HTML_EXT = {".html", ".htm"}
LATER = {".pdf": "pdf", ".docx": "docx", ".doc": "doc", ".pptx": "pptx", ".xlsx": "xlsx"}


class Unsupported(ValueError):
    """这种格式这一期不支持；消息是给人看的一句话。"""


@dataclass
class Parsed:
    text: str
    kind: str  # markdown | text | code | html | json
    warnings: list[str] = field(default_factory=list)


class _Html(HTMLParser):
    SKIP = {"script", "style", "noscript", "template"}
    BLOCK = {"p", "div", "section", "article", "li", "tr", "br", "pre", "table", "ul", "ol", "header", "footer"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in self.BLOCK:
            self.out.append("\n\n" if tag != "br" else "\n")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif re.fullmatch(r"h[1-6]", tag) or tag in self.BLOCK:
            self.out.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.out.append(data)


def _decode(data: bytes) -> tuple[str, list[str]]:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8"), []
    except UnicodeDecodeError:
        pass
    for enc in ("gb18030", "utf-16"):
        try:
            return data.decode(enc), [f"不是 UTF-8，按 {enc} 读"]
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace"), ["有读不出的字节，已用替换符代替"]


def _ext(name: str) -> str:
    m = re.search(r"(\.[A-Za-z0-9]+)$", name or "")
    return m.group(1).lower() if m else ""


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse(data: bytes, media_type: str = "", name: str = "") -> Parsed:
    if len(data) > MAX_BYTES:
        raise Unsupported(f"单个文件不超过 {MAX_BYTES // (1024 * 1024)} MB")
    ext, mt = _ext(name), (media_type or "").split(";")[0].strip().lower()
    if ext in LATER or mt in ("application/pdf",) or "officedocument" in mt:
        what = LATER.get(ext, "pdf" if mt == "application/pdf" else "Office 文档")
        raise Unsupported(f"{what} 要到资料库第三期才能解析；先转成文字或 md 再导入")
    if b"\x00" in data[:8192] and not mt.startswith("text/"):
        raise Unsupported("看起来是二进制文件，读不出文字")
    text, warn = _decode(data)
    if ext in HTML_EXT or mt == "text/html":
        p = _Html()
        p.feed(text)
        p.close()
        out = html.unescape("".join(p.out))
        out = re.sub(r"[ \t]+", " ", out)
        return Parsed(_tidy(out), "html", warn)
    if ext == ".json" or mt == "application/json":
        try:
            return Parsed(json.dumps(json.loads(text), ensure_ascii=False, indent=2), "json", warn)
        except ValueError:
            return Parsed(_tidy(text), "text", [*warn, "JSON 解析不了，按文字导入"])
    if ext in (".md", ".markdown") or mt == "text/markdown":
        return Parsed(_tidy(text), "markdown", warn)
    if ext in TEXT_EXT and ext not in (".txt", ".rst", ".log", ".csv", ".tsv"):
        return Parsed(text.replace("\r\n", "\n").strip("\n"), "code", warn)
    if ext in TEXT_EXT or mt.startswith("text/") or not ext:
        return Parsed(_tidy(text), "text", warn)
    raise Unsupported(f"不认识的文件类型 {ext}；文字类文件请用 .txt 或 .md")
