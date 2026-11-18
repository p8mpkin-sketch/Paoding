"""流式采集的落盘缓冲（P1-2）：不需要 Docker。对照是"整段读进内存再取头尾"的旧做法。"""

import random
import subprocess
import sys
import time

import pytest

from paoding_executor.capture import Capture, pump
from paoding_executor.runtime import echo


def reference(data: bytes, limit: int) -> bytes:
    half = limit // 2
    return data if len(data) <= limit else data[:half] + data[len(data) - (limit - half) :]


@pytest.mark.parametrize("seed", range(40))
def test_capture_matches_head_plus_tail(seed):
    rnd = random.Random(seed)
    limit = rnd.choice([2, 3, 7, 64, 100, 1000])
    data = bytes(
        rnd.randrange(256) for _ in range(rnd.choice([0, 1, limit - 1, limit, limit + 1, 3 * limit, 10 * limit + 3]))
    )
    with Capture(limit) as cap:
        pos = 0
        while pos < len(data):
            n = rnd.randint(1, max(1, limit))
            cap.write(data[pos : pos + n])
            pos += n
        want = reference(data, limit)
        assert cap.total == len(data) and cap.stored == len(want) and cap.truncated == (len(data) > limit)
        assert cap.read() == want and cap.reader().read() == want
        r, got = cap.reader(), b""
        while piece := r.read(5):
            got += piece
        assert got == want
        a, b = sorted((rnd.randint(0, len(want)), rnd.randint(0, len(want))))
        assert cap.read(a, b) == want[a:b]


def test_echo_reads_only_head_and_tail():
    with Capture(1000) as cap:
        cap.write(b"A" * 300 + b"B" * 5000 + b"C" * 300)
        text, cut = echo(cap, limit=100)
    assert cut and text.startswith("A" * 50) and text.endswith("C" * 50) and "省略 900 字节" in text
    assert echo(b"short") == ("short", False)


def test_pump_streams_and_reports_exit_code():
    with Capture(1 << 16) as cap:
        code, took = pump(
            [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(4)"], cap, 30
        )
        assert code == 4 and sorted(cap.read().split()) == [b"err", b"out"]


def test_pump_kills_at_the_deadline():
    t0 = time.monotonic()
    with Capture(1 << 16) as cap:
        code, took = pump([sys.executable, "-u", "-c", "import time; print('start'); time.sleep(60)"], cap, 1.0)
        assert code is None and cap.read() == b"start\n"
    assert time.monotonic() - t0 < 15


def test_pump_holds_one_chunk_not_the_whole_output():
    """50 MB 的输出进一个 1 MB 的缓冲：留存 1 MB，总量如实。"""
    with Capture(1 << 20) as cap:
        code, _ = pump(["head", "-c", str(50 << 20), "/dev/zero"], cap, 60)
        assert code == 0 and cap.total == 50 << 20 and cap.stored == 1 << 20 and cap.truncated
