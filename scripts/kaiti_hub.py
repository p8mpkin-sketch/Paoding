"""组装根里的起草服务（一句话开题第二期，设计 docs/design/kaiti §6）：把 qicao 的 KaitiService 挂到图服务的
/v1/drafts 前缀上，只接受人的令牌（起草要花钱）。图服务不认识它，也不调用它；开题仍由前端用人的令牌提交。

配置（config.yaml 的 kaiti 段，都可省）：
    draft:    heuristic | messages | off   缺省：fake 后端 heuristic（演示起草，不调模型），real 后端 messages
    url:      起草请求打到的 Anthropic 兼容端点（缺省同 backend 的上游）
    model:    模型名
    token_env: 起草令牌所在的环境变量名（缺省 PD_DRAFT_TOKEN）。密钥只从环境变量读，不进配置文件、不进日志
    settings: 设置快照文件（YAML/JSON，形状同 GET /v1/settings）；设置存储上线后换成它
    priors:   预算先验表（档位 → 默认预算）；缺省占位表

零确认在第二期一律关（cz 2026-11-19，#83 第 2 条附条件），这里没有开关可开。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from paoding_graph.contract import BadBody, GraphHttp
from paoding_qicao.contract import (
    BadRequest,
    Drafter,
    Intake,
    KaitiService,
    MessagesClient,
    Settings,
    TablePriors,
    heuristic_drafter,
    model_drafter,
    placeholder_priors,
)

KEYS = {"draft", "url", "model", "token_env", "settings", "priors"}


class KaitiConfigError(ValueError):
    pass


def kaiti_config(raw: Any, base: Path) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or set(raw) - KEYS:
        raise KaitiConfigError(f"kaiti 只认 {sorted(KEYS)} 这几项")
    if "api_key" in raw or "token" in raw:
        raise KaitiConfigError("起草密钥不进配置文件：用 kaiti.token_env 指一个环境变量")
    out = dict(raw)
    for k in ("settings", "priors"):
        if out.get(k):
            out[k] = str((base / str(out[k])).resolve())
    if out.get("draft", "heuristic") not in ("heuristic", "messages", "off"):
        raise KaitiConfigError("kaiti.draft 取 heuristic、messages 或 off")
    return out


def _load(path: str | None) -> Any:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) if path else {}


class KaitiHub:
    def __init__(self, cfg: dict[str, Any], real: bool, upstream: str) -> None:
        settings = Settings.from_doc(_load(cfg.get("settings")))
        priors = TablePriors.load(cfg["priors"]) if cfg.get("priors") else placeholder_priors()
        kind = cfg.get("draft") or ("messages" if real else "heuristic")
        drafter: Drafter | None = None
        profile = ""
        if kind == "heuristic":
            drafter, profile = heuristic_drafter, "heuristic"
        elif kind == "messages":
            prof = settings.draft_profile(None)
            model = str(cfg.get("model") or (prof or {}).get("model") or "")
            token = os.environ.get(str(cfg.get("token_env") or "PD_DRAFT_TOKEN"), "")
            url = str(cfg.get("url") or upstream)
            if model and token and url:
                drafter = model_drafter(MessagesClient(url, token, model))
                profile = str((prof or {}).get("name") or model)
        self.state = {"draft": kind if drafter else "off", "profile": profile, "priors": priors.version()}
        self.svc = KaitiService(Intake.load(), lambda: settings, priors, drafter, profile)

    def mount(self, http: GraphHttp) -> None:
        http.mount("POST", r"/v1/drafts/extract", self._wrap(self.svc.extract_view), human=True)
        http.mount("POST", r"/v1/drafts", self._wrap(self.svc.draft_view), human=True)

    @staticmethod
    def _wrap(fn: Any) -> Any:
        def route(q: dict[str, str], body: Any) -> Any:
            try:
                return fn(body)
            except BadRequest as e:
                raise BadBody(str(e)) from None

        return route
