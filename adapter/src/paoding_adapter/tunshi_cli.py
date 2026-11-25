"""方案分析的驱动程序（docs/design/fenjue/13-kernel.md §3）：在模型容器里代替 CLI 跑固定流程。

会话运行器照起 CLI 的办法起它：同一组参数（只认 `--mcp-config`、`--session-id` / `--resume`、`--model`），同样的
环境（`ANTHROPIC_BASE_URL` 是端点代理，`ANTHROPIC_API_KEY` 是任务令牌），stdout 上同形的 stream-json 事件流。
它手里没有真实密钥、没有图服务的令牌、没有出站网络，只有任务令牌与宿主的四个工具（`paoding_adapter.tunshi`）。

它做三件事，其余都在 `paoding_fenjue` 的引擎里（`analysis.Session`）：

1. 工具：经 MCP 调宿主的 `intake`、`fetch`、`check`、`deliver`；
2. 模型：把引擎的每一次调用渲染成一条流式的 Messages 请求发给端点代理，按档位取模型；429 的预算拒绝交回引擎
   停在当前单元，暂时性的失败有限次重试，重试不过交回“端点调不通”；每次调用的用时、重试与停止原因记在工作区的
   `analysis/model_calls.jsonl`，汇总在 `analysis/model_stats.json`，思考块的原文记在 `analysis/thinking.jsonl`；
3. 事件：每次模型调用、每次工具调用各出事件，活动面板据此显示在做哪一步；事件里只有步骤名、对象编号与用量，
   不带外部原文，也不带模型的输出。

这里用标准库直接发 HTTP，而不用官方 SDK：它跑在只有 Python 标准库的模型容器里，请求必须经我们自己的端点代理
计量（T3），而且每次调用都是无工具的一问一答，没有 SDK 能省掉的东西。请求体不带采样参数与思考配置。

时限（13-kernel.md §3.2 的表）：流式之后，一次模型调用不再是“整段生成完才有首字节”，所以不设“等整段”的时限，
改成两条——流上多久没有任何字节（`MODEL_IDLE_S`，真正起作用的那条），与一次调用的总时限（`MODEL_CALL_S`，兜底）。
端点代理等上游的 600 秒不动（它是体质文件），驱动的静默时限必须比它短，所以起作用的总是驱动这一条。

只用标准库与 `paoding_fenjue.contract`、`paoding_graph`（都只用标准库）；以 `python -I` 运行。
容器里这两个包挂在 `PD_LIB` 指的目录下。
"""

from __future__ import annotations

import http.client
import json
import os
import signal
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

if os.environ.get("PD_LIB"):  # 模型容器：包挂在固定目录；宿主子进程从自己的环境里找
    sys.path.insert(0, os.environ["PD_LIB"])

from paoding_fenjue.contract import (  # noqa: E402
    DAN_ROLES,
    BudgetExhausted,
    EngineError,
    Reply,
    Unavailable,
    analysis,
    pills,
)

MCP_NAME = "paoding"
API_VERSION = "2023-06-01"
HTTP_TIMEOUT_S = 900.0  # 一次工具调用（fetch 在沙箱里下载）最长等这么久；模型调用不用它，见下面三条
CONNECT_S = 30.0  # 连上端点代理（本机或容器里的中继）最长等这么久
# 流上多久没有任何字节就放弃这一次（含发出请求后等响应头）。上游每隔一会儿有 ping 或增量，正常的慢不会撞它；
# 撞它的是上游挂住。它必须短于端点代理等上游的时限（proxy.py 里 600 秒，体质文件不改），这样先到的总是这一条。
MODEL_IDLE_S = 300.0
MODEL_IDLE_MAX_S = 540.0  # 配置能给的最大值：比代理的 600 秒留出一分钟
# 一次调用从发出到收完的总时限（兜底：字节一直在滴但永远收不完）。24000 token 的上限按 10 token/秒也收得完
MODEL_CALL_S = 2400.0
THINKING_KEEP = 200_000  # 一次调用的思考原文在 thinking.jsonl 里最多留这么多字
KEEPALIVE_S = 20.0
# 暂时性失败（408、409、非预算的 429、5xx、连不上）之后各等多久再试；PD_RETRY_WAITS 可改（测试用短的）
RETRY_WAITS = tuple(float(x) for x in os.environ.get("PD_RETRY_WAITS", "2,8,30").split(",") if x.strip())
RETRYABLE = (408, 409, 429, 500, 502, 503, 504, 529)
BUDGET_SCOPES = {
    "task_reserve_exhausted": "task",
    "problem_budget_exhausted": "problem",
    "global_cap_exhausted": "global",
}
_BOOLEANS = {"--verbose", "--bare", "--restricted", "--strict-mcp-config"}


def parse_argv(argv: list[str]) -> dict[str, Any]:
    flags: dict[str, Any] = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in _BOOLEANS:
            flags[a] = True
            i += 1
        elif a.startswith("-") and i + 1 < len(argv):
            flags[a] = argv[i + 1]
            i += 2
        else:
            i += 1
    return flags


class Events:
    """stdout 上的事件流。几个线程都会写（主线程与保活线程），一行一把锁。"""

    def __init__(self, sid: str) -> None:
        self.sid, self.turns, self._n = sid, 0, 0
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def emit(self, ev: Mapping[str, Any]) -> None:
        with self._lock:
            sys.stdout.write(json.dumps(ev, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def say(self, text: str) -> None:
        self.emit({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})

    def turn(self, model: str, usage: Mapping[str, Any], stop: str) -> None:
        with self._lock:  # 按题读时几个调用并发着回来
            self.turns += 1
        self.emit(
            {"type": "assistant", "message": {"model": model, "usage": dict(usage), "stop_reason": stop, "content": []}}
        )

    def tool(self, name: str, args: Mapping[str, Any]) -> str:
        self._n += 1
        tid = f"t{self._n}"
        block = {"type": "tool_use", "id": tid, "name": f"mcp__{MCP_NAME}__{name}", "input": dict(args)}
        self.emit({"type": "assistant", "message": {"content": [block]}})
        return tid

    def tool_result(self, tid: str, out: Any, is_error: bool) -> None:
        body = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, sort_keys=True)
        block = {"type": "tool_result", "tool_use_id": tid, "is_error": is_error, "content": body}
        self.emit({"type": "user", "message": {"content": [block]}})

    def keepalive(self) -> None:
        """长时间的模型调用、等人批访问申请时，事件流上没有新事件；会话运行器把久无事件当作卡死。
        每隔一会儿出一条 system 事件表示还活着（活动面板不认它，不成条目、不入账）。每一处阻塞的等待都有自己的
        超时，所以保活不会把真的卡死盖住：超时到了程序自己报错退出。"""

        def loop() -> None:
            while not self._stop.wait(KEEPALIVE_S):
                self.emit({"type": "system", "subtype": "keepalive"})

        threading.Thread(target=loop, daemon=True).start()

    def close(self) -> None:
        self._stop.set()


def post(url: str, body: Mapping[str, Any], headers: Mapping[str, str], timeout: float) -> tuple[int, Any]:
    """POST 一个 JSON，交回 (状态码, 解析后的响应体)。连不上或超时交回 (0, 原因)。不走环境里的代理。"""
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"content-type": "application/json", **headers},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as r:
            data = r.read()
            status = int(r.status)
    except urllib.error.HTTPError as e:
        data, status = e.read() or b"", int(e.code)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return 0, f"{type(e).__name__}: {e}"[:300]
    try:
        return status, (json.loads(data) if data else None)
    except ValueError:
        return status, data[:300].decode("utf-8", "replace")


class StreamFailed(Exception):
    """一次流式调用没有收完。kind：connect（连不上代理）| idle（流上静默超过时限）| deadline（超过总时限）|
    cut（流断了，没有停止原因）| stream_error（流里的 error 事件）。都按暂时性失败重试。"""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind, self.detail = kind, detail


class Assembly:
    """把 Messages 的流事件拼回一条非流式形状的回答（model、usage、stop_reason、content）。

    用量：message_start 给输入侧，message_delta 给累计输出；哪边给了什么都收，null 不覆盖已有的数（与代理的计量
    同一个规矩，各家兼容端点放的位置不一样）。内容块按下标拼；没有 content_block_start 就来增量的（有的兼容端点
    这样）按增量的类型现开一块。认不得的事件与增量忽略（ping、签名、工具参数）。"""

    def __init__(self) -> None:
        self.model, self.stop = "", ""
        self.usage: dict[str, Any] = {}
        self.blocks: dict[int, dict[str, Any]] = {}
        self.done = False
        self.error = ""
        self.events, self.last = 0, ""  # 收到几个事件、最后一个的类型：流断了的时候写进原因里

    def take(self, d: Any) -> None:
        if not isinstance(d, dict):
            return
        t = d.get("type")
        self.events += 1
        self.last = str(t or "")[:40]
        if t == "error":
            err = d.get("error")
            e: Mapping[str, Any] = err if isinstance(err, dict) else {}
            self.error = str(e.get("type") or e.get("message") or "error")[:200]
            return
        raw = d.get("message")
        msg: Mapping[str, Any] = raw if isinstance(raw, dict) else {}
        if isinstance(msg.get("model"), str) and msg["model"]:
            self.model = msg["model"]
        for u in (msg.get("usage"), d.get("usage")):
            if isinstance(u, dict):
                self.usage.update({k: v for k, v in u.items() if v is not None})
        idx = d.get("index")
        i = idx if isinstance(idx, int) and not isinstance(idx, bool) else 0
        if t == "content_block_start":
            cb = d.get("content_block")
            block: dict[str, Any] = dict(cb) if isinstance(cb, dict) else {}
            if block.get("type") == "text":
                block["text"] = str(block.get("text") or "")
            elif block.get("type") == "thinking":
                block["thinking"] = str(block.get("thinking") or "")
            self.blocks[i] = block
        elif t == "content_block_delta":
            raw_delta = d.get("delta")
            delta: Mapping[str, Any] = raw_delta if isinstance(raw_delta, dict) else {}
            for kind, field in (("text_delta", "text"), ("thinking_delta", "thinking")):
                if delta.get("type") == kind and isinstance(delta.get(field), str):
                    b = self.blocks.setdefault(i, {"type": field, field: ""})
                    if b.get("type") == field:
                        b[field] = str(b.get(field) or "") + delta[field]
        elif t == "message_delta":
            raw_delta = d.get("delta")
            delta = raw_delta if isinstance(raw_delta, dict) else {}
            if delta.get("stop_reason"):
                self.stop = str(delta["stop_reason"])
        elif t == "message_stop":
            self.done = True

    @property
    def complete(self) -> bool:
        """收完了：见到 message_stop，或至少见到了停止原因（有的兼容端点不发 message_stop）。"""
        return self.done or bool(self.stop)

    def message(self) -> dict[str, Any]:
        content = [self.blocks[k] for k in sorted(self.blocks)]
        return {"model": self.model, "usage": dict(self.usage), "stop_reason": self.stop, "content": content}


def stream_post(
    url: str,
    body: Mapping[str, Any],
    headers: Mapping[str, str],
    idle_s: float,
    total_s: float,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[int, Any, dict[str, float]]:
    """发一条流式的 Messages 请求，交回 (状态码, 回答, 计时)。回答是拼好的非流式形状；出错的响应（4xx、5xx）交回
    它的 JSON。端点不理会 `stream`、照旧回一整个 JSON 的，也认。计时：first_byte_s（发出到响应头）、elapsed_s。

    没收完抛 StreamFailed。两条时限各管各的：套接字的读超时是 `idle_s`（每等一次字节至多这么久），总时限由一个
    定时器到点关掉套接字（读超时管不住“一直有字节但收不完”）。不走环境里的代理。

    定时器关的是连上之后留下的那个套接字，不是 `conn.sock`：响应既不分块也没有长度（读到连接关闭为止）时，
    http.client 拿到响应头就把 `conn.sock` 置空，套接字只剩响应对象手里的那一份，从 `conn` 上已经够不着了。

    流断在停止原因之前（cut）时，原因里带上已经收到多少：几个事件、最后一个事件的类型、多少字节。"""
    u = urllib.parse.urlsplit(url)
    cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    conn = cls(u.netloc, timeout=CONNECT_S)
    t0 = clock()
    timing: dict[str, float] = {}
    expired = threading.Event()
    held: list[socket.socket] = []  # 连上之后的套接字，留给定时器关
    got = {"bytes": 0}

    def expire() -> None:
        expired.set()
        for sock in held:
            try:
                sock.shutdown(socket.SHUT_RDWR)  # 让阻塞着的读立刻返回；close 做不到
            except OSError:
                pass

    def seen() -> str:
        if asm is None:
            return f"已收到 {got['bytes']} 字节，还没有解析出事件"
        last = f"，最后一个是 {asm.last or '没有类型的事件'}" if asm.events else ""
        return f"已收到 {asm.events} 个事件{last}，共 {got['bytes']} 字节"

    watchdog = threading.Timer(total_s, expire)
    watchdog.daemon = True
    stage = "connect"
    asm: Assembly | None = None
    try:
        conn.connect()
        conn.sock.settimeout(idle_s)
        held.append(conn.sock)
        watchdog.start()
        stage = "wait"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        conn.request("POST", path, body=data, headers={"content-type": "application/json", **headers})
        resp = conn.getresponse()
        timing["first_byte_s"] = round(clock() - t0, 3)
        stage = "read"
        status = int(resp.status)
        ctype = (resp.getheader("content-type") or "").lower()
        if status >= 400 or not ctype.startswith("text/event-stream"):
            raw = resp.read()
            if expired.is_set():  # 读到一半被定时器关掉：手里的是半截，不当成完整的回答去解析
                raise StreamFailed("deadline", f"超过一次调用的总时限 {total_s:g} 秒")
            try:
                out: Any = json.loads(raw) if raw else None
            except ValueError:
                out = raw[:300].decode("utf-8", "replace")
            return status, out, timing
        asm = Assembly()
        lines: list[bytes] = []
        # 见到 message_stop 之后也读到流真的结束：代理是“先入账再收尾”，读到结束才保证这次的花费已经落账
        while True:
            line = resp.readline()
            if not line:
                break
            got["bytes"] += len(line)
            line = line.rstrip(b"\r\n")
            if line:
                lines.append(line)
                continue
            _feed(asm, lines)
            lines = []
        _feed(asm, lines)  # 末尾没有空行收口的最后一个事件
        if asm.error:
            raise StreamFailed("stream_error", asm.error)
        if expired.is_set() and not asm.done:  # 定时器关掉套接字后，读到的是“流结束”而不是异常
            raise StreamFailed("deadline", f"超过一次调用的总时限 {total_s:g} 秒")
        if not asm.complete:
            raise StreamFailed("cut", f"流在停止原因之前就结束了（{seen()}）")
        return status, asm.message(), timing
    except StreamFailed:
        raise
    except (OSError, http.client.HTTPException) as e:
        why = f"{type(e).__name__}: {e}"[:200]
        if asm is not None and asm.done and not asm.error:
            return 200, asm.message(), timing  # 回答已经收全，只是收尾没等到：照常用
        if expired.is_set():
            raise StreamFailed("deadline", f"超过一次调用的总时限 {total_s:g} 秒") from None
        if stage == "connect":
            raise StreamFailed("connect", why) from None
        if isinstance(e, TimeoutError):
            where = "等响应头" if stage == "wait" else "流上"
            raise StreamFailed("idle", f"{where}超过 {idle_s:g} 秒没有任何字节") from None
        raise StreamFailed("cut", f"{why}（{seen()}）" if stage == "read" else why) from None
    finally:
        watchdog.cancel()
        timing["elapsed_s"] = round(clock() - t0, 3)
        conn.close()


def _feed(asm: Assembly, lines: list[bytes]) -> None:
    for line in lines:
        if line.startswith(b"data:"):
            try:
                asm.take(json.loads(line[5:].strip()))
            except ValueError:
                continue


def is_timeout(status: int, why: str) -> bool:
    """这一次失败算不算“上游超时”：驱动自己等到时限（静默、总时限），或代理报上游读超时（502 带 TimeoutError）、504。"""
    return status == 504 or why.startswith(("idle", "deadline")) or "TimeoutError" in why or "timed out" in why


class CallLog:
    """模型调用的流水（工作区 `analysis/`，随工作区接力到下一个会话，随导出给人读）。

    - `model_calls.jsonl`：每次真的发出去的调用一行（取备忘的不算）：键、模板、模型、上限、结果、停止原因、
      token、用时、首字节、输出速度、每次没成的尝试（原因与用时）。不带提示词，不带模型的输出。
    - `model_stats.json`：上面的汇总，每次调用后重算——截断几次、上游超时几次、重试几次、最慢的一次是哪个、
      各模板各多少次。下次重跑要量的三个数直接读它。
    - `thinking.jsonl`：模型回了思考块时，这次调用的思考原文一行（过长截掉）。它是模型的输出，可能复述外部原文，
      所以只留在工作区，不进事件流（13 §3.1）。
    写不成只在 stderr 记一笔：流水不是事件账的一部分，不能让它把分析打断。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()  # 按题读时几个调用并发着回来：一次只写一行、只重算一遍汇总

    def add(self, row: Mapping[str, Any], thinking: list[str]) -> None:
        with self._lock:
            self._add(row, thinking)

    def _add(self, row: Mapping[str, Any], thinking: list[str]) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with (self.root / "model_calls.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            if thinking:
                text = "\n\n".join(thinking)
                doc = {"key": row.get("key"), "at": row.get("at"), "chars": len(text), "text": text[:THINKING_KEEP]}
                with (self.root / "thinking.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n")
            tmp = self.root / ".model_stats.json.tmp"
            tmp.write_text(json.dumps(summarize(self.rows()), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            os.replace(tmp, self.root / "model_stats.json")
        except OSError as e:
            sys.stderr.write(f"[tunshi] 调用流水没有写成：{type(e).__name__}: {e}\n")

    def rows(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for line in (self.root / "model_calls.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue  # 写到一半被打断的那一行：不认
            if isinstance(r, dict):
                out.append(r)
        return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """调用流水的汇总。最慢的一次按“单次请求的用时”比（不含失败的尝试与重试之间的等待；那些另计在 retries 里）。"""

    def n(r: Mapping[str, Any], k: str) -> float:
        v = r.get(k)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0

    def tries(r: Mapping[str, Any]) -> list[dict[str, Any]]:
        a = r.get("failed_attempts")
        return [x for x in a if isinstance(x, dict)] if isinstance(a, list) else []

    by: dict[str, dict[str, Any]] = {}
    for r in rows:
        t = by.setdefault(
            str(r.get("template") or "?"),
            {"calls": 0, "max_tokens": int(n(r, "max_tokens")), "truncated": 0, "out_min": None, "out_max": 0},
        )
        t["calls"] += 1
        t["truncated"] += 1 if r.get("outcome") == "truncated" else 0
        if r.get("outcome") in ("ok", "truncated", "refused"):
            out_n = int(n(r, "tokens_out"))
            t["out_min"] = out_n if t["out_min"] is None else min(t["out_min"], out_n)
            t["out_max"] = max(t["out_max"], out_n)
    done = [r for r in rows if n(r, "elapsed_s") > 0]
    slow = max(done, key=lambda r: n(r, "elapsed_s"), default=None)
    slowest = None
    if slow is not None:
        keys = ("key", "template", "elapsed_s", "first_byte_s", "tokens_out", "tokens_per_s", "outcome")
        slowest = {k: slow.get(k) for k in keys}
    return {
        "v": 1,
        "calls": len(rows),
        "truncated": sum(1 for r in rows if r.get("outcome") == "truncated"),
        "refused": sum(1 for r in rows if r.get("outcome") == "refused"),
        "gave_up": sum(1 for r in rows if r.get("outcome") in ("unavailable", "rejected", "budget")),
        "retries": sum(len(tries(r)) for r in rows),
        "upstream_timeouts": sum(1 for r in rows for a in tries(r) if a.get("timeout")),
        "wasted_s": round(sum(n(a, "elapsed_s") for r in rows for a in tries(r)), 1),
        "slowest": slowest,
        "by_template": dict(sorted(by.items())),
    }


class Mcp:
    """宿主工具端点的客户端（MCP over HTTP：initialize → tools/list → tools/call）。"""

    def __init__(self, url: str) -> None:
        self.url, self.n = url, 0
        info = {"name": "tunshi", "version": "1"}
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": info})
        post(self.url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, {}, 30)
        self.tools = [t["name"] for t in self.rpc("tools/list", {})["tools"]]

    def rpc(self, method: str, params: Mapping[str, Any]) -> Any:
        self.n += 1
        body = {"jsonrpc": "2.0", "id": self.n, "method": method, "params": dict(params)}
        status, out = post(self.url, body, {}, HTTP_TIMEOUT_S)
        if status != 200 or not isinstance(out, dict):
            raise RuntimeError(f"工具端点调不通（{method}）：{status} {out}")
        if "error" in out:
            raise RuntimeError(f"工具端点报错（{method}）：{out['error'].get('message')}")
        return out["result"]


class HostTools:
    """`analysis.Tools`：把引擎编排要的工具调用转给宿主，并出活动事件。

    简报很长（原话、立项单、榜），事件里只留几项计数；等人批访问申请时 `fetch` 每隔几秒问一次，同一个来源只在
    状态变了的时候出事件，免得活动面板被“还在等”刷满。"""

    def __init__(self, mcp: Mcp, events: Events) -> None:
        self.mcp, self.events = mcp, events
        self._fetch_seen: dict[Any, Any] = {}

    def call(self, name: str, args: Mapping[str, Any]) -> dict[str, Any]:
        quiet = False
        if name == "fetch":
            quiet = args.get("source") in self._fetch_seen
        tid = None if quiet else self.events.tool(name, args)
        r = self.mcp.rpc("tools/call", {"name": name, "arguments": dict(args)})
        out = r.get("structuredContent")
        if not isinstance(out, dict):
            raise RuntimeError(f"工具 {name} 的返回不是对象")
        if name == "fetch":
            if quiet and out.get("status") != self._fetch_seen.get(args.get("source")):
                tid = self.events.tool(name, args)  # 状态变了：补一对事件
            self._fetch_seen[args.get("source")] = out.get("status")
        if tid is not None:
            self.events.tool_result(tid, _shown(name, out), bool(r.get("isError")))
        return out


def _shown(name: str, out: Mapping[str, Any]) -> Any:
    if name != "intake" or out.get("ok") is False:
        return out
    keep = {k: out.get(k) for k in ("ok", "run", "form", "deliveries", "budget", "relays_left", "closing")}
    keep["materials"] = len(out.get("materials") or {})
    keep["follow_ups"] = len(out.get("follow_ups") or [])
    keep["intake"] = "ok" if out.get("intake") else "；".join(out.get("intake_errors") or [])[:200]
    return keep


class ModelDan:
    """真模型的调用（`Dan`）：一次调用 = 一条流式的 Messages 请求，经端点代理。"""

    def __init__(
        self,
        base_url: str,
        token: str,
        form_ref: str,
        models: Mapping[str, str],
        default_model: str,
        events: Events,
        sleep: Any = time.sleep,
        *,
        log: CallLog | None = None,
        idle_s: float = MODEL_IDLE_S,
        call_s: float = MODEL_CALL_S,
    ) -> None:
        self.url = base_url.rstrip("/") + "/v1/messages"
        self.token, self.form_ref, self.models, self.default_model = token, form_ref, dict(models), default_model
        self.events, self.sleep, self.log = events, sleep, log
        # 静默时限不许等于或超过代理等上游的时限：否则先到的是代理那条，这里量到的就不是真正起作用的那个
        self.idle_s = min(max(float(idle_s), 1.0), MODEL_IDLE_MAX_S)
        self.call_s = max(float(call_s), self.idle_s)

    def call(self, role: str, key: str, facts: Mapping[str, Any]) -> Reply:
        try:
            req = pills.render(role, key, facts, self.form_ref)
        except pills.NoPrompt as e:
            raise EngineError(f"这一步的提示词取不到：{e}") from None
        model = self.models.get(DAN_ROLES[role]) or self.default_model
        if not model:
            raise EngineError(f"没有给“{DAN_ROLES[role]}”档位配模型，也没有缺省模型")
        body = {
            "model": model,
            "max_tokens": req.max_tokens,
            "system": req.system,
            "messages": [{"role": "user", "content": req.user}],
            "stream": True,
        }
        headers = {"x-api-key": self.token, "anthropic-version": API_VERSION, "accept": "text/event-stream"}
        self.events.say(pills.label(role, key))
        row: dict[str, Any] = {
            "v": 1,
            "at": round(time.time(), 3),
            "key": key,
            "role": role,
            "template": req.template,
            "model": model,
            "max_tokens": req.max_tokens,
            "failed_attempts": [],
        }
        thinking: list[str] = []
        try:
            return self._ask(model, body, headers, row, thinking)
        finally:
            row.setdefault("outcome", "interrupted")  # 软线或终止打断在半路
            if self.log is not None:
                self.log.add(row, thinking)

    def _ask(
        self, model: str, body: Mapping[str, Any], headers: Mapping[str, str], row: dict[str, Any], thinking: list[str]
    ) -> Reply:
        """发出去、重试、归类。`row` 是这次调用在流水里的那一行，边做边填（抛出去的也留得下）。"""
        last = ""
        for wait in (*RETRY_WAITS, None):
            t0 = time.monotonic()
            try:
                status, out, timing = stream_post(self.url, body, headers, self.idle_s, self.call_s)
                why = _error_type(out) or (out if isinstance(out, str) else "")
            except StreamFailed as e:
                status, out, timing, why = 0, None, {}, str(e)
            if status == 200 and isinstance(out, dict):
                reply = self._reply(model, out)
                blocks = [b for b in out.get("content") or [] if isinstance(b, dict)]
                thinking.extend(str(b.get("thinking") or "") for b in blocks if b.get("type") == "thinking")
                thinking[:] = [t for t in thinking if t.strip()]
                secs = float(timing.get("elapsed_s") or 0.0)
                cut = reply.stop == "max_tokens" or reply.tokens_out >= int(body["max_tokens"])
                row.update(
                    outcome="refused" if reply.stop == "refusal" else "truncated" if cut else "ok",
                    stop=reply.stop,
                    tokens_in=reply.tokens_in,
                    tokens_out=reply.tokens_out,
                    elapsed_s=secs,
                    first_byte_s=timing.get("first_byte_s"),
                    tokens_per_s=round(reply.tokens_out / secs, 1) if secs > 0 else None,
                    thinking_blocks=sum(1 for b in blocks if b.get("type") in ("thinking", "redacted_thinking")),
                    thinking_chars=sum(len(t) for t in thinking),
                )
                return reply
            last = f"{status or '没收完'} {why}".strip()[:300]
            failed = {
                "status": status,
                "why": str(why)[:200],
                "timeout": is_timeout(status, str(why)),
                "elapsed_s": round(time.monotonic() - t0, 3),
            }
            row["failed_attempts"].append(failed)
            if status == 429 and why in BUDGET_SCOPES:
                row["outcome"] = "budget"
                raise BudgetExhausted(BUDGET_SCOPES[str(why)], last)
            if status == 401:  # 任务令牌已撤（会话正在被收掉）：不重试
                row["outcome"] = "unavailable"
                raise Unavailable(f"任务令牌已失效（{last}）")
            if status not in RETRYABLE and status != 0:
                # 400、403、404、413 一类：配置或请求本身的问题，重试与接力都救不了，如实交给人
                row["outcome"] = "rejected"
                raise EngineError(f"模型端点拒绝了请求（{last}）；请检查这个档位的模型与端点配置")
            if wait is None:
                break
            self.sleep(wait)
        row["outcome"] = "unavailable"
        raise Unavailable(last)

    def _reply(self, model: str, out: Mapping[str, Any]) -> Reply:
        raw_usage, raw_blocks = out.get("usage"), out.get("content")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        stop = str(out.get("stop_reason") or "")
        self.events.turn(str(out.get("model") or model), usage, stop)

        def num(k: str) -> int:
            v = usage.get(k)
            return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0

        tin = num("input_tokens") + num("cache_read_input_tokens") + num("cache_creation_input_tokens")
        tout = num("output_tokens")
        blocks: list[Any] = raw_blocks if isinstance(raw_blocks, list) else []
        text = "".join(str(b.get("text", "")) for b in blocks if isinstance(b, dict) and b.get("type") == "text")
        # 拒答、被输出上限截断、没有文字块：都没有可用的 JSON。交回 None，引擎按“形状不对”带着说明重来（至多 2 次），
        # 花掉的 token 照记。不在这里重试，也不把半截输出当结果
        parsed = None if stop in ("refusal", "max_tokens") else pills.parse(text)
        return Reply(parsed, tin, tout, stop)


def _error_type(out: Any) -> str:
    if isinstance(out, dict):
        err = out.get("error")
        if isinstance(err, dict):
            return str(err.get("type") or err.get("message") or "")
        if isinstance(err, str):
            return err
    return ""


def run(flags: Mapping[str, Any], events: Events) -> str:
    base, token = os.environ.get("ANTHROPIC_BASE_URL", ""), os.environ.get("ANTHROPIC_API_KEY", "")
    cfg = json.loads(Path(str(flags["--mcp-config"])).read_text(encoding="utf-8"))["mcpServers"]
    mcp = Mcp(cfg[MCP_NAME]["url"])
    events.emit(
        {
            "type": "system",
            "subtype": "init",
            "session_id": events.sid,
            "tools": [f"mcp__{MCP_NAME}__{t}" for t in mcp.tools],
            "mcp_servers": [{"name": MCP_NAME, "status": "connected"}],
            "cwd": str(Path.cwd()),
            "driver": "tunshi",
        }
    )
    events.keepalive()
    tools = HostTools(mcp, events)
    brief = tools.call("intake", {})
    if brief.get("ok") is False:
        raise RuntimeError(f"取不到简报：{brief.get('code')} {brief.get('detail')}")
    dan = ModelDan(
        base,
        token,
        str(brief["form"]),
        brief.get("models") or {},
        str(flags.get("--model") or ""),
        events,
        log=CallLog(Path.cwd() / analysis.ANALYSIS),
        idle_s=float(brief.get("model_idle_s") or MODEL_IDLE_S),
        call_s=float(brief.get("model_call_s") or MODEL_CALL_S),
    )
    sess = analysis.Session(Path.cwd(), brief, dan, tools, closing=brief.get("closing") or None, say=events.say)
    out = sess.run()
    return f"{out.status}：{out.detail}"[:300]


def main() -> int:
    def on_sigint(*_: object) -> None:  # 软线：与真 CLI 一样，SIGINT 结束当前回合
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, on_sigint)
    flags = parse_argv(sys.argv[1:])
    events = Events(str(flags.get("--session-id") or flags.get("--resume") or ""))
    try:
        said = run(flags, events)
    except KeyboardInterrupt:
        events.close()
        events.emit({"type": "result", "subtype": "interrupted", "is_error": True, "result": "interrupted"})
        return 130
    except Exception as e:  # noqa: BLE001  进程边界：留栈到 stderr，事件流上如实报错
        traceback.print_exc(file=sys.stderr)
        events.close()
        events.emit(
            {
                "type": "result",
                "subtype": "error_during_execution",
                "is_error": True,
                "result": f"{type(e).__name__}: {e}"[:300],
                "num_turns": events.turns,
            }
        )
        return 1
    events.close()
    events.emit(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": said,
            "num_turns": events.turns,
            "session_id": events.sid,
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
