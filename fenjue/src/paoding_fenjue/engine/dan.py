"""丹：引擎里每一次模型调用的接口（docs/design/fenjue/08-algorithms.md §2 丹方）。

一颗丹 = 一个角色（读丹、主丹、萃丹、盲审丹、位丹）+ 档位 + 固定的输入形状。引擎只经 `Dan.call()` 调模型，
模型的输出只是提议：调用方按 Schema 与校验器判过不过，不过就带着错误清单重来（至多 2 次）。

这里给两种实现：

- `Recorded`：按“键 + 输入的 sha256”回放录好的输出（CI 用，等于假 CLI 的做法，11 §7）。输入变了而录音没更新，
  当场报“录音过期”，不悄悄用旧答案；
- `Recorder`：包住任意一个真正出答案的函数（真模型的适配器，或夹具的脚本），边答边录，供重录夹具。

真模型的适配器（经端点代理计量，T3）随引擎形态（E4）接入，不在这里。
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..shapes import digest

ROLES = {"reader": "light", "main": "heavy", "extra": "heavy", "blind": "mid", "placer": "mid"}


@dataclass(frozen=True)
class Reply:
    output: Any
    tokens_in: int = 0
    tokens_out: int = 0


class Dan(Protocol):
    def call(self, role: str, key: str, payload: Mapping[str, Any]) -> Reply: ...


class StaleRecording(LookupError):
    """录音里没有这一问，或问的内容已变（输入 sha256 对不上）。"""


def input_sha(role: str, payload: Mapping[str, Any]) -> str:
    """丹输入的指纹：角色 + 载荷（JCS）。定界包裹的随机标记不进载荷，所以同一段原文重跑指纹不变。"""
    return digest({"role": role, "payload": {k: v for k, v in payload.items() if k != "nonce"}})


@dataclass
class Recorded:
    entries: dict[str, dict[str, Any]]
    calls: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> Recorded:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return cls({e["key"]: e for e in doc["entries"]})

    def call(self, role: str, key: str, payload: Mapping[str, Any]) -> Reply:
        e = self.entries.get(key)
        sha = input_sha(role, payload)
        if e is None:
            raise StaleRecording(f"录音里没有 {key}")
        if e["role"] != role or e["input_sha256"] != sha:
            raise StaleRecording(f"录音过期：{key} 的输入变了（录的 {e['input_sha256'][:12]}，现在 {sha[:12]}）")
        self.calls.append(key)
        return Reply(e["output"], int(e.get("tokens_in", 0)), int(e.get("tokens_out", 0)))


Answer = Callable[[str, str, Mapping[str, Any]], Reply]


@dataclass
class Recorder:
    answer: Answer
    entries: list[dict[str, Any]] = field(default_factory=list)

    def call(self, role: str, key: str, payload: Mapping[str, Any]) -> Reply:
        r = self.answer(role, key, payload)
        self.entries.append(
            {
                "key": key,
                "role": role,
                "tier": ROLES[role],
                "input_sha256": input_sha(role, payload),
                "output": r.output,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
            }
        )
        return r

    def dump(self, path: Path) -> None:
        doc = {"v": 1, "entries": sorted(self.entries, key=lambda e: e["key"])}
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 定界包裹（08 §4.4 D2）


def new_nonce() -> str:
    return secrets.token_hex(16)


def fence(raw: str, nonce: str) -> str:
    """把外部原文包进 `<external-data nonce=…>`；原文里同形的开闭标签先转义，伪造不了“数据结束”。"""
    safe = raw.replace("<external-data", "&lt;external-data").replace("</external-data", "&lt;/external-data")
    return f'<external-data nonce="{nonce}">\n{safe}\n</external-data nonce="{nonce}">'


def estimate_tokens(s: str) -> int:
    """粗估 token 数（中英混排约 3 字一个）；只用于覆盖报告与单元上限，真实花费以端点代理计量为准（T3）。"""
    return max(1, len(s) // 3)
