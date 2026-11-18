"""压测（阶段二第 11 项）：给调度与 SSE 推送一组基准数字，作为"要不要做状态快照"的依据。

三组，互相独立，都不用真模型：

    uv run python scripts/bench/bench.py kernel [--events 20000] [--problems 4]
    uv run python scripts/bench/bench.py sse    [--clients 1,10,50,100] [--events 200]
    uv run python scripts/bench/bench.py sched  [--problems 1,4,8] [--sessions 1,3]   # 要 Docker

- kernel：进程内的图服务（SQLite 临时文件）。人连续写 Intent 与 Hint，按窗口记单次提交的延迟；
  再记冷启动全量重放、as_of 回放和状态体积随日志长度怎么变。这一组直接回答"启动全量重放什么时候变慢"。
- sse：子进程起 scripts/run.py（执行层 none），C 个客户端订同一道题的 /stream，写入方逐条提交，
  记"提交返回 → 每个客户端收到这一帧"的延迟分布。
- sched：子进程起 scripts/run.py（假 CLI + Docker 执行层），同时开 P 道 6×7 小题，记每道题开题到 solved
  的时间与总墙钟，比较 max_sessions 取不同值时的吞吐。

结果打印成 JSON（一行一个读数），--out 另存一份。数字随机器变，只在同一台机器上比较。
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT: list[dict[str, Any]] = []


def emit(**kw: Any) -> None:
    OUT.append(kw)
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def ms(x: float) -> float:
    return round(x * 1000, 3)


# ---------- 题目 ----------

STATEMENT = "在执行环境里算出 6 乘 7 的结果，把结果原样提交。".encode()
ANSWER = b"42"


def open_ops(statement_hash: str) -> list[dict[str, Any]]:
    return [
        {
            "op": "register_artifact",
            "body": {"hash": statement_hash, "size": len(STATEMENT), "media_type": "text/plain", "class": "input"},
        },
        {
            "op": "open_problem",
            "body": {
                "title": "算出 6×7",
                "origin": {"statement_ref": "$0", "materials": []},
                "goal": {
                    "statement": "提交 6 乘 7 的结果",
                    "check": {"judge_id": "exact_match", "expect": {"sha256": hashlib.sha256(ANSWER).hexdigest()}},
                    "max_attempts": 3,
                    "accept": "judge",
                },
                "scope": [{"resource": "workspace", "pattern": "*", "actions": ["read", "write"], "risk": "r0"}],
                "budget": {"usd_milli": 5_000_000, "wall_s": 360000, "verify_share": 0.2, "bootstrap_share": 0.3},
                "env": {"base": "basic", "baseline_ref": "basic@1"},
                "judges": ["exact_match", "replay"],
            },
        },
    ]


def human_op(i: int, premise: str | None = None) -> dict[str, Any]:
    if i % 2:
        return {"op": "hint", "body": {"text": f"第 {i} 条提示"}}
    return {
        "op": "add_intent",
        "body": {
            "title": f"第 {i} 步",
            "summary": "",
            "premises": [premise] if premise else [],
            "risk": "r0",
            "budget": {"usd_milli": 100},
        },
    }


# ---------- kernel ----------


def bench_kernel(a: argparse.Namespace) -> None:
    sys.path[:0] = [str(ROOT / p / "src") for p in ("graph",)]
    from paoding_graph.contract import Config, GraphService, TokenRegistry

    judges: dict[str, Any] = {
        "exact_match": {"version": "1", "grade": "decisive", "kind": "builtin", "max_cost": 0.0},
        "replay": {"version": "1", "grade": "decisive", "kind": "builtin", "max_cost": 0.01},
    }
    cfg = Config(judges=judges)
    tmp = Path(tempfile.mkdtemp(prefix="pd-bench-"))
    db = tmp / "g.sqlite"
    reg = TokenRegistry()
    reg.issue({"kind": "human", "id": "cz"}, "tok-human")
    svc = GraphService(db, cfg, reg)
    h = hashlib.sha256(STATEMENT).hexdigest()
    pids = [f"p{k}" for k in range(a.problems)]
    for pid in pids:
        out = svc.submit("tok-human", pid, f"open-{pid}", open_ops(h))
        assert out["ok"], out
    window, lat, last_intent = a.window, [], {pid: None for pid in pids}
    t_all = time.perf_counter()
    for i in range(a.events):
        pid = pids[i % len(pids)]
        premise = None  # 人写的 Intent 只能以论断或带判据的 Intent 为前提；这里只量节点数的影响
        t0 = time.perf_counter()
        out = svc.submit("tok-human", pid, f"e{i}", [human_op(i, premise)])
        lat.append(time.perf_counter() - t0)
        assert out["ok"], out
        if i % 2 == 0:
            last_intent[pid] = out["results"][0]["id"]
        if (i + 1) % window == 0:
            emit(
                bench="kernel.submit",
                events=svc.head(),
                per_problem_nodes=(i + 1) // 2 // len(pids),
                p50_ms=ms(pct(lat, 50)),
                p95_ms=ms(pct(lat, 95)),
                p99_ms=ms(pct(lat, 99)),
                throughput_eps=round(len(lat) / sum(lat), 1),
            )
            lat = []
    total = time.perf_counter() - t_all
    head = svc.head()
    state_bytes = len(json.dumps(svc.state, ensure_ascii=False).encode())
    emit(bench="kernel.total", events=head, wall_s=round(total, 2), state_json_mb=round(state_bytes / 1e6, 2))

    # 冷启动：新开一个 GraphService，从头重放日志（service.py 的构造函数）
    for _ in range(2):
        t0 = time.perf_counter()
        GraphService(db, cfg, reg)
        emit(bench="kernel.cold_start", events=head, replay_s=round(time.perf_counter() - t0, 3))
    # as_of 回放：冷缓存，取一半处与 90% 处
    for frac in (0.5, 0.9):
        fresh = GraphService(db, cfg, reg)
        seq = int(head * frac)
        t0 = time.perf_counter()
        fresh.state_at(seq)
        emit(bench="kernel.as_of_cold", events=head, as_of=seq, s=round(time.perf_counter() - t0, 3))
        t0 = time.perf_counter()
        fresh.state_at(seq + 1)
        emit(bench="kernel.as_of_next", events=head, as_of=seq + 1, s=round(time.perf_counter() - t0, 4))
    emit(
        bench="kernel.rss",
        max_rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        db_mb=round(db.stat().st_size / 1e6, 2),
    )
    shutil.rmtree(tmp, ignore_errors=True)


# ---------- 全栈子进程 ----------


class Stack:
    def __init__(self, port: int, config: str, scripts: bool = False):
        self.home = Path(tempfile.mkdtemp(prefix="pd-bench-stack-"))
        (self.home / "config.yaml").write_text(config, encoding="utf-8")
        ready = self.home / "ready"
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts/run.py"), "--home", str(self.home), "--port", str(port),
             "--no-static", "--ready-file", str(ready), "--log-format", "text"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=open(self.home / "stack.err", "wb"),
        )  # fmt: skip
        for _ in range(240):
            if ready.exists() and ready.read_text().strip():
                break
            if self.proc.poll() is not None:
                raise RuntimeError((self.home / "stack.err").read_text())
            time.sleep(0.25)
        self.url = ready.read_text().strip()
        self.host, self.port = self.url.split("//")[1].split(":")
        self.token = (self.home / "human.token").read_text().strip()

    def call(self, path: str, body: Any = None, raw: bytes | None = None) -> Any:
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        method = "PUT" if raw is not None else ("GET" if body is None else "POST")
        headers = {"Authorization": f"Bearer {self.token}"}
        headers["Content-Type"] = "application/octet-stream" if raw is not None else "application/json"
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    def open(self, pid: str) -> None:
        h = self.call("/v1/blobs", raw=STATEMENT)["hash"]
        out = self.call("/v1/problems", {"id": pid, "idem_key": f"open-{pid}", "ops": open_ops(h)})
        assert out["ok"], out

    def close(self) -> None:
        self.proc.send_signal(2)
        try:
            self.proc.wait(30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.home, ignore_errors=True)


class SseClient(threading.Thread):
    """读 /stream，记下每个 seq 的到达时刻（perf_counter）。"""

    def __init__(self, host: str, port: str, pid: str):
        super().__init__(daemon=True)
        self.host, self.port, self.pid = host, int(port), pid
        self.arrived: dict[int, float] = {}
        self.ready = threading.Event()
        self.stop = False

    def run(self) -> None:
        c = http.client.HTTPConnection(self.host, self.port, timeout=120)
        c.request("GET", f"/v1/problems/{self.pid}/stream")
        r = c.getresponse()
        seq, event = None, None
        while not self.stop:
            raw = r.fp.readline()
            if not raw:
                return
            line = raw.decode().rstrip("\n")
            if line.startswith("retry:"):
                self.ready.set()
            elif line.startswith("id: "):
                seq = int(line[4:])
            elif line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and seq is not None and event is None:
                self.arrived.setdefault(seq, time.perf_counter())
            elif line == "":
                seq, event = None, None


def bench_sse(a: argparse.Namespace) -> None:
    for i, c in enumerate(int(x) for x in a.clients.split(",")):
        st = Stack(a.port + i, "executor: none\npoll_s: 5\ndog_interval_s: 5\n")
        try:
            pid = "bench"
            st.open(pid)
            clients = [SseClient(st.host, st.port, pid) for _ in range(c)]
            for cl in clients:
                cl.start()
            for cl in clients:
                assert cl.ready.wait(30), "SSE 没连上"
            time.sleep(0.5)
            sent: dict[int, float] = {}
            lat_submit = []
            t_all = time.perf_counter()
            for k in range(a.events):
                t0 = time.perf_counter()
                out = st.call(f"/v1/problems/{pid}/proposals", {"idem_key": f"s{k}", "ops": [human_op(k)]})
                t1 = time.perf_counter()
                assert out["ok"], out
                lat_submit.append(t1 - t0)
                head = st.call(f"/v1/problems/{pid}/status")["as_of"]
                sent[head] = t1
                if a.interval_ms:
                    time.sleep(a.interval_ms / 1000)
            deadline = time.time() + 30
            while time.time() < deadline and any(len(cl.arrived) < len(sent) for cl in clients):
                time.sleep(0.1)
            wall = time.perf_counter() - t_all
            lat = [cl.arrived[s] - t for cl in clients for s, t in sent.items() if s in cl.arrived]
            missing = sum(1 for cl in clients for s in sent if s not in cl.arrived)
            emit(
                bench="sse.fanout",
                clients=c,
                events=len(sent),
                deliveries=len(lat),
                missing=missing,
                p50_ms=ms(pct(lat, 50)),
                p95_ms=ms(pct(lat, 95)),
                p99_ms=ms(pct(lat, 99)),
                max_ms=ms(max(lat) if lat else float("nan")),
                submit_p50_ms=ms(pct(lat_submit, 50)),
                submit_p99_ms=ms(pct(lat_submit, 99)),
                wall_s=round(wall, 2),
            )
            for cl in clients:
                cl.stop = True
        finally:
            st.close()


# ---------- sched ----------


def bench_sched(a: argparse.Namespace) -> None:
    e2e = ROOT / "scripts/e2e"
    runs = 0
    for sessions in (int(x) for x in a.sessions.split(",")):
        for p in (int(x) for x in a.problems.split(",")):
            cfg = (
                "backend:\n  kind: fake\n  scripts:\n"
                + "".join(f'    {k}: "{e2e / (k + ".json")}"\n' for k in ("bootstrap", "reason", "explore"))
                + "executor:\n  kind: docker\n  bases:\n    basic: python:3.12-slim\n"
                + f"poll_s: 0.3\ndog_interval_s: 1.0\nmax_sessions: {sessions}\n"
            )
            st = Stack(a.port + 100 + runs, cfg)
            runs += 1
            try:
                pids = [f"s{k}" for k in range(p)]
                t0 = time.perf_counter()
                opened = {}
                for pid in pids:
                    st.open(pid)
                    opened[pid] = time.perf_counter()
                done: dict[str, float] = {}
                terminal: dict[str, Any] = {}
                deadline = time.time() + a.timeout
                while len(done) < p and time.time() < deadline:
                    for pid in pids:
                        if pid in done:
                            continue
                        s = st.call(f"/v1/problems/{pid}/status")["problem"]
                        if s.get("closed"):
                            done[pid], terminal[pid] = time.perf_counter(), s.get("terminal")
                    time.sleep(0.2)
                per = [done[x] - opened[x] for x in done]
                emit(
                    bench="sched.solve",
                    max_sessions=sessions,
                    problems=p,
                    solved=sum(1 for t in terminal.values() if t == "solved"),
                    closed=len(done),
                    p50_s=round(pct(per, 50), 2),
                    max_s=round(max(per) if per else float("nan"), 2),
                    wall_s=round(time.perf_counter() - t0, 2),
                    problems_per_min=round(len(done) / (time.perf_counter() - t0) * 60, 1),
                    mean_s=round(statistics.mean(per), 2) if per else None,
                )
            finally:
                st.close()


def main() -> int:
    ap = argparse.ArgumentParser(prog="bench.py")
    ap.add_argument("--out", type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("kernel")
    k.add_argument("--events", type=int, default=20000)
    k.add_argument("--problems", type=int, default=4)
    k.add_argument("--window", type=int, default=2000)
    s = sub.add_parser("sse")
    s.add_argument("--clients", default="1,10,50,100")
    s.add_argument("--events", type=int, default=200)
    s.add_argument("--interval-ms", type=int, default=0)
    s.add_argument("--port", type=int, default=8710)
    c = sub.add_parser("sched")
    c.add_argument("--problems", default="1,4,8")
    c.add_argument("--sessions", default="1,3")
    c.add_argument("--timeout", type=float, default=600)
    c.add_argument("--port", type=int, default=8810)
    a = ap.parse_args()
    {"kernel": bench_kernel, "sse": bench_sse, "sched": bench_sched}[a.cmd](a)
    if a.out:
        a.out.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in OUT) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    sys.exit(main())
