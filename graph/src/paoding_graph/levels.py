"""把 reducer 的 JSON 状态投影成参考模型的 State，调用搬运来的等级函数与消费门。

`refmodel.py` 是 docs/design/reference-model/kernel.py 的逐字节副本（CI 比对），
本模块只做数据形状的转换，不含任何等级语义。等级不存储、不可写（I3）：每次读时重算。
估值类字段（expected_gain、Hint 等）在转换时一律不带入（I8）。
"""

from __future__ import annotations

from . import refmodel as rm
from .state import State


def to_refstate(state: State, pid: str) -> rm.State:
    facts = {
        fid: rm.Fact(
            fid,
            f["claim_type"],
            tuple(f["premises"]),
            f.get("session") or "",
            f.get("body_ref"),
            control="control" in f.get("check", {}),  # 判据带对照（§3.3.3）：续期门与 r2 前提读它
        )
        for fid, f in state["facts"].items()
        if f["problem_id"] == pid
    }
    intents = {
        iid: rm.Intent(
            iid,
            i["risk"],
            tuple(i["premises"]),
            done=i["done"]["judge_id"] if i.get("done") else None,
            needs_scope=bool(i.get("needs_scope")),
            budget=i["budget"]["usd_milli"],
        )
        for iid, i in state["intents"].items()
        if i["problem_id"] == pid
    }
    verdicts = [
        rm.Verdict(
            v["seq"], v["target"], v["judge"], v["version"], v["grade"], v["result"], candidate=v.get("candidate")
        )
        for v in state["verdicts"]
        if v["problem_id"] == pid
    ]
    return rm.State(
        facts=facts,
        intents=intents,
        verdicts=verdicts,
        revoked={tuple(x) for x in state.get("revoked", [])},
        approvals={k: list(v) for k, v in state.get("approvals", {}).items() if k in intents},
        leases={k: list(v) for k, v in state.get("lease_seqs", {}).items() if k in intents},
        abandoned={k for k in state.get("abandoned", []) if k in intents},
        now=state.get("now", 0),
        closed=pid in state["problems"] and state["problems"][pid]["closed"],
    )


def compute(state: State, pid: str) -> tuple[rm.State, rm.Result]:
    st = to_refstate(state, pid)
    return st, rm.compute(st)


def levels(state: State, pid: str) -> dict[str, str]:
    return compute(state, pid)[1].levels


def intent_state(state: State, pid: str, iid: str) -> str:
    st, res = compute(state, pid)
    return rm.intent_state(st, res, st.intents[iid])


def gate(state: State, pid: str, iid: str) -> bool:
    st, res = compute(state, pid)
    return rm.gate(st, res, st.intents[iid])
