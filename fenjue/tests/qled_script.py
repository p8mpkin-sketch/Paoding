"""按题读的“丹”：测试里扮演模型的脚本（docs/design/fenjue/14-question-led.md）。

原有的步骤（片段阅读、识别候选、提炼、归位）照旧交给夹具目录里的 `script.Script`；按题读新增的几步在这里答：
题面换检索词、从真实名字里挑词、按题阅读（细事实 + 观察 + 值得追的名字）、答题稿、回头核对、改写。
夹具目录（engine_fixtures/）一个字节不动：这里只是换了一句带问句的题面去读同一份组合夹具，脚本放在夹具目录之外。
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "engine_fixtures"))

from script import READER, Script  # noqa: E402

from paoding_fenjue.engine.dan import Reply  # noqa: E402

STATEMENT = "看看验收夹具丁的上下文压缩是怎么做的、阶段确认又是怎么实现的，有什么值得我们集成的做法"

TERMS = {
    "Q1": {"zh": ["压缩", "摘要"], "en": ["fold", "summar", "context"]},
    "Q2": {"zh": ["阶段"], "en": ["stage", "check"]},
}

# 细事实：路径 → [(子问, 类别, 一句话, [起行, 止行])]。行号对着夹具里的原文写的（mossgate/*.py）。
FACTS: dict[str, list[tuple[str, str, str, list[int]]]] = {
    "mossgate/folding.py": [
        ("Q1", "config", "触发折叠的比例由常量 FOLD_AT 给出，值是 0.8", [3, 3]),
        ("Q1", "mechanism", "count_tokens 按每条文本长度除以 4 估算词元数，不调用真正的分词器", [6, 7]),
        ("Q1", "mechanism", "fold_turns 在估算值不超过 FOLD_AT 乘以窗口时原样交回，不做折叠", [12, 13]),
        ("Q1", "mechanism", "折叠时保留最近的 keep 条（缺省 6 条），更早的交给模型压成一段摘要", [10, 15]),
        ("Q1", "mechanism", "摘要以 role 为 summary 的一条记录放在保留的几条前面，被折叠的原文不再保留", [16, 16]),
    ],
    "mossgate/handover.py": [
        ("Q1", "mechanism", "换会话时新会话只拿到摘要作为记忆", [1, 9]),
    ],
    "mossgate/stages.py": [
        ("Q2", "mechanism", "阶段要附上检查输出才记为完成", [1, 28]),
        ("Q2", "mechanism", "下一阶段等上一阶段完成后才开始", [1, 28]),
    ],
}
OWN_FACT = ("Q1", "mechanism", "我们自己的压缩在事件条数过线时触发")


class QScript:
    """`verdicts`：条目编号 → 第一轮核对的判定（缺省 supported）；改写后的第二轮一律 supported。
    `skip_asked`：识别候选的前几次不提名压缩这个主题（模拟模型把已登记的主题剔掉）。
    `truncate_first`：这些文件的第一次阅读被输出上限截断。`cite_unknown`：答题稿的建议引用一个不存在的事实编号。
    `depth`：子问 → 审读判的层次（缺省 mechanism）。`q1_dir`：挑词时为 Q1 挑的目录（含这个字样的）。
    `follow`：路径 → 读这个文件时交回的值得追的名字（覆盖缺省）。"""

    def __init__(
        self,
        verdicts: Mapping[str, str] | None = None,
        *,
        skip_asked: int = 0,
        truncate_first: tuple[str, ...] = (),
        cite_unknown: bool = False,
        depth: Mapping[str, str] | None = None,
        q1_dir: str = "\0",
        follow: Mapping[str, list[dict[str, str]]] | None = None,
    ) -> None:
        self.base = Script("delta", "code")
        self.verdicts = dict(verdicts or {})
        self.skip_asked, self.truncate_first, self.cite_unknown = skip_asked, truncate_first, cite_unknown
        self.depth, self.q1_dir = dict(depth or {}), q1_dir
        self.follow = dict(follow or {})
        self.calls: list[str] = []
        self.payloads: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def call(self, role: str, key: str, payload: Mapping[str, Any]) -> Reply:
        with self._lock:
            self.calls.append(key)
            self.payloads[key] = dict(payload)
        t = payload.get("template")
        if t == "wenti/terms/v1":
            return Reply({"terms": [{"q": q["id"], **TERMS[q["id"]]} for q in payload["questions"]]}, 400, 150)
        if t == "wenti/pick/v1":
            names = _section(payload["excerpt"], "名字")
            files = _section(payload["excerpt"], "文件")
            dirs = [d.split(" | ", 1)[0] for d in _section(payload["excerpt"], "目录")]
            q1 = [n for n in names if "fold" in n.lower()] or [n for n in names if "count" in n.lower()]
            picks = [
                {"q": "Q1", "names": q1, "files": _has(files, "folding"), "dirs": _has(dirs, self.q1_dir)},
                {"q": "Q2", "names": [n for n in names if "stage" in n.lower()], "files": _has(files, "stages")},
            ]
            return Reply({"picks": picks}, 900, 200)
        if t == "reader/q/v1":
            return self._read(key, payload)
        if t == "shihuo/v2":
            with self._lock:
                out = self.base(role, key, payload).output
            tail = key.rsplit(":", 1)[1]
            if (int(tail) if tail.isdigit() else 1) <= self.skip_asked:
                out = {**out, "patterns": [p for p in out["patterns"] if p["name"] != "anchored-fold"]}
            return Reply(out, 20_000, 2_500)
        if t == "dati/v1":
            return self._draft(payload)
        if t == "heyan/v1":
            second = key.startswith("heyan:r2")
            rows = []
            for it in payload["items"]:
                v = "supported" if second else self.verdicts.get(it["n"], "supported")
                rows.append({"n": it["n"], "verdict": v, "note": "" if v == "supported" else "原文没有说到后半句"})
            return Reply({"verdicts": rows}, 3_000, 300)
        if t == "heyan/depth/v1":
            rows = [
                {"q": q["id"], "level": self.depth.get(q["id"], "mechanism"), "missing": ""}
                for q in payload["questions"]
            ]
            for r in rows:
                if r["level"] != "mechanism":
                    r["missing"] = "动手做的那段逻辑没有讲到"
            return Reply({"depth": rows}, 1_500, 200)
        if t == "dati/fix/v1":
            fixed = [{"n": it["n"], "text": it["text"] + "（已按原文收窄）"} for it in payload["items"]]
            return Reply({"fixed": fixed}, 2_000, 300)
        with self._lock:  # 夹具的脚本自己不带锁：并发的提炼与归位在这里排队
            return self.base(role, key, payload)

    def _read(self, key: str, payload: Mapping[str, Any]) -> Reply:
        path, (a, b) = payload["path"], payload["lines"]
        if path in self.truncate_first and key.endswith(":1"):
            return Reply(None, 5_000, 16_000, "max_tokens")
        if payload["side"] == "ours":
            q, k, t = OWN_FACT
            fact = {"q": q, "kind": k, "text": t, "lines": [a, min(b, a + 2)]}
            return Reply({"facts": [fact], "observations": [], "follow": []}, 4_000, 300)
        facts = [
            {"q": q, "kind": k, "text": t, "lines": [max(a, x), min(b, y)]} for q, k, t, (x, y) in FACTS.get(path, [])
        ]
        qid = facts[0]["q"] if facts else "Q2" if path == "README.md" else payload["questions"][0]["id"]
        obs = [
            {**o, "lines": [a, b], "q": qid} for o in READER[("delta", "code")].get((path, payload.get("slot", "")), [])
        ]
        follow: list[Any] = [{"name": "fold_turns", "q": "Q1"}] if path.endswith("handover.py") else []
        follow = self.follow.get(path, follow)
        return Reply(
            {"facts": facts, "observations": obs, "follow": follow}, 4_000 + (b - a) * 12, 200 + 90 * len(facts)
        )

    def _draft(self, payload: Mapping[str, Any]) -> Reply:
        theirs, ours = payload["facts_theirs"], payload["facts_ours"]
        answers = []
        for q in payload["questions"]:
            pts: list[dict[str, Any]] = [
                {"text": f["text"] + "。", "facts": [f["id"]]} for f in theirs if f["q"] == q["id"]
            ]
            if pts and ours and q["id"] == "Q1":
                pts[0]["ours"] = [ours[0]["id"]]
            answers.append({"q": q["id"], "points": pts})
        cand = next((c for c in payload["candidates"] if c["slot"] == "H4"), None)
        q1 = [f["id"] for f in theirs if f["q"] == "Q1"]
        rec = {
            "title": "折叠时保留最近几条",
            "priority": "高",
            "text": "折叠时留住最近几条原文、只压更早的部分，这一点可以直接借鉴。",
            "facts": q1[:2] + (["f000000000000"] if self.cite_unknown else []),
            **({"candidate": cand["id"]} if cand else {}),
        }
        doc = {
            "answers": answers,
            "recommendations": [rec] if q1 else [],
            "not_recommended": [{"text": "按文本长度估算词元的做法太粗，不建议照搬。", "facts": q1[1:2]}],
            "unsure": [{"text": "摘要失败时有没有退路，读到的部分里没有看到。"}],
        }
        return Reply(doc, 30_000, 3_000)


def _section(listing: str, title: str) -> list[str]:
    body = listing.split(f"## {title}\n", 1)[1] if f"## {title}\n" in listing else ""
    return [x for x in body.split("\n\n## ")[0].splitlines() if x.strip()]


def _has(files: list[str], word: str) -> list[str]:
    return [f for f in files if word in f]
