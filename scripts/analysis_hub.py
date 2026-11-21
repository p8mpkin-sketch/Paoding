"""方案分析（吞噬引擎，焚决 09；界面 docs/design/engine-ui）一期的读端点与第 1 次确认的提交。

引擎最小版本还没接进内核（没有分析实例），所以引擎的工作区就是唯一的事实来源。工作区根目录下一个运行一个目录：
`<root>/<run>/run.json`、`engine.json`、`intake.json`、`obs.jsonl`、`artifacts/<sha256>.json`（引擎 run.py 写）。
本模块只读这些文件，从不改；人提交的确认另存到自己的目录里，等引擎续做时取走。

    GET  /v1/analyses                         分析列表
    GET  /v1/analyses/{run}                   详情：run.json、立项单、待你确认的交付（产物、人读报告、需要你做的）、
                                              观察库、产物清单、已提交还没被引擎取走的确认
    GET  /v1/analyses/{run}/artifacts/{sha}   一份产物（只认 run.json 里登记过的 sha256）
    POST /v1/analyses/{run}/decision          人的令牌：{block, deliver_seq, budget_add_usd_milli?}，一期只收第 1 次确认
    GET  /v1/fenjue/bang                      候选方案（异火榜），只读

决定块的格式归引擎（paoding_fenjue.engine.decision）：这里用同一个解析器与 Schema 校验，校验过了才收，
收下的原文与引擎续做时读到的逐字节相同。引擎接进内核以后，提交改走分析实例上既有的 follow_up，读端点不变。
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from paoding_fenjue.engine import decision as dblock
from paoding_fenjue.engine import schema
from paoding_fenjue.engine.budget import STAGE_SHARE
from paoding_fenjue.engine.run import (
    ARM_ZH,
    HELD_ZH,
    KIND_ZH,
    OUTCOME_ZH,
    REL_ZH,
    RES_ZH,
    local_artifact_id,
    report_dry_run,
    report_g1,
    report_g2,
)
from paoding_graph.contract import BadBody, GraphHttp, MountError

RUN_RE = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}"
SHA_RE = r"[0-9a-f]{64}"
MAX_BLOCK = 8_000  # 决定块原文的上限（字节）；第 1 次确认的块远小于它
MAX_BUDGET_ADD = 100_000  # 一次追加预算的上限（千分之一美元，即 100 美元）

# 产物分三类（界面“文件”栏）：你给的材料、执行输出（确定性的勘察与快照）、分析写的（模型参与，只能当说明）
_MATERIAL = ("snapshot:",)
_EXEC = ("survey:", "read:", "candidates.needs")

Forward = Callable[[str, str, int], None]

# 引擎枚举的人读说法（引擎 run.py 写报告用的同一张表）：界面照这张表显示，不另抄一份
WORDS = {
    "reading_kind": KIND_ZH,
    "arm": ARM_ZH,
    "resolution": RES_ZH,
    "relation": REL_ZH,
    "held": HELD_ZH,
    "outcome": OUTCOME_ZH,
}


def _kind(name: str) -> str:
    if name.startswith(_MATERIAL):
        return "material"
    if name.startswith(_EXEC) or name.endswith(".v"):
        return "exec"
    return "analysis"


def _read_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise MountError(500, "broken_workspace", f"{p.name} 读不了：{e}") from e


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _handoff_view(h: dict[str, Any] | None) -> dict[str, Any] | None:
    """交接包的摘要：交了哪几个、暂缓哪几个、候选方案怎么变、校验过没过。整份在“文件”里。"""
    if h is None:
        return None
    return {
        "decided_by": h.get("decided_by"),
        "date": h.get("date"),
        "items": [
            {
                "candidate": it["candidate"],
                "title": it["seed"]["title"],
                "module": it["placement"]["fire"]["id"],
                "slot": it["placement"]["fire"]["slot"],
                "plain_summary": it["placement"].get("plain_summary", ""),
            }
            for it in h.get("items", [])
        ],
        "held": h.get("held", []),
        "bang_updates": [
            {"op": u["op"], "id": u.get("id") or u.get("entry", {}).get("id"), "status": u.get("status")}
            for u in h.get("bang_updates", [])
        ],
        "profile_proposals": len(h.get("profile_proposals", [])),
        "library_import": bool(h.get("library_import")),
        "validator": h.get("validator", []),
    }


def _dry_view(r: dict[str, Any] | None, v: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """预评估报告里界面用的那几栏（每个做法一行）；整份在“文件”里。"""
    if r is None:
        return None
    return {
        "auto_picked": r.get("auto_picked", []),
        "plain_summary": r.get("plain_summary", ""),
        "estimate": r.get("estimate"),
        "items": [
            {
                "candidate": it["candidate"],
                "statement": it["essence_draft"]["statement"],
                "slot": it["slot"],
                "replaces": it.get("replaces"),
                "kernel_forecast": it.get("kernel_forecast", []),
                "difficulty": it.get("difficulty"),
                "likely_outcome": it["likely_outcome"],
                "why": it.get("why", ""),
                "conflicts": it.get("conflicts", []),
            }
            for it in r.get("items", [])
        ],
        "validators": v or [],
    }


def default_bang(root: Path) -> Path:
    """仓库里的候选方案：正式的 yihuobang.json 还没写入时，用引擎样例里的首批条目。"""
    live = root / "docs" / "design" / "fenjue" / "yihuobang.json"
    return (
        live if live.exists() else root / "docs" / "design" / "fenjue" / "engine" / "examples" / "yihuobang.seed.json"
    )


class AnalysisHub:
    def __init__(self, workspaces: Path, decisions: Path, bang: Path, forward: Forward | None = None):
        """workspaces：引擎工作区的根目录；decisions：人提交的确认存在这里（一个运行一个 jsonl）；
        forward：有分析实例时把校验过的决定块交给引擎（run, block, follow_up_seq），没有就只存。"""
        self.root = workspaces
        self.decisions = decisions
        self.bang_path = bang
        self.forward = forward
        self._lock = threading.Lock()

    def mount(self, http: GraphHttp) -> None:
        http.mount("GET", r"/v1/analyses", self._list)
        http.mount("GET", rf"/v1/analyses/(?P<run>{RUN_RE})", self._detail)
        http.mount("GET", rf"/v1/analyses/(?P<run>{RUN_RE})/artifacts/(?P<sha>{SHA_RE})", self._artifact)
        http.mount("POST", rf"/v1/analyses/(?P<run>{RUN_RE})/decision", self._decide, human=True)
        http.mount("GET", r"/v1/fenjue/bang", self._bang)

    # ------------------------------------------------------------ 读

    def _ws(self, run: str) -> Path:
        ws = self.root / run
        if not (ws / "run.json").is_file():
            raise MountError(404, "unknown_ref", f"没有这次分析：{run}")
        return ws

    def _art(self, ws: Path, state: dict[str, Any], name: str) -> Any:
        sha = state.get("artifacts", {}).get(name)
        return None if sha is None else _read_json(ws / "artifacts" / f"{sha}.json")

    def _submitted(self, run: str) -> list[dict[str, Any]]:
        p = self.decisions / f"{run}.jsonl"
        if not p.exists():
            return []
        return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def _pending(self, run: str, state: dict[str, Any]) -> list[dict[str, Any]]:
        """已提交、引擎还没取走的确认：同一闸点同一次交付、run.json 里那一格还没有 decision。"""
        open_gates = {(g["gate"], g["deliver_seq"]) for g in state.get("gates", []) if "decision" not in g}
        return [s for s in self._submitted(run) if (s["gate"], s["deliver_seq"]) in open_gates]

    def _summary(self, run: str, ws: Path) -> dict[str, Any]:
        state = _read_json(ws / "run.json")
        intake = _read_json(ws / "intake.json") or {}
        eng = _read_json(ws / "engine.json") or {}
        gate = next((g for g in reversed(state.get("gates", [])) if "decision" not in g), None)
        waiting = gate is not None and state.get("step") == gate["gate"]
        pending = self._pending(run, state) if waiting else []
        cands = self._art(ws, state, "candidates.json")
        snaps = (cands or {}).get("basis", {}).get("snapshots") or []
        if not snaps:
            snap = self._art(ws, state, "snapshot:s1")
            snaps = [snap] if snap else []
        return {
            "run": run,
            "mode": state.get("mode", intake.get("mode", "formal")),
            "step": state.get("step"),
            "statement": intake.get("statement", ""),
            "sources": intake.get("sources", []),
            "requested_by": intake.get("requested_by", ""),
            "date": intake.get("date", ""),
            "updated_at": _iso((ws / "run.json").stat().st_mtime),
            "waiting": (
                {"gate": gate["gate"], "deliver_seq": gate["deliver_seq"], "submitted": bool(pending)}
                if waiting and gate
                else None
            ),
            "spent_usd_milli": int(state.get("spent", {}).get("usd_milli", 0)),
            "budget_usd_milli": int(eng.get("budget_usd_milli", 0)),
            "candidates": len((cands or {}).get("candidates", [])),
            "license": snaps[0].get("license") if snaps else None,
        }

    def _list(self, q: dict[str, str], body: object) -> dict[str, Any]:
        items = []
        if self.root.is_dir():
            for ws in sorted(self.root.iterdir()):
                if ws.is_dir() and re.fullmatch(RUN_RE, ws.name) and (ws / "run.json").is_file():
                    items.append(self._summary(ws.name, ws))
        items.sort(key=lambda x: x["updated_at"], reverse=True)
        return {"items": items, "stage_share": STAGE_SHARE}

    def _detail(self, q: dict[str, str], body: object) -> dict[str, Any]:
        run = q["run"]
        ws = self._ws(run)
        state = _read_json(ws / "run.json")
        eng = _read_json(ws / "engine.json") or {}
        out = self._summary(run, ws)
        obs = []
        p = ws / "obs.jsonl"
        if p.exists():
            obs = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        registered = _read_json(ws / "registered.json") or {}
        arts = [
            {
                "name": n,
                "sha256": sha,
                # E-U5 对照表里的那个 id：交付时登记过的用内核给的，没登记过的（或没接内核）用引擎的本地占位
                "artifact_id": registered.get(sha) or local_artifact_id(n, sha),
                "kind": _kind(n),
                "bytes": _size(ws / "artifacts" / f"{sha}.json"),
            }
            for n, sha in state.get("artifacts", {}).items()
        ]
        cands = self._art(ws, state, "candidates.json")
        dry = self._art(ws, state, "dry_run.json")

        def seq(gate: str) -> int | None:
            g = next((g for g in reversed(state.get("gates", [])) if g["gate"] == gate), None)
            return g["deliver_seq"] if g else None

        # 人读报告只列真正交付过的：预评估一口气走完，中间没有交付，只有最后那一份
        reports: list[dict[str, Any]] = []
        if cands and dry is None:
            reports.append({"kind": "G1", "gate": "G1", "deliver_seq": seq("G1"), "text": report_g1(cands)})
        essences = []
        for cid in eng.get("picked", []):
            ess = self._art(ws, state, f"essence:{cid}")
            if ess is not None:
                essences.append({**ess, "validators": self._art(ws, state, f"essence:{cid}.v") or []})
        if essences and dry is None:
            reports.append({"kind": "G2", "gate": "G2", "deliver_seq": seq("G2"), "text": report_g2(essences)})
        placements = []
        for cid in eng.get("confirmed", eng.get("picked", [])):
            pl = self._art(ws, state, f"placement:{cid}")
            if pl is not None:
                placements.append({**pl, "problems": eng.get("placement_problems", {}).get(cid, [])})
        for name, kind, gate in (("report:G3", "G3", "G3"), ("report:S6", "handoff", None)):
            rep = self._art(ws, state, name)
            if rep is not None:
                reports.append(
                    {"kind": kind, "gate": gate, "deliver_seq": seq(gate) if gate else None, "text": rep["markdown"]}
                )
        if dry is not None:
            reports.append({"kind": "dry_run", "gate": None, "deliver_seq": None, "text": report_dry_run(dry)})
        handoff = self._art(ws, state, "handoff.json")
        return {
            **out,
            "intake": _read_json(ws / "intake.json"),
            "engine": state.get("engine", {}),
            "units": state.get("units", []),
            "spent": state.get("spent", {}),
            "gates": state.get("gates", []),
            "relays": state.get("relays", 0),
            "picked": eng.get("picked", []),
            "stage_share": STAGE_SHARE,
            "needs": self._needs(state, ws, essences, placements, handoff, dry),
            "candidates_doc": cands,
            "essences": essences,
            "placements": placements,
            "order": self._art(ws, state, "order.json"),
            "g3": eng.get("g3"),
            "handoff": _handoff_view(handoff),
            "dry_run": _dry_view(dry, self._art(ws, state, "dry_run.v")),
            "words": WORDS,
            "reports": reports,
            "observations": obs,
            "artifacts": arts,
            "submitted": self._pending(run, state),
            "history": self._submitted(run),
        }

    def _needs(
        self,
        state: dict[str, Any],
        ws: Path,
        essences: list[dict[str, Any]],
        placements: list[dict[str, Any]],
        handoff: dict[str, Any] | None,
        dry: dict[str, Any] | None,
    ) -> list[str]:
        """这一次交付要你做的（引擎交付里的 needs，从产物现算，与 Engine._deliver_g1/_g2/_g3、交接、预评估同口径）。"""
        if state.get("step") == "G1":
            return list(self._art(ws, state, "candidates.needs") or [])
        if state.get("step") == "G2":
            out = []
            for e in essences:
                bad = [
                    c["id"]
                    for c in [*e.get("checks", []), *e.get("validators", [])]
                    if not c["ok"] and not c.get("advisory") and not c.get("override")
                ]
                if bad:
                    out.append(f"{e['candidate']} 未过：{', '.join(bad)}")
            return out
        if state.get("step") == "G3":
            out = []
            for p in placements:
                bad = [c["id"] for c in p.get("checks", []) if not c["ok"]] + list(p.get("problems", []))
                if bad:
                    out.append(f"{p['candidate']} 未过：{', '.join(bad)[:300]}")
            return out
        if state.get("step") == "done" and dry is not None:
            bad = [c["id"] for c in self._art(ws, state, "dry_run.v") or [] if not c["ok"]]
            out = [f"校验未过（只标不拦）：{', '.join(bad)}"] if bad else []
            return [
                *out,
                "这是预评估：单稿、不盲审、不写实现步骤，不能直接交实现线；要正式走一遍就复用这次的快照与观察重开一题",
            ]
        if state.get("step") == "done" and handoff is not None:
            out = []
            bad = [c["id"] for c in handoff.get("validator", []) if not c["ok"]]
            if bad:
                out.append("交接包校验未过：" + "；".join(bad))
            if handoff.get("items"):
                out.append("交实现线的做法：在主仓库的工作分支跑 uv run python scripts/lianhua.py import <交接包>")
            if handoff.get("library_import"):
                out.append("报告存进资料库：由界面以你的身份导入（只作参考，不作依据）")
            return out
        return []

    def _artifact(self, q: dict[str, str], body: object) -> dict[str, Any]:
        ws = self._ws(q["run"])
        state = _read_json(ws / "run.json")
        names = [n for n, sha in state.get("artifacts", {}).items() if sha == q["sha"]]
        if not names:
            raise MountError(404, "unknown_ref", "这次分析没有这份产物")
        return {
            "name": names[0],
            "sha256": q["sha"],
            "kind": _kind(names[0]),
            "content": self._art(ws, state, names[0]),
        }

    def _bang(self, q: dict[str, str], body: object) -> dict[str, Any]:
        doc = _read_json(self.bang_path)
        if doc is None:
            return {"v": 1, "entries": [], "source": None}
        return {**doc, "source": self.bang_path.name}

    # ------------------------------------------------------------ 第 1 次确认

    def _decide(self, q: dict[str, str], body: dict[str, Any] | None) -> dict[str, Any]:
        """校验过才收：块解析得了、闸点对、没有读不懂的行、Schema 合、编号都在候选里、所见的交付没变、没重复提交。"""
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("block"), str)
            or not isinstance(body.get("deliver_seq"), int)
        ):
            raise BadBody("请求体是 {block: 决定块原文, deliver_seq: 你看的那次交付, budget_add_usd_milli?}")
        block = body["block"]
        add = body.get("budget_add_usd_milli", 0)
        if not isinstance(add, int) or isinstance(add, bool) or not 0 <= add <= MAX_BUDGET_ADD:
            raise BadBody(f"budget_add_usd_milli 取 0 到 {MAX_BUDGET_ADD} 的整数")
        if len(block.encode("utf-8")) > MAX_BLOCK:
            raise BadBody("决定块太长")
        run = q["run"]
        with self._lock:
            ws = self._ws(run)
            state = _read_json(ws / "run.json")
            step = state.get("step")
            gate = next((g for g in reversed(state.get("gates", [])) if "decision" not in g), None)
            if gate is None or step != gate["gate"]:
                raise MountError(409, "not_at_gate", f"这次分析现在不在等你确认（{step}）")
            if gate["gate"] != "G1":
                raise MountError(409, "not_yet", "第 2、3 次确认的提交在界面后续几期，这一期只读")
            if body["deliver_seq"] != gate["deliver_seq"]:
                raise MountError(409, "stale_view", "你看的不是最新一次交付，请刷新")
            if self._pending(run, state):
                raise MountError(409, "already_submitted", "这一次确认已经提交过，等引擎续做")
            dec = self._check(block, ws, state)
            row = {
                "run": run,
                "gate": gate["gate"],
                "deliver_seq": gate["deliver_seq"],
                "block": block,
                "block_sha256": hashlib.sha256(block.encode("utf-8")).hexdigest(),
                "decision": dec,
                "budget_add_usd_milli": add,
                "by": "human",
                "at": _iso(time.time()),
                "forwarded": self.forward is not None,
            }
            self.decisions.mkdir(parents=True, exist_ok=True)
            with (self.decisions / f"{run}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        if self.forward is not None:
            self.forward(run, block, add)
        return {"ok": True, "submitted": row}

    def _check(self, block: str, ws: Path, state: dict[str, Any]) -> dict[str, Any]:
        try:
            dec = dblock.parse(block)
        except dblock.NoBlock as e:
            raise MountError(400, "no_block", str(e)) from e
        if dec["gate"] != "G1":
            raise MountError(400, "wrong_gate", f"决定块写的是{dec['gate']}，现在等的是第 1 次确认")
        if dec.get("unparsed"):
            raise MountError(400, "unparsed", "这几行没读懂：" + "；".join(dec["unparsed"]))
        errs = schema.errors(dec, "decision")
        if errs:
            raise MountError(400, "bad_decision", "；".join(errs[:3]))
        doc = self._art(ws, state, "candidates.json") or {}
        ids = {c["id"] for c in doc.get("candidates", [])}
        picked = dec.get("pick", [])
        excluded = [r["candidate"] for r in dec.get("exclude", [])]
        unknown = sorted({*picked, *excluded} - ids)
        if unknown:
            raise MountError(400, "unknown_candidate", f"没有候选 {', '.join(unknown)}")
        if not picked:
            raise MountError(400, "nothing_picked", "请至少选一个候选")
        if set(picked) & set(excluded):
            raise MountError(400, "pick_and_exclude", "同一个候选不能既选又排除")
        for e in dec.get("edit", []):
            cid, _, fld = e["pointer"].partition(".")
            if cid not in ids or fld != "title" or not str(e["value"]).strip():
                raise MountError(400, "bad_edit", f"第 1 次确认只能改候选的标题：{e['pointer']}")
        if dec.get("redo"):
            raise MountError(400, "not_yet", "重做发现在界面二期")
        return dec


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0
