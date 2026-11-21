"""方案分析会话的测试台：真图服务 + 真端点代理 + 真工具端点 + 驱动程序（宿主子进程），模型换成按调用键回放录音的
假上游，执行层是进程内替身。验收夹具与录音取引擎自己的那一套（fenjue/tests/engine_fixtures）。"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from adapter_rig import CFG, FakeUpstream, Rig, make_graph

from paoding_fenjue.contract import GONGFA_ENV, analysis, engine_gongfa_path, gongfa, kernel_config, materials
from paoding_graph.contract import seen_card

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "fenjue" / "tests" / "engine_fixtures"))

import cases  # noqa: E402

MODELS = {"light": "claude-haiku-5-5", "mid": "claude-sonnet-5-5", "heavy": "claude-opus-5-5"}
PRICES = {"light": [250, 1250], "mid": [1000, 5000], "heavy": [5000, 25000]}


@pytest.fixture
def engine_gongfa(monkeypatch):
    """分析实例的功法：solve 席位是方案分析形态。驱动程序的子进程不继承这个环境变量（它的环境是运行器现拼的）。"""
    monkeypatch.setenv(GONGFA_ENV, str(engine_gongfa_path()))
    gongfa.cache_clear()
    yield
    monkeypatch.delenv(GONGFA_ENV)
    gongfa.cache_clear()


class Replay:
    """假上游的回放：请求的用户消息第一行是 `# 调用 <键>`，按键取录音里的输出。键不在录音里就回 400 并记下。"""

    def __init__(self, *recordings: Path) -> None:
        self.entries: dict[str, dict[str, Any]] = {}
        for p in recordings:
            for e in json.loads(p.read_text(encoding="utf-8"))["entries"]:
                self.entries[e["key"]] = e
        self.calls: list[str] = []
        self.misses: list[str] = []
        self.requests: list[dict[str, Any]] = []
        self.override: dict[str, Any] = {}  # 键 → 这一次改回什么（字典），或一个可调用对象

    def __call__(self, body: dict[str, Any]) -> dict[str, Any] | None:
        self.requests.append(body)
        user = body["messages"][0]["content"]
        key = user.split("\n", 1)[0].removeprefix("# 调用 ").strip()
        self.calls.append(key)
        o = self.override.get(key) or self.override.get("*")
        if callable(o):
            o = o(key, body)
        if o is not None:
            return o
        e = self.entries.get(key)
        if e is None:
            self.misses.append(key)
            return {"status": 400, "body": {"type": "error", "error": {"type": "no_recording", "message": key}}}
        return {
            "text": json.dumps(e["output"], ensure_ascii=False),
            "usage": {"input_tokens": e["tokens_in"], "output_tokens": e["tokens_out"]},
            "model": body.get("model", ""),
        }


class LocalExec:
    """执行层的替身：真的在本机把命令跑一遍（`/workspace` 换成在途会话的工作区），并照执行层的形状登记 exec 类留档。
    只给抓取的测试用：命令是宿主写死的下载程序，连的是测试自己起的本机 HTTP 服务。"""

    def __init__(self, graph, blobs, root: Path) -> None:
        self.graph, self.blobs, self.root, self.calls, self.destroyed = graph, blobs, root, [], []

    def destroy(self, sid):
        self.destroyed.append(sid)

    def exec(self, sid, cmd, pid, idem_key, timeout_s=60, cwd="/workspace", register_as="exec"):
        from paoding_executor.contract import ExecResult

        self.calls.append(cmd)
        lease = next(x["id"] for x in self.graph.state["leases"].values() if x["active"] and x["problem_id"] == pid)
        ws = str(self.root / lease / "workspace")
        r = subprocess.run(
            ["sh", "-c", cmd.replace("/workspace", ws)], cwd=ws, capture_output=True, text=True, timeout=timeout_s
        )
        text = r.stdout + r.stderr
        data = text.encode()
        h = self.blobs.put(data)
        prov = {
            "sandbox_id": sid,
            "base": "basic",
            "baseline_ref": "base@1",
            "tool": "shell",
            "command": cmd[:200],
            "cwd": cwd,
            "exit_code": r.returncode,
            "touched": [],
            "started_at": 1,
            "ended_at": 2,
            "truncated": False,
        }
        body = {"hash": h, "size": len(data), "media_type": "text/plain; charset=utf-8", "class": "exec", "exec": prov}
        out = self.graph.submit("tok-exec", pid, idem_key, [{"op": "register_artifact", "body": body}])
        assert out["ok"], out
        return ExecResult(out["results"][0]["id"], h, r.returncode, text, False, prov)


class HotExec(LocalExec):
    """支持会话中途对齐出站闸门的执行层（真的 DockerExecutor 就是）：记下每次对齐编出的规则。"""

    def __init__(self, graph, blobs, root: Path) -> None:
        super().__init__(graph, blobs, root)
        self.aligned: list[list[str]] = []

    def reconcile(self, sid, spec):
        self.aligned.append(sorted(str(x) for x in getattr(spec, "egress", []) or []))
        return {"added": [], "removed": []}


class Site:
    """本机的一个 HTTP 服务：按路径给出固定的字节；`redirects` 里的路径 302 到别处。记下收到的路径。"""

    def __init__(self, files: dict[str, bytes], redirects: dict[str, str] | None = None) -> None:
        site = self
        self.files, self.redirects, self.seen = dict(files), dict(redirects or {}), []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                site.seen.append(self.path)
                if self.path in site.redirects:
                    self.send_response(302)
                    self.send_header("location", site.redirects[self.path])
                    self.send_header("content-length", "0")
                    self.end_headers()
                    return
                data = site.files.get(self.path)
                self.send_response(200 if data is not None else 404)
                data = data if data is not None else b"not found"
                self.send_header("content-type", "application/octet-stream")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]
        self.target = f"127.0.0.1:{self.port}"
        self.url = f"http://{self.target}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class TunshiRig(Rig):
    def __init__(self, tmp_path, graph, upstream, replay):
        super().__init__(tmp_path, graph, upstream)
        self.replay = replay
        self.cfg.stall_s = 60
        self.cfg.extra_env = {"PD_RETRY_WAITS": "0.05,0.05"}
        self.cfg.analysis = lambda pid: self.profile
        self.cfg.analysis_export = tmp_path / "analyses"
        self.profile: dict[str, Any] = {
            "bang": cases.bang(),
            "canaries": cases.CANARIES,
            "models": MODELS,
            "prices": PRICES,
            "access_wait_s": 3,
            "access_poll_s": 0.2,
        }
        self.n = 0

    def put(self, content: bytes, media: str, pid: str) -> str:
        self.n += 1
        out = self.graph.submit(
            "tok-human",
            pid,
            f"in-{pid}-{self.n}",
            [
                {
                    "op": "register_artifact",
                    "body": {
                        "hash": self.blobs.put(content),
                        "size": len(content),
                        "media_type": media,
                        "class": "input",
                    },
                }
            ],
        )
        assert out["ok"], out
        return out["results"][0]["id"]

    def open(
        self,
        pid: str = "p1",
        *,
        intake: dict[str, Any] | None = None,
        material: bytes | None = None,
        media: str = "application/gzip",
        statement: str = "看看这个系统里有什么值得我们集成的做法",
        usd_milli: int = 400_000,
        extra_materials: tuple[str, ...] = (),
        scope: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """开一道方案分析的题。intake 里来源的 artifact 写 "$material" 时换成刚登记的那份材料的编号。"""
        mats: list[str] = list(extra_materials)
        mid = None
        if material is not None:
            mid = self.put(material, media, pid)
            mats.append(mid)
        if intake is not None:
            doc = json.loads(json.dumps(intake).replace("$material", mid or ""))
            mats.append(self.put(json.dumps(doc, ensure_ascii=False).encode(), analysis.INTAKE_MEDIA, pid))
        st = statement.encode()
        sid = self.put(st, "text/plain", pid)
        out = self.graph.submit(
            "tok-human",
            pid,
            f"open-{pid}",
            [
                {
                    "op": "open_problem",
                    "body": {
                        "title": "方案分析",
                        "origin": {"statement_ref": sid, "materials": mats},
                        "goal": {"statement": statement, "accept": "open"},
                        "scope": scope
                        or [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}],
                        "budget": {
                            "usd_milli": usd_milli,
                            "wall_s": 36000,
                            "verify_share": 0.2,
                            "bootstrap_share": 0.3,
                        },
                        "env": {"base": "basic", "baseline_ref": "base@1"},
                        "judges": [],
                    },
                }
            ],
        )
        assert out["ok"], out
        self.statement = statement
        return {"material": mid}

    def lease(self, pid: str = "p1", reserve: int | None = None) -> str:
        self.n += 1
        b = self.graph.budget(pid)
        left = b["cap"]["usd_milli"] - b["spent"]["usd_milli"] - b["reserved"]["usd_milli"]
        out = self.graph.submit(
            "tok-sinan",
            pid,
            f"lease-{pid}-{self.n}",
            [
                {
                    "op": "lease",
                    "body": {
                        "kind": "solve",
                        "holder": "sn1",
                        "reserve": {"usd_milli": reserve or max(1, left), "wall_s": 3600},
                        "ttl_s": 600,
                    },
                }
            ],
        )
        assert out["ok"], out
        return out["results"][0]["id"]

    def session(self, pid: str = "p1", reserve: int | None = None):
        lid = self.lease(pid, reserve)
        return lid, self.run(lid, pid)

    def follow_up(self, text: str, pid: str = "p1", add: int | None = None) -> None:
        self.n += 1
        body: dict[str, Any] = {"text": text, "seen": {"seq": self.graph.state["seq"]}}
        if add:
            body["budget_add_usd_milli"] = add
        out = self.graph.submit("tok-human", pid, f"fu-{pid}-{self.n}", [{"op": "follow_up", "body": body}])
        assert out["ok"], out

    def decide(self, request: str, decision: str = "approve", pid: str = "p1", reason: str | None = None) -> None:
        """人在权限申请卡上批准或拒绝。"""
        self.n += 1
        body: dict[str, Any] = {
            "request": request,
            "decision": decision,
            "seen": seen_card(self.graph.state, pid, "scope", request),
        }
        if reason:
            body["reason"] = reason
        out = self.graph.submit("tok-human", pid, f"grant-{pid}-{self.n}", [{"op": "grant_scope", "body": body}])
        assert out["ok"], out

    def requests(self, pid: str = "p1") -> list[dict[str, Any]]:
        reqs = self.graph.state.get("scope_requests", {}).values()
        return sorted((x for x in reqs if x["problem_id"] == pid), key=lambda x: x["seq"])

    def run_units(self, lease_id: str) -> dict[str, Any]:
        return json.loads((self.ws(lease_id) / "analysis" / "run.json").read_text(encoding="utf-8"))

    def deliveries(self, pid: str = "p1") -> list[dict[str, Any]]:
        return list(self.graph.state["problems"][pid].get("deliveries") or [])

    def answer(self, d: dict[str, Any]) -> str:
        art = self.graph.state["artifacts"][d["answer"]]
        return self.blobs.get(art["hash"]).decode("utf-8")

    def ws(self, lease_id: str) -> Path:
        return self.cfg.root / lease_id / "workspace"

    def stderr(self, lease_id: str) -> str:
        p = self.cfg.root / lease_id / "cli.stderr.log"
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def fixture_tar(fx: str, form: str = "code") -> bytes:
    return materials.pack(cases.HERE / fx / form)


RISK_TABLE = (
    {"resource": "net", "pattern": "127.0.0.1:*", "actions": ["connect"], "risk": "r1"},
    {"resource": "net", "pattern": "codeload.github.com:443", "actions": ["connect"], "risk": "r1"},
)


def make_rig(tmp_path, *recordings: Path, usage: dict[str, Any] | None = None, local_exec: bool | str = False, **cfg):
    """cfg：覆盖内核 Config 的字段。缺省开着运行时扩权，本机回环与一个代码托管站在风险表里是 r1（要人批）。"""
    replay = Replay(*recordings)
    up = FakeUpstream(usage=usage, reply=replay)
    base = dataclasses.replace(
        CFG, external_resources=frozenset({"net"}), grants_runtime=True, risk_table=RISK_TABLE, **kernel_config()
    )
    graph = make_graph(tmp_path, dataclasses.replace(base, **cfg))
    rig = TunshiRig(tmp_path, graph, up, replay)
    if local_exec:
        kind = LocalExec if local_exec == "cold" else HotExec
        rig.executor = rig.runner.executor = kind(graph, rig.blobs, rig.cfg.root)
    return rig, up


@pytest.fixture
def trig(tmp_path, engine_gongfa):
    made: list[Any] = []

    def make(*recordings: Path, **kw):
        root = tmp_path / f"rig{len(made)}"  # 一个测试里起几台：各用各的目录（各自的事件账）
        root.mkdir()
        rig, up = make_rig(root, *recordings, **kw)
        made.append((rig, up))
        return rig

    yield make
    for rig, up in made:
        rig.close()
        up.close()
