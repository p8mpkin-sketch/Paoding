"""闸点决定块的解析（docs/design/fenjue/09-engine.md §2.4）：cz 追问正文里的一段，确定性解析，解析不了的行不猜。

```
【决定 v1】闸点 1
选：C1，C3
排除：C2（已在地图待办里，不必走吞噬）
改：C1.title = 阶段证据确认
备注：C3 先看压缩，不看接力
```

行首关键字、候选编号、`编号.栏 = 值`。解析不了的行进 `unparsed`，引擎把它们列进下一次交付的 `needs`。
"""

from __future__ import annotations

import re
from typing import Any

_HEAD = re.compile(r"【决定\s*v1】\s*闸点\s*([123])")
_CAND = re.compile(r"^C[0-9]+$")
_SEP = re.compile(r"[，,、\s]+")
_WITH_WHY = re.compile(r"^(C[0-9]+)\s*(?:[（(](.*)[）)])?$")
_EDIT = re.compile(r"^(C[0-9]+(?:\.[A-Za-z_][\w]*|\.[0-9]+)+)\s*=\s*(.+)$")
_NONE = {"无", "没有", "none", "-", "—"}

_KEYS = {
    "G1": {"选": "pick", "排除": "exclude", "改": "edit", "备注": "note", "重做识火": "redo"},
    "G2": {"确认": "confirm", "改": "edit", "退回": "back", "放弃": "drop", "备注": "note"},
    "G3": {
        "交实现线": "to_implementation",
        "搁置": "hold",
        "排除": "exclude",
        "存入资料库": "library_import",
        "退回": "back",
        "备注": "note",
    },
}


class NoBlock(ValueError):
    """正文里没有决定块。"""


def _ids(value: str) -> list[str] | None:
    if value.strip() in _NONE:
        return []
    ids = [x for x in _SEP.split(value.strip()) if x]
    return ids if ids and all(_CAND.match(x) for x in ids) else None


def _with_why(value: str) -> list[dict[str, str]] | None:
    if value.strip() in _NONE:
        return []
    out = []
    for part in re.split(r"[；;]|(?<=[）)])\s*[，,、]\s*", value.strip()):
        part = part.strip().strip("，,、")
        if not part:
            continue
        m = _WITH_WHY.match(part)
        if not m:
            return None
        row = {"candidate": m.group(1)}
        if m.group(2):
            row["why"] = m.group(2).strip()
        out.append(row)
    return out


def parse(body: str) -> dict[str, Any]:
    """追问正文 → 决定（decision.schema.json 的形状）。"""
    lines = body.splitlines()
    start = next((i for i, ln in enumerate(lines) if _HEAD.search(ln)), None)
    if start is None:
        raise NoBlock("正文里没有【决定 v1】闸点 N 这一行")
    m = _HEAD.search(lines[start])
    assert m is not None
    gate = f"G{m.group(1)}"
    keys = _KEYS[gate]
    out: dict[str, Any] = {"v": 1, "gate": gate}
    unparsed: list[str] = []
    for raw in lines[start + 1 :]:
        line = raw.strip()
        if not line:
            continue
        if _HEAD.search(line):
            break
        parts = re.split(r"[：:]", line, maxsplit=1)
        if len(parts) != 2 or parts[0].strip() not in keys:
            unparsed.append(line)
            continue
        if not _apply(out, keys[parts[0].strip()], parts[1].strip()):
            unparsed.append(line)
    if unparsed:
        out["unparsed"] = unparsed
    return out


def _apply(out: dict[str, Any], field: str, value: str) -> bool:
    if field in ("pick", "confirm", "drop", "to_implementation"):
        ids = _ids(value)
        if ids is None:
            return False
        out.setdefault(field, []).extend(ids)
        return True
    if field in ("exclude", "hold"):
        rows = _with_why(value)
        if rows is None:
            return False
        if field == "exclude" and any("why" not in r for r in rows):
            return False  # 排除必须附理由（进异火榜“已排除”）
        out.setdefault(field, []).extend(rows)
        return True
    if field == "back":
        if value in _NONE:
            out.setdefault("back", [])
            return True
        ids = _ids(value)
        if ids is not None:
            out.setdefault("back", []).extend(ids)
            return True
        if re.fullmatch(r"闸点\s*[12]", value):
            out.setdefault("back", []).append(value.replace(" ", ""))
            return True
        return False
    if field == "edit":
        m = _EDIT.match(value)
        if not m:
            return False
        out.setdefault("edit", []).append({"pointer": m.group(1), "value": m.group(2).strip()})
        return True
    if field == "library_import":
        out["library_import"] = value not in _NONE and value not in ("否", "不")
        return True
    if field == "redo":
        out["redo"] = value or "重做"
        return True
    out["note"] = (out.get("note", "") + "\n" + value).strip() if out.get("note") else value
    return True


def render(decision: dict[str, Any]) -> str:
    """决定 → 决定块原文（界面按产物生成，cz 点选、改字；这里给测试与界面共用的写法）。"""
    gate = decision["gate"]
    lines = [f"【决定 v1】闸点 {gate[1]}"]
    names = {v: k for k, v in _KEYS[gate].items()}
    for field, label in names.items():
        if field not in decision:
            continue
        v = decision[field]
        if field in ("pick", "confirm", "drop", "to_implementation", "back"):
            lines.append(f"{label}：{'，'.join(v) if v else '无'}")
        elif field in ("exclude", "hold"):
            parts = [r["candidate"] + (f"（{r['why']}）" if r.get("why") else "") for r in v]
            lines.append(f"{label}：{'，'.join(parts) if parts else '无'}")
        elif field == "edit":
            lines += [f"改：{e['pointer']} = {e['value']}" for e in v]
        elif field == "library_import":
            lines.append(f"{label}：{'报告' if v else '无'}")
        else:
            lines.append(f"{label}：{v}")
    return "\n".join(lines)
