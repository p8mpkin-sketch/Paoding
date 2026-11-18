"""流式采集（§3.6.2）：命令输出边读边落盘，内存里只有一个读块。

`Capture` 是一个定长的落盘缓冲：前 `limit // 2` 字节顺序写，其后的字节写进一个环，
所以无论命令吐出多少，磁盘占用不超过 `limit`，留下的是头与尾（§3.2.2 的截断约定）。
`pump` 把一个子进程的输出逐块读进 `Capture`，并在墙钟到点时杀掉它。
"""
from __future__ import annotations

import os
import select
import subprocess
import tempfile
import time
from collections.abc import Iterator

CHUNK = 64 * 1024


class Capture:
    def __init__(self, limit: int, spool_dir: str | None = None):
        if limit < 2:
            raise ValueError("limit 至少 2 字节")
        self.limit, self.half = limit, limit // 2
        self._tail = limit - self.half
        self._f = tempfile.TemporaryFile(dir=spool_dir)
        self._ring = 0                    # 环里下一个写入位置；进入环之后也是最旧字节的位置
        self.total = 0                    # 命令实际吐出的字节数

    @property
    def stored(self) -> int:
        return min(self.total, self.limit)

    @property
    def truncated(self) -> bool:
        return self.total > self.limit

    def write(self, chunk: bytes) -> None:
        mv = memoryview(chunk)
        if self.total < self.limit:                           # 顺序段：文件内容就是输出本身
            n = min(len(mv), self.limit - self.total)
            self._f.seek(self.total)
            self._f.write(mv[:n])
            self.total += n
            mv = mv[n:]
        while len(mv):                                        # 环：只保留最后 _tail 字节
            n = min(len(mv), self._tail - self._ring)
            self._f.seek(self.half + self._ring)
            self._f.write(mv[:n])
            self._ring = (self._ring + n) % self._tail
            self.total += n
            mv = mv[n:]

    def _segments(self) -> list[tuple[int, int]]:
        """留存内容在文件里的 (偏移, 长度)，按输出的先后排列。"""
        if not self.truncated:
            return [(0, self.total)]
        return [(0, self.half), (self.half + self._ring, self._tail - self._ring), (self.half, self._ring)]

    def chunks(self, start: int = 0, end: int | None = None) -> Iterator[bytes]:
        """留存内容的 [start, end) 区间，逐块给出。"""
        end = self.stored if end is None else min(end, self.stored)
        pos = 0
        for off, length in self._segments():
            lo, hi = max(start, pos), min(end, pos + length)
            at = off + (lo - pos)
            while lo < hi:
                self._f.seek(at)
                data = self._f.read(min(CHUNK, hi - lo))
                if not data:
                    return
                yield data
                lo += len(data)
                at += len(data)
            pos += length

    def read(self, start: int = 0, end: int | None = None) -> bytes:
        return b"".join(self.chunks(start, end))

    def reader(self) -> _Reader:
        """留存内容的只读流，交给 Blob 仓库逐块写入。"""
        return _Reader(self)

    def close(self) -> None:
        self._f.close()

    def __enter__(self) -> Capture:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class _Reader:
    def __init__(self, cap: Capture):
        self._cap, self._pos = cap, 0

    def read(self, n: int = -1) -> bytes:
        end = self._cap.stored if n is None or n < 0 else min(self._cap.stored, self._pos + n)
        data = self._cap.read(self._pos, end)
        self._pos += len(data)
        return data


def pump(argv: list[str], cap: Capture, deadline_s: float) -> tuple[int | None, float]:
    """运行 argv，把标准输出与标准错误（合并以保序）逐块读进 cap。

    返回 (退出码, 耗时秒)。到 deadline_s 还没结束就杀掉子进程，退出码给 None。"""
    t0 = time.monotonic()
    p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
    assert p.stdout is not None
    fd = p.stdout.fileno()
    killed = False
    try:
        while True:
            left = deadline_s - (time.monotonic() - t0)
            if left <= 0:
                killed = True
                break
            ready, _, _ = select.select([fd], [], [], min(left, 1.0))
            if not ready:
                continue
            chunk = os.read(fd, CHUNK)
            if not chunk:                                     # 写端全部关闭：命令及其后代都结束了
                break
            cap.write(chunk)
    finally:
        if killed or p.poll() is None:
            if killed:
                p.kill()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        p.stdout.close()
    return (None if killed else p.returncode), time.monotonic() - t0
