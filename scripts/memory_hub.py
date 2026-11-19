"""全栈里的通鉴一角（v1.5 能力一最小版）：通鉴服务、召回运行器，以及挂在图服务 HTTP 上的两个读端点。

    GET  /v1/memory          条目与派生状态
    POST /v1/memory/match    开题前匹配：请求体是开题事件体（不含 profile），应答是召回候选与 match_digest

配置（StackConfig.memory）：case_seal（判例往下的投影，缺省开）、model_epoch（类牛层的代际键）。
召回是否带进新题由开题人决定（向导、评测台的 memory 开关），栈只负责封存与复核。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from paoding_graph.contract import BadBody, GraphHttp, GraphService, TokenRegistry, views
from paoding_tongjian.contract import RecallConfig, RecallRunner, Tongjian, TongjianConfig

DEFAULTS: dict[str, Any] = {"case_seal": True, "model_epoch": "unknown"}


def memory_config(raw: object) -> dict[str, Any]:
    if raw is None:
        return dict(DEFAULTS)
    if not isinstance(raw, dict) or set(raw) - set(DEFAULTS):
        raise ValueError(f"memory 只认 {sorted(DEFAULTS)} 这几项")
    out = {**DEFAULTS, **raw}
    if not isinstance(out["case_seal"], bool):
        raise ValueError("memory.case_seal 取 true 或 false")
    out["model_epoch"] = str(out["model_epoch"])
    return out


class MemoryHub:
    def __init__(self, home: Path, graph: GraphService, tokens: TokenRegistry, sinan_token: str, cfg: dict[str, Any]):
        self.graph = graph
        self.tj = Tongjian(
            home / "tongjian.sqlite", graph, TongjianConfig(case_seal=cfg["case_seal"], model_epoch=cfg["model_epoch"])
        )
        self.recaller = RecallRunner(RecallConfig(token=sinan_token), graph, graph, tokens)

    def mount(self, http: GraphHttp) -> None:
        http.mount("GET", r"/v1/memory", lambda q, b: {"items": self.tj.items(), "as_of": self.tj.state["seq"]})
        http.mount("POST", r"/v1/memory/match", self._match)

    def _match(self, q: dict[str, str], body: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(body, dict) or not isinstance(body.get("problem"), dict):
            raise BadBody("请求体是 {problem: 开题事件体, q?: 题面词法}")
        problem = body["problem"]
        prof = views.profile_preview(problem, self.graph.cfg)["profile"]
        return self.tj.match({**problem, "profile": prof}, str(body.get("q", "")))

    def tick(self) -> dict[str, Any]:
        """一轮：先领走待做的召回，再封存已关的题。"""
        return {"recalled": self.recaller.tick(), "sealed": self.tj.sweep()}

    def close(self) -> None:
        self.tj.close()
