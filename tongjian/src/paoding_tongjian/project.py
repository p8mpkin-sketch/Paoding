"""判例投影与记忆条目（规格 4.3 第 1 步与"记忆条目与投影资产"；01-memory §2）。纯函数，不调用模型。

输入是一道已关题目的图状态与它自己的事件；输出是 `Case` 与 `MemItem`。封存过滤全是确定性的：
Goal 候选、`vault:` 引用、无对照的观察、E0 到 E2 的论断一律不入（01-memory §2.3）。

    解题链 := 从被判官接受的 Goal 候选出发，沿 yields、derives_from 与 Intent 前提回溯到的会话、Intent 与论断（8.4）
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from paoding_graph.contract import State, apply, canonicalize, compute_levels, empty_state, replay, state_hash

from .keys import check_key, digest, env_key, mem_id, sig_key, signature

PREFIX = "[忆] "  # 召回节点的标题前缀（与内核 reducer/recall.py 相同）
REDUCER = "graph-v1"


def _accepted_candidate(state: State, pid: str) -> str | None:
    passed = [
        v for v in state["verdicts"] if v["problem_id"] == pid and v["target"] == "goal" and v["result"] == "pass"
    ]
    return passed[-1]["candidate"] if passed else None


def chain(state: State, pid: str) -> dict[str, list[str]]:
    """解题链。没解出的题链为空。产出候选的会话所写的论断也算在链上（薄路径的 Bootstrap 直接交答案）。"""
    cand = _accepted_candidate(state, pid)
    if cand is None:
        return {"sessions": [], "intents": [], "facts": []}
    session = state["artifacts"][cand]["producer"].get("session")
    lease = state["leases"].get(session or "")
    sessions = {session} if session else set()
    intents: set[str] = set()
    todo: list[str] = []
    if lease is not None and lease["kind"] == "explore" and lease.get("target"):
        todo.append(lease["target"])
    todo += [f for f, x in state["facts"].items() if x["problem_id"] == pid and session and x["session"] == session]
    facts: set[str] = set()
    while todo:
        n = todo.pop()
        if n in facts or n in intents:
            continue
        if n in state["intents"]:
            intents.add(n)
            todo += state["intents"][n]["premises"]
            todo += [f for f, x in state["facts"].items() if x.get("yielded_by") == n]  # yields 边
        elif n in state["facts"]:
            facts.add(n)
            todo += state["facts"][n]["premises"]
    for l in state["leases"].values():
        if l["problem_id"] == pid and l["kind"] == "explore" and l.get("target") in intents:
            sessions.add(l["id"])
    return {"sessions": sorted(sessions), "intents": sorted(intents), "facts": sorted(facts)}


def seal(events: Sequence[Mapping[str, Any]], pid: str, terminal: str | None) -> dict[str, Any]:
    """链头封存（规格 2.4 的 Seal）：校验方式是把本题日志重放到 head_seq，比对 head_hash 与 state_hash。"""
    mine = [e for e in events if e["problem_id"] == pid]
    head = mine[-1]
    st = replay(mine, apply, empty_state())
    out = {"problem_id": pid, "head_seq": head["seq"], "head_hash": head["hash"], "state_hash": state_hash(st)}
    return {**out, "reducer": REDUCER, **({"terminal": terminal} if terminal else {})}


def _verdicts(state: State, pid: str, target: str) -> list[Mapping[str, Any]]:
    return [v for v in state["verdicts"] if v["problem_id"] == pid and v["target"] == target]


def _blob(state: State, aid: str) -> dict[str, Any]:
    a = state["artifacts"][aid]
    return {"hash": a["hash"], "size": a["size"]}


def portable_check(state: State, check: Mapping[str, Any], version: str) -> dict[str, Any]:
    """把判据从题内的 ArtifactId 换成字节哈希，好带进别的题（新题开题时再登记为 input 类）。"""
    out: dict[str, Any] = {
        "judge_id": check["judge_id"],
        "judge_version": version,
        "spec": _blob(state, check["spec_ref"]),
    }
    if "expect" in check:
        out["expect"] = check["expect"]
    if "control" in check:
        out["control"] = [_blob(state, a) for a in check["control"]["inputs"]]
    return out


def _admissible(state: State, pid: str, check: Mapping[str, Any] | None, candidates: set[str]) -> bool:
    """封存过滤（01-memory §2.3）：有 spec、带对照、不引保密库、不碰 Goal 候选。"""
    if not check or "spec_ref" not in check or "control" not in check or check.get("sealed"):
        return False
    if "vault:" in canonicalize(check).decode():
        return False
    refs = {check["spec_ref"], *check["control"]["inputs"]}
    return not (refs & candidates)


def recall_outcomes(state: State, pid: str, on_chain: set[str]) -> list[dict[str, Any]]:
    """本题每条召回的结果 {mem, verdict, on_chain, fact}：记忆状态更新的唯一入口（随 case_sealed 带回）。"""
    items = (state["problems"][pid].get("recall") or {}).get("items", [])
    sessions = {l["id"] for l in state["leases"].values() if l["problem_id"] == pid and l["kind"] == "recall"}
    out = []
    for it in items:
        fid = next(
            (
                f
                for f, x in state["facts"].items()
                if x["problem_id"] == pid
                and x["session"] in sessions
                and x["title"] == PREFIX + it["title"]
                and canonicalize(x.get("check")) == canonicalize(it["check"])
            ),
            None,
        )
        vs = _verdicts(state, pid, fid) if fid else []
        verdict = vs[-1]["result"] if vs else ("pending" if fid else "not_submitted")
        out.append({"mem": it["mem"], "verdict": verdict, "on_chain": fid in on_chain, "fact": fid})
    return out


def case(state: State, events: Sequence[Mapping[str, Any]], pid: str, model_epoch: str) -> dict[str, Any]:
    """关题即投影出一份判例（规格 4.3 的 Case；最小版本的归因只给分角色花费）。"""
    p = state["problems"][pid]
    terminal = p.get("terminal") or "unsolved"
    ch = chain(state, pid)
    _, res = compute_levels(state, pid)
    cand = _accepted_candidate(state, pid)
    win = state["leases"].get(state["artifacts"][cand]["producer"].get("session") or "") if cand else None
    path = "none" if win is None else ("thin" if win["kind"] == "bootstrap" else "thick")
    cuts = [
        {
            "title": i["title"],
            "judge_id": i["done"]["judge_id"],
            "on_chain": iid in ch["intents"],
            "attempts": sum(1 for l in state["leases"].values() if l.get("target") == iid and l["kind"] == "explore"),
            "knot": False,
        }
        for iid, i in sorted(state["intents"].items(), key=lambda kv: int(kv[0][2:]))
        if i["problem_id"] == pid and i.get("done")
    ]
    excluded = [n["title"] for nid, n in _nodes(state, pid) if res.levels.get(nid) == "X"]
    spend: dict[str, int] = {}
    for c in state["costs"]:
        if c["problem_id"] == pid:
            spend[c["lease_kind"]] = spend.get(c["lease_kind"], 0) + int(c["usd_milli"])
    s = seal(events, pid, terminal)
    return {
        "id": digest(s),
        "seal": s,
        "sig": signature(p),
        "sig_key": sig_key(p),
        "env_key": env_key(p),
        "model_epoch": model_epoch,
        "title": p["title"],
        "terminal": terminal,
        "path": path,
        "cuts": cuts,
        "excluded": excluded,
        "attribution": {"chain": ch, "spend_usd_milli": dict(sorted(spend.items()))},
        "recall_outcomes": recall_outcomes(state, pid, set(ch["facts"])),
    }


def _nodes(state: State, pid: str) -> list[tuple[str, Mapping[str, Any]]]:
    nodes: list[tuple[str, Mapping[str, Any]]] = [(f, x) for f, x in state["facts"].items() if x["problem_id"] == pid]
    nodes += [(i, x) for i, x in state["intents"].items() if x["problem_id"] == pid]
    return sorted(nodes, key=lambda kv: int(kv[0][2:]))


def derive(state: State, pid: str, c: Mapping[str, Any]) -> list[dict[str, Any]]:
    """判例往下的二次投影：此牛层的环境事实与排除路径，类牛层的花费画像（最小版本只这三类）。"""
    _, res = compute_levels(state, pid)
    env = {"env_key": c["env_key"]}
    src = {"case": c["id"], "problem": pid, "seal_head": c["seal"]["head_hash"]}
    candidates = {r["candidate"] for r in state["requests"].values() if r["problem_id"] == pid and r["candidate"]}
    out: list[dict[str, Any]] = []
    for fid in c["attribution"]["chain"]["facts"]:
        f = state["facts"][fid]
        if f["claim_type"] != "observation" or res.levels.get(fid) != "E3":
            continue
        check = f.get("check")
        if check is None or not _admissible(state, pid, check, candidates):
            continue
        ok = [v for v in _verdicts(state, pid, fid) if v["result"] == "pass" and v["grade"] == "decisive"]
        if not ok or not ok[-1].get("controlled"):
            continue
        pc = portable_check(state, check, ok[-1]["version"])
        title = f["title"].removeprefix(PREFIX)  # 召回节点再次在链：同一条判据，同一个 id
        out.append(
            {
                "id": mem_id("env_fact", env, check_key(pc)),
                "kind": "env_fact",
                "scope": env,
                "source": {**src, "node": fid},
                "title": title,
                "check": pc,
            }
        )
    for nid, n in _nodes(state, pid):
        if res.levels.get(nid) != "X" or n["title"].startswith(PREFIX):
            continue
        key = {"title": n["title"], "check": check_key(dict(n.get("check") or n.get("done") or {}))}
        out.append(
            {
                "id": mem_id("excluded", env, key),
                "kind": "excluded",
                "scope": env,
                "source": {**src, "node": nid},
                "title": n["title"],
            }
        )
    spend = c["attribution"]["spend_usd_milli"]
    out.append(
        {
            "id": mem_id("spend_profile", {"sig_key": c["sig_key"]}, c["id"]),
            "kind": "spend_profile",
            "scope": {"sig_key": c["sig_key"]},
            "source": src,
            "title": f"花费画像：{c['title']}",
            "model_epoch": c["model_epoch"],
            "body": {"usd_milli": sum(spend.values()), "by_kind": spend, "terminal": c["terminal"], "path": c["path"]},
        }
    )
    uniq: dict[str, dict[str, Any]] = {}
    for m in out:
        uniq.setdefault(m["id"], m)
    return list(uniq.values())
