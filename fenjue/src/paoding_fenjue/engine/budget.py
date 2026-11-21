"""预算先验（docs/design/fenjue/09-engine.md §5）：可插拔数据源，设计与测试阶段用占位表。

真实数据由设置层的预算先验数据源注入（与一句话开题同一个接口），键为“方案分析 / 模式 / 大小分档”。
**不读任何本机题库或校准目录。** 这里的数全是〔占位〕。

三级预算里，整题一级归体质 T3（端点代理计量、到顶拒绝），引擎只做每步与每单元两级：每步按 `STAGE_SHARE` 分，
到了就收尾当前单元、带检查点部分交付。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

STAGE_SHARE = {"S3": 0.45, "S4": 0.35, "S5": 0.20}
DRY_RUN_SHARE = 0.5
MARGIN = 0.2


class Prior(Protocol):
    def tokens(self, tier: str) -> dict[str, tuple[int, int]]: ...

    def price(self) -> dict[str, tuple[int, int]]: ...


@dataclass(frozen=True)
class Placeholder:
    """09 §5.2 的占位表：每次运行按步的 token 上限（入 / 出），与按档位的每百万 token 价格（千分之一美元）。"""

    def tokens(self, tier: str) -> dict[str, tuple[int, int]]:
        reader = {"S": (150_000, 15_000), "M": (300_000, 30_000), "L": (450_000, 45_000), "XL": (600_000, 60_000)}
        main = {"S": (375_000, 30_000), "M": (875_000, 50_000), "L": (1_580_000, 70_000), "XL": (2_200_000, 80_000)}
        return {
            "S3.light": reader[tier],
            "S3.heavy": main[tier],
            "S4.heavy": (352_000, 24_000),  # 每候选
            "S4.mid": (20_000, 4_000),
            "S5.heavy": (225_000, 10_000),
            "S5.mid": (20_000, 4_000),
        }

    def price(self) -> dict[str, tuple[int, int]]:
        return {"light": (250, 1_250), "mid": (1_000, 5_000), "heavy": (5_000, 25_000)}


def cost_usd_milli(prior: Prior, tier: str, tokens_in: int, tokens_out: int) -> int:
    pin, pout = prior.price()[tier]
    return (tokens_in * pin + tokens_out * pout) // 1_000_000


def run_budget(prior: Prior, size_tier: str, n_candidates: int, *, dry_run: bool = False) -> int:
    """一次运行的预算（千分之一美元）：Σ 档位 (入 × 价_入 + 出 × 价_出) × (1 + 余量)。缓存读价先不计（占位）。"""
    t = prior.tokens(size_tier)
    total = 0
    for key, (tin, tout) in t.items():
        step, tier = key.split(".")
        n = n_candidates if step in ("S4", "S5") else 1
        total += cost_usd_milli(prior, tier, tin * n, tout * n)
    total = int(total * (1 + MARGIN))
    return int(total * DRY_RUN_SHARE) if dry_run else total


def stage_cap(total: int, step: str) -> int:
    return int(total * STAGE_SHARE[step])
