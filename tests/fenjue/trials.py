"""体质试炼 T1–T5 的清单（焚决 F1，docs/design/fenjue/02-lianhua.md §6.2）。

体质五项的对抗测试今天散在各组件里。这里把它们按体质项收拢成一张表，一条命令就能问“体质还在吗”：

    uv run python tests/fenjue/trials.py            # 跑全部五项
    uv run python tests/fenjue/trials.py T2 T5      # 只跑其中几项
    uv run python tests/fenjue/trials.py --gongfa 某套功法.json   # 换一套功法（例如换上新炼的火）再跑一遍
    uv run python tests/fenjue/trials.py --holdout  # 每道题都分给常设留出的火（上一团火）再跑一遍

CI 照旧跑全量测试，这张表不替代它；test_trials.py 核对表里的每一项都还存在（改名、删测试会让它变红）。
这张表以“一套功法”为参数（F5）：--gongfa 指一份功法文件，经环境变量 PAODING_FENJUE_GONGFA 交给功法组件，
测试起的子进程一并继承；--holdout 把留出比例拉满，等于把每个有留出的火位换回上一团火。需要 Docker 的测试没有
Docker 时照旧自动跳过。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TRIALS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "T1": (
        "判",
        "独立判定：严格道终态只经判官洁净重放或人按清单验收；开放道只到 delivered、判定来源 self",
        (
            "judgebox/tests",
            "qicao/tests/test_qicao.py",
            "qicao/tests/test_external_entry.py",
            "graph/tests/test_acceptance.py",
            "graph/tests/test_external_verdict.py",
            "graph/tests/test_open_lane.py",
            "eval/tests/test_open_lane_isolation.py",
            "tests/integration/test_external_verdict_flip.py",
            "tests/integration/test_external_verdict_repro.py",
        ),
    ),
    "T2": (
        "闸",
        "零出站与运行时扩权：闸门唯一出口、扩权只经人、密钥只在端点代理内存、凭据遮盖",
        (
            "executor/tests/test_compile.py",
            "executor/tests/test_docker.py",
            "graph/tests/test_scope_grants.py",
            "adapter/tests/test_keyring.py",
            "adapter/tests/test_container.py",
            "adapter/tests/test_request_access.py",
            "adapter/tests/test_access_live.py",
            "adapter/tests/test_solve.py",
            "adapter/tests/test_activity.py",
            "shuku/tests/test_canary.py",
            "tests/integration/test_stack_scope_grants.py",
            "tests/integration/test_settings_keys.py",
        ),
    ),
    "T3": (
        "顶",
        "预算硬顶：容器外计量与拒绝、预留原子、墙钟与停滞回收",
        (
            "adapter/tests/test_proxy.py",
            "graph/tests/test_leases.py",
            "watchdog/tests",
            "tests/integration/test_ledger.py",
            "tests/integration/test_watchdog_session.py",
        ),
    ),
    "T4": (
        "账",
        "事件账：只追加、按题哈希链、纯函数内核、旧日志逐字节回放、权能矩阵冻结",
        (
            "graph/tests/test_eventlog.py",
            "graph/tests/test_jcs.py",
            "graph/tests/test_reducer.py",
            "graph/tests/test_malformed.py",
            "graph/tests/test_seen.py",
            "graph/tests/test_recall_kernel.py::test_m1_log_replays_byte_for_byte",
            "tests/fenjue/test_t4_zhang.py",
            "tests/fenjue/test_tables.py",
            "graph/tests/test_gongfa_fields.py",  # 体质修炼 001 的 T4-1、T4-2
            "tests/fenjue/test_f3_gongfa.py",
            "tests/integration/test_backup.py",
            "tests/integration/test_oplog.py",
        ),
    ),
    "T5": (
        "证",
        "证据分级：可作依据的只有 exec、judge、input；四类读数分列；等级不出题；估值不进等级",
        (
            "graph/tests/test_isolation.py",
            "graph/tests/test_knowledge_class.py",
            "graph/tests/test_blobs.py",
            "graph/tests/test_open_lane.py::test_deliver_checks_refs_mechanically",
            "graph/tests/test_open_lane.py::test_readings_open_lane_never_enters_strict_statistics",
            "graph/tests/test_open_lane.py::test_readings_terminal_values_never_cross_lanes",
            "executor/tests/test_capture.py",
        ),
    ),
}


def targets(names: list[str]) -> list[str]:
    picked = names or list(TRIALS)
    unknown = [n for n in picked if n not in TRIALS]
    if unknown:
        raise SystemExit(f"没有这几项体质：{unknown}（只有 {list(TRIALS)}）")
    out: list[str] = []
    for n in picked:
        out += [t for t in TRIALS[n][2] if t not in out]
    return out


GONGFA_ENV = "PAODING_FENJUE_GONGFA"


def with_gongfa(argv: list[str]) -> tuple[list[str], str | None]:
    """拆出 --gongfa 文件与 --holdout；返回体质项与要用的功法文件（None 即包里的那套）。"""
    names, path, holdout = [], None, False
    it = iter(argv)
    for a in it:
        if a == "--gongfa":
            path = next(it, None)
            if path is None:
                raise SystemExit("--gongfa 后面要跟一份功法文件")
        elif a == "--holdout":
            holdout = True
        else:
            names.append(a)
    if holdout:
        g = json.loads(Path(path).read_text(encoding="utf-8")) if path else _packaged()
        g["holdout_permille"] = 1000
        fd, tmp = tempfile.mkstemp(prefix="gongfa-holdout-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(g, f, ensure_ascii=False)
        path = tmp
    return names, path


def _packaged() -> dict:
    from importlib import resources

    return dict(json.loads(resources.files("paoding_fenjue").joinpath("gongfa.json").read_text(encoding="utf-8")))


def main(argv: list[str]) -> int:
    import pytest

    names, path = with_gongfa(argv)
    if path:
        os.environ[GONGFA_ENV] = str(Path(path).resolve())
        print(f"功法：{path}")
    for n in names or list(TRIALS):
        name, what, _ = TRIALS[n]
        print(f"{n} {name}：{what}")
    return int(pytest.main(["-q", *[str(ROOT / t) for t in targets(names)]]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
