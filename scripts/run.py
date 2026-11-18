"""一键起全栈：图服务（HTTP + SSE）→ 判官运行器 → 司南 → 哮天犬，共用一个数据目录。

    uv run python scripts/run.py --home /tmp/paoding-run --port 8100

配置文件（YAML）缺省读 <home>/config.yaml，没有就是空配置：会话后端是假 CLI（不需要任何密钥），
执行层是本机 Docker，司南不开没有脚本的任务种类。形状见 scripts/e2e/config.yaml。

Ctrl+C（或 SIGTERM）优雅退出：叫停在途会话、销毁执行容器、关掉全部服务；再按一次立刻退出。
日志是结构化的：一行一个 JSON 对象（时间、级别、组件名、消息、上下文 ID），写 stderr 与 <home>/logs/stack.log；
--log-format text 把 stderr 换成给人看的单行格式（文件仍是 JSON）。字段见 scripts/oplog.py，运维说明见 docs/ops.md。
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stack import Stack, StackConfig, StackError, default_static, log, setup_logging  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run.py", description="庖丁全栈（M0 单机）")
    ap.add_argument(
        "--home", required=True, type=Path, help="数据目录：g.sqlite、blobs/、vault/、sessions/、human.token"
    )
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--config", type=Path, help="配置文件（YAML）；缺省 <home>/config.yaml，没有就是空配置")
    ap.add_argument("--static", type=Path, help="前端构建产物；缺省用 web/dist（构建过的话）")
    ap.add_argument("--no-static", action="store_true", help="只起 API，不托管前端")
    ap.add_argument(
        "--allow-origin", action="append", help="放行的跨源来源；缺省只放 vite 开发服务器 http://127.0.0.1:5173"
    )
    ap.add_argument("--ready-file", type=Path, help="起好后把图服务地址写到这个文件（脚本等它用）")
    ap.add_argument("--log-format", choices=("json", "text"), help="stderr 的日志格式；缺省取配置的 log.format（json）")
    ap.add_argument(
        "--access-log", action="store_true", help="打开 HTTP 访问日志（缺省关；也可在配置里写 log.access: true）"
    )
    a = ap.parse_args(argv)
    setup_logging(fmt=a.log_format or "json")  # 配置读进来之前先有一个能用的 stderr
    static = None if a.no_static else (a.static or default_static())
    try:
        cfg = StackConfig.load(
            a.home.resolve(),
            a.config.resolve() if a.config else None,
            port=a.port,
            static_dir=static,
            allow_origins=tuple(a.allow_origin) if a.allow_origin else None,
        )
        if a.access_log:
            cfg.log["access"] = True
        setup_logging(level=cfg.log["level"], fmt=a.log_format or cfg.log["format"], file=cfg.log_file())
        stack = Stack(cfg)
        url = stack.start()
    except (StackError, ValueError) as e:
        log("stack").error("%s", e)
        return 2
    if static:
        log("stack").info("网页在 %s/ （右上角填人的令牌）", url)
    if a.ready_file:
        a.ready_file.write_text(url + "\n", encoding="utf-8")

    done = threading.Event()
    hits = [0]

    def on_signal(signum, _frame):
        hits[0] += 1
        if hits[0] > 1:  # 第二下：不等了
            log("stack").warning("再次收到 %s：立刻退出", signal.Signals(signum).name)
            for lid in list(stack.runner.live):
                stack.runner.kill(lid, "shutdown")
            if stack.executor is not None:
                stack.executor.close()
            os._exit(130)
        log("stack").info("收到 %s，开始停机（再按一次立刻退出）", signal.Signals(signum).name)
        done.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    while not done.wait(1.0):
        pass
    stack.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
