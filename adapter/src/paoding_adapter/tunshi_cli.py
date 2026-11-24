"""方案分析的驱动程序（docs/design/fenjue/13-kernel.md §3）：在模型容器里代替 CLI 跑固定流程。

会话运行器照起 CLI 的办法起它：同一组参数（只认 `--mcp-config`、`--session-id` / `--resume`、`--model`），同样的
环境（`ANTHROPIC_BASE_URL` 是端点代理，`ANTHROPIC_API_KEY` 是任务令牌），stdout 上同形的 stream-json 事件流。
它手里没有真实密钥、没有图服务的令牌、没有出站网络，只有任务令牌与宿主的四个工具（`paoding_adapter.tunshi`）。

它做三件事，其余都在 `paoding_fenjue` 的引擎里（`analysis.Session`）：

1. 工具：经 MCP 调宿主的 `intake`、`fetch`、`check`、`deliver`；
2. 模型：把引擎的每一次调用渲染成一条 Messages 请求发给端点代理，按档位取模型；429 的预算拒绝交回引擎停在
   当前单元，暂时性的失败有限次重试，重试不过交回“端点调不通”；
3. 事件：每次模型调用、每次工具调用各出事件，活动面板据此显示在做哪一步；事件里只有步骤名、对象编号与用量，
   不带外部原文，也不带模型的输出。

这里用标准库直接发 HTTP，而不用官方 SDK：它跑在只有 Python 标准库的模型容器里，请求必须经我们自己的端点代理
计量（T3），而且每次调用都是无工具、非流式的一问一答，没有 SDK 能省掉的东西。请求体不带采样参数与思考配置。

只用标准库与 `paoding_fenjue.contract`、`paoding_graph`（都只用标准库）；以 `python -I` 运行。
容器里这两个包挂在 `PD_LIB` 指的目录下。
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Mapping
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
HTTP_TIMEOUT_S = 900.0  # 一次模型调用或一次工具调用（fetch 在沙箱里下载）最长等这么久
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
    """真模型的调用（`Dan`）：一次调用 = 一条 Messages 请求，经端点代理。"""

    def __init__(
        self,
        base_url: str,
        token: str,
        form_ref: str,
        models: Mapping[str, str],
        default_model: str,
        events: Events,
        sleep: Any = time.sleep,
    ) -> None:
        self.url = base_url.rstrip("/") + "/v1/messages"
        self.token, self.form_ref, self.models, self.default_model = token, form_ref, dict(models), default_model
        self.events, self.sleep = events, sleep

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
        }
        headers = {"x-api-key": self.token, "anthropic-version": API_VERSION}
        self.events.say(pills.label(role, key))
        last = ""
        for wait in (*RETRY_WAITS, None):
            status, out = post(self.url, body, headers, HTTP_TIMEOUT_S)
            if status == 200 and isinstance(out, dict):
                return self._reply(model, out)
            kind = _error_type(out)
            last = f"{status or '连不上'} {kind or (out if isinstance(out, str) else '')}".strip()[:300]
            if status == 429 and kind in BUDGET_SCOPES:
                raise BudgetExhausted(BUDGET_SCOPES[kind], last)
            if status == 401:  # 任务令牌已撤（会话正在被收掉）：不重试
                raise Unavailable(f"任务令牌已失效（{last}）")
            if status not in RETRYABLE and status != 0:
                # 400、403、404、413 一类：配置或请求本身的问题，重试与接力都救不了，如实交给人
                raise EngineError(f"模型端点拒绝了请求（{last}）；请检查这个档位的模型与端点配置")
            if wait is None:
                break
            self.sleep(wait)
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
    dan = ModelDan(base, token, str(brief["form"]), brief.get("models") or {}, str(flags.get("--model") or ""), events)
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
