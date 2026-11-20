"""录黄金日志（焚决 F1，docs/design/fenjue/06-migration.md §3.2）。不是测试，手动跑一次、录完冻结：

    uv run python tests/fenjue/record_goldens.py            # 写 tests/fenjue/goldens/<道>.json
    uv run python tests/fenjue/record_goldens.py --check    # 只核对：重录结果与已冻结的是否一致（不写盘）

做法：在既有内核测试运行时截下每个测试台（graph/tests/conftest.py 的 Kernel）的事件日志。这些测试本来就逐一
构造了各道的事件形状（严格道、外部裁决、人工验收、开放道、扩权、整理、资料类……），截下来就是一份覆盖面
最广的“已有事件”样本。每份日志只在满足两条时收：用今天的 reducer 从头重放得到的状态与测试台当时的状态
逐字节相同（排除测试里直接改状态、或替换了内核函数的测试台）；各题的视图能算出来。

收下的每份日志记：事件原文、终态哈希、若干前缀的哈希、各题 /work 与状态视图的摘要、读数视图 problems 的摘要。
冻结之后，tests/fenjue/test_t4_zhang.py 逐份重放比对（回放不变式 R1）。录制只在新增一类事件形状时重跑，
重跑只许新增文件，不许改已冻结的（--check 先确认旧的没变）。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent / "goldens"

# 测试模块 → 所属的道（一份黄金日志文件）。没列的模块不录。
LANES: dict[str, str] = {
    "test_reducer.py": "strict_kernel",
    "test_isolation.py": "strict_kernel",
    "test_leases.py": "strict_kernel",
    "test_human_ops.py": "strict_kernel",
    "test_touches.py": "strict_kernel",
    "test_seen.py": "strict_kernel",
    "test_control_kernel.py": "strict_kernel",
    "test_open_caps.py": "strict_kernel",
    "test_prefs.py": "strict_kernel",
    "test_practice_envelope.py": "strict_kernel",
    "test_recall_kernel.py": "strict_recall",
    "test_external_verdict.py": "strict_external",
    "test_acceptance.py": "strict_human",
    "test_open_lane.py": "open_lane",
    "test_scope_grants.py": "grants",
    "test_curate.py": "curate",
    "test_knowledge_class.py": "knowledge",
    "test_open_lane_people.py": "open_lane_l3",  # #111 地图 v0.9：追问、叫停、闲置自动关（F1 时在途，合入后补录）
}
MIN_EVENTS = 3
MAX_EVENTS = 300  # 压测类的长日志不录：它们的事件形状在短日志里都有，录进来只让文件变大


def digest(x: Any) -> str:
    from paoding_graph.jcs import canonicalize

    return hashlib.sha256(canonicalize(x)).hexdigest()


def snapshot(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """一份日志的冻结内容；重放得不出同样的状态或视图算不出来时返回 None。"""
    from paoding_graph import views
    from paoding_graph import work as wk
    from paoding_graph.reducer import apply, empty_state
    from paoding_graph.replay import replay, state_hash

    s = replay(events, apply, empty_state())
    n = len(events)
    cuts = sorted({max(1, n // 4), max(1, n // 2), max(1, 3 * n // 4)} - {n})
    prefix = {str(c): state_hash(replay(events[:c], apply, empty_state())) for c in cuts}
    pids = sorted({e["problem_id"] for e in events if e["problem_id"] in s["problems"]})
    try:
        vs = {pid: {"work": digest(wk.work(s, pid)), "status": digest(views.status(s, pid))} for pid in pids}
        problems = digest(views.problems(s))
    except (KeyError, TypeError, ValueError):
        return None
    return {"state_hash": state_hash(s), "prefix_hashes": prefix, "views": vs, "problems": problems}


class Recorder:
    def __init__(self) -> None:
        self.logs: dict[str, dict[str, dict[str, Any]]] = {}

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item: pytest.Item, nextitem: pytest.Item | None):  # type: ignore[no-untyped-def]
        lane = LANES.get(Path(str(item.fspath)).name)
        # 夹具 k 在 setup 阶段造测试台，所以包住整个协议（setup、call、teardown）
        conftest = sys.modules.get("conftest")
        if lane is None or conftest is None or not hasattr(conftest, "Kernel"):
            yield
            return
        made: list[Any] = []
        cls = conftest.Kernel
        orig = cls.__init__

        def spy(self_: Any, *a: Any, **kw: Any) -> None:
            orig(self_, *a, **kw)
            made.append(self_)

        cls.__init__ = spy
        try:
            yield
        finally:
            cls.__init__ = orig
        self._keep(lane, item.nodeid, made)

    def _keep(self, lane: str, nodeid: str, made: list[Any]) -> None:
        from paoding_graph.reducer import apply, empty_state
        from paoding_graph.replay import replay, state_hash

        for i, k in enumerate(made):
            evs = [dict(e) for e in k.events]
            if not MIN_EVENTS <= len(evs) <= MAX_EVENTS:
                continue
            try:
                same = state_hash(replay(evs, apply, empty_state())) == state_hash(k.state)
            except (KeyError, TypeError, ValueError, AssertionError):
                continue
            if not same:
                continue
            snap = snapshot(evs)
            if snap is None:
                continue
            head = evs[-1]["hash"]
            self.logs.setdefault(lane, {}).setdefault(head, {"from": f"{nodeid}#{i}", "events": evs, **snap})


def signature(ev: dict[str, Any]) -> tuple[Any, ...]:
    """事件形状：种类、提交者、事件体的键，外加几处分道的取值。挑日志时按它去重。"""
    b = ev["body"]
    goal = b.get("goal") if isinstance(b.get("goal"), dict) else {}
    return (
        ev["kind"],
        ev["actor"]["kind"],
        ev["actor"].get("role"),
        tuple(sorted(b)),
        goal.get("accept"),
        b.get("class"),
        b.get("outcome"),
        b.get("decision"),
        b.get("kind"),
    )


def pick(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """贪心覆盖：先短后长，一份日志带来新的事件形状才收；另外每道都收下最长的一份，留住长序列上的交互。"""
    seen: set[tuple[Any, ...]] = set()
    out = []
    ordered = sorted(logs, key=lambda g: (len(g["events"]), g["from"]))
    for g in ordered:
        sigs = {signature(e) for e in g["events"]}
        if sigs - seen:
            out.append(g)
            seen |= sigs
    if ordered and ordered[-1] not in out:
        out.append(ordered[-1])
    return sorted(out, key=lambda g: g["from"])


def record() -> dict[str, dict[str, Any]]:
    rec = Recorder()
    mods = sorted({str(ROOT / "graph" / "tests" / m) for m in LANES})
    code = pytest.main(["-q", "-p", "no:cacheprovider", "-p", "no:randomly", *mods], plugins=[rec])
    if code != 0:
        raise SystemExit(f"内核测试没有全绿（{code}），不录")
    out: dict[str, dict[str, Any]] = {}
    for lane, by_head in sorted(rec.logs.items()):
        logs = pick(list(by_head.values()))
        out[lane] = {
            "note": f"焚决 F1 冻结的黄金日志（{lane}）：截自既有内核测试的测试台，见 tests/fenjue/record_goldens.py",
            "logs": logs,
        }
    return out


def main(argv: list[str]) -> int:
    check = "--check" in argv
    got = record()
    OUT.mkdir(exist_ok=True)
    bad = 0
    for lane, doc in got.items():
        p = OUT / f"{lane}.json"
        text = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        if p.exists():
            old = json.loads(p.read_text(encoding="utf-8"))
            old_heads = {g["events"][-1]["hash"] for g in old["logs"]}
            new_heads = {g["events"][-1]["hash"] for g in doc["logs"]}
            if not old_heads <= new_heads:
                print(f"{lane}: 已冻结的日志有 {len(old_heads - new_heads)} 份重录不出来了")
                bad += 1
            continue  # 已冻结的不改写
        if check:
            print(f"{lane}: 尚未冻结（{len(doc['logs'])} 份）")
            continue
        p.write_text(text, encoding="utf-8")
        print(f"{lane}: {len(doc['logs'])} 份日志，{sum(len(g['events']) for g in doc['logs'])} 条事件 → {p.name}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "graph" / "tests"))
    raise SystemExit(main(sys.argv[1:]))
