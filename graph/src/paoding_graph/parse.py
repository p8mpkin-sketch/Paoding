"""提议体的解析层：未经校验的 JSON 只在这里被当作"可能不合形状"的东西对待。

内核的校验函数经 `Obj` 读提议体；字段缺失或类型不对一律抛 `BadBody`，`validate` 只接这一种异常并
转成 `schema_error`。校验函数其余部分（读状态、算等级、算账）不再包在宽泛的 try/except 里：
那里抛出的 KeyError、TypeError 是内核自己的缺陷，应当原样暴露，而不是伪装成调用方的输入错误。

纯函数，不做 IO。
"""

from __future__ import annotations

from typing import Any


class BadBody(ValueError):
    """提议体不合形状（缺字段、类型不对、取值非法）。"""


_MISSING: Any = object()


class Obj:
    """一个 JSON 对象的只读视图，按类型取字段。where 是它在提议体里的位置，用于报错。"""

    __slots__ = ("raw", "where")

    def __init__(self, raw: Any, where: str = "body") -> None:
        if not isinstance(raw, dict) or not all(isinstance(k, str) for k in raw):
            raise BadBody(f"{where} 必须是对象")
        self.raw: dict[str, Any] = raw
        self.where = where

    def __contains__(self, key: str) -> bool:
        return key in self.raw

    def keys(self) -> set[str]:
        return set(self.raw)

    def _at(self, key: str) -> str:
        return f"{self.where}.{key}"

    def get(self, key: str, default: Any = None) -> Any:
        """原样取值（不限类型）；只用于内容不由内核解释的字段，如 expect。"""
        return self.raw.get(key, default)

    def req(self, key: str) -> Any:
        if key not in self.raw:
            raise BadBody(f"缺字段 {self._at(key)}")
        return self.raw[key]

    def string(self, key: str, default: Any = _MISSING) -> str:
        """必须是字符串；给了 default 则字段可缺。"""
        v = self.raw.get(key, default) if default is not _MISSING else self.req(key)
        if not isinstance(v, str):
            raise BadBody(f"{self._at(key)} 须为字符串")
        return v

    def opt_string(self, key: str) -> str | None:
        """字符串，或缺省、null。"""
        v = self.raw.get(key)
        if v is not None and not isinstance(v, str):
            raise BadBody(f"{self._at(key)} 须为字符串")
        return v

    def text(self, key: str, default: Any = _MISSING) -> str:
        """标量转成字符串（数字写成文字也收）；对象与数组不收。"""
        v = self.raw.get(key, default) if default is not _MISSING else self.req(key)
        if v is None or isinstance(v, (dict, list)):
            raise BadBody(f"{self._at(key)} 须为文字")
        return str(v)

    def integer(self, key: str, default: Any = _MISSING) -> int:
        """整数；整数值的字符串与浮点也收（与此前的 int(...) 取值一致），布尔不收。"""
        v = self.raw.get(key, default) if default is not _MISSING else self.req(key)
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise BadBody(f"{self._at(key)} 须为整数")
        try:
            return int(v)
        except (ValueError, OverflowError):
            raise BadBody(f"{self._at(key)} 须为整数") from None

    def number(self, key: str, default: Any = _MISSING) -> float:
        v = self.raw.get(key, default) if default is not _MISSING else self.req(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
            raise BadBody(f"{self._at(key)} 须为有限的数")
        return v

    def array(self, key: str, default: Any = _MISSING) -> list[Any]:
        v = self.raw.get(key, default) if default is not _MISSING else self.req(key)
        if v is None and default is not _MISSING:
            return []
        if not isinstance(v, list):
            raise BadBody(f"{self._at(key)} 须为数组")
        return list(v)

    def strings(self, key: str, default: Any = _MISSING) -> list[str]:
        """字符串数组（引用列表：元素要当键用）。"""
        out = self.array(key, default)
        if not all(isinstance(x, str) for x in out):
            raise BadBody(f"{self._at(key)} 须为字符串数组")
        return out

    def texts(self, key: str, default: Any = _MISSING) -> list[str]:
        out = self.array(key, default)
        if any(x is None or isinstance(x, (dict, list)) for x in out):
            raise BadBody(f"{self._at(key)} 须为文字数组")
        return [str(x) for x in out]

    def child(self, key: str) -> Obj:
        return Obj(self.req(key), self._at(key))

    def children(self, key: str, default: Any = _MISSING) -> list[Obj]:
        return [Obj(x, f"{self._at(key)}[{n}]") for n, x in enumerate(self.array(key, default))]
