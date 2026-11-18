"""出站闸门（§3.6.2；P0-4）：沙箱网络的唯一出口，按授权规则的 host:port 转发 TCP。

本文件在闸门容器里独立运行（`python -c <本文件源码> <JSON 配置>`），只用标准库，不 import 本项目的任何东西。
一个闸门顶替一台授权目标主机：它在沙箱网络上以该主机名为别名，所以沙箱里解析这个名字得到的是闸门。

配置：{"host": 主机名, "upstream": 目标在上游网络的地址, "allow_src": 执行容器的地址,
       "rules": [{"port": 端口, "actions": [动作…]}]}

规则的执行：
- actions 含 connect（或 *）的端口才监听并转发；其余端口不监听，连接被内核直接拒绝，和没写进授权范围一样。
- 只接受源地址是执行容器的连接：同一张网络上的别的容器过不了闸门。
- 每条连接在标准输出记一行 JSON（执行层在容器之外读它，用来填访问摘要）：
  {"event": "connect", "dst": "host:port", "ok": 上游是否接通, "t": 毫秒}
  {"event": "deny", "dst": "host:port", "why": "source", "src": 来源地址, "t": 毫秒}
"""

import json
import socket
import struct
import sys
import threading
import time
from typing import Any

OPEN_ACTIONS = {"connect", "*"}
_lock = threading.Lock()


def log(**kw: Any) -> None:
    kw["t"] = int(time.time() * 1000)
    with _lock:
        sys.stdout.write(json.dumps(kw, sort_keys=True) + "\n")
        sys.stdout.flush()


def reset(conn: socket.socket) -> None:
    """立刻以 RST 关闭：对端看到的是连接被重置，不是正常结束。"""
    try:
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    except OSError:
        pass
    conn.close()


def pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle(conn: socket.socket, peer: tuple[str, int], cfg: dict[str, Any], port: int) -> None:
    dst = f"{cfg['host']}:{port}"
    if peer[0] != cfg["allow_src"]:
        log(event="deny", dst=dst, why="source", src=peer[0])
        reset(conn)
        return
    try:
        up = socket.create_connection((cfg["upstream"], port), timeout=10)
    except OSError as e:
        log(event="connect", dst=dst, ok=False, error=type(e).__name__)
        reset(conn)
        return
    up.settimeout(None)
    log(event="connect", dst=dst, ok=True)
    back = threading.Thread(target=pipe, args=(up, conn), daemon=True)
    back.start()
    pipe(conn, up)
    back.join()
    conn.close()
    up.close()


def serve(sock: socket.socket, cfg: dict[str, Any], port: int) -> None:
    while True:
        conn, peer = sock.accept()
        threading.Thread(target=handle, args=(conn, peer, cfg, port), daemon=True).start()


def main(cfg: dict[str, Any]) -> None:
    socks: list[tuple[socket.socket, int]] = []
    for rule in cfg["rules"]:
        opened = bool(OPEN_ACTIONS & set(rule["actions"]))
        log(event="rule", dst=f"{cfg['host']}:{rule['port']}", actions=sorted(rule["actions"]), open=opened)
        if not opened:
            continue
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", int(rule["port"])))
        s.listen(128)
        socks.append((s, int(rule["port"])))
    for s, port in socks:
        threading.Thread(target=serve, args=(s, cfg, port), daemon=True).start()
    log(event="ready", host=cfg["host"], ports=[p for _, p in socks])
    threading.Event().wait()


if __name__ == "__main__":
    main(json.loads(sys.argv[1]))
