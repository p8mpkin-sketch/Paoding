"""端点代理自检：不起全栈，只看“CLI → 端点代理 → 模型端点”这一段通不通。

    ANTHROPIC_API_KEY=sk-... uv run python scripts/check_proxy.py \\
        --upstream https://api.deepseek.com/anthropic --model deepseek-chat [--cli claude]

做三件事，每步打印状态码、耗时、上游给的 usage 与折算的毫美元：
1. 经代理发一个非流式 /v1/messages
2. 经代理发一个流式 /v1/messages
3. 给了 --cli：用真 CLI（-p 一句话）经代理跑一轮，CLI 的 stderr 原样打出来

真实密钥只交给本进程里的代理；CLI 拿到的是一次性的任务令牌。不写图服务、不留数据（计量写进一个空的桩）。
密钥也可以放进 --key-env 指定的环境变量。退出码：全部通过 0，否则 1。
"""

from __future__ import annotations

import argparse
import gzip
import http.client
import json
import logging
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from paoding_adapter.proxy import EndpointProxy, PriceTable, ProxyConfig  # noqa: E402

PRICES = ROOT / "adapter" / "config" / "prices.yaml"


class _Ledger:
    """代理入账要一个图服务；自检不落盘，记下来打印即可。"""

    def __init__(self) -> None:
        self.costs: list[dict] = []

    def submit(self, token: str, pid: str, idem: str, ops: list[dict]) -> dict:
        self.costs += [op["body"] for op in ops]
        return {"ok": True, "results": [{"ok": True, "id": idem}]}


def _post(url: str, token: str, model: str, stream: bool) -> tuple[int, float, bytes]:
    u = url.removeprefix("http://")
    host, port = u.rsplit(":", 1)
    c = http.client.HTTPConnection(host, int(port), timeout=120)
    body = json.dumps(
        {"model": model, "max_tokens": 16, "stream": stream, "messages": [{"role": "user", "content": "回一个字：好"}]}
    )
    t0 = time.monotonic()
    c.request(
        "POST",
        "/v1/messages",
        body=body,
        headers={"x-api-key": token, "content-type": "application/json", "anthropic-version": "2023-06-01"},
    )
    r = c.getresponse()
    data = r.read()
    if r.getheader("content-encoding", "") == "gzip":  # 上游不理 identity 时代理原样转发压缩的正文
        data = gzip.decompress(data)
    c.close()
    return r.status, time.monotonic() - t0, data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="check_proxy.py", description="端点代理自检")
    ap.add_argument("--upstream", required=True, help="模型端点，例如 https://api.deepseek.com/anthropic")
    ap.add_argument("--model", required=True, help="例如 deepseek-chat")
    ap.add_argument("--key-env", default="ANTHROPIC_API_KEY", help="真实密钥所在的环境变量（缺省 ANTHROPIC_API_KEY）")
    ap.add_argument("--cli", default="", help="真 CLI 的命令（例如 claude）；不给就不跑第 3 步")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
    key = os.environ.get(a.key_env, "")
    if not key:
        print(f"环境变量 {a.key_env} 没有设：真实密钥从这里读", file=sys.stderr)
        return 1
    ledger = _Ledger()
    proxy = EndpointProxy(ProxyConfig(a.upstream, key, "check"), PriceTable.load(PRICES), ledger)  # type: ignore[arg-type]
    proxy.serve()
    token = secrets.token_urlsafe(16)
    proxy.register_task(token, "check", "check", 1_000_000)
    ok = True
    try:
        for stream in (False, True):
            st, dt, data = _post(proxy.url, token, a.model, stream)
            good = st == 200 and (b"message_stop" in data if stream else b'"usage"' in data)
            ok &= good
            print(f"{'流式' if stream else '非流式'}：HTTP {st}，{dt:.1f} 秒，{'通过' if good else '失败'}")
            if not good:
                print("  正文头：", data[:400].decode("utf-8", "replace"))
        if a.cli:
            with tempfile.TemporaryDirectory() as home:
                env = {
                    "ANTHROPIC_BASE_URL": proxy.url,
                    "ANTHROPIC_API_KEY": token,
                    "HOME": home,
                    "PATH": os.environ.get("PATH", ""),
                    "LANG": "C.UTF-8",
                }
                cmd = [*a.cli.split(), "-p", "回一个字：好", "--bare", "--model", a.model, "--output-format", "json"]
                t0 = time.monotonic()
                r = subprocess.run(cmd, env=env, capture_output=True, stdin=subprocess.DEVNULL, timeout=300)
                good = r.returncode == 0
                ok &= good
                print(f"真 CLI：退出码 {r.returncode}，{time.monotonic() - t0:.1f} 秒，{'通过' if good else '失败'}")
                print("  stdout 尾：", r.stdout.decode("utf-8", "replace")[-400:])
                if r.stderr:
                    print("  stderr 尾：", r.stderr.decode("utf-8", "replace")[-800:])
        total = sum(c["usd_milli"] for c in ledger.costs)
        print(f"计量：{len(ledger.costs)} 个请求，合计 {total} 毫美元（{[c['model'] for c in ledger.costs]}）")
        ok &= bool(ledger.costs) and total > 0
    finally:
        proxy.close()
    print("全部通过" if ok else "有失败，见上面与代理日志（logger adapter）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
