"""V1 结构校验：按 `schemas/*.schema.json`（JSON Schema 2020-12，docs/design/fenjue/10-schemas.md 原样搬入）校验产物。

只实现这十一份 Schema 用到的关键字（type、enum、const、properties、required、additionalProperties、
patternProperties、items、min/maxItems、min/maxLength、minimum、maximum、pattern、minProperties、$ref、allOf、oneOf、
format 只作注释）。不引第三方库：焚决组件零依赖，校验器又是量具，规则越少越好核对。

用到的关键字之外的关键字一律报错（`unsupported`），免得 Schema 以后加了新关键字而校验器静默放过。
"""

from __future__ import annotations

import json
import re
from functools import cache
from importlib import resources
from typing import Any

NAMES = (
    "common",
    "observation",
    "intake",
    "candidates",
    "essence",
    "placement",
    "dry-run",
    "handoff",
    "run",
    "bang",
    "decision",
)
_ANNOTATIONS = {"$schema", "$id", "title", "description", "$defs", "format"}
_KEYWORDS = _ANNOTATIONS | {
    "type",
    "enum",
    "const",
    "properties",
    "required",
    "additionalProperties",
    "patternProperties",
    "items",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "pattern",
    "minProperties",
    "$ref",
    "allOf",
    "oneOf",
}


@cache
def load(name: str) -> dict[str, Any]:
    """一份 Schema（按文件名去掉 `.schema.json`）。"""
    if name not in NAMES:
        raise KeyError(f"没有这份 Schema：{name}")
    text = resources.files("paoding_fenjue.engine").joinpath(f"schemas/{name}.schema.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def _resolve(ref: str, here: str) -> tuple[dict[str, Any], str]:
    doc, _, frag = ref.partition("#")
    name = doc.removesuffix(".schema.json") if doc else here
    node: Any = load(name)
    for part in [p for p in frag.split("/") if p]:
        node = node[part]
    if not isinstance(node, dict):
        raise ValueError(f"$ref 指向的不是 Schema：{ref}")
    return node, name


def _type_ok(v: Any, t: str) -> bool:
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "string":
        return isinstance(v, str)
    if t == "boolean":
        return isinstance(v, bool)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "null":
        return v is None
    raise ValueError(f"未知类型：{t}")


def _check(v: Any, s: dict[str, Any], doc: str, at: str, out: list[str]) -> None:
    unknown = set(s) - _KEYWORDS
    if unknown:
        out.append(f"{at or '/'}: Schema 用了校验器不认识的关键字 {sorted(unknown)}")
        return
    if "$ref" in s:
        target, tdoc = _resolve(s["$ref"], doc)
        _check(v, target, tdoc, at, out)
    for sub in s.get("allOf", []):
        _check(v, sub, doc, at, out)
    if "oneOf" in s:
        hits = 0
        for sub in s["oneOf"]:
            trial: list[str] = []
            _check(v, sub, doc, at, trial)
            hits += not trial
        if hits != 1:
            out.append(f"{at or '/'}: oneOf 命中 {hits} 个分支（应恰好 1 个）")
    if "type" in s:
        types = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_type_ok(v, t) for t in types):
            out.append(f"{at or '/'}: 应为 {'/'.join(types)}")
            return
    if "enum" in s and v not in s["enum"]:
        out.append(f"{at or '/'}: {v!r} 不在 {s['enum']}")
    if "const" in s and v != s["const"]:
        out.append(f"{at or '/'}: 应为 {s['const']!r}")
    if isinstance(v, str):
        if len(v) < s.get("minLength", 0):
            out.append(f"{at or '/'}: 太短（至少 {s['minLength']} 字）")
        if "maxLength" in s and len(v) > s["maxLength"]:
            out.append(f"{at or '/'}: 太长（{len(v)} > {s['maxLength']} 字）")
        if "pattern" in s and not re.search(s["pattern"], v):
            out.append(f"{at or '/'}: {v!r} 不合 {s['pattern']}")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in s and v < s["minimum"]:
            out.append(f"{at or '/'}: {v} < {s['minimum']}")
        if "maximum" in s and v > s["maximum"]:
            out.append(f"{at or '/'}: {v} > {s['maximum']}")
    if isinstance(v, list):
        if len(v) < s.get("minItems", 0):
            out.append(f"{at or '/'}: 至少 {s['minItems']} 项")
        if "maxItems" in s and len(v) > s["maxItems"]:
            out.append(f"{at or '/'}: 至多 {s['maxItems']} 项")
        if "items" in s:
            for i, item in enumerate(v):
                _check(item, s["items"], doc, f"{at}/{i}", out)
    if isinstance(v, dict):
        if len(v) < s.get("minProperties", 0):
            out.append(f"{at or '/'}: 至少 {s['minProperties']} 个键")
        for k in s.get("required", []):
            if k not in v:
                out.append(f"{at or '/'}: 缺 {k}")
        props: dict[str, Any] = s.get("properties", {})
        pats: dict[str, Any] = s.get("patternProperties", {})
        extra = s.get("additionalProperties", True)
        for k, item in v.items():
            matched = False
            if k in props:
                _check(item, props[k], doc, f"{at}/{k}", out)
                matched = True
            for p, ps in pats.items():
                if re.search(p, k):
                    _check(item, ps, doc, f"{at}/{k}", out)
                    matched = True
            if not matched:
                if extra is False:
                    out.append(f"{at or '/'}: 多出的键 {k}")
                elif isinstance(extra, dict):
                    _check(item, extra, doc, f"{at}/{k}", out)


def errors(obj: Any, name: str) -> list[str]:
    """按 Schema `name` 校验 `obj`，返回逐条错误（空列表即通过）。"""
    out: list[str] = []
    _check(obj, load(name), name, "", out)
    return out


def def_errors(obj: Any, name: str, definition: str) -> list[str]:
    """按 Schema `name` 里 `$defs/<definition>` 一节校验（K1 只校验遮蔽视图）。"""
    out: list[str] = []
    _check(obj, load(name)["$defs"][definition], name, "", out)
    return out
