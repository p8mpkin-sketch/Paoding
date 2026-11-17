"""脚本化假 CLI（3.4.5 的 1、2、7）。离线预备阶段代替真 CLI，接受同一组参数。

它做真 CLI 在这条链上该做的事，但“想什么”由脚本决定：
- 每一步先向 ANTHROPIC_BASE_URL 发一次 /v1/messages（带 ANTHROPIC_API_KEY，即任务令牌），让代理计量；
- 再执行一个工具：内置工具只认 --tools 列出的那些，--restricted 下文件工具不出工作目录；
  MCP 工具经 --mcp-config 里的地址调用（initialize → tools/list → tools/call）；
- 按 stream-json 输出事件：首个 system/init，末行 result。

脚本（JSON，路径由 PD_FAKE_SCRIPT 给出）：{"steps": [...], "resume_steps": [...]}。
步骤：{"tool": 名, "input": {...}} | {"exit": 码} | {"hang": 秒}。
input 里形如 "$r3.artifact" 的字符串替换为第 3 步工具结果的字段（步号从 0 起）。
只用标准库；以 python -I 运行，不导入工作区里的任何东西。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def parse(argv):
    flags, i = {}, 0
    booleans = {"--verbose", "--bare", "--restricted", "--strict-mcp-config"}
    while i < len(argv):
        a = argv[i]
        if a in booleans:
            flags[a] = True
            i += 1
        elif a.startswith("-"):
            flags[a] = argv[i + 1]
            i += 2
        else:
            i += 1
    return flags


def emit(ev):
    sys.stdout.write(json.dumps(ev, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def post(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
            return r.status, (json.loads(data) if data else None)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


class Mcp:
    def __init__(self, url):
        self.url, self.n = url, 0
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "fakecli", "version": "0"}})
        post(self.url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, {})
        self.tools = [t["name"] for t in self.rpc("tools/list", {})["tools"]]

    def rpc(self, method, params):
        self.n += 1
        _, out = post(self.url, {"jsonrpc": "2.0", "id": self.n, "method": method, "params": params}, {})
        if "error" in out:
            raise RuntimeError(out["error"]["message"])
        return out["result"]


def subst(v, results):
    if isinstance(v, str) and v.startswith("$r") and "." in v:
        n, key = v[2:].split(".", 1)
        return results[int(n)].get(key)
    if isinstance(v, list):
        return [subst(x, results) for x in v]
    if isinstance(v, dict):
        return {k: subst(x, results) for k, x in v.items()}
    return v


def builtin(name, inp, allowed, restricted, cwd):
    if name not in allowed:
        return True, f"No such tool available: {name}"
    p = Path(inp.get("file_path") or inp.get("path") or ".")
    p = (cwd / p).resolve() if not p.is_absolute() else p.resolve()
    if restricted and p != cwd and cwd not in p.parents:
        return True, f"Access denied: {p} is outside the working directory"
    if name == "Read":
        return (False, p.read_text()) if p.is_file() else (True, "File does not exist")
    if name == "Write":
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(inp["content"])
        return False, f"Wrote {p}"
    if name == "Glob":
        return False, "\n".join(sorted(str(x) for x in p.glob(inp.get("pattern", "*"))))
    return True, f"{name} not simulated"


def main():
    flags = parse(sys.argv[1:])
    script = json.loads(Path(os.environ["PD_FAKE_SCRIPT"]).read_text())
    steps = script.get("resume_steps", []) if "--resume" in flags else script.get("steps", [])
    base, key = os.environ.get("ANTHROPIC_BASE_URL", ""), os.environ.get("ANTHROPIC_API_KEY", "")
    cfg = json.loads(Path(flags["--mcp-config"]).read_text())["mcpServers"]
    allowed = [t for t in flags.get("--tools", "").split(",") if t]
    restricted = bool(flags.get("--restricted"))
    cwd = Path.cwd().resolve()
    mcps = {name: Mcp(s["url"]) for name, s in cfg.items()}
    tools = allowed + [f"mcp__{n}__{t}" for n, m in mcps.items() for t in m.tools]
    sid = flags.get("--session-id") or flags.get("--resume")
    emit({"type": "system", "subtype": "init", "session_id": sid, "tools": tools,
          "mcp_servers": [{"name": n, "status": "connected"} for n in mcps], "cwd": str(cwd)})
    results, turns, cost = [], 0, 0.0
    for step in steps:
        if "exit" in step:
            sys.exit(step["exit"])
        if "hang" in step:
            time.sleep(step["hang"])
            continue
        turns += 1
        st, msg = post(base.rstrip("/") + "/v1/messages",
                       {"model": step.get("model", "claude-sonnet-5-5"), "max_tokens": 1024, "messages": []},
                       {"x-api-key": key, "anthropic-version": "2023-06-01"})
        if st != 200:
            emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
                  "result": f"API Error: {st} {json.dumps(msg)}", "num_turns": turns, "total_cost_usd": cost})
            sys.exit(1)
        emit({"type": "assistant", "message": {"usage": msg.get("usage", {}), "content": [
            {"type": "tool_use", "id": f"t{turns}", "name": step["tool"], "input": step.get("input", {})}]}})
        name, inp = step["tool"], subst(step.get("input", {}), results)
        if name.startswith("mcp__"):
            _, server, tool = name.split("__", 2)
            if server not in mcps or tool not in mcps[server].tools:
                err, out = True, f"No such tool available: {name}"
            else:
                r = mcps[server].rpc("tools/call", {"name": tool, "arguments": inp})
                err, out = r.get("isError", False), r.get("structuredContent")
        else:
            err, out = builtin(name, inp, allowed, restricted, cwd)
        results.append(out if isinstance(out, dict) else {"text": out, "is_error": err})
        emit({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{turns}", "is_error": err,
             "content": out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "num_turns": turns,
          "total_cost_usd": cost, "session_id": sid})


if __name__ == "__main__":
    main()
