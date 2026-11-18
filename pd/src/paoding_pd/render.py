"""pd 的文本输出约定（§3.2 输出约定；HMI F0）。

1. 四语域行首标记。语域由数据的出处类别查 REGISTER 表得到，不由内容决定：渲染入口 `Out.add(src, text)`
   只收出处类别，没有直接写语域的入口（HMI 3.4 的强制点）。
2. 等级词表固定（LEVEL_WORDS），界面不另造说法。
3. 判据徽章：凡写“达成、通过、solved”的位置都带判官名与版本（judge@version）。
4. accepted 的题不出现“证明”字样。

所有文本按纯文本输出：模型撰写的内容里的换行被压成空格，行首标记不会被内容伪造。
"""
from __future__ import annotations

from paoding_graph.contract import LEVEL_WORDS, REGISTER, intent_status, node_levels, seen_card

# 出处类别 → 语域的表与等级词表在图服务一侧（views.py）：pd 的文本与网页的卡片读同一张表（一卡多端）。


def _flat(text: str) -> str:
    return " ".join(str(text).split())


class Out:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, src: str, text: str) -> None:
        self.lines.append(f"[{REGISTER[src]}] {_flat(text)}")

    def blank(self) -> None:
        self.lines.append("")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


# ---------- 判据徽章与等级 ----------

def judge_badge(state: dict, pid: str, judge_id: str) -> str:
    snap = state["problems"][pid].get("judge_snapshot", {}).get(judge_id, {})
    return f"{judge_id}@{snap.get('version', '?')}"


def deciding_verdict(state: dict, pid: str, target: str) -> dict | None:
    vs = [v for v in state["verdicts"] if v["problem_id"] == pid and v["target"] == target]
    return vs[-1] if vs else None


def level_phrase(state: dict, pid: str, target: str, level: str | None) -> str:
    if level is None:
        return "无等级"
    word = LEVEL_WORDS.get(level, level)
    if level in ("E3", "E3d", "X"):
        v = deciding_verdict(state, pid, target)
        who = f"{v['judge']}@{v['version']}" if v else "裁决人"
        return f"{level} {word}（{who}）"
    return f"{level} {word}"


def terminal_phrase(state: dict, pid: str) -> str:
    p = state["problems"][pid]
    if not p.get("closed"):
        return "进行中"
    t = p.get("terminal", "unsolved")
    if t == "solved":
        return f"solved（{judge_badge(state, pid, p['goal']['check']['judge_id'])}）"
    if t == "accepted":
        return "accepted（人验收，未经判官判定）"
    return "unsolved"


# ---------- 视图 ----------

def status(state: dict, pid: str, budget: dict) -> str:
    p = state["problems"][pid]
    lv = node_levels(state, pid)
    o = Out()
    o.add("terminal", f"题 {pid} 终态 {terminal_phrase(state, pid)}；目标等级 {level_phrase(state, pid, 'goal', lv.get('goal'))}")
    o.add("title", f"题名：{p['title']}")
    o.add("predicate", f"目标判据 {judge_badge(state, pid, p['goal']['check']['judge_id'])} "
                       f"expect={p['goal']['check'].get('expect', {})} 候选上限 {p['goal']['max_attempts']}")
    o.add("profile", "画像 " + " ".join(f"{k}={v}" for k, v in sorted(p["profile"].items()))
          + ("（含人工覆盖）" if p.get("profile_overrides") else ""))
    o.add("budget", _budget_line(budget))
    o.blank()
    facts = sorted((f for f in state["facts"].values() if f["problem_id"] == pid), key=lambda f: int(f["id"][2:]))
    for f in facts:
        _fact(o, state, pid, f, lv.get(f["id"]))
    intents = sorted((i for i in state["intents"].values() if i["problem_id"] == pid), key=lambda i: int(i["id"][2:]))
    for i in intents:
        _intent(o, state, pid, i, lv.get(i["id"]))
    hints = sorted((h for h in state["hints"].values() if h["problem_id"] == pid), key=lambda h: h["seq"])
    for h in hints:
        o.add("hint", f"{h['id']} {h['author']}{'（已关闭）' if h.get('closed') else ''}：{h['text']}")
        after = [i["id"] for i in intents if int(i["id"][2:]) > h["seq"]]
        o.add("structure", f"{h['id']} 之后新增的 Intent：{', '.join(after) or '无'}（时序关联，不是因果）")
    for l in sorted((l for l in state["leases"].values() if l["problem_id"] == pid and l["active"]),
                    key=lambda l: l["issued_seq"]):
        o.add("lease", f"在途 {l['id']} {l['kind']}{' ' + l['target'] if l.get('target') else ''} "
                       f"预留 {l['reserve']['usd_milli']} 毫美元")
    return o.text()


def _budget_line(b: dict) -> str:
    cap, spent, res = b["cap"].get("usd_milli"), b["spent"]["usd_milli"], b["reserved"]["usd_milli"]
    marks = "、".join(f"{m}%" for m in b.get("marks", [])) or "无"
    return f"预算 花 {spent} / 留 {res} / 顶 {cap} 毫美元；标记 {marks}"


def _fact(o: Out, state: dict, pid: str, f: dict, level: str | None) -> None:
    if f["claim_type"] == "observation" and f.get("check"):
        c = f["check"]
        spec = state["artifacts"][c["spec_ref"]]["hash"][:12] if c.get("spec_ref") else "无"
        o.add("level", f"{f['id']} {level_phrase(state, pid, f['id'], level)}；谓词 {judge_badge(state, pid, c['judge_id'])} "
                       f"规格 {spec} expect={c.get('expect', {})}")
        roots = ", ".join(f"{g}({state['artifacts'][g]['class']})" for g in f.get("grounds", []))
        o.add("structure", f"{f['id']} 证据根：{roots or '无证据根'}")
    else:
        o.add("level", f"{f['id']} {level_phrase(state, pid, f['id'], level)}；推断，前提 {', '.join(f['premises']) or '无'}")
    o.add("title", f"{f['id']} 标题：{f['title']}")
    if f.get("summary"):
        o.add("summary", f"{f['id']} 摘要：{f['summary']}")


def _intent(o: Out, state: dict, pid: str, i: dict, level: str | None) -> None:
    st = intent_status(state, pid, i["id"])
    done = ""
    if i.get("done"):
        badge = judge_badge(state, pid, i["done"]["judge_id"])
        done = f"；完成判据 {badge}" + (f"，已达成（{badge}）" if st == "achieved" else "")
    o.add("status", f"{i['id']} 状态 {st}；风险 {i['risk']}；预算 {i['budget']['usd_milli']} 毫美元{done}")
    o.add("title", f"{i['id']} 标题：{i['title']}")
    if i.get("summary"):
        o.add("summary", f"{i['id']} 摘要：{i['summary']}")
    dr = state.get("decision_reasons", {}).get(i["id"])
    if dr:
        o.add("human_reason", f"{i['id']} {'拒绝' if dr['decision'] == 'deny' else '批准'}，{dr['by']}：{dr['reason']}")
    if "expected_gain" in i:
        o.add("estimate", f"{i['id']} ≈期望增益 {i['expected_gain']}")


def report(state: dict, pid: str, budget: dict) -> str:
    """首行：终态与根结论的等级上限。确定性投影，不调用模型；未解出时同样产出。"""
    lv = node_levels(state, pid)
    o = Out()
    o.add("terminal", f"终态 {terminal_phrase(state, pid)}；根结论等级上限 {level_phrase(state, pid, 'goal', lv.get('goal'))}")
    o.add("budget", _budget_line(budget))
    o.blank()
    rank = {"E3": 0, "E3d": 1, "E2": 2, "E1": 3, "E0": 4, "X": 5}
    facts = sorted((f for f in state["facts"].values() if f["problem_id"] == pid),
                   key=lambda f: (rank.get(lv.get(f["id"]), 9), int(f["id"][2:])))
    for f in facts:
        _fact(o, state, pid, f, lv.get(f["id"]))
    abandoned = [i for i in state["intents"].values() if i["problem_id"] == pid
                 and intent_status(state, pid, i["id"]) == "abandoned"]
    for i in abandoned:
        o.add("status", f"已放弃 {i['id']}")
        o.add("title", f"{i['id']} 标题：{i['title']}")
    return o.text()


def profile(state: dict, pid: str) -> str:
    p = state["problems"][pid]
    o = Out()
    derived = p.get("derived_profile", p["profile"])
    for k, v in sorted(p["profile"].items()):
        o.add("profile", f"{k} = {v}" + (f"（推出值 {derived[k]}，已由人覆盖）" if derived.get(k) != v else ""))
    for ov in p.get("profile_overrides", []):
        o.add("human_reason", f"覆盖 {ov['axis']}：{ov['derived']} → {ov['value']}，{ov['by']}：{ov['reason']}")
    o.add("structure", "依据：可逆性取授权范围里的最高风险；判官轴取目标判官的等级与代价；信息轴看是否有外部资源")
    for r in p["scope"]:
        o.add("structure", f"范围 {r['resource']} {r['pattern']} {','.join(r['actions'])} {r['risk']}")
    return o.text()


def approval_card(state: dict, pid: str, iid: str) -> str:
    """审批卡（HMI 3.5）的文本形态。字段来自图里校验过的数据；末行是这张卡的 card_hash（H2），与网页卡相同。"""
    i = state["intents"][iid]
    lv = node_levels(state, pid)
    o = Out()
    o.add("status", f"审批 {iid}：状态 {intent_status(state, pid, iid)}；风险 {i['risk']}；预留 {i['budget']['usd_milli']} 毫美元；"
                    "一次批准只管一次租约")
    o.add("title", f"动作：{i['title']}")
    if i.get("summary"):
        o.add("summary", f"说明：{i['summary']}")
    o.add("structure", "回退：未声明回退" if not i.get("rollback") else "回退：见下")
    if i.get("done"):
        o.add("predicate", f"结果预测：完成判据 {judge_badge(state, pid, i['done']['judge_id'])} "
                           f"expect={i['done'].get('expect', {})}")
    for p in i["premises"]:
        o.add("level", f"前提 {p} {level_phrase(state, pid, p, lv.get(p))}")
    if not i["premises"]:
        o.add("level", "前提：无")
    for r in i.get("needs_scope", []):
        o.add("structure", f"需要范围 {r['resource']} {r['pattern']} {','.join(r['actions'])} {r['risk']}")
    o.add("structure", "争议：无未决反证（M0 无反证操作）")
    seen = seen_card(state, pid, "approval", iid)
    o.add("structure", f"card_hash {seen['card_hash'][:12]} · 所见 seq {seen['seq']}")
    return o.text()
