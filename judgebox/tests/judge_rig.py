"""judgebox 测试台：真图服务（SQLite 临时文件）+ Blob 仓库 + 保密库 + 判官运行器。执行层默认是进程内替身。"""

import hashlib
import shutil
import subprocess
from dataclasses import replace

import pytest
from paoding_judgebox.contract import JudgeConfig, JudgeRunner, Vault, kernel_judges, load_registry

from paoding_executor.contract import ExecResult
from paoding_graph.contract import BlobStore, Config, GraphService, TokenRegistry

IMAGE = "python:3.12-slim"
REG = load_registry()
R = {"usd_milli": 100, "wall_s": 60}


def docker_ok() -> bool:
    if not shutil.which("docker") or subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        return False
    return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode == 0


class FakeBox:
    """SandboxPort 的进程内替身：按脚本逐次给出 (exit_code, 输出, touched, 耗时毫秒)；记录起了什么、拆了什么。"""

    def __init__(self, runs=()):
        self.runs, self.launched, self.destroyed, self.cmds = list(runs), [], [], []
        self.fail_launch = False

    def launch(self, spec, lease_id, mount_workspace=True):
        if self.fail_launch:
            raise RuntimeError("no daemon")
        sid = f"box-{len(self.launched)}"
        self.launched.append({"sid": sid, "spec": spec, "lease": lease_id, "mount_workspace": mount_workspace})
        return sid

    def exec(self, sid, cmd, pid, idem_key, timeout_s=60, cwd="/workspace", register_as="exec"):
        self.cmds.append((sid, cmd, register_as, timeout_s))
        code, text, touched, ms = (0, "", [], 0) if cmd.startswith("printf") else self.runs.pop(0)
        prov = {
            "sandbox_id": sid,
            "base": "basic",
            "baseline_ref": "basic@1",
            "tool": "shell",
            "command": cmd,
            "cwd": cwd,
            "exit_code": code,
            "touched": touched,
            "started_at": 1000,
            "ended_at": 1000 + ms,
            "truncated": False,
        }
        return ExecResult(None, hashlib.sha256(text.encode()).hexdigest(), code, text, False, prov)

    def destroy(self, sid):
        self.destroyed.append(sid)


class JRig:
    def __init__(self, tmp_path, registry=None, executor=None):
        self.registry = registry or {k: dict(v) for k, v in REG.items()}
        self.reg = TokenRegistry()
        for kind, ident, name in (
            ("human", "cz", "human"),
            ("sinan", "sn1", "sinan"),
            ("executor", "ex1", "exec"),
            ("judge", "jr1", "judge"),
        ):
            self.reg.issue({"kind": kind, "id": ident}, f"tok-{name}")
        t = [1000]

        def tick():
            t[0] += 1
            return t[0]

        self.clock = t
        self.svc = GraphService(
            tmp_path / "g.sqlite", Config(judges=kernel_judges(REG), external_resources=frozenset()), self.reg, tick
        )
        self.blobs = BlobStore(tmp_path / "blobs")
        self.vault = Vault(tmp_path / "vault")
        self.box = executor if executor is not None else FakeBox()
        self.cfg = JudgeConfig(token="tok-judge", registry=self.registry, bases={"basic": IMAGE})
        self.runner = JudgeRunner(self.cfg, self.svc, self.svc, self.blobs, self.vault, self.box)
        self.n = 0

    # ---------- 提交 ----------

    def submit(self, who, pid, ops):
        self.n += 1
        return self.svc.submit(who if who.startswith("tok-") else f"tok-{who}", pid, f"k{self.n}", ops)

    def one(self, who, pid, op, body):
        out = self.submit(who, pid, [{"op": op, "body": body}])
        assert out["ok"], out
        return out["results"][0].get("id")

    def art(self, data: bytes, cls="input", who="human", pid="p1"):
        return self.one(
            who,
            pid,
            "register_artifact",
            {"hash": self.blobs.put(data), "size": len(data), "media_type": "text/plain", "class": cls},
        )

    def open(self, pid="p1", check=None, max_attempts=3, risk="r0", usd_milli=5000, scope=None, goal=None, judges=None):
        st = b"statement " + pid.encode()
        out = self.submit(
            "human",
            pid,
            [
                {
                    "op": "register_artifact",
                    "body": {"hash": self.blobs.put(st), "size": len(st), "media_type": "text/plain", "class": "input"},
                },
                {
                    "op": "open_problem",
                    "body": {
                        "title": "取回取值",
                        "origin": {"statement_ref": "$0", "materials": []},
                        "goal": {
                            "statement": "取回取值并原样提交",
                            "check": check or {"judge_id": "exact_match"},
                            "max_attempts": max_attempts,
                            "accept": "judge",
                            **(goal or {}),
                        },
                        "scope": [{"resource": "net", "pattern": "target-a:8080", "actions": ["connect"], "risk": risk}]
                        if scope is None
                        else scope,
                        "budget": {"usd_milli": usd_milli, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
                        "env": {"base": "basic", "baseline_ref": "basic@1"},
                        "judges": judges or ["exact_match", "replay"],
                    },
                },
            ],
        )
        assert out["ok"], out
        return out

    def session(self, pid="p1", kind="bootstrap", target=None):
        """一条任务租约与它的会话令牌（与 Adapter 签发的同形）。"""
        lid = self.one(
            "sinan",
            pid,
            "lease",
            {"kind": kind, **({"target": target} if target else {}), "holder": "sn1", "reserve": R, "ttl_s": 600},
        )
        tok = f"tok-s-{lid}"
        self.reg.issue({"kind": "adapter", "id": "ad1", "session": lid, "role": kind}, tok)
        return lid, tok

    def candidate(self, data: bytes, pid="p1", target="goal", judge="exact_match", who="human"):
        aid = self.art(data, pid=pid)
        out = self.submit(
            who, pid, [{"op": "request_judge", "body": {"target": target, "judge_id": judge, "candidate": aid}}]
        )
        return aid, out

    def fact(self, tok, check, pid="p1", title="端口开放"):
        """一条带判据的观察：依据是执行层登记的输出。返回 (fact id, request id)。"""
        data = f"exec for {title}".encode()
        prov = {
            "sandbox_id": "s",
            "base": "basic",
            "baseline_ref": "basic@1",
            "tool": "shell",
            "command": "probe",
            "cwd": "/",
            "exit_code": 0,
            "touched": [],
            "started_at": 1,
            "ended_at": 2,
            "truncated": False,
        }
        ex = self.one(
            "exec",
            pid,
            "register_artifact",
            {
                "hash": self.blobs.put(data),
                "size": len(data),
                "media_type": "text/plain",
                "class": "exec",
                "exec": prov,
            },
        )
        fid = self.one(
            tok,
            pid,
            "add_fact",
            {
                "title": title,
                "summary": "",
                "claim_type": "observation",
                "check": check,
                "premises": [],
                "grounds": [ex],
            },
        )
        rid = self.one(tok, pid, "request_judge", {"target": fid, "judge_id": check["judge_id"]})
        return fid, rid

    def spec(self, script: str, pid="p1"):
        return self.art(script.encode(), pid=pid)

    @property
    def state(self):
        return self.svc.state

    def level(self, pid, node):
        from paoding_graph.contract import node_levels

        return node_levels(self.state, pid)[node]


def with_flake(registry, jid, **kw):
    out = {k: dict(v) for k, v in registry.items()}
    out[jid] = {**out[jid], **kw}
    return out


@pytest.fixture
def jr(tmp_path):
    return JRig(tmp_path)
