"""最小外部平台模拟（docs/design/external-verdict/ §1.1）：清单、说明、提交、回执四类端点，标准库 HTTP，跑在本机。

复现（test_external_verdict_repro.py）、翻转（test_external_verdict_flip.py）与 judgebox 的 connector 运行器测试共用。
口令、令牌、端口都是现场随机生成的假数据。另带一份与它配套的连接器档案（profile()），供各处写进临时 connectors.d。
"""

from __future__ import annotations

import itertools
import json
import secrets
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class Platform:
    """四类端点。凭据是一条 Bearer 令牌（真实部署里它归钥匙环管，见设计 §5.6）。

    GET  /api/tasks                       任务清单：id、标题、时限、提交次数上限
    GET  /api/tasks/{id}                  说明：题面；领题即开始计时，服务地址此刻现分配
    POST /api/tasks/{id}/submissions      提交：{answer} → 202 {submission_id}
    GET  /api/submissions/{sid}           回执：先 pending 若干次，再 accepted / rejected（平台说了算）
    """

    TIME_LIMIT_S = 6 * 3600
    MAX_SUBMISSIONS = 3
    PENDING_POLLS = 2

    def __init__(self) -> None:
        self.token = "plat-" + secrets.token_hex(8)
        self.flag = "FLAG-" + secrets.token_hex(6)  # 只有平台知道；本地任何一方都拿不到
        self.ports = itertools.count(31000)
        self.started: dict[str, str] = {}  # task → 本次领题分到的服务地址
        self.subs: dict[str, dict[str, Any]] = {}
        self.log: list[str] = []
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.srv.shutdown()

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        plat = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def _send(self, code: int, body: Any) -> None:
                data = json.dumps(body, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authed(self) -> bool:
                if self.headers.get("Authorization") != f"Bearer {plat.token}":
                    self._send(401, {"error": "unauthorized"})
                    return False
                return True

            def do_GET(self) -> None:  # noqa: N802
                if not self._authed():
                    return
                plat.log.append(f"GET {self.path}")
                parts = self.path.strip("/").split("/")
                if parts == ["api", "tasks"]:
                    return self._send(
                        200,
                        [
                            {
                                "id": "T-17",
                                "title": "找出服务里的口令",
                                "time_limit_s": plat.TIME_LIMIT_S,
                                "max_submissions": plat.MAX_SUBMISSIONS,
                            }
                        ],
                    )
                if parts[:2] == ["api", "tasks"] and len(parts) == 3:
                    addr = f"127.0.0.1:{next(plat.ports)}"  # 每次领题现分配：开题时无从预测
                    plat.started[parts[2]] = addr
                    return self._send(
                        200,
                        {
                            "id": parts[2],
                            "statement": "服务里藏着一个口令，找到后提交给平台。平台按回执判定，限时与计分由平台规定。",
                            "instance": addr,
                            "time_limit_s": plat.TIME_LIMIT_S,
                        },
                    )
                if parts[:2] == ["api", "submissions"] and len(parts) == 3:
                    s = plat.subs.get(parts[2])
                    if s is None:
                        return self._send(404, {"error": "no such submission"})
                    s["polls"] += 1
                    if s["polls"] <= plat.PENDING_POLLS:
                        return self._send(200, {"id": parts[2], "task": s["task"], "status": "pending"})
                    ok = s["answer"] == plat.flag
                    return self._send(
                        200,
                        {
                            "id": parts[2],
                            "task": s["task"],
                            "status": "accepted" if ok else "rejected",
                            "score": 100 * ok,
                        },
                    )
                self._send(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                if not self._authed():
                    return
                plat.log.append(f"POST {self.path}")
                parts = self.path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["api", "tasks"] and parts[3] == "submissions":
                    n = sum(1 for s in plat.subs.values() if s["task"] == parts[2])
                    if n >= plat.MAX_SUBMISSIONS:
                        return self._send(429, {"error": "submission limit"})
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                    sid = "s-" + secrets.token_hex(4)
                    plat.subs[sid] = {"task": parts[2], "answer": body.get("answer"), "polls": 0}
                    return self._send(202, {"submission_id": sid})
                self._send(404, {"error": "not found"})

        return H

    # 测试方的动作：读清单与说明，把任务的自然语言描述拼出来贴进一句话开题
    def get(self, path: str) -> Any:
        req = urllib.request.Request(self.base + path, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def post(self, path: str, body: Any) -> Any:
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def pasted(self, with_example: bool = False) -> str:
        t = self.get("/api/tasks")[0]
        hours = t["time_limit_s"] // 3600
        text = (
            f"平台任务 {t['id']}（{self.base}/tasks/{t['id']}）：{t['title']}。"
            "服务里藏着一个口令，找到后提交给平台，平台回执判定通过就算完成。"
            f"服务地址领题后由平台返回。限时 {hours} 小时，每题最多提交 {t['max_submissions']} 次。"
        )
        if with_example:  # 平台说明里常见的"提交示例"
            text += f'提交方式：`curl -X POST {self.base}/api/tasks/{t["id"]}/submissions -d \'{{"answer":"..."}}\'`'
        return text


def profile(plat: Platform, *, cid: str = "mock-platform", deliver: str = "judge") -> dict[str, Any]:
    """与平台模拟配套的连接器档案（§5.1 的格式）。凭据只写槽位名；值由钥匙环注入。"""
    return {
        "id": cid,
        "version": "1",
        "base_url": plat.base,
        "match": {"hosts": ["127.0.0.1"]},
        "task_ref": {"pattern": "T-[0-9]+"},
        "credential": {"key_slot": "mock-platform"},
        "endpoints": {
            "list": {"method": "GET", "path": "/api/tasks"},
            "brief": {"method": "GET", "path": "/api/tasks/{task}"},
            "submit": {"method": "POST", "path": "/api/tasks/{task}/submissions", "body": {"answer": "$candidate"}},
            "receipt": {"method": "GET", "path": "/api/submissions/{sid}"},
        },
        "items": {
            "id": "/id",
            "title": "/title",
            "time_limit_s": "/time_limit_s",
            "max_submissions": "/max_submissions",
        },
        "fields": {
            "statement": "/statement",
            "submission_id": "/submission_id",
            "status": "/status",
            "task": "/task",
            "instance": "/instance",
            "time_limit_s": "/time_limit_s",
            "max_submissions": "/max_submissions",
        },
        "verdict": {"accepted": "pass", "rejected": "fail", "pending": "pending"},
        "deliver": deliver,
        "poll": {"first_s": 1, "max_s": 8, "settle_s": 600},
    }
