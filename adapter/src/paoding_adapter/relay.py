"""端点中继：在模型容器所在的内部网络上代表容器外的两个端点（端点代理、工具端点）。

模型容器的网络是 `--internal` 的，没有出站路由，也到不了宿主。它能连到的只有同一张网络上的这个中继；
中继把每个监听端口的字节流原样转给一个挂载进来的 Unix 套接字，套接字另一头是 Adapter 进程（container.py
的 UnixBridge），再转到本机回环上的端点。中继不看内容、不持有任何密钥或令牌。

用法（容器内，python -I）：relay.py <端口>=<套接字路径> [<端口>=<套接字路径> …]
只用标准库；不导入工作区里的任何东西。
"""

import socket
import sys
import threading
from collections.abc import Callable

Connect = Callable[[], socket.socket]  # 给出一条到上游的连接


def pump(a: socket.socket, b: socket.socket) -> None:
    try:
        while chunk := a.recv(65536):
            b.sendall(chunk)
    except OSError:
        pass
    finally:
        for s, how in ((b, socket.SHUT_WR), (a, socket.SHUT_RD)):
            try:
                s.shutdown(how)
            except OSError:
                pass


def bridge(client: socket.socket, connect: Connect) -> None:
    """connect() 给出上游连接；两个方向各一个线程，任一方向读完就半关另一头。"""
    try:
        up = connect()
    except OSError:
        client.close()
        return
    t = threading.Thread(target=pump, args=(client, up), daemon=True)
    t.start()
    pump(up, client)
    t.join()
    client.close()
    up.close()


def accept_loop(srv: socket.socket, connect: Connect) -> None:
    while True:
        try:
            client, _ = srv.accept()
        except OSError:
            return
        threading.Thread(target=bridge, args=(client, connect), daemon=True).start()


def to_unix(path: str) -> Connect:
    def connect() -> socket.socket:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(path)
        return s

    return connect


def main(argv: list[str]) -> int:
    threads = []
    for spec in argv:
        port, _, path = spec.partition("=")
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", int(port)))
        srv.listen(64)
        t = threading.Thread(target=accept_loop, args=(srv, to_unix(path)), daemon=True)
        t.start()
        threads.append(t)
    sys.stdout.write("ready\n")
    sys.stdout.flush()
    for t in threads:
        t.join()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
