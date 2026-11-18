"""由线格式的 JSON Schema（graph/src/paoding_graph/wire_schema.py）生成网页前端的类型文件 web/src/api/types.ts。

    uv run python scripts/gen-types.py          # 写文件
    uv run python scripts/gen-types.py --check  # 只比对；与仓库里的文件不同则退出码 1（CI 用）

只认 wire_schema 用到的那几种关键字；遇到别的关键字直接报错，免得悄悄生成错的类型。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "graph" / "src"))

from paoding_graph.wire_schema import SECTIONS, D  # noqa: E402

OUT = ROOT / "web" / "src" / "api" / "types.ts"
WIDTH = 110
KNOWN = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "propertyNames",
    "items",
    "anyOf",
    "allOf",
    "const",
    "enum",
    "$ref",
    "description",
    "x-ts-param",
    "x-ts-args",
    "x-ts-params",
}

HEADER = """\
// 线格式类型：图服务 HTTP 绑定的应答与请求（graph/SPEC.md「HTTP 绑定」，HMI 设计 §11.2、§14）。
//
// 本文件是生成物，不要手改：改 graph/src/paoding_graph/wire_schema.py，再跑
//   uv run python scripts/gen-types.py
// CI 用 --check 比对；图服务的测试用同一份 schema 严格校验真应答。
"""

UNION, INTER, ATOM = 0, 1, 2


def lit(v: object) -> str:
    return json.dumps(v, ensure_ascii=False)


def wrap(t: tuple[str, int], need: int) -> str:
    s, p = t
    return f"({s})" if p < need else s


def comment(text: str, ind: str) -> str:
    return f"{ind}/** {text} */\n"


def ts(s: dict, ind: str = "") -> tuple[str, int]:
    """schema → (TypeScript 类型表达式, 优先级)。ind 是多行对象展开时当前一行的缩进。"""
    unknown = set(s) - KNOWN
    if unknown:
        raise SystemExit(f"gen-types: 不认识的关键字 {sorted(unknown)}")
    if "$ref" in s:
        name = s["$ref"].rsplit("/", 1)[1]
        args = s.get("x-ts-args")
        return (f"{name}<{', '.join(args)}>" if args else name), ATOM
    if "x-ts-param" in s:
        return s["x-ts-param"], ATOM
    if "const" in s:
        return lit(s["const"]), ATOM
    if "enum" in s:
        return " | ".join(lit(v) for v in s["enum"]), UNION if len(s["enum"]) > 1 else ATOM
    if "anyOf" in s:
        return " | ".join(wrap(ts(x, ind), INTER) for x in s["anyOf"]), UNION
    if "allOf" in s:
        return " & ".join(wrap(ts(x, ind), ATOM) for x in s["allOf"]), INTER
    t = s.get("type")
    if t is None:
        return "unknown", ATOM
    if t in ("integer", "number"):
        return "number", ATOM
    if t in ("string", "boolean", "null"):
        return t, ATOM
    if t == "array":
        return wrap(ts(s["items"], ind), ATOM) + "[]", ATOM
    if t == "object":
        return obj(s, ind), ATOM
    raise SystemExit(f"gen-types: 不认识的类型 {t!r}")


def obj(s: dict, ind: str) -> str:
    if "additionalProperties" in s:
        key = ts(s["propertyNames"], ind)[0] if "propertyNames" in s else "string"
        return f"Record<{key}, {ts(s['additionalProperties'], ind)[0]}>"
    props = s.get("properties")
    if not props:
        return "Record<string, unknown>"
    req = set(s.get("required", []))
    inner = ind + "  "
    fields = [(k, "" if k in req else "?", v) for k, v in props.items()]
    if not any("description" in v for _, _, v in fields):
        flat = "{ " + "; ".join(f"{k}{q}: {ts(v, inner)[0]}" for k, q, v in fields) + " }"
        if len(ind) + len(flat) <= WIDTH and "\n" not in flat:
            return flat
    lines = ["{"]
    for k, q, v in fields:
        line = ""
        if "description" in v:
            line += comment(v["description"], inner)
        lines.append(f"{line}{inner}{k}{q}: {ts(v, inner)[0]};")
    lines.append(ind + "}")
    return "\n".join(lines)


def declaration(name: str, s: dict) -> str:
    params = s.get("x-ts-params")
    head = f"export type {name}{'<' + ', '.join(params) + '>' if params else ''} ="
    out = comment(s["description"], "") if "description" in s else ""
    body = ts(s)[0]
    members = s.get("anyOf") or ([{"const": v} for v in s["enum"]] if "enum" in s else None)
    if members and len(members) > 2 and len(head) + 1 + len(body) + 1 > WIDTH:
        parts = []
        for x in members:
            c = comment(x["description"], "  ") if "description" in x else ""
            parts.append(f"{c}  | {wrap(ts(x, '  '), INTER)}")
        return out + head + "\n" + "\n".join(parts) + ";\n"
    return out + f"{head} {body};\n"


def render() -> str:
    chunks = [HEADER]
    for name, s in D.items():
        if name in SECTIONS:
            chunks.append(f"\n// ---------- {SECTIONS[name]} ----------\n\n")
        chunks.append(declaration(name, s))
    return "".join(chunks)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="只比对，不写文件")
    a = ap.parse_args()
    text = render()
    if a.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(
                f"{OUT.relative_to(ROOT)} 与 schema 不一致；跑 uv run python scripts/gen-types.py 重新生成",
                file=sys.stderr,
            )
            return 1
        print(f"{OUT.relative_to(ROOT)} 与 schema 一致")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"写出 {OUT.relative_to(ROOT)}（{len(D)} 个类型）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
