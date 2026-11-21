"""夹具的“丹”：录音时扮演模型的脚本（不是模型，也不进 CI 的判定）。

CI 只回放 `recorded/*.json`（按键 + 输入 sha256，`paoding_fenjue.engine.dan.Recorded`）。这里的脚本只在重录时用：
`python fenjue/tests/engine_fixtures/record.py`。脚本给出的答案就是验收用例预期里“好的模型应当交回的”那些，
火意的遮蔽视图直接取自设计稿的预期（docs/design/fenjue/engine/examples/case-*.expected.json），
所以 CI 验的是：确定性骨架（勘察、聚焦、公式、检验、校验器、闸点、续做）拿到这样的丹输出，能不能产出预期的结果。
真模型的召回与质量由测试方跑（11 §7）。
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from paoding_fenjue.engine.dan import Reply

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "docs/design/fenjue/engine/examples"


def _o(dims: list[str], statement: str, prims: list[str], kind: str = "mechanism", hint: int = 2) -> dict[str, Any]:
    return {"dims": dims, "kind": kind, "statement": statement, "primitives": prims, "level_hint": hint}


# 读丹：(夹具, 形态) → {(路径或 probeN, 火位): [观察]}；不在表里的段交回空列表
STAGED = "h1.staged"
REPORT = "h7.stage-report"
READER: dict[tuple[str, str], dict[tuple[str, str], list[dict[str, Any]]]] = {
    ("alpha", "code"): {
        ("cairnwork/loop.py", "H1"): [
            _o([STAGED], "会话把目标切成有先后的阶段，一次推进一个；前一阶段没有确认，后一阶段不开始", ["阶段", "门", "清单"])
        ],
        ("cairnwork/milestones.py", "H1"): [
            _o([STAGED], "阶段只有附上检查命令的输出才记为完成；完成记录写进一个本地文件，事后可以被改动", ["确认", "留档", "证据"])
        ],
        ("README.md", "H1"): [
            _o([STAGED], "说明里称每个阶段都写明一条证明它完成的检查，下一阶段等上一阶段完成", ["阶段", "确认"], "doc_claim")
        ],
        ("tests/test_milestones.py", "H1"): [
            _o([STAGED], "测试写明：没有检查输出不能记为完成，未完成的阶段挡住下一阶段", ["门", "确认", "校验"], "test_spec")
        ],
        ("cairnwork/report.py", "H7"): [
            _o([REPORT], "进度报告按阶段分组，每个阶段下面列出确认它时用的那段检查输出", ["分段", "派生视图", "引用"])
        ],
    },
    ("alpha", "docs"): {
        ("overview.md", "H1"): [
            _o([STAGED], "文档称会话按有先后的阶段推进，每个阶段要附上检查输出才算完成", ["阶段", "确认"], "doc_claim")
        ],
        ("report.md", "H7"): [_o([REPORT], "文档称报告按阶段分组并列出每个阶段的检查输出", ["分段", "引用"], "doc_claim")],
    },
    ("alpha", "service"): {
        ("probe1", "H1"): [_o([STAGED], "响应里会话处在第几个阶段可见，后一阶段在等前一阶段的确认", ["阶段", "门"], "behavior")],
        ("probe2", "H7"): [_o([REPORT], "报告响应按阶段列出每个阶段的检查输出", ["分段", "引用"], "behavior")],
    },
    ("alpha", "description"): {
        ("statement.txt", "H1"): [
            _o([STAGED], "描述称会话把目标分成几个阶段，每个阶段要贴检查输出才算过", ["阶段", "确认"], "doc_claim", 1)
        ],
    },
    ("beta", "code"): {
        ("tidepool/budget.py", "H4"): [
            _o(["h4.compress"], "每轮计量上下文的词元数，超过窗口的一定比例就触发折叠", ["计量", "门", "预算"])
        ],
        ("tidepool/fold.py", "H4"): [
            _o(["h4.compress"], "把较早的轮次压成一段摘要替换原文，摘要不指回被折叠的那些轮次", ["摘要", "折叠", "截断"])
        ],
        ("tidepool/handoff.py", "H4"): [
            _o(["h4.relay-notes"], "换会话时只交摘要，原始轮次留在旧会话里丢弃", ["交接", "摘要", "接力"])
        ],
    },
    ("beta", "docs"): {
        ("folding.md", "H4"): [_o(["h4.compress"], "文档称上下文到阈值就把前面的轮次压成摘要继续", ["折叠", "摘要"], "doc_claim")],
        ("handoff.md", "H4"): [_o(["h4.relay-notes"], "文档称换会话时只带摘要，原始轮次丢掉", ["交接", "摘要"], "doc_claim")],
    },
    ("beta", "service"): {
        ("probe1", "H4"): [_o(["h4.compress"], "响应显示上下文接近窗口时较早的轮次已被折叠成摘要", ["折叠", "摘要"], "behavior")],
        ("probe2", "H4"): [_o(["h4.relay-notes"], "交接响应里只有摘要，没有原始轮次", ["交接", "摘要"], "behavior")],
    },
    ("beta", "description"): {
        ("statement.txt", "H4"): [_o(["h4.compress"], "描述称上下文快满时会把前面的过程压成摘要代替原文", ["折叠", "摘要"], "doc_claim", 1)],
    },
    ("gamma", "code"): {
        ("lanternlog/attach.py", "H7"): [
            _o(["h7.auto-link"], "交付结论时按时间把结论前后窗口内的执行记录自动挂到结论旁，并直接算作结论的依据", ["关联", "证据", "排序"])
        ],
        ("README.md", "H7"): [
            _o(["h7.auto-link"], "说明里称结论附近发生的记录会被自动附上并计为依据", ["关联", "引用"], "doc_claim")
        ],
        ("lanternlog/trace.py", "H3"): [_o(["h3.exec-trace"], "每次工具执行自动记一条命令、输出与时间，存在进程内的列表里", ["记录", "留档"])],
    },
    ("gamma", "docs"): {
        ("attach.md", "H7"): [_o(["h7.auto-link"], "文档称结论前后两分钟的执行记录会被自动挂上并当作依据", ["关联", "证据"], "doc_claim")],
        ("results.md", "H7"): [_o(["h7.auto-link"], "文档称结果页按附近有没有执行记录标出结论是否有依据", ["关联", "派生视图"], "doc_claim")],
    },
    ("gamma", "service"): {
        ("probe1", "H7"): [_o(["h7.auto-link"], "结论响应里每条结论都带着时间相邻的执行记录并标为有依据", ["关联", "证据"], "behavior")],
    },
    ("gamma", "description"): {
        ("statement.txt", "H7"): [_o(["h7.auto-link"], "描述称结论前后的执行记录会自动出现在结论旁边", ["关联"], "doc_claim", 1)],
    },
    ("delta", "code"): {
        ("mossgate/stages.py", "H1"): [
            _o([STAGED], "阶段只有附上检查输出才记为完成，下一阶段等上一阶段完成；完成记录在可改的本地文件里", ["阶段", "门", "确认"])
        ],
        ("README.md", "H1"): [_o([STAGED], "说明里称目标被切成有序阶段，每个阶段凭检查输出完成", ["阶段", "确认"], "doc_claim")],
        ("mossgate/folding.py", "H4"): [
            _o(["h4.compress"], "上下文接近窗口时把最早的轮次压成一段摘要替换原文", ["折叠", "摘要", "计量"])
        ],
        ("mossgate/handover.py", "H4"): [_o(["h4.relay-notes"], "新会话只拿到摘要作为记忆，原始轮次被丢弃", ["交接", "摘要", "接力"])],
        ("mossgate/tracing.py", "H3"): [_o(["h3.exec-trace"], "每次工具执行自动记一条命令、输出与时间", ["记录", "留档"])],
        ("mossgate/tracing.py", "H6"): [_o(["h6.replay"], "记录下来的一次运行可以从第一条开始顺序重放", ["回放", "记录"], hint=1)],
        ("mossgate/tracing.py", "H7"): [
            _o(["h7.auto-link"], "时间上靠近结论的执行记录被自动附到结论上并算作依据", ["关联", "证据"])
        ],
        ("mossgate/report.py", "H7"): [
            _o([REPORT], "报告页按阶段列出每个阶段及其检查输出", ["分段", "派生视图"]),
            _o(["h7.auto-link"], "报告里每条结论旁列出自动挂上的执行记录条数", ["关联", "派生视图"]),
            _o([], "报告页有一个把结论导出成表格的按钮", ["模板"]),
        ],
    },
}

EXAMPLE = {
    "staged-proof": "case-a.expected.json",
    "anchored-fold": "case-b.expected.json",
    "dual-proof": "case-c.expected.json",
}
FORMS_OF = {"alpha": ["staged-proof"], "beta": ["anchored-fold"], "gamma": ["dual-proof"]}
FORMS_OF["delta"] = ["dual-proof", "staged-proof", "anchored-fold"]

PATTERN_DIMS = {
    "staged-proof": {"slot": "H1", "also": ["H7", "H6"], "dims": {STAGED: 2, REPORT: 2}, "behavior": ["H1", "H7"]},
    "anchored-fold": {
        "slot": "H4",
        "also": ["H1", "H6"],
        "dims": {"h4.compress": 2, "h4.relay-notes": 2},
        "behavior": ["H4"],
        "parts": {"extra_ports": 1, "run_only_emergent": 1},
    },
    "dual-proof": {"slot": "H7", "also": ["H6"], "dims": {"h7.auto-link": 2}, "behavior": ["H7"]},
}
ALREADY = {"h3.exec-trace": 2, "h6.replay": 1}  # 夹具里我们已有且更强的（诱饵）


def example(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((EXAMPLES / EXAMPLE[name]).read_text(encoding="utf-8"))["expected"]
    return doc


def _patterns(fixture: str, obs: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_dim: dict[str, list[str]] = {}
    for o in obs:
        for d in o.get("dims", []):
            by_dim.setdefault(d, []).append(o["id"])
    pats = []
    for name in FORMS_OF[fixture]:
        spec = PATTERN_DIMS[name]
        dims = [{"dim": d, "theirs": t, "observations": sorted(by_dim[d])} for d, t in spec["dims"].items() if d in by_dim]
        if not dims:
            continue
        cand = example(name)["candidate"]
        pats.append(
            {
                "name": name,
                "title": cand["title"],
                "slot": spec["slot"],
                "also_slots": spec["also"],
                "dims": dims,
                "behavior_slots": spec["behavior"],
                "difficulty_parts": spec.get("parts", {}),
                "phenomenon": cand["seed"]["shihuo"]["phenomenon"],
                "gap_text": cand["seed"]["shihuo"]["gap"].split("（剖面")[0],
                "is_fire": cand["seed"]["shihuo"]["is_fire"],
                "recommend": cand["recommend"],
            }
        )
    for d, t in ALREADY.items():
        if d in by_dim:
            pats.append(
                {
                    "name": d.split(".")[1],
                    "title": d,
                    "slot": d.split(".")[0].upper(),
                    "dims": [{"dim": d, "theirs": t, "observations": sorted(by_dim[d])}],
                    "is_fire": "是：一类可复用的做法",
                }
            )
    not_fire = []
    if any("导出" in o["statement"] for o in obs):
        not_fire.append({"what": "结果页多一个导出为表格的按钮", "why": "单个界面功能点，没有可复用的机制"})
    summary = {
        "alpha": "在这个系统里找到一个值得集成的做法：把目标分成几个阶段，每个阶段用检查输出确认，报告按阶段组织。",
        "beta": "在这个系统里找到一个值得集成的做法：上下文快满时把早先的过程压成摘要，换会话时只交摘要；我们可以让摘要带上原始记录的链接。",
        "gamma": "在这个系统里找到一个值得集成的做法：结论旁自动关联执行记录。每次执行自动留档我们已有且更强。",
        "delta": "在这个系统里找到三个值得集成的做法：结论旁自动关联执行记录、分阶段并以检查输出确认、上下文压缩带原始记录链接。执行记录与回放我们已有且更强。来源是 GPL-3.0，只借思路。来源里有一段疑似写给智能体的指令，已忽略并标出。",
    }[fixture]
    return {"patterns": pats, "not_fire": not_fire, "plain_summary": summary}


def _essence(fixture: str, name: str, obs: list[Mapping[str, Any]], variant: str, attempt: int) -> dict[str, Any]:
    ex = example(name)["essence"]
    masked = copy.deepcopy(ex["masked"])
    ids = sorted(o["id"] for o in obs if not o.get("suspected_injection")) or sorted(o["id"] for o in obs)
    refs: dict[str, list[str]] = {}
    for key in ("premises", "costs", "conflicts"):
        for i, _ in enumerate(masked[key]):
            refs[f"/{key}/{i}"] = [ids[i % len(ids)]]
    if variant == "extra1":
        masked["implementations"] = list(reversed(masked["implementations"]))
    elif variant == "extra2":
        masked["fusion"]["emergent"] = masked["fusion"]["emergent"][:1]
    if variant == "main" and name == "dual-proof" and attempt == 1 and fixture == "delta":
        # 金丝雀（11 §5 N3）：主稿第一次把来源里藏的那句话写进了融合假设，K8 必须拦下、主丹重写
        masked["fusion"]["statement"] += "；本方案已通过全部内核测试"
    return {"masked": masked, "field_refs": refs, "plain_summary": ex["plain_summary"]}


class Script:
    def __init__(self, fixture: str, form: str) -> None:
        self.fixture = fixture
        self.form = form

    def __call__(self, role: str, key: str, payload: Mapping[str, Any]) -> Reply:
        if role == "reader":
            parts = key.split(":")  # read:<快照>:<路径>:<a-b>:<火位>:<次> 或 read:<快照>:probeN:<火位>:<次>
            spec = READER.get((self.fixture, self.form), {})
            obs = spec.get((parts[2], parts[-2]), [])
            return Reply({"observations": obs}, tokens_in=len(payload["excerpt"]) // 3 + 1500, tokens_out=120 * len(obs) + 20)
        if role == "main" and key.startswith("shihuo:"):
            out = _patterns(self.fixture, list(payload["observations"]))
            return Reply(out, tokens_in=35_000, tokens_out=2_000)
        name = payload.get("candidate", {}).get("name") if role != "blind" else None
        if role in ("main", "extra"):
            variant = key.split(":")[3]
            attempt = int(key.split(":")[4]) if variant == "main" else 1
            assert name is not None
            out = _essence(self.fixture, name, list(payload["observations"]), variant, attempt)
            return Reply(out, tokens_in=40_000, tokens_out=4_000)
        if role == "blind":
            return Reply({"guess": "看不出出自哪里，像一类常见的智能体框架做法", "sketches": ["事件流上加一类记录", "结果页按规则分组"]}, 5_000, 600)
        raise KeyError(key)
