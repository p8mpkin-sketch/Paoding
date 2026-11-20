"""体质对功法的两张表，写成数据（焚决 F1，docs/design/fenjue/01-boundary.md §4、§6）。

- PORTS：经脉 M1–M7，功法碰体质只有这七条路。
- SEATS：内核的权能矩阵：每种令牌（席位）能提交哪些事件。取自 reducer 的 `_who`，冻结在这里；
  test_tables.py 逐格比对。表与内核不一致说明内核的权能变了，那是体质修炼，必须连同本表一起改、单独裁决。

F2 把这两张表搬进 paoding_fenjue 的契约，供验体的“经脉越界”一检使用；本步只冻结与比对。
"""

from __future__ import annotations

PORTS: dict[str, str] = {
    "M1": "提议：会话令牌提交事件提议，validate 当场校验",
    "M2": "执行：exec 经执行层，输出自动登记为 exec 类",
    "M3": "模型：经端点代理，换密钥、计量、到顶拒绝",
    "M4": "读：状态、视图、Artifact 正文、活动流水；as_of 回放；无写入",
    "M5": "判：request_judge，判官运行器洁净重放",
    "M6": "人：卡片与人的令牌，带 seen.card_hash",
    "M7": "知：资料检索与引用，knowledge 类不作依据",
}

_ADAPTER_COMMON = ("cost", "register_artifact", "release", "renew", "request_judge")

# 适配层令牌按席位（actor.role）
SEATS: dict[str, tuple[str, ...]] = {
    "bootstrap": tuple(sorted((*_ADAPTER_COMMON, "add_fact", "request_scope"))),
    "explore": tuple(sorted((*_ADAPTER_COMMON, "add_fact", "request_scope"))),
    "reason": tuple(sorted((*_ADAPTER_COMMON, "abandon_intent", "add_fact", "add_intent", "request_scope"))),
    "solve": tuple(sorted((*_ADAPTER_COMMON, "deliver", "request_scope"))),
    "verify": tuple(sorted(_ADAPTER_COMMON)),
    "recall": tuple(sorted((*_ADAPTER_COMMON, "add_fact"))),
    "idler": tuple(sorted(_ADAPTER_COMMON)),
}

# 其余令牌（不带席位）
ACTORS: dict[str, tuple[str, ...]] = {
    "adapter": tuple(sorted(_ADAPTER_COMMON)),
    "executor": ("register_artifact",),
    "graph": ("budget_mark", "close_problem", "grant_scope", "kb_query", "register_artifact", "request_scope"),
    "human": (
        "abandon_intent",
        "accept",
        "add_intent",
        "approve",
        "close_problem",
        "curate",
        "grant_scope",
        "hint",
        "open_problem",
        "profile_override",
        "register_artifact",
        "request_judge",
        "request_scope",
        "revoke_scope",
    ),
    "judge": (
        "bind_deadline",
        "cost",
        "judge_verdict",
        "lease",
        "register_artifact",
        "release",
        "renew",
        "request_judge",
    ),
    "sinan": ("lease", "release", "renew", "request_judge"),
    "watchdog": ("close_problem", "expire_lease"),
}
