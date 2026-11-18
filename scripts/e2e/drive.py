"""端到端驱动：扮演人，经 HTTP 开一道自带答案摘要的小题，然后只旁观到终态，最后输出摘要。

    python scripts/e2e/drive.py --url http://127.0.0.1:8100 --token-file <home>/human.token [--pid e2e] [--timeout 180]

人只做开题这一件事；之后的每条事件都由组件写入。输出一行 JSON：终态、事件数、耗时、预算消耗。
只用标准库，可以在任何 Python 3.12 下跑。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request

STATEMENT = "在执行环境里算出 6 乘 7 的结果，把结果原样提交。".encode()
ANSWER = b"42"


def call(url: str, path: str, body=None, token: str | None = None, raw: bytes | None = None) -> dict:
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    method = "PUT" if raw is not None else ("GET" if body is None else "POST")
    headers = {"Content-Type": "application/octet-stream" if raw is not None else "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read())


def open_problem(url: str, token: str, pid: str) -> dict:
    h = call(url, "/v1/blobs", token=token, raw=STATEMENT)["hash"]
    return call(url, "/v1/problems", {"id": pid, "idem_key": f"open-{pid}", "ops": [
        {"op": "register_artifact", "body": {"hash": h, "size": len(STATEMENT), "media_type": "text/plain; charset=utf-8",
                                              "class": "input"}},
        {"op": "open_problem", "body": {
            "title": "算出 6×7", "origin": {"statement_ref": "$0", "materials": []},
            "goal": {"statement": "提交 6 乘 7 的结果",
                     "check": {"judge_id": "exact_match", "expect": {"sha256": hashlib.sha256(ANSWER).hexdigest()}},
                     "max_attempts": 3, "accept": "judge"},
            "scope": [{"resource": "workspace", "pattern": "*", "actions": ["read", "write"], "risk": "r0"}],
            "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
            "env": {"base": "basic", "baseline_ref": "basic@1"}, "judges": ["exact_match", "replay"]}}]}, token=token)


def wait_terminal(url: str, pid: str, timeout_s: float) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        st = call(url, f"/v1/problems/{pid}/status")
        if st["problem"].get("closed"):
            return st
        time.sleep(0.5)
    return call(url, f"/v1/problems/{pid}/status")


def summary(url: str, pid: str, t0: float) -> dict:
    st = call(url, f"/v1/problems/{pid}/status")
    b = call(url, f"/v1/problems/{pid}/budget")
    evs = call(url, f"/v1/problems/{pid}/events?after=0&limit=5000")["events"]
    kinds: dict[str, int] = {}
    for e in evs:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    close = next((e for e in evs if e["kind"] == "close_problem"), None)
    return {"pid": pid, "terminal": st["problem"].get("terminal"), "closed": bool(st["problem"].get("closed")),
            "closed_by": close["actor"]["kind"] if close else None,
            "events": len(evs), "by_kind": kinds, "elapsed_s": round(time.monotonic() - t0, 2),
            "spent_usd_milli": b["spent"]["usd_milli"], "reserved_usd_milli": b["reserved"]["usd_milli"],
            "cap_usd_milli": b["cap"]["usd_milli"], "by_task_kind": b["by_kind"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--pid", default="e2e")
    ap.add_argument("--timeout", type=float, default=180)
    a = ap.parse_args()
    token = open(a.token_file, encoding="utf-8").read().strip()
    t0 = time.monotonic()
    opened = open_problem(a.url, token, a.pid)
    if not opened.get("ok"):
        print(json.dumps({"error": "open_problem rejected", "detail": opened}, ensure_ascii=False))
        return 1
    wait_terminal(a.url, a.pid, a.timeout)
    s = summary(a.url, a.pid, t0)
    print(json.dumps(s, ensure_ascii=False))
    return 0 if s["terminal"] == "solved" else 1


if __name__ == "__main__":
    sys.exit(main())
