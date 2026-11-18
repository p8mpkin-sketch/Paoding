"""判官运行器（§3.3.2）：持有 judge 令牌的独立组件。从 /work 领 judge 租约，运行判官，登记输出，提交裁决。

一次请求的步骤：领租约（预留计入验证池）→ 按哈希取候选与规格 → 运行判官 → 把输出登记为 judge 类 →
`judge_verdict`（版本取自注册表，等级由内核按开题时的快照写入）→ `cost` 入账 → 释放租约。

判官不读 Worker 的叙述：输入只有登记在目标上的判据、候选的字节、按哈希挂入的规格与保密库。
注册表版本与开题时的快照不一致时拒绝运行（判官被换过）。这里没有模型调用。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from paoding_graph.contract import BlobError, BlobPort, GraphPort, GraphReader

from .builtin import BUILTINS, Ctx, Outcome
from .vault import Vault

MAX_TRIES = 3  # 同一请求领租约的次数上限：环境一直坏时不空转，留给人看


@dataclass
class JudgeConfig:
    token: str  # judge 组件令牌
    holder: str = "jr1"
    registry: dict = field(default_factory=dict)
    reserve_usd_milli: int = 1
    ttl_s: int = 300
    bases: dict = field(default_factory=dict)  # Problem.env.base → 镜像
    judges: dict = field(default_factory=lambda: dict(BUILTINS))  # judge_id → 函数；配置判官的插件位


class JudgeRunner:
    def __init__(
        self,
        cfg: JudgeConfig,
        graph: GraphPort,
        reader: GraphReader,
        blobs: BlobPort,
        vault: Vault | None = None,
        executor: Any = None,
        clock: Callable[[], int] = lambda: int(time.time() * 1000),
    ):
        self.cfg, self.graph, self.reader, self.blobs = cfg, graph, reader, blobs
        self.vault, self.executor, self.clock = vault, executor, clock

    # ---------- 轮询入口 ----------

    def tick(self, pid: str | None = None) -> list[dict]:
        """把 /work 里的 judge 项各跑一遍。rejudge 项（unstable 的复判）先沿用上次请求的输入补一条请求。"""
        done = []
        st = self.reader.state
        for p in sorted(st["problems"]) if pid is None else [pid]:
            for item in self.reader.work(p):
                if item["kind"] == "rejudge":
                    out = self.graph.submit(
                        self.cfg.token,
                        p,
                        f"rejudge:{item['target']}:{self.reader.state['seq']}",
                        [
                            {
                                "op": "request_judge",
                                "body": {
                                    "target": item["target"],
                                    "judge_id": item["judge"],
                                    **({"candidate": item["candidate"]} if item.get("candidate") else {}),
                                },
                            }
                        ],
                    )
                    if out["ok"]:
                        done.append(self.run(p, out["results"][0]["id"]))
                elif item["kind"] == "judge":
                    done.append(self.run(p, item["target"]))
        return [d for d in done if d]

    # ---------- 一次请求 ----------

    def run(self, pid: str, rid: str) -> dict | None:
        st = self.reader.state
        req = st["requests"].get(rid)
        if req is None or req["problem_id"] != pid or req.get("verdict_seq") is not None:
            return None
        tries = sum(1 for l in st["leases"].values() if l["kind"] == "judge" and l.get("target") == rid)
        if tries >= MAX_TRIES:
            return None
        out = self.graph.submit(
            self.cfg.token,
            pid,
            f"judge-lease:{rid}:{tries}",
            [
                {
                    "op": "lease",
                    "body": {
                        "kind": "judge",
                        "target": rid,
                        "holder": self.cfg.holder,
                        "reserve": {"usd_milli": self.cfg.reserve_usd_milli, "wall_s": self.cfg.ttl_s},
                        "ttl_s": self.cfg.ttl_s,
                    },
                }
            ],
        )
        if not out["ok"]:
            return {"request": rid, "status": "not_leased", **out["results"][0]}
        lid = out["results"][0]["id"]
        t0 = self.clock()
        verdict_ok, o = False, None
        try:
            o = self._judge(pid, rid, lid)
            aid = self._register(pid, rid, lid, o)
            v = self.graph.submit(
                self.cfg.token,
                pid,
                f"verdict:{rid}:{lid}",
                [
                    {
                        "op": "judge_verdict",
                        "body": {
                            "request": rid,
                            "result": o.result,
                            "version": self._spec(st, pid, req)["version"],
                            "evidence": [aid],
                            "reason": o.reason,
                        },
                    }
                ],
            )
            verdict_ok = v["ok"]
            return {
                "request": rid,
                "lease": lid,
                "result": o.result,
                "reason": o.reason,
                "evidence": aid,
                "status": "judged" if verdict_ok else "rejected",
                **({} if verdict_ok else v["results"][0]),
            }
        finally:
            wall = max(o.wall_s if o else 0, (self.clock() - t0) // 1000)
            self.graph.submit(
                self.cfg.token,
                pid,
                f"judge-cost:{lid}",
                [
                    {
                        "op": "cost",
                        "body": {
                            "task_id": lid,
                            "source": "judge",
                            "tokens_in": 0,
                            "tokens_cached": 0,
                            "tokens_out": 0,
                            "usd_milli": 0,
                            "wall_s": int(wall),
                            "price_table": "judge@0",
                        },
                    }
                ],
            )  # 程序化判官不耗 token，只记墙钟
            self.graph.submit(
                self.cfg.token,
                pid,
                f"judge-release:{lid}",
                [{"op": "release", "body": {"lease": lid, "outcome": "done" if verdict_ok else "failed"}}],
            )

    def _spec(self, st: dict, pid: str, req: dict) -> dict:
        return self.cfg.registry.get(req["judge_id"]) or {
            "version": st["problems"][pid]["judge_snapshot"][req["judge_id"]]["version"]
        }

    def _judge(self, pid: str, rid: str, lid: str) -> Outcome:
        st = self.reader.state
        req, p = st["requests"][rid], st["problems"][pid]
        jid = req["judge_id"]
        spec, fn = self.cfg.registry.get(jid), self.cfg.judges.get(jid)
        now = self.clock()
        if spec is None or fn is None:
            return Outcome("inconclusive", "unsupported", f"判官 {jid} 没有运行器".encode(), _builtin_prov(jid, now))
        if str(spec["version"]) != str(p["judge_snapshot"][jid]["version"]):
            return Outcome(
                "inconclusive",
                "env_error",
                f"判官 {jid} 的版本与开题时的快照不一致，拒绝运行".encode(),
                _builtin_prov(jid, now),
            )
        target = req["target"]
        if target == "goal":
            check, risk = p["goal"]["check"], p["profile"]["reversibility"]
        elif target in st["facts"]:
            f = st["facts"][target]
            check = f["check"]
            risk = st["intents"][f["yielded_by"]]["risk"] if f.get("yielded_by") in st["intents"] else "r0"
        else:
            check, risk = st["intents"][target]["done"], st["intents"][target]["risk"]
        try:
            cand = self._bytes(st, req.get("candidate"))
            spec_art = st["artifacts"].get(check.get("spec_ref") or "")
            spec_bytes = self.blobs.get(spec_art["hash"]) if spec_art else None  # 读取时校验哈希：被改过即拒
        except (BlobError, OSError) as e:  # Blob 缺失、被改过或读盘失败：环境错误（无结论，不进裁决序列）
            return Outcome(
                "inconclusive", "env_error", f"判官输入读取失败：{type(e).__name__}".encode(), _builtin_prov(jid, now)
            )
        ctx = Ctx(
            spec=spec,
            check=check,
            problem=p,
            target=target,
            target_risk=risk,
            candidate=cand,
            candidate_ref=req.get("candidate"),
            spec_bytes=spec_bytes,
            spec_hash=spec_art["hash"] if spec_art else None,
            vault=self.vault,
            executor=self.executor,
            request_id=rid,
            lease_id=lid,
            bases=self.cfg.bases,
            now_ms=now,
            grounded=_grounded(st, req.get("candidate")),
        )
        o = fn(ctx)
        if not o.provenance:
            o.provenance = _builtin_prov(jid, now)
        return o

    def _bytes(self, st: dict, aid: str | None) -> bytes | None:
        return self.blobs.get(st["artifacts"][aid]["hash"]) if aid else None

    def _register(self, pid: str, rid: str, lid: str, o: Outcome) -> str:
        h = self.blobs.put(o.output)
        out = self.graph.submit(
            self.cfg.token,
            pid,
            f"judge-out:{rid}:{lid}",
            [
                {
                    "op": "register_artifact",
                    "body": {
                        "hash": h,
                        "size": len(o.output),
                        "media_type": "text/plain; charset=utf-8",
                        "class": "judge",
                        "exec": o.provenance,
                    },
                }
            ],
        )
        if not out["ok"]:
            raise RuntimeError(f"判官输出登记失败：{out['results']}")
        return out["results"][0]["id"]


def _grounded(st: dict, aid: str | None) -> tuple:
    """候选挂进洁净容器时，它算不算"访问过的可采信输入"（§3.3.2）。

    算：input 类（人给的材料）；exec 与 judge 类里自身访问摘要非空的（它的内容来自碰过资源的运行）。
    不算：authored 类（Worker 自己写的）；访问摘要为空的 exec 输出，否则 `echo ok` 的输出换个身份就能充数。"""
    art = st["artifacts"].get(aid or "")
    if art is None:
        return ()
    if art["class"] == "input" or (art["class"] in ("exec", "judge") and art.get("exec", {}).get("touched")):
        return (aid,)
    return ()


def _builtin_prov(jid: str, now: int) -> dict:
    return {
        "sandbox_id": "builtin",
        "base": "builtin",
        "baseline_ref": "builtin",
        "tool": jid,
        "command": jid,
        "cwd": "",
        "exit_code": None,
        "touched": [],
        "started_at": now,
        "ended_at": now,
        "truncated": False,
    }
