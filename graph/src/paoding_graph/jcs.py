"""RFC 8785 JSON 规范化（JCS）。事件哈希、内容键、状态哈希都经过它（规格 §3.1.2）。

与 json.dumps(sort_keys=True) 的三处差别，正是 JCS 要求的：
1. 键按 UTF-16 码元排序，不是按 Unicode 码点；
2. 数字按 ECMAScript Number.prototype.toString 输出（1.0 → "1"，1e21 → "1e+21"）；
3. 字符串只转义 JCS 规定的字符，其余原样输出 UTF-8。
NaN 与 Infinity 不是合法 JSON，直接拒绝。
"""
from __future__ import annotations

import math
from typing import Any

__all__ = ["canonicalize", "JCSError"]


class JCSError(ValueError):
    pass


_ESC = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _str(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch in _ESC:
            out.append(_ESC[ch])
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _number(x: float | int) -> str:
    if isinstance(x, bool):
        raise JCSError("bool 不是数字")
    if isinstance(x, int):
        if abs(x) > 2**53:
            raise JCSError(f"整数超出 IEEE-754 双精度可精确表示的范围：{x}")
        return str(x)
    if math.isnan(x) or math.isinf(x):
        raise JCSError("NaN 与 Infinity 不是合法 JSON")
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    # repr 给出最短往返的十进制数字串，与 ECMAScript 的 "k 最小" 要求一致
    r = repr(abs(x))
    mant, _, exp = r.partition("e")
    digits = mant.replace(".", "")
    point = mant.index(".") if "." in mant else len(mant)
    e10 = int(exp or 0) + point          # 小数点位置：value = 0.digits × 10^e10
    stripped = digits.lstrip("0")
    e10 -= len(digits) - len(stripped)
    digits = stripped.rstrip("0") or "0"
    k, n = len(digits), e10
    if k <= n <= 21:
        s = digits + "0" * (n - k)
    elif 0 < n <= 21:
        s = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        s = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        es = f"e+{e}" if e >= 0 else f"e-{-e}"
        s = digits[0] + ("." + digits[1:] if k > 1 else "") + es
    return sign + s


def _ser(v: Any, out: list[str]) -> None:
    if v is None:
        out.append("null")
    elif v is True:
        out.append("true")
    elif v is False:
        out.append("false")
    elif isinstance(v, (int, float)):
        out.append(_number(v))
    elif isinstance(v, str):
        out.append(_str(v))
    elif isinstance(v, (list, tuple)):
        out.append("[")
        for i, item in enumerate(v):
            if i:
                out.append(",")
            _ser(item, out)
        out.append("]")
    elif isinstance(v, dict):
        for k in v:
            if not isinstance(k, str):
                raise JCSError(f"对象键必须是字符串：{k!r}")
        out.append("{")
        for i, k in enumerate(sorted(v, key=lambda s: s.encode("utf-16-be"))):
            if i:
                out.append(",")
            out.append(_str(k))
            out.append(":")
            _ser(v[k], out)
        out.append("}")
    else:
        raise JCSError(f"不可规范化的类型：{type(v).__name__}")


def canonicalize(v: Any) -> bytes:
    out: list[str] = []
    _ser(v, out)
    return "".join(out).encode("utf-8")
