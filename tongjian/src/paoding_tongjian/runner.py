"""召回运行器（01-memory §4.3；规格增量 8）：不含模型，与判官运行器同构。

/work 给出 recall 项时：领 recall 租约 → 为租约签一枚角色为 recall 的任务令牌 → 一批提交
"每条召回判据原样作观察 + 对它请求判定" → 释放租约、作废令牌。复核由本题的判官运行器在洁净容器里做：
通过者是本题自己的 E3（I7 不变），不通过者按等级函数处理，不能作可采信前提（I2）。
内核按角色白名单只放行这两种操作，运行器写不进别的东西。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from paoding_graph.contract import GraphPort, GraphReader, TokenIssuer

PREFIX = "[忆] "


@dataclass
class RecallConfig:
    token: str  # 领租约用的司南类组件令牌；提交与释放用为租约另签的任务令牌
    holder: str = "rc1"
    ttl_s: int = 120
    reserve: dict[str, int] | None = None


class RecallRunner:
    def __init__(self, cfg: RecallConfig, graph: GraphPort, reader: GraphReader, issuer: TokenIssuer):
        self.cfg, self.graph, self.reader, self.issuer = cfg, graph, reader, issuer

    def tick(self) -> list[dict[str, Any]]:
        done = []
        for pid in sorted(self.reader.state["problems"]):
            if any(w["kind"] == "recall" for w in self.reader.work(pid)):
                done.append(self.run(pid))
        return done

    def run(self, pid: str) -> dict[str, Any]:
        st = self.reader.state
        items = st["problems"][pid]["recall"]["items"]
        tries = sum(1 for l in st["leases"].values() if l["problem_id"] == pid and l["kind"] == "recall")
        lease = {
            "kind": "recall",
            "holder": self.cfg.holder,
            "reserve": self.cfg.reserve or {"usd_milli": 1, "wall_s": 60},
            "ttl_s": self.cfg.ttl_s,
        }
        out = self.graph.submit(self.cfg.token, pid, f"recall-lease:{pid}:{tries}", [{"op": "lease", "body": lease}])
        if not out["ok"]:
            return {"problem_id": pid, "status": "not_leased", **out["results"][0]}
        lid = out["results"][0]["id"]
        tok = self.issuer.issue({"kind": "adapter", "id": self.cfg.holder, "session": lid, "role": "recall"})
        try:
            ops: list[dict[str, Any]] = []
            for it in items:
                ops.append(
                    {
                        "op": "add_fact",
                        "body": {
                            "title": PREFIX + it["title"],
                            "summary": f"召回自通鉴的环境事实 {it['mem'][:12]}：上次在同一环境为真，本题判官重跑复核",
                            "claim_type": "observation",
                            "check": it["check"],
                            "premises": [],
                            "grounds": [it["check"]["spec_ref"]],
                        },
                    }
                )
                ops.append(
                    {"op": "request_judge", "body": {"target": f"${len(ops) - 1}", "judge_id": it["check"]["judge_id"]}}
                )
            sub = self.graph.submit(tok, pid, f"recall-submit:{lid}", ops)
            outcome = "done" if sub["ok"] else "failed"
            rel = self.graph.submit(
                tok, pid, f"recall-release:{lid}", [{"op": "release", "body": {"lease": lid, "outcome": outcome}}]
            )
        finally:
            self.issuer.revoke(tok)
        return {
            "problem_id": pid,
            "lease": lid,
            "status": "submitted" if sub["ok"] else "rejected",
            "facts": [r.get("id") for r in sub["results"][::2]] if sub["ok"] else [],
            "released": rel["ok"],
            **({} if sub["ok"] else {"detail": sub["results"]}),
        }
