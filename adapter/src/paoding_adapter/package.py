"""任务包渲染与留档（§3.4.2，HMI H4）。

顺序：① 角色提示 ② 题目简报 ③ 锦囊索引 ④ 节点清单 ⑤ 状态 ⑥ 焦点 ⑦ 限额。
①到④同题内只追加不改写，是稳定前缀：确定性键序，不放时间戳、随机 id、当前时间。
①到⑤经“追加系统提示”注入，⑥⑦作为首条用户消息，所以同一 as_of_seq 下并发启动的会话系统前缀逐字节相同。

④只列节点 id 与 title，按创建顺序；等级与状态这类每次都变的东西放在⑤。
整个任务包以确定性 JSON 登记为 authored 类 Artifact，producer.session 即租约 id（会话令牌决定）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from paoding_graph.contract import as_of_seq, intent_status, node_levels

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
MEDIA_TYPE = "application/vnd.paoding.task-package+json"


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Rendered:
    package: dict            # TaskPackage 的内容形态（各段正文就地给出，留档时整体登记）
    system: str              # ①–⑤：追加系统提示
    user: str                # ⑥⑦：首条用户消息
    prefix: str = ""         # ①–④：同题内只追加的稳定前缀

    def as_bytes(self) -> bytes:
        return _j(self.package).encode()


def role_prompt(role: str) -> str:
    return (PROMPTS / "common.md").read_text(encoding="utf-8") + "\n" + \
        (PROMPTS / f"{role}.md").read_text(encoding="utf-8")


def problem_brief(state: dict, pid: str, statement: str, judges_cfg: dict) -> str:
    p = state["problems"][pid]
    judges = [{"judge_id": j, "grade": judges_cfg.get(j, {}).get("grade")} for j in sorted(p["judges"])]
    return "\n".join([
        f"题目：{p['title']}",
        "题面：", statement.rstrip(),
        f"目标：{p['goal']['statement']}",
        f"目标判据：{_j(p['goal']['check'])}，候选上限 {p['goal']['max_attempts']}",
        f"授权范围：{_j(p['scope'])}",
        f"可用判官：{_j(judges)}",
    ])


def listing(state: dict, pid: str) -> str:
    nodes = [n for c in ("facts", "intents") for n in state[c].values() if n["problem_id"] == pid]
    nodes.sort(key=lambda n: int(n["id"][2:]))
    return "\n".join(f"{n['id']} {n['title']}" for n in nodes) or "（暂无）"


def status(state: dict, pid: str, budget: dict) -> str:
    lv = node_levels(state, pid)
    facts = {fid: lv.get(fid) for fid, f in state["facts"].items() if f["problem_id"] == pid}
    intents = {iid: intent_status(state, pid, iid) for iid, i in state["intents"].items() if i["problem_id"] == pid}
    intents = {k: v for k, v in intents.items() if v != "open"}          # 只列非默认状态，⑤随图增长尽量慢
    b = {k: budget.get(k, {}).get("usd_milli") for k in ("cap", "spent", "reserved")}
    return _j({"levels": facts, "intents_not_open": intents, "budget_usd_milli": b})


def render(state: dict, pid: str, lease: dict, *, statement: str, judges_cfg: dict, budget: dict,
           kits: list[dict] | None = None, focus: dict | None = None, limits: dict | None = None) -> Rendered:
    role = lease["kind"]
    kit_index = sorted(({"name": k["name"], "description": k["description"], "path": k["path"]}
                        for k in (kits or [])), key=lambda k: k["name"])
    focus = dict(focus or {})
    focus.setdefault("premises", [])
    focus.setdefault("hints", sorted(h for h, x in state["hints"].items()
                                     if x["problem_id"] == pid and not x.get("closed")))
    if role == "explore":
        focus.setdefault("intent", lease["target"])
        it = state["intents"][lease["target"]]
        focus.setdefault("restate", f"推进 Intent {lease['target']}：{it['title']}")
    focus.setdefault("restate", {"bootstrap": "摸清材料与环境，提交直接观察到的事实。",
                                 "reason": "读图，提交推断与下一步 Intent。"}.get(role, ""))
    hint_text = [{"id": h, "text": state["hints"][h]["text"]} for h in focus["hints"]]
    sections = [
        ("① 角色", role_prompt(role)),
        ("② 题目", problem_brief(state, pid, statement, judges_cfg)),
        ("③ 锦囊", _j(kit_index)),
        ("④ 节点", listing(state, pid)),
    ]
    # 段间空行放在下一段的开头：这样①–④的字节在只追加节点时恰好是后一个包的前缀（3.4.5 的 5）
    prefix = "\n".join(f"# {h}\n{t.rstrip()}\n" for h, t in sections)
    st = status(state, pid, budget)
    system = prefix + f"\n# ⑤ 状态\n{st}\n"
    shown = {**focus, **({"hint_text": hint_text} if hint_text else {})}
    shown.pop("restate")                                   # 复述放在最末一行（⑥的 restate）
    user = (f"# ⑥ 焦点\n{_j(shown)}\n\n"
            f"# ⑦ 限额\n{_j(limits or {})}\n\n任务：{focus['restate']}\n")
    package = {"role_prompt": sections[0][1], "problem_brief": sections[1][1], "kit_index": kit_index,
               "listing": sections[3][1], "status": st, "focus": focus, "limits": limits or {},
               "as_of_seq": as_of_seq(state), "task_id": lease["id"], "role": role}
    return Rendered(package, system, user, prefix)


def common_prefix_ratio(a: str, b: str) -> float:
    """b 与 a 的公共前缀占 a 的字节比例。遥测读数，不设阈值（异议 002 第 3 项裁决）。"""
    x, y = a.encode(), b.encode()
    n = 0
    for n, (p, q) in enumerate(zip(x, y)):
        if p != q:
            break
    else:
        n = min(len(x), len(y))
    return n / len(x) if x else 1.0
