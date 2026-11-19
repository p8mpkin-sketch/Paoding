"""任务包渲染与留档（§3.4.2，HMI H4）。

顺序：① 角色提示 ② 题目简报 ③ 锦囊索引 ④ 节点清单 ⑤ 状态 ⑥ 焦点 ⑦ 限额。
①到④同题内只追加不改写，是稳定前缀：确定性键序，不放时间戳、随机 id、当前时间。
①到⑤经“追加系统提示”注入，⑥⑦作为首条用户消息，所以同一 as_of_seq 下并发启动的会话系统前缀逐字节相同。

④只列节点 id 与 title，按创建顺序；等级与状态这类每次都变的东西放在⑤。
整个任务包以确定性 JSON 登记为 authored 类 Artifact，producer.session 即租约 id（会话令牌决定）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paoding_graph.contract import State, as_of_seq, intent_status, node_levels

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
MEDIA_TYPE = "application/vnd.paoding.task-package+json"


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Rendered:
    package: dict[str, Any]  # TaskPackage 的内容形态（各段正文就地给出，留档时整体登记）
    system: str  # ①–⑤：追加系统提示
    user: str  # ⑥⑦：首条用户消息
    prefix: str = ""  # ①–④：同题内只追加的稳定前缀

    def as_bytes(self) -> bytes:
        return _j(self.package).encode()


ACCESS_NOTE = (
    "- request_access：需要访问授权范围之外的外部地址时，调用它申请，写明为什么需要（target 写 host:port）。"
    "申请不是授权：granted 才能连，pending 先做别的，denied 就别再要这个地址。不要猜别的地址或换端口重试。"
    "本任务开始时没有任何出站权限。\n"
)


def role_prompt(role: str, access: bool = False) -> str:
    """access：运行时扩权开着、会话有 request_access 工具时（设计 docs/design/runtime-grants/ §6.2）补一段。"""
    common = (PROMPTS / "common.md").read_text(encoding="utf-8")
    if access:  # 接在工具清单（show 那一行）之后
        at = common.index("\n", common.index("- show：")) + 1
        common = common[:at] + ACCESS_NOTE + common[at:]
    return common + "\n" + (PROMPTS / f"{role}.md").read_text(encoding="utf-8")


def problem_brief(state: State, pid: str, statement: str, judges_cfg: dict[str, Any]) -> str:
    p = state["problems"][pid]
    judges = [{"judge_id": j, "grade": judges_cfg.get(j, {}).get("grade")} for j in sorted(p["judges"])]
    return "\n".join(
        [
            f"题目：{p['title']}",
            "题面：",
            statement.rstrip(),
            f"目标：{p['goal']['statement']}",
            f"目标判据：{_j(p['goal']['check'])}，候选上限 {p['goal']['max_attempts']}",
            f"授权范围：{_j(p['scope'])}",
            f"可用判官：{_j(judges)}",
        ]
    )


def memory_notes(state: State, pid: str) -> str:
    """开题时随召回清单登记的叙述（v1.5，01-memory §4）：排除路径、花费画像，以及消融臂 recall_noverify
    里不复核的事实。它们是叙述或估值，不是节点，不能作前提；复核过的召回事实在④里，是本题自己的节点。
    没有召回清单的题这里是空串，③与旧版逐字节相同。"""
    notes = (state["problems"][pid].get("recall") or {}).get("notes") or []
    if not notes:
        return ""
    return "\n记忆（叙述，未在本题复核；上次在同一环境的情形，可能已变）：\n" + _j(notes)


def listing(state: State, pid: str) -> str:
    nodes: list[Mapping[str, Any]] = [
        *[f for f in state["facts"].values() if f["problem_id"] == pid],
        *[i for i in state["intents"].values() if i["problem_id"] == pid],
    ]
    nodes.sort(key=lambda n: int(n["id"][2:]))
    return "\n".join(f"{n['id']} {n['title']}" for n in nodes) or "（暂无）"


def status(state: State, pid: str, budget: Mapping[str, Any]) -> str:
    lv = node_levels(state, pid)
    facts = {fid: lv.get(fid) for fid, f in state["facts"].items() if f["problem_id"] == pid}
    intents = {iid: intent_status(state, pid, iid) for iid, i in state["intents"].items() if i["problem_id"] == pid}
    intents = {k: v for k, v in intents.items() if v != "open"}  # 只列非默认状态，⑤随图增长尽量慢
    b = {k: budget.get(k, {}).get("usd_milli") for k in ("cap", "spent", "reserved")}
    return _j({"levels": facts, "intents_not_open": intents, "budget_usd_milli": b})


def render(
    state: State,
    pid: str,
    lease: Mapping[str, Any],
    *,
    statement: str,
    judges_cfg: dict[str, Any],
    budget: Mapping[str, Any],
    kits: list[dict[str, Any]] | None = None,
    focus: dict[str, Any] | None = None,
    limits: dict[str, Any] | None = None,
) -> Rendered:
    role = lease["kind"]
    kit_index = sorted(
        ({"name": k["name"], "description": k["description"], "path": k["path"]} for k in (kits or [])),
        key=lambda k: k["name"],
    )
    focus = dict(focus or {})
    focus.setdefault("premises", [])
    focus.setdefault(
        "hints", sorted(h for h, x in state["hints"].items() if x["problem_id"] == pid and not x.get("closed"))
    )
    if role == "explore":
        focus.setdefault("intent", lease["target"])
        it = state["intents"][lease["target"]]
        focus.setdefault("restate", f"推进 Intent {lease['target']}：{it['title']}")
    focus.setdefault(
        "restate",
        {"bootstrap": "摸清材料与环境，提交直接观察到的事实。", "reason": "读图，提交推断与下一步 Intent。"}.get(
            role, ""
        ),
    )
    hint_text = [{"id": h, "text": state["hints"][h]["text"]} for h in focus["hints"]]
    sections = [
        ("① 角色", role_prompt(role, "request_access" in (limits or {}).get("tools", ()))),
        ("② 题目", problem_brief(state, pid, statement, judges_cfg)),
        ("③ 锦囊", _j(kit_index) + memory_notes(state, pid)),
        ("④ 节点", listing(state, pid)),
    ]
    # 段间空行放在下一段的开头：这样①–④的字节在只追加节点时恰好是后一个包的前缀（3.4.5 的 5）
    prefix = "\n".join(f"# {h}\n{t.rstrip()}\n" for h, t in sections)
    st = status(state, pid, budget)
    system = prefix + f"\n# ⑤ 状态\n{st}\n"
    shown = {**focus, **({"hint_text": hint_text} if hint_text else {})}
    shown.pop("restate")  # 复述放在最末一行（⑥的 restate）
    user = f"# ⑥ 焦点\n{_j(shown)}\n\n# ⑦ 限额\n{_j(limits or {})}\n\n任务：{focus['restate']}\n"
    package = {
        "role_prompt": sections[0][1],
        "problem_brief": sections[1][1],
        "kit_index": kit_index,
        **({"memory_notes": sections[2][1]} if sections[2][1] != _j(kit_index) else {}),
        "listing": sections[3][1],
        "status": st,
        "focus": focus,
        "limits": limits or {},
        "as_of_seq": as_of_seq(state),
        "task_id": lease["id"],
        "role": role,
    }
    return Rendered(package, system, user, prefix)


def common_prefix_ratio(a: str, b: str) -> float:
    """b 与 a 的公共前缀占 a 的字节比例。遥测读数，不设阈值（异议 002 第 3 项裁决）。"""
    x, y = a.encode(), b.encode()
    n = 0
    for n, (p, q) in enumerate(zip(x, y, strict=False)):  # noqa: B007  n 在循环后使用
        if p != q:
            break
    else:
        n = min(len(x), len(y))
    return n / len(x) if x else 1.0
