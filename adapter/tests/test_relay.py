"""端点中继的两种上游：Unix 套接字（模型容器）与 tcp:<主机>:<端口>（Docker Desktop 上评测台的 baseline）。

不需要 Docker。"""

from __future__ import annotations

import socket
import threading
from pathlib import Path

from paoding_adapter import relay


def _echo(srv: socket.socket) -> None:
    conn, _ = srv.accept()
    conn.sendall(b"up:" + conn.recv(100))
    conn.close()


def _through(connect: relay.Connect) -> bytes:
    """经 relay.bridge 转一次：客户端写 ping，读回上游的应答。"""
    front = socket.socket()
    front.bind(("127.0.0.1", 0))
    front.listen(1)
    threading.Thread(target=relay.accept_loop, args=(front, connect), daemon=True).start()
    c = socket.create_connection(front.getsockname(), timeout=5)
    c.sendall(b"ping")
    c.shutdown(socket.SHUT_WR)
    out = b""
    while chunk := c.recv(100):
        out += chunk
    c.close()
    front.close()
    return out


def test_tcp_upstream() -> None:
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    threading.Thread(target=_echo, args=(srv,), daemon=True).start()
    assert _through(relay.upstream(f"tcp:127.0.0.1:{srv.getsockname()[1]}")) == b"up:ping"


def test_unix_upstream_is_default(tmp_path: Path) -> None:
    path = tmp_path / "s.sock"
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(1)
    threading.Thread(target=_echo, args=(srv,), daemon=True).start()
    assert _through(relay.upstream(str(path))) == b"up:ping"
