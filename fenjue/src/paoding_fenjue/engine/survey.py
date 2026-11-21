"""摄入与勘察（docs/design/fenjue/08-algorithms.md §3.1–§3.4，09 §2.3 的 `intake`、`probe`）：确定性，零 token。

快照是一份定版的材料目录（上传的归档解开后的样子）。四种形态在目录里的约定：

- 代码 `code`、文档 `docs`：目录里就是文件；
- 行为 `service`：`plan.json`（cz 批准过的探测计划）与 `responses.json`（每条的响应）；
- 描述 `description`：`statement.txt`（cz 的原话）。

同一份快照重跑，勘察单逐字节相同：一切按路径排序，sha256 记原文，原文本身不进勘察单之外的任何产物。
本模块不发请求：地址类来源（仓库、服务、文档地址）要经扩权卡抓取，那是工具面（E3）的事，这里只认已经定版的目录。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..shapes import digest
from . import data, text

EXCLUDED_DIRS = {"vendor", "node_modules", "dist", "build", ".git", "__pycache__"}
LANGS = {".py": "python", ".js": "javascript", ".ts": "typescript", ".md": "markdown", ".toml": "toml", ".json": "json"}
LANGS |= {".yaml": "yaml", ".yml": "yaml", ".txt": "text", ".cfg": "ini", ".ini": "ini", ".sh": "shell"}
EXCERPT_LINES = 60  # 一段的行数上限（≤ 4k token 的近似）〔占位〕
READ_BUDGET = {"S": 30, "M": 60, "L": 90, "XL": 120}  # 读预算（段）〔占位，取自预算先验〕
THETA = 0.2  # 信号太弱的门槛〔占位〕
WEIGHTS = {"lex": 0.35, "struct": 0.25, "central": 0.15, "doc": 0.20, "noise": 0.30}  # α β γ δ ε〔占位〕

_LICENSES = (  # (必须都出现的短语, spdx, status)
    (("apache license", "version 2.0"), "Apache-2.0", "permissive"),
    (("mit license",), "MIT", "permissive"),
    (("bsd", "redistribution and use"), "BSD-3-Clause", "permissive"),
    (("gnu lesser general public license",), "LGPL-3.0-only", "weak_copyleft"),
    (("mozilla public license",), "MPL-2.0", "weak_copyleft"),
    (("gnu affero general public license",), "AGPL-3.0-only", "strong_copyleft"),
    (("gnu general public license", "version 3"), "GPL-3.0-only", "strong_copyleft"),
    (("gnu general public license", "version 2"), "GPL-2.0-only", "strong_copyleft"),
)
_SPDX_STATUS = {spdx: status for _, spdx, status in _LICENSES}


class Refused(ValueError):
    """立项来源命中拒收表：当场拒收，不发任何请求。"""


# ---------------------------------------------------------------- 摄入


def refusal(source: Mapping[str, Any], material: str | None = None) -> str | None:
    """来源（及其材料路径）命中拒收表就返回理由。表是数据：本机题库或校准目录一类。"""
    t = data.table("refusals")
    blobs = [str(v) for v in source.values() if isinstance(v, str)]
    if material:
        blobs.append(material)
    for b in blobs:
        f = text.fold(b).replace("\\", "/")
        if any(text.fold(p) in f for p in t["path_prefixes"]):
            return str(t["why"])
        parts = re.split(r"[/:?#=&]+", f)
        for part in parts:
            words = set(re.split(r"[^a-z0-9-]+", part)) | set(re.split(r"[^a-z0-9]+", part))
            if any(n in words or n == part for n in t["name_parts"]):
                return str(t["why"])
    return None


def scope_allowed(intake: Mapping[str, Any], target: str) -> bool:
    """D4：扩权申请的目标必须是立项登记过的来源（地址完全相同，或以它为前缀）。"""
    urls = [s["url"] for s in intake.get("sources", []) if s.get("url")]
    return any(target == u or target.startswith(u.rstrip("/") + "/") for u in urls)


# ---------------------------------------------------------------- 快照与勘察


@dataclass(frozen=True)
class Excerpt:
    """一段原文的位置：快照、路径（或探测条目）、行区间、原文 sha256。原文按需从快照取，不进产物。"""

    snapshot: str
    path: str
    lines: tuple[int, int]
    sha256: str
    probe_item: int | None = None

    def ref(self) -> dict[str, Any]:
        r: dict[str, Any] = {"snapshot": self.snapshot, "sha256": self.sha256}
        if self.probe_item is not None:
            r["probe_item"] = self.probe_item
        else:
            r["path"] = self.path
            r["lines"] = list(self.lines)
        return r

    def key(self) -> str:
        if self.probe_item is not None:
            return f"{self.snapshot}:probe{self.probe_item}"
        return f"{self.snapshot}:{self.path}:{self.lines[0]}-{self.lines[1]}"


@dataclass
class Snapshot:
    sid: str
    form: str
    root: Path
    files: list[dict[str, Any]] = field(default_factory=list)
    texts: dict[str, str] = field(default_factory=dict)

    def excerpt_text(self, e: Excerpt) -> str:
        if e.probe_item is not None:
            return self.texts[f"probe{e.probe_item}"]
        lines = self.texts[e.path].splitlines(keepends=True)
        return "".join(lines[e.lines[0] - 1 : e.lines[1]])


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _lang(p: Path) -> str:
    if p.name.upper().startswith(("LICENSE", "COPYING")):
        return "license"
    return LANGS.get(p.suffix.lower(), "other")


def load_snapshot(sid: str, form: str, root: Path) -> Snapshot:
    """把定版的材料目录读成快照（只读文件，不执行）。"""
    snap = Snapshot(sid, form, root)
    if form == "service":
        plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
        responses = json.loads((root / "responses.json").read_text(encoding="utf-8"))
        by_item = {r["item"]: r for r in responses["responses"]}
        for item in plan["items"]:
            body = json.dumps(
                {"request": item, "response": by_item.get(item["no"])}, ensure_ascii=False, sort_keys=True, indent=1
            )
            snap.texts[f"probe{item['no']}"] = body
    paths = [p for p in sorted(root.rglob("*")) if p.is_file() and not (EXCLUDED_DIRS & set(p.relative_to(root).parts))]
    for p in paths:
        rel = p.relative_to(root).as_posix()
        raw = p.read_bytes()
        body = raw.decode("utf-8", errors="replace")
        snap.texts[rel] = body
        snap.files.append(
            {"path": rel, "size": len(raw), "lang": _lang(p), "lines": len(body.splitlines()), "sha256": _sha(raw)}
        )
    return snap


def identity(snap: Snapshot) -> dict[str, str]:
    if snap.form == "service":
        return {"probe_plan_sha256": _sha((snap.root / "plan.json").read_bytes())}
    if snap.form == "description":
        return {"text_sha256": _sha((snap.root / "statement.txt").read_bytes())}
    return {"archive_sha256": digest([{"path": f["path"], "sha256": f["sha256"]} for f in snap.files])}


def size_tier(lines: int) -> str:
    return "S" if lines < 10_000 else "M" if lines < 200_000 else "L" if lines < 2_000_000 else "XL"


def detect_license(snap: Snapshot) -> dict[str, Any]:
    """LICENSE*、COPYING*、包清单的 license 字段、文件头的 SPDX 标识；描述形态是 cz 的话。"""
    if snap.form == "description":
        return {"status": "cz_description", "detected": "立项原话"}
    for f in snap.files:
        if f["lang"] == "license":
            body = text.fold(snap.texts[f["path"]])
            for needles, spdx, status in _LICENSES:
                if all(n in body for n in needles):
                    return _license(status, spdx, f["path"])
            return {"status": "unknown", "detected": f["path"], "reuse": "idea_only"}
    for f in snap.files:
        m = re.search(r"SPDX-License-Identifier:\s*([A-Za-z0-9.+-]+)", snap.texts[f["path"]])
        if m:
            spdx = m.group(1)
            return _license(_SPDX_STATUS.get(spdx, "unknown"), spdx, f"{f['path']}（SPDX）")
    return {"status": "none_found", "detected": "没找到许可证文件（视为保留所有权利）", "reuse": "idea_only"}


def _license(status: str, spdx: str, detected: str) -> dict[str, Any]:
    reuse = "may_consult_code" if status == "permissive" else "idea_only"
    return {"status": status, "spdx": spdx, "detected": detected, "reuse": reuse}


_PY_SYMBOL = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)", re.MULTILINE)
_JS_SYMBOL = re.compile(r"(?:function\s+([A-Za-z_]\w*)|(?:const|let|class)\s+([A-Za-z_]\w*))")
_PY_IMPORT = re.compile(r"^\s*(?:from\s+\.?([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE)
_CONST = re.compile(r"^([A-Z][A-Z0-9_]{3,})\s*=", re.MULTILINE)
_CONFIG_KEY = re.compile(r"^\s*([A-Za-z_][\w.-]*)\s*[=:]", re.MULTILINE)
_HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_CLI = re.compile(r"^\s*(?:\$\s+)?([a-z][a-z0-9-]{3,})\s+(?:run|start|init|--)", re.MULTILINE)


@dataclass
class Survey:
    """勘察单：一切引用的底。`body()` 是登记成 exec 类 Artifact 的那份。"""

    snapshot: dict[str, Any]
    files: list[dict[str, Any]]
    symbols: dict[str, list[str]]
    imports: dict[str, list[str]]
    headings: dict[str, list[str]]
    config_keys: list[str]
    names: list[str]
    injection: dict[str, list[str]]
    excerpts: list[Excerpt]
    scores: dict[str, dict[str, float]]

    def body(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot,
            "files": self.files,
            "symbols": self.symbols,
            "imports": self.imports,
            "headings": self.headings,
            "config_keys": self.config_keys,
            "names": self.names,
            "injection": self.injection,
            "excerpts": [e.ref() for e in self.excerpts],
            "scores": self.scores,
        }

    def find(self, key: str) -> Excerpt:
        for e in self.excerpts:
            if e.key() == key:
                return e
        raise KeyError(key)


def _excerpts(snap: Snapshot) -> list[Excerpt]:
    out: list[Excerpt] = []
    if snap.form == "service":
        for k in sorted(k for k in snap.texts if k.startswith("probe")):
            no = int(k[5:])
            out.append(Excerpt(snap.sid, k, (1, 1), _sha(snap.texts[k].encode()), probe_item=no))
        return sorted(out, key=lambda e: e.probe_item or 0)
    for f in snap.files:
        if f["lang"] in ("license", "other") or f["lines"] == 0:
            continue
        lines = snap.texts[f["path"]].splitlines(keepends=True)
        for a in range(0, len(lines), EXCERPT_LINES):
            b = min(len(lines), a + EXCERPT_LINES)
            chunk = "".join(lines[a:b])
            out.append(Excerpt(snap.sid, f["path"], (a + 1, b), _sha(chunk.encode())))
    return out


def _module(path: str) -> str:
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else path


def _noise(path: str) -> float:
    p = path.lower()
    return 1.0 if re.search(r"(^|/)(tests?|examples?|fixtures?|migrations?)(/|_)", p) or "generated" in p else 0.0


def probe(snap: Snapshot) -> Survey:
    """勘察：文件清单、符号、引用图、文档标题、配置键、外部专名表、注入探测、分段与按火位打分。"""
    symbols: dict[str, list[str]] = {}
    imports: dict[str, list[str]] = {}
    headings: dict[str, list[str]] = {}
    config: set[str] = set()
    idents: set[str] = set()
    injection: dict[str, list[str]] = {}
    for key in sorted(snap.texts):
        body = snap.texts[key]
        lang = next((f["lang"] for f in snap.files if f["path"] == key), "probe")
        if lang == "python":
            symbols[key] = sorted(set(_PY_SYMBOL.findall(body)) | set(_CONST.findall(body)))
            imports[key] = sorted({a or b for a, b in _PY_IMPORT.findall(body)})
        elif lang in ("javascript", "typescript"):
            symbols[key] = sorted({a or b for a, b in _JS_SYMBOL.findall(body)})
        elif lang in ("toml", "yaml", "ini"):
            config.update(_CONFIG_KEY.findall(body))
        elif lang == "markdown":
            headings[key] = [h.strip() for h in _HEADING.findall(body)]
            idents.update(_CLI.findall(body))
        hits = text.injection_hits(body)
        if hits:
            injection[key] = hits
    for key, syms in symbols.items():
        idents.update(syms)
        stem = key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        idents.add(stem)
        idents.update(p for p in key.split("/")[:-1])
    for mods in imports.values():
        idents.update(m.split(".")[0] for m in mods)
    for hs in headings.values():
        for h in hs:
            idents.update(re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", h))
    idents.update(config)
    if snap.form != "description":
        idents.add(snap.root.name)
    names = text.name_table(sorted(idents))

    excerpts = _excerpts(snap)
    # 引用图的扇入（按模块）：被别的文件 import 的次数，归一
    fan_in: dict[str, int] = {}
    stems = {f["path"].rsplit("/", 1)[-1].rsplit(".", 1)[0]: f["path"] for f in snap.files}
    for src, mods in imports.items():
        for m in mods:
            tgt = stems.get(m.split(".")[-1])
            if tgt and tgt != src:
                fan_in[_module(tgt)] = fan_in.get(_module(tgt), 0) + 1
    top = max(fan_in.values(), default=0)
    doc_text = text.fold(" ".join(snap.texts[k] for k in headings))
    scores: dict[str, dict[str, float]] = {}
    for e in excerpts:
        body = text.fold(snap.excerpt_text(e))
        row: dict[str, float] = {}
        for slot, sig in data.signatures().items():
            lex = min(1.0, sum(body.count(text.fold(w)) for w in sig["lex"]) / 5)
            struct = min(1.0, sum(body.count(text.fold(w)) for w in sig["struct"]) / 2)
            central = fan_in.get(_module(e.path), 0) / top if top else 0.0
            mod = text.fold(_module(e.path).rsplit(".", 1)[0])
            doc = 1.0 if e.path not in headings and mod in doc_text and lex > 0 else 0.0
            if e.path in headings:
                doc = min(1.0, lex * 2)
            s = (
                WEIGHTS["lex"] * lex
                + WEIGHTS["struct"] * struct
                + WEIGHTS["central"] * central
                + WEIGHTS["doc"] * doc
                - WEIGHTS["noise"] * _noise(e.path)
            )
            row[slot] = round(s, 4)
        scores[e.key()] = row
    return Survey(
        snapshot={},
        files=snap.files,
        symbols=symbols,
        imports=imports,
        headings=headings,
        config_keys=sorted(config),
        names=names,
        injection=injection,
        excerpts=excerpts,
        scores=scores,
    )


def flagged(snap: Snapshot, e: Excerpt) -> list[str]:
    """这一段原文的注入探测命中（D6）。"""
    return text.injection_hits(snap.excerpt_text(e))
