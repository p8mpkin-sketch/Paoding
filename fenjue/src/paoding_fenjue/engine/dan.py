"""丹：引擎里每一次模型调用的接口（docs/design/fenjue/08-algorithms.md §2 丹方）。

一颗丹 = 一个角色（读丹、主丹、萃丹、盲审丹、位丹）+ 档位 + 固定的输入形状。引擎只经 `Dan.call()` 调模型，
模型的输出只是提议：调用方按 Schema 与校验器判过不过，不过就带着错误清单重来（至多 2 次）。

这里给两种实现：

- `Recorded`：按“键 + 输入的 sha256”回放录好的输出（CI 用，等于假 CLI 的做法，11 §7）。输入变了而录音没更新，
  当场报“录音过期”，不悄悄用旧答案；
- `Recorder`：包住任意一个真正出答案的函数（真模型的适配器，或夹具的脚本），边答边录，供重录夹具。

真模型的适配器在 `paoding_adapter.tunshi_cli`（经端点代理计量，T3；本组件不开网络）。这里另有 `Memo`：
包住真模型的丹，把问过的调用记在工作区，会话被打断后重做的单元不再为同一问付钱。
"""

from __future__ import annotations

import json
import secrets
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..shapes import digest


def truncated(r: Reply, limit: int) -> bool:
    """这次回答是被输出上限截断的：停止原因是 max_tokens，或用掉的输出 token 正好到了上限（端点不报停止原因时）。"""
    return r.stop == "max_tokens" or (limit > 0 and r.tokens_out >= limit)


ROLES = {"reader": "light", "main": "heavy", "extra": "heavy", "blind": "mid", "placer": "mid"}


@dataclass(frozen=True)
class Reply:
    output: Any
    tokens_in: int = 0
    tokens_out: int = 0
    stop: str = ""  # 模型的停止原因（max_tokens = 输出到上限被截断）；回放与备忘里没有就是空


class Dan(Protocol):
    def call(self, role: str, key: str, payload: Mapping[str, Any]) -> Reply: ...


class BudgetExhausted(RuntimeError):
    """模型调用被预算挡下（端点代理到顶即拒，T3）。scope：task（这个会话的预留用完）| problem（整题预算用完）|
    global（全局硬顶）。引擎收到后停在当前单元、存检查点，不再调模型。"""

    def __init__(self, scope: str, detail: str = "") -> None:
        super().__init__(detail or scope)
        self.scope = scope


class Unavailable(RuntimeError):
    """模型端点此刻调不通（重试过了仍不行）。与预算无关：检查点留着，换一个会话接着做。"""


class ReplyDefect(RuntimeError):
    """处理某一次模型回答的代码出了错（原异常挂在 `__cause__`）。`key` 是那次调用的键。

    只有这一种缺陷可以算到模型的回答头上、带着原因让模型重写：回答多半是没料到的形状。别处的缺陷（读上一步的产物、
    算难度、写报告）与这一步的回答无关，让模型重写既花钱又改不了结果。"""

    def __init__(self, key: str, cause: BaseException) -> None:
        super().__init__(f"{type(cause).__name__}: {cause}")
        self.key = key


@contextmanager
def reading(key: str) -> Iterator[None]:
    """圈出“解析、校验这一次回答”的那段代码：里面抛出的异常包成 `ReplyDefect`。圈里不调模型、不做别的事。"""
    try:
        yield
    except ReplyDefect:
        raise
    except Exception as e:
        raise ReplyDefect(key, e) from e


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
        return Reply(e["output"], int(e.get("tokens_in", 0)), int(e.get("tokens_out", 0)), str(e.get("stop", "")))


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
                **({"stop": r.stop} if r.stop else {}),
            }
        )
        return r

    def dump(self, path: Path) -> None:
        doc = {"v": 1, "entries": sorted(self.entries, key=lambda e: e["key"])}
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


@dataclass
class Memo:
    """调用备忘（13 §6）：包住真模型的丹，把每次调用的回答按“键 + 输入指纹”记在工作区的 `calls.jsonl`。

    会话随时可能被打断（软线、预留用完、端点调不通、进程被终止）：被打断的单元下次从头做，但它已经问过的调用
    直接取备忘，不再花钱。输入变了（指纹对不上）就当没问过。备忘里的回答与录音同一个形状，token 数照原样交回，
    所以被打断的单元补记花费时不多不少。`forget` 供“退回重做”用：那是要重新取样，不能拿旧回答充数。"""

    inner: Dan
    path: Path
    hits: int = 0

    def __post_init__(self) -> None:
        self._seen: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.Lock()  # 并发的调用各自问模型，记备忘时一次只写一行
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    e = json.loads(line)
                    self._seen[(e["key"], e["input_sha256"])] = e
                except (ValueError, KeyError, TypeError):
                    continue  # 写到一半被打断的那一行：不认

    def call(self, role: str, key: str, payload: Mapping[str, Any]) -> Reply:
        sha = input_sha(role, payload)
        e = self._seen.get((key, sha))
        if e is not None and e.get("role") == role:
            self.hits += 1
            return Reply(e["output"], int(e.get("tokens_in", 0)), int(e.get("tokens_out", 0)), str(e.get("stop", "")))
        r = self.inner.call(role, key, payload)
        row = {
            "key": key,
            "role": role,
            "input_sha256": sha,
            "output": r.output,
            "tokens_in": r.tokens_in,
            "tokens_out": r.tokens_out,
            **({"stop": r.stop} if r.stop else {}),
        }
        with self._lock:
            self._seen[(key, sha)] = row
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return r

    def forget(self, prefixes: tuple[str, ...]) -> int:
        """丢掉键以这些前缀开头的备忘，返回丢了几条。"""
        drop = [k for k in self._seen if k[0].startswith(prefixes)]
        for k in drop:
            del self._seen[k]
        if drop:
            body = "".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in self._seen.values())
            self.path.write_text(body, encoding="utf-8")
        return len(drop)


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
