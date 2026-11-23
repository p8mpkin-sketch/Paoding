"""吞噬引擎的工作流（docs/design/fenjue/09-engine.md §2–§4、§6）：
S0 立项 → S3 识火 → G1 → S4 萃意 → G2 → S5 入位与火序 → G3 → S6 交接包；试算模式一口气走完、出试算报告。

还没有接进内核：交付（`Delivery`）就是将来 `deliver` 的内容（人读报告 + 结构化产物的 sha256 + needs），
闸点的决定块就是将来 cz `follow_up` 的正文。每次交付的报告末尾附“产物 → Artifact id → sha256”对照表（界面 E-U5）；
没接内核时 Artifact id 是按 sha256 给的本地占位（`local_artifact_id`），接上之后换成 `register_artifact` 返回的 id。

状态外置：工作区里的 `run.json`（run.schema.json）是检查点，`obs.jsonl` 是只追加的观察库，`artifacts/<sha256>.json`
是内容寻址的产物。任何时候中断，新的 `Engine` 读 `run.json` 从第一个未完成的单元接着做；已完成的单元不重做，
已登记的观察不重读（09 §6）。
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..shapes import digest
from . import budget, checks, cuiyi, data, decision, handoff, ruwei, schema, shihuo, survey, text
from .dan import BudgetExhausted, Dan, new_nonce

ENGINE_FIRE = "h1.tunshi@1"
DRY_RUN_PICK = 3  # 试算按 P 自动取前 3（〔占位〕，09 §3）
READ_TIERS = ("light", "mid", "heavy")


def local_artifact_id(name: str, sha: str) -> str:
    """没接内核时的 Artifact id 占位：按 sha256 取，同一份产物同一个 id。"""
    return f"local:{sha[:16]}"


def artifact_table(
    arts: Mapping[str, str],
    artifact_id: Callable[[str, str], str] = local_artifact_id,
    final_of: Callable[[str, str], tuple[str, str | None]] | None = None,
) -> str:
    """E-U5：交付末尾的固定格式对照表。界面按这张表取结构化产物，不必等工作区的 run.json。"""
    if not arts:
        return ""
    rows = ["", "", "## 产物对照", "", "| 产物 | Artifact id | sha256 |", "| --- | --- | --- |"]
    notes: list[str] = []
    for name, sha in arts.items():
        aid = artifact_id(name, sha)  # 登记时可能重产：先取编号，再按“编号实际登记的内容”取 sha256
        final, note = final_of(name, sha) if final_of else (sha, None)
        rows.append(f"| {name} | {aid} | {final} |")
        if note:
            notes.append(note)
    if notes:
        rows += ["", *notes]
    return "\n".join(rows)


class EngineError(RuntimeError):
    """这一步做不了（顺序不对、决定块不合、录音缺失之外的错误）。"""


@dataclass
class Config:
    run: str
    source_label: str
    date: str
    bang: list[dict[str, Any]] = field(default_factory=list)  # 异火榜（只读）
    pains: list[dict[str, Any]] = field(default_factory=list)  # 记录在案的痛点 {dim, anchor}（π = 3）
    canaries: list[str] = field(default_factory=list)  # 验收模式的金丝雀词元（V12）
    prior: budget.Prior = field(default_factory=budget.Placeholder)
    budget_usd_milli: int | None = None  # 不给就按预算先验算
    nonce: Callable[[], str] = new_nonce
    by: str = "cz"
    locks: list[dict[str, Any]] = field(default_factory=list)  # 在途炼档占着的火位 {slot, dossier}（火位锁）
    artifact_id: Callable[[str, str], str] = local_artifact_id
    # 登记时产物被重产过：(名, 原 sha256) → (实际登记的 sha256, 说明行)；不重产就是 (原 sha256, None)
    artifact_final: Callable[[str, str], tuple[str, str | None]] | None = None


@dataclass
class Delivery:
    """一次交付：`answer` 是人读报告，`artifacts` 是结构化产物的 sha256，`needs` 是给 cz 的话。"""

    gate: str | None
    outcome: str
    answer: str
    artifacts: dict[str, str]
    needs: list[str]
    passed: bool = True
    stop: str | None = None  # 没走到闸点就停下的原因：budget:task | budget:problem | budget:global | stage | soft_line


class Engine:
    def __init__(self, workspace: Path, dan: Dan, materials: Mapping[str, Path], config: Config) -> None:
        self.ws = workspace
        self.dan = dan
        self.materials = dict(materials)
        self.cfg = config
        self.ws.mkdir(parents=True, exist_ok=True)
        (self.ws / "artifacts").mkdir(exist_ok=True)
        self.state: dict[str, Any] = self._load("run.json") or {}
        self.x: dict[str, Any] = self._load("engine.json") or {}  # 引擎自己的簿记（run.json 的 Schema 之外的）
        self._snaps: dict[str, survey.Snapshot] = {}
        self._surveys: dict[str, survey.Survey] = {}

    # ------------------------------------------------------------ 工作区

    def _load(self, name: str) -> Any:
        p = self.ws / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def _save_state(self) -> None:
        errs = schema.errors(self.state, "run")
        if errs:
            raise EngineError(f"run.json 不合 Schema：{errs[:3]}")
        # 先写旁边的临时文件再改名：会话随时可能被终止（硬顶、停机），检查点不能停在写了一半的样子
        for name, doc in (("engine.json", self.x), ("run.json", self.state)):
            tmp = self.ws / f".{name}.tmp"
            tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            os.replace(tmp, self.ws / name)

    def put(self, name: str, obj: Any) -> str:
        sha = digest(obj)
        p = self.ws / "artifacts" / f"{sha}.json"
        if not p.exists():
            tmp = p.with_name(f".{sha}.tmp")
            tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            os.replace(tmp, p)
        self.state["artifacts"][name] = sha
        return sha

    def get(self, name: str) -> Any:
        sha = self.state["artifacts"].get(name)
        if sha is None:
            return None
        return json.loads((self.ws / "artifacts" / f"{sha}.json").read_text(encoding="utf-8"))

    def observations(self) -> dict[str, dict[str, Any]]:
        p = self.ws / "obs.jsonl"
        out: dict[str, dict[str, Any]] = {}
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    o = json.loads(line)
                    out.setdefault(o["id"], o)
        return out

    def _append_obs(self, obs: Sequence[Mapping[str, Any]]) -> None:
        have = self.observations()
        with (self.ws / "obs.jsonl").open("a", encoding="utf-8") as f:
            for o in obs:
                if o["id"] not in have:
                    f.write(json.dumps(o, ensure_ascii=False, sort_keys=True) + "\n")
                    have[o["id"]] = dict(o)

    def _unit(self, uid: str) -> dict[str, Any] | None:
        return next((u for u in self.state["units"] if u["id"] == uid), None)

    def _done(self, uid: str) -> bool:
        u = self._unit(uid)
        return bool(u and u["state"] == "done")

    def _mark(self, uid: str, step: str, st: str, **kw: Any) -> None:
        u = self._unit(uid)
        if u is None:
            u = {"id": uid, "step": step, "state": st}
            self.state["units"].append(u)
        u["state"] = st
        u.update(kw)
        self._save_state()

    def _spend(self, step: str, tier: str, tin: int, tout: int) -> None:
        """记一次调用的花费（每步的预算份额按它扣）。单次调用常常不到千分之一美元（片段阅读用轻档）：
        逐次取整会把它们全记成 0，这一步的份额就永远扣不动。所以不足一个单位的零头按步累着，凑满了再进位。"""
        sp = self.state["spent"]
        pin, pout = self.cfg.prior.price()[tier]
        carry: dict[str, int] = self.x.setdefault("spend_carry", {})
        num = tin * pin + tout * pout + int(carry.get(step, 0))
        cost, carry[step] = num // 1_000_000, num % 1_000_000
        sp["usd_milli"] += cost
        sp.setdefault("by_step", {})[step] = sp.get("by_step", {}).get(step, 0) + cost
        tk = sp.setdefault("tokens", {})
        row = tk.setdefault(tier, [0, 0])
        row[0] += tin
        row[1] += tout

    def _stage_left(self, step: str) -> int:
        cap = budget.stage_cap(int(self.x["budget_usd_milli"]), step)
        return cap - int(self.state["spent"].get("by_step", {}).get(step, 0))

    # ------------------------------------------------------------ S0 立项

    def _out(self, d: Delivery) -> Delivery:
        d.answer = d.answer + artifact_table(d.artifacts, self.cfg.artifact_id, self.cfg.artifact_final)
        if self.cfg.artifact_final is not None:  # 交付里的产物表也改认实际登记的那份
            d.artifacts = {n: self.cfg.artifact_final(n, s)[0] for n, s in d.artifacts.items()}
        return d

    def start(self, intake: dict[str, Any], *, reuse: Path | None = None) -> Delivery:
        """S0–S3：立项、快照、勘察、识火，交付闸点 1（试算模式一口气走到试算报告）。已有 run.json 就接着做。

        reuse：试算转正式（09 §3）——复用那次试算的快照、勘察与观察（按快照身份核对，不重读），
        识火按存下的提议重做差距比对（公式，不花 token），从闸点 1 开始。"""
        return self._guard(lambda: self._start(intake, reuse))

    def _guard(self, go: Callable[[], Delivery]) -> Delivery:
        """跑一段流程；模型调用被预算挡下（端点代理到顶即拒）就停在当前单元，带检查点部分交付。"""
        try:
            return self._out(go())
        except BudgetExhausted as e:
            return self._out(self._stop(f"budget:{e.scope}"))

    def _material(self, s: Mapping[str, Any]) -> Path | None:
        """来源的定版目录：上传与资料库按 Artifact id 取，地址类来源（抓取后）按 `source:<编号>` 取。"""
        return self.materials.get(s.get("artifact") or f"source:{s['no']}")

    def _start(self, intake: dict[str, Any], reuse: Path | None) -> Delivery:
        if not self.state:
            errs = schema.errors(intake, "intake")
            if errs:
                raise EngineError(f"立项单不合 Schema：{errs[:3]}")
            if intake["mode"] not in ("formal", "dry_run"):
                raise EngineError(f"这一期做正式与试算两种模式，不做 {intake['mode']}")
            if reuse is not None and intake["mode"] != "formal":
                raise EngineError("只有正式模式能复用试算")
            refused = list(intake.get("refused", []))
            keep = []
            for s in intake["sources"]:
                mat = self._material(s)
                why = survey.refusal(s, str(mat) if mat else None)
                if why:
                    refused.append({"no": s["no"], "why": why})
                else:
                    keep.append(s)
            intake = {**intake, "refused": refused} if refused else intake
            (self.ws / "intake.json").write_text(
                json.dumps(intake, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
            )
            self.state = {
                "v": 1,
                "run": self.cfg.run,
                "mode": intake["mode"],
                "engine": {"fire": ENGINE_FIRE, "gongfa_digest": data.gongfa_basis()["gongfa_digest"]},
                "step": "S0",
                "units": [],
                "spent": {"usd_milli": 0, "by_step": {}, "tokens": {}},
                "gates": [],
                "artifacts": {},
                "relays": 0,
            }
            if not keep:
                self.state["step"] = "failed"
                self._save_state()
                why = "；".join(f"来源 {r['no']}：{r['why']}" for r in refused)
                return Delivery(None, "partial", f"立项没有成：{why}。没有发出任何请求。", {}, [why], passed=False)
            self.x["sources"] = [s["no"] for s in keep]
            if reuse is not None:
                self._reuse(reuse)
            self._save_state()
        return self._resume()

    def _reuse(self, prev: Path) -> None:
        old = json.loads((prev / "run.json").read_text(encoding="utf-8"))
        if old.get("mode") != "dry_run":
            raise EngineError("只能复用试算的运行")
        keep = ("snapshot:", "survey:", "read:")
        for u in old["units"]:
            if u["id"].startswith(keep) and u["state"] == "done":
                self.state["units"].append(dict(u))
        for name, sha in old["artifacts"].items():
            if name.startswith(keep) or name == "candidates.proposal":
                src = prev / "artifacts" / f"{sha}.json"
                (self.ws / "artifacts" / f"{sha}.json").write_bytes(src.read_bytes())
                self.state["artifacts"][name] = sha
        if (prev / "obs.jsonl").exists():
            (self.ws / "obs.jsonl").write_bytes((prev / "obs.jsonl").read_bytes())
        self.x["reused_from"] = old["run"]

    @property
    def intake(self) -> dict[str, Any]:
        doc: dict[str, Any] = self._load("intake.json")
        return doc

    def _sources(self) -> list[dict[str, Any]]:
        keep = set(self.x.get("sources", []))
        return [s for s in self.intake["sources"] if s["no"] in keep]

    # ------------------------------------------------------------ S1–S2 快照与勘察

    def _snapshot(self) -> None:
        early = self.state["step"] in ("S0", "S1", "S2")
        if early:
            self.state["step"] = "S1"
        for i, s in enumerate(self._sources(), 1):
            sid = f"s{i}"
            mat = self._material(s)
            if mat is None:
                raise EngineError(f"来源 {s['no']} 的材料没有定版（地址类来源要先经扩权卡抓取）")
            snap = survey.load_snapshot(sid, s["form"], mat)
            self._snaps[sid] = snap
            if self._done(f"snapshot:{sid}") and self.get(f"snapshot:{sid}")["identity"] != survey.identity(snap):
                raise EngineError(f"快照 {sid} 与上次不同：材料变了，不能复用（重新立项）")
            if not self._done(f"snapshot:{sid}"):
                body = {
                    "id": sid,
                    "form": s["form"],
                    "identity": survey.identity(snap),
                    "artifact": s.get("artifact", ""),
                    "size_tier": survey.size_tier(sum(f["lines"] for f in snap.files)),
                    "license": survey.detect_license(snap),
                }
                if not body["artifact"]:
                    del body["artifact"]
                sha = self.put(f"snapshot:{sid}", body)
                self._mark(f"snapshot:{sid}", "S1", "done", output=sha)
        if "budget_usd_milli" not in self.x:
            tiers = [self.get(f"snapshot:{sid}")["size_tier"] for sid in self._snaps]
            tier = max(tiers, key=lambda t: ["S", "M", "L", "XL"].index(t))
            n = int(self.intake.get("max_candidates", 3))
            dry = self.state["mode"] == "dry_run"
            self.x["budget_usd_milli"] = self.cfg.budget_usd_milli or budget.run_budget(
                self.cfg.prior, tier, min(n, 3), dry_run=dry
            )
        if early:
            self.state["step"] = "S2"
        for sid, snap in self._snaps.items():
            sv = survey.probe(snap)
            sv.snapshot = self.get(f"snapshot:{sid}")
            self._surveys[sid] = sv
            if not self._done(f"survey:{sid}"):
                sha = self.put(f"survey:{sid}", sv.body())
                self._mark(f"survey:{sid}", "S2", "done", output=sha)

    def context(self) -> checks.Context:
        # 抄写比对（K4、V6）的语料：外部原文。描述形态是 cz 自己的话，复述它不算抄外部代码，不进语料
        corpus = [
            text.tokens(snap.texts[k])
            for snap in self._snaps.values()
            if snap.form != "description"
            for k in sorted(snap.texts)
        ]
        names = sorted({n for sv in self._surveys.values() for n in sv.names})
        snaps = [self.get(f"snapshot:{sid}") for sid in self._snaps]
        return checks.Context(
            names=names,
            corpus=corpus,
            observations=self.observations(),
            license=snaps[0]["license"],
            canaries=self.cfg.canaries,
            out_of_scope_requests=int(self.x.get("out_of_scope_requests", 0)),
        )

    def request_access(self, target: str) -> bool:
        """D4：扩权申请先比对立项登记的来源；不在其中的不发出，并记一次越界（V12 的读数）。"""
        if survey.scope_allowed(self.intake, target):
            return True
        self.x["out_of_scope_requests"] = int(self.x.get("out_of_scope_requests", 0)) + 1
        self._save_state()
        return False

    # ------------------------------------------------------------ S3 识火

    def _shihuo(self) -> Delivery:
        self.state["step"] = "S3"
        snaps = [(self._snaps[sid], self._surveys[sid]) for sid in self._snaps]
        tiers = [self.get(f"snapshot:{sid}")["size_tier"] for sid in self._snaps]
        read_budget = max(survey.READ_BUDGET[t] for t in tiers)
        if self.state["mode"] == "dry_run":
            read_budget //= 2  # 试算：读预算减半（09 §3）
        focus = list(self.intake.get("focus", []))
        coverage: list[dict[str, Any]] = []
        used = 0
        for sp in shihuo.plan(snaps):
            uid = f"read:{sp.slot}"
            if self._done(uid):
                row = self.get(uid)
                coverage.append(row["coverage"])
                used += int(row["reads"])
                continue
            if self._stage_left("S3") <= 0:
                return self._budget_cut("S3", uid)
            self._mark(uid, "S3", "doing")
            res = shihuo.read_slot(
                self.dan,
                sp,
                read_budget - used,
                read_budget,
                focused_out=bool(focus) and sp.slot not in focus,
                nonce=self.cfg.nonce,
            )
            self._append_obs(res.observations)
            self._spend("S3", "light", res.tokens_in, res.tokens_out)
            used += res.reads
            coverage.append(res.coverage)
            body = {
                "coverage": res.coverage,
                "reads": res.reads,
                "observations": sorted(o["id"] for o in res.observations),
            }
            sha = self.put(uid, body)
            self._mark(
                uid, "S3", "done", output=sha, summary=f"{sp.slot}：读 {res.reads} 段，{len(res.observations)} 条观察"
            )
        inp = shihuo.Inputs(
            observations=self.observations(),
            snapshots=[self.get(f"snapshot:{sid}") for sid in self._snaps],
            surveys=list(self._surveys.values()),
            coverage=coverage,
            bang=self.cfg.bang,
            pains=self.cfg.pains,
            source_label=self.cfg.source_label,
            date=self.cfg.date,
            run=self.cfg.run,
            mode=self.state["mode"],
            max_candidates=int(self.intake.get("max_candidates", 5)),
            focus=focus,
        )
        if not self._done("candidates"):
            ctx = self.context()
            errors: list[str] = []
            doc: dict[str, Any] = {}
            proposal: Mapping[str, Any] = {}
            passed = False
            stored = self.get("candidates.proposal") if self.x.get("reused_from") else None
            for attempt in range(1, shihuo.ATTEMPTS + 1):
                self._mark("candidates", "S3", "doing", attempts=attempt)
                if stored is not None:  # 试算转正式：按存下的提议重做差距比对，不调丹
                    proposal, stored = stored, None
                else:
                    r = self.dan.call("main", f"shihuo:patterns:{attempt}", shihuo.propose_payload(inp, errors))
                    self._spend("S3", "heavy", r.tokens_in, r.tokens_out)
                    proposal = r.output if isinstance(r.output, dict) else {}
                doc, errors = shihuo.build(inp, proposal)
                if doc:
                    vres = shihuo.validate(doc, ctx)
                    errors += [f"{c['id']}：{c.get('detail', '')}" for c in vres if not c["ok"]]
                if not errors:
                    passed = True
                    break
            if not doc:
                raise EngineError(f"主丹三次都没给出能建清单的提议：{errors[:3]}")
            self.put("candidates.json", doc)
            self.put("candidates.proposal", dict(proposal))
            self.put(
                "candidates.needs",
                shihuo.needs(doc, inp, proposal) + ([] if passed else [f"未过：{e}" for e in errors]),
            )
            self._mark("candidates", "S3", "done", output=self.state["artifacts"]["candidates.json"])
        if self.state["mode"] == "dry_run":
            return self._dry_run()
        return self._deliver_g1()

    def _budget_cut(self, step: str, uid: str) -> Delivery:
        self._mark(uid, step, "budget_cut")
        self.x["paused_from"] = step
        self.state["step"] = "paused_budget"
        self._save_state()
        name = {"S3": "识别候选", "S4": "提炼要点", "S5": "归位与实验设计"}.get(step, step)
        msg = f"“{name}”这一步的预算份额用完，停在单元 {uid}；追加预算后从这里接着做（已完成的单元不重做）"
        return Delivery(
            None,
            "partial",
            msg,
            self._shown(),
            [msg, "追加预算继续，或缩小范围"],
            passed=False,
            stop="stage",
        )

    def _shown(self) -> dict[str, str]:
        """中途停下时随交付带出的产物：已经成形、给人看得懂的那几样（快照、勘察等中间件不带）。"""
        keep = ("candidates.json", "essence:", "placement:", "order.json", "report:")
        arts: dict[str, str] = self.state.get("artifacts", {})
        return {k: v for k, v in arts.items() if k.startswith(keep) and not k.endswith(".v")}

    STOP_ZH = {
        "budget:task": "这个会话的预留预算用完",
        "budget:problem": "这道题的预算用完",
        "budget:global": "全局预算上限已到",
        "soft_line": "预算或时间接近上限",
    }

    def _stop(self, why: str) -> Delivery:
        """没走到下一个确认点就得停：把在做的单元标成待续、存检查点，交出此刻已有的产物。"""
        step = self.state.get("step")
        if not self.state or step in ("G1", "G2", "G3", "done", "failed", "paused_budget", "halted"):
            raise EngineError(f"现在没有在做的步骤可停（{step}）")
        doing = [u for u in self.state["units"] if u["state"] == "doing"]
        for u in doing:
            u["state"] = "budget_cut"
        self.x["paused_from"] = step if step in ("S3", "S4", "S5", "S6") else "S3"
        self.state["step"] = "paused_budget"
        self._save_state()
        at = f"单元 {doing[0]['id']}" if doing else f"步骤 {step}"
        said = self.STOP_ZH.get(why, why)
        msg = f"{said}，停在{at}；已完成的部分都留着，继续时从这里接着做，不重做"
        more = "追加预算后追问一句“继续”" if why != "budget:task" else "追问一句“继续”即可接着做"
        return Delivery(None, "partial", msg, self._shown(), [msg, more], passed=False, stop=why)

    def pause(self, why: str = "soft_line") -> Delivery:
        """收尾轮（预算或墙钟到软线）：不再调模型，停在当前单元并部分交付。"""
        return self._out(self._stop(why))

    def note(self, **kv: Any) -> None:
        """引擎簿记（engine.json）里记几样编排要用的东西（例如看到第几条追问），随即落盘。"""
        self.x.update(kv)
        self._save_state()

    def finish(self, d: Delivery) -> Delivery:
        """给一份交付补上产物对照表（E-U5）。"""
        return self._out(d)

    def adopt(self, name: str, sha: str) -> None:
        """产物登记被拒后重产了一份：以重产的为准（登记自愈，13 §6）。"""
        self.state["artifacts"][name] = sha
        self._save_state()

    def set_budget(self, usd_milli: int) -> None:
        """这次运行的预算以题的预算为准（接进内核后每个会话开头对一次；追问里追加的预算就这样进来）。"""
        if usd_milli > 0 and self.state and self.x.get("budget_usd_milli") != usd_milli:
            self.x["budget_usd_milli"] = usd_milli
            self._save_state()

    def _deliver_g1(self) -> Delivery:
        doc = self.get("candidates.json")
        needs = list(self.get("candidates.needs") or [])
        self.state["step"] = "G1"
        if not any(g["gate"] == "G1" and "decision" not in g for g in self.state["gates"]):
            self.state["gates"].append({"gate": "G1", "deliver_seq": self._next_seq()})
        self._save_state()
        arts = {"candidates.json": self.state["artifacts"]["candidates.json"]}
        return Delivery("G1", "partial", report_g1(doc), arts, needs, passed=checks.hard_ok(doc["checks"]))

    def _next_seq(self) -> int:
        self.x["seq"] = int(self.x.get("seq", 0)) + 1
        return int(self.x["seq"])

    # ------------------------------------------------------------ 闸点

    def follow_up(self, body: str, *, follow_up_seq: int | None = None) -> Delivery:
        """cz 的追问正文（带决定块）。G1 之后进萃意，G2 之后进入位与火序，G3 之后出交接包。"""
        return self._guard(lambda: self._follow_up(body, follow_up_seq))

    def _follow_up(self, body: str, follow_up_seq: int | None) -> Delivery:
        step = self.state.get("step")
        if step not in ("G1", "G2", "G3"):
            raise EngineError(f"现在不在闸点上（{step}）")
        try:
            dec = decision.parse(body)
        except decision.NoBlock as e:
            return self._redeliver(step, [str(e)])
        if dec["gate"] != step:
            return self._redeliver(step, [f"决定块写的是{dec['gate']}，现在等的是{step}"])
        errs = schema.errors(dec, "decision")
        if errs:
            return self._redeliver(step, [f"决定块不合：{e}" for e in errs])
        if not self._snaps:  # 换了进程（接进内核后每个会话一个）：先把定版材料读回来，并核对它没变
            self._snapshot()
        gate = next(g for g in reversed(self.state["gates"]) if g["gate"] == step)
        gate["decision"] = dec
        gate["follow_up_seq"] = follow_up_seq if follow_up_seq is not None else self._next_seq()
        self._save_state()
        if step == "G1":
            return self._apply_g1(dec)
        if step == "G2":
            return self._apply_g2(dec, gate["follow_up_seq"])
        return self._apply_g3(dec)

    def _redeliver(self, step: str, problems: list[str]) -> Delivery:
        d = {"G1": self._deliver_g1, "G2": self._deliver_g2, "G3": self._deliver_g3}[step]()
        d.needs = [*problems, *d.needs]
        return d

    def _apply_g1(self, dec: dict[str, Any]) -> Delivery:
        doc = self.get("candidates.json")
        ids = {c["id"] for c in doc["candidates"]}
        problems = [f"决定块里这一行没读懂：{ln}" for ln in dec.get("unparsed", [])]
        picked = [c for c in dec.get("pick", []) if c in ids]
        problems += [f"没有候选 {c}" for c in dec.get("pick", []) if c not in ids]
        if dec.get("redo"):
            for u in self.state["units"]:
                if u["step"] == "S3":
                    u["state"] = "void"
            self.state["artifacts"] = {
                k: v for k, v in self.state["artifacts"].items() if not k.startswith(("read:", "candidates"))
            }
            self.state["gates"][-1]["decision"] = dec
            forget = getattr(self.dan, "forget", None)
            if forget is not None:  # 重做是要重新读、重新取样：调用备忘里这一步的旧回答不能再用
                forget(("read:", "shihuo:"))
            self._save_state()
            return self._resume()
        if problems or not picked:
            if not picked:
                problems.append("请至少选一个候选")
            self.state["gates"][-1].pop("decision", None)
            self._save_state()
            return self._redeliver("G1", problems)
        for e in dec.get("edit", []):
            cid, _, fld = e["pointer"].partition(".")
            for c in doc["candidates"]:
                if c["id"] == cid and fld in ("title",):
                    c["title"] = str(e["value"])
                    c["seed"]["title"] = str(e["value"])
        if dec.get("edit"):
            self.put("candidates.json", doc)
        self.x["picked"] = picked
        self.state["step"] = "S4"
        self._save_state()
        return self._resume()

    # ------------------------------------------------------------ S4 萃意

    def _cuiyi(self) -> Delivery:
        cut = self._cuiyi_units()
        return cut if cut is not None else self._deliver_g2()

    def _cuiyi_units(self) -> Delivery | None:
        """每个选中候选的萃意单元；只在预算份额用完时返回一次部分交付。"""
        doc = self.get("candidates.json")
        dry = self.state["mode"] == "dry_run"
        obs = self.observations()
        ctx = self.context()
        rounds: dict[str, int] = self.x.setdefault("rounds", {})
        for cid in self.x["picked"]:
            uid = f"cuiyi:{cid}"
            if self._done(uid):
                continue
            if self._stage_left("S4") <= 0:
                return self._budget_cut("S4", uid)
            cand = next(c for c in doc["candidates"] if c["id"] == cid)
            self._mark(uid, "S4", "doing", depends_on=[self.state["artifacts"]["candidates.json"]])
            res = cuiyi.distill(self.dan, cand, obs, ctx, rnd=int(rounds.get(cid, 1)), dry=dry)
            for tier, (tin, tout) in res.tokens.items():
                self._spend("S4", tier, tin, tout)
            vres = checks.v_essence(res.essence, ctx, self.x["picked"])
            self.put(f"essence:{cid}.v", vres)
            sha = self.put(f"essence:{cid}", res.essence)
            self._mark(
                uid,
                "S4",
                "done",
                output=sha,
                summary=f"{cid}：{'过' if res.passed else '未过'}，取 {res.essence['drafts']['chosen']}",
            )
        return None

    def _deliver_g2(self) -> Delivery:
        self.state["step"] = "G2"
        if not any(g["gate"] == "G2" and "decision" not in g for g in self.state["gates"]):
            self.state["gates"].append({"gate": "G2", "deliver_seq": self._next_seq()})
        self._save_state()
        arts = {}
        essences = []
        passed = True
        needs = []
        for cid in self.x["picked"]:
            ess = self.get(f"essence:{cid}")
            vres = self.get(f"essence:{cid}.v") or []
            essences.append(ess)
            arts[f"essence:{cid}"] = self.state["artifacts"][f"essence:{cid}"]
            bad = [
                c["id"]
                for c in [*ess["checks"], *vres]
                if not c["ok"] and not c.get("advisory") and not c.get("override")
            ]
            if bad:
                passed = False
                needs.append(f"{cid} 未过：{', '.join(bad)}")
        needs.append("请逐个确认提炼出的核心做法，或逐栏修改、退回重做、放弃（第 2 次确认）")
        return Delivery("G2", "partial", report_g2(essences), arts, needs, passed=passed)

    def _apply_g2(self, dec: dict[str, Any], seq: int) -> Delivery:
        picked = list(self.x["picked"])
        problems = [f"决定块里这一行没读懂：{ln}" for ln in dec.get("unparsed", [])]
        named = (
            set(dec.get("confirm", []))
            | set(dec.get("drop", []))
            | {b for b in dec.get("back", []) if b.startswith("C")}
        )
        problems += [f"没有候选 {c}" for c in sorted(named - set(picked))]
        ctx = self.context()
        edited: dict[str, dict[str, Any]] = {}
        for e in dec.get("edit", []):
            path = cuiyi.pointer(e["pointer"])
            cid = e["pointer"].split(".")[0]
            if path is None or cid not in picked:
                problems.append(f"改不了：{e['pointer']}")
                continue
            ess = edited.get(cid) or self.get(f"essence:{cid}")
            err = cuiyi.apply_edit(ess, path, str(e["value"]))
            if err:
                problems.append(err)
                continue
            ess.setdefault("human_edits", []).append(
                {"pointer": "/masked/" + "/".join(path), "by": self.cfg.by, "date": self.cfg.date, "follow_up_seq": seq}
            )
            edited[cid] = ess
        if problems:
            self.state["gates"][-1].pop("decision", None)
            self._save_state()
            return self._redeliver("G2", problems)
        for cid, ess in edited.items():
            cuiyi.recheck_after_edit(ess, ctx)
            self.put(f"essence:{cid}", ess)
            self.put(f"essence:{cid}.v", checks.v_essence(ess, ctx, picked))
        back = [b for b in dec.get("back", []) if b.startswith("C")]
        if any(b.startswith("闸点") for b in dec.get("back", [])):
            for cid in picked:
                self._mark(f"cuiyi:{cid}", "S4", "void")
            self.x["picked"] = []
            self.state["step"] = "G1"
            self._save_state()
            return self._deliver_g1()
        for cid in dec.get("drop", []):
            self._mark(f"cuiyi:{cid}", "S4", "void")
            self.x.setdefault("dropped", []).append(cid)
        self.x["picked"] = [c for c in picked if c not in dec.get("drop", [])]
        if back:
            rounds = self.x.setdefault("rounds", {})
            for cid in back:
                rounds[cid] = int(rounds.get(cid, 1)) + 1
                self._mark(f"cuiyi:{cid}", "S4", "void")
            self.state["step"] = "S4"
            self._save_state()
            return self._resume()
        confirmed = [c for c in dec.get("confirm", []) if c in self.x["picked"]]
        pending = [c for c in self.x["picked"] if c not in confirmed]
        self.x["confirmed"] = confirmed
        if pending:
            self.state["gates"][-1].pop("decision", None)
            self._save_state()
            return self._redeliver("G2", [f"还没有确认：{', '.join(pending)}"])
        self.state["step"] = "S5"
        self._save_state()
        return self._ruwei()

    # ------------------------------------------------------------ S5 入位与火序

    def _ruwei(self) -> Delivery:
        doc = self.get("candidates.json")
        confirmed = list(self.x.get("confirmed", []))
        self.state["step"] = "S5"
        rounds: dict[str, int] = self.x.setdefault("rounds_s5", {})
        deps: dict[str, list[str]] = self.x.setdefault("depends", {})
        problems: dict[str, list[str]] = self.x.setdefault("placement_problems", {})
        dry = self.state["mode"] == "dry_run"
        for cid in confirmed:
            uid = f"ruwei:{cid}"
            dep = [self.state["artifacts"][f"essence:{cid}"]]
            unit = self._unit(uid)
            if self._done(uid) and unit is not None and unit.get("depends_on") == dep:
                continue
            if self._stage_left("S5") <= 0:
                return self._budget_cut("S5", uid)
            cand = next(c for c in doc["candidates"] if c["id"] == cid)
            ess = self.get(f"essence:{cid}")
            self._mark(uid, "S5", "doing", depends_on=dep)
            res = ruwei.place(self.dan, cand, ess, rnd=int(rounds.get(cid, 1)), full=not dry, locks=self.cfg.locks)
            for tier, (tin, tout) in res.tokens.items():
                if tin or tout:
                    self._spend("S5", tier, tin, tout)
            deps[cid] = res.depends_on
            problems[cid] = res.problems
            sha = self.put(f"placement:{cid}", res.placement)
            self._mark(
                uid,
                "S5",
                "done",
                output=sha,
                summary=f"{cid}：{res.placement['fire']['slot']}，难度 {res.placement['difficulty']['value']}"
                + (f"，未过 {len(res.problems)} 项" if res.problems else ""),
            )
        if dry:
            return self._dry_report()
        placements = {cid: self.get(f"placement:{cid}") for cid in confirmed}
        names = {c["id"]: c["name"] for c in doc["candidates"]}
        rels = ruwei.relations(placements, deps, self.cfg.bang, names)
        ctx = self.context()
        for cid, p in placements.items():
            p["conflicts"]["candidates"] = rels[cid]
            p["checks"] = []
            p["checks"] = checks.v_placement(p, self.get(f"essence:{cid}"), ctx, confirmed)
            self.put(f"placement:{cid}", p)
        self.put("order.json", ruwei.order(doc["candidates"], placements))
        self._save_state()
        return self._deliver_g3()

    def _deliver_g3(self) -> Delivery:
        self.state["step"] = "G3"
        if not any(g["gate"] == "G3" and "decision" not in g for g in self.state["gates"]):
            self.state["gates"].append({"gate": "G3", "deliver_seq": self._next_seq()})
        confirmed = list(self.x.get("confirmed", []))
        placements = [self.get(f"placement:{c}") for c in confirmed]
        order = self.get("order.json")
        text_ = report_g3(placements, order, self.get("candidates.json"))
        self.put("report:G3", {"v": 1, "gate": "G3", "markdown": text_})
        self._save_state()
        arts = {f"placement:{c}": self.state["artifacts"][f"placement:{c}"] for c in confirmed}
        arts["order.json"] = self.state["artifacts"]["order.json"]
        arts["report:G3"] = self.state["artifacts"]["report:G3"]
        needs = []
        passed = True
        for p in placements:
            bad = [c["id"] for c in p["checks"] if not c["ok"]]
            more = self.x.get("placement_problems", {}).get(p["candidate"], [])
            if bad or more:
                passed = False
                needs.append(f"{p['candidate']} 未过：{', '.join(bad + more)[:300]}")
        needs.append("请逐个决定：交实现线、搁置（写理由）或排除（写理由）；可勾选把报告存进资料库（第 3 次确认）")
        return Delivery("G3", "answered", text_, arts, needs, passed=passed)

    def _apply_g3(self, dec: dict[str, Any]) -> Delivery:
        confirmed = list(self.x.get("confirmed", []))
        order = self.get("order.json")
        problems = [f"决定块里这一行没读懂：{ln}" for ln in dec.get("unparsed", [])]
        to_impl = list(dec.get("to_implementation", []))
        hold = {r["candidate"]: r.get("why", "") for r in dec.get("hold", [])}
        excl = {r["candidate"]: r.get("why", "") for r in dec.get("exclude", [])}
        named = set(to_impl) | set(hold) | set(excl) | {b for b in dec.get("back", []) if b.startswith("C")}
        problems += [f"没有入位的候选 {c}" for c in sorted(named - set(confirmed))]
        held = {h["candidate"]: h for h in order["held"]}
        for c in to_impl:
            if c in held:
                problems.append(f"{c} 在挂起（{held[c].get('note', held[c]['why'])}），不能直接交实现线")
        if any(b.startswith("闸点") for b in dec.get("back", [])):
            # 入位单元不作废：重新确认时火意没变的直接复用（_ruwei 比对依赖），改过或退回过的才重跑
            self.x["confirmed"] = []
            self.state["step"] = "G2"
            self._save_state()
            return self._deliver_g2()
        back = [b for b in dec.get("back", []) if b.startswith("C") and b in confirmed]
        if problems:
            self.state["gates"][-1].pop("decision", None)
            self._save_state()
            return self._redeliver("G3", problems)
        if back:
            rounds = self.x.setdefault("rounds_s5", {})
            for c in back:
                rounds[c] = int(rounds.get(c, 1)) + 1
                self._mark(f"ruwei:{c}", "S5", "void")
            self.state["gates"][-1].pop("decision", None)
            self._save_state()
            return self._ruwei()
        pending = [c for c in confirmed if c not in named]
        if pending:
            self.state["gates"][-1].pop("decision", None)
            self._save_state()
            return self._redeliver("G3", [f"还没有决定：{', '.join(pending)}"])
        self.x["g3"] = {
            "to_implementation": to_impl,
            "hold": hold,
            "exclude": excl,
            "library_import": bool(dec.get("library_import")),
        }
        self.state["step"] = "S6"
        self._save_state()
        return self._handoff()

    # ------------------------------------------------------------ S6 交接包

    def _fates(self, doc: Mapping[str, Any]) -> dict[str, tuple[str, str, str]]:
        g3 = self.x.get("g3", {})
        g1: dict[str, Any] = next(
            (g.get("decision", {}) for g in self.state["gates"] if g["gate"] == "G1" and "decision" in g), {}
        )
        g1_excl = {r["candidate"]: r.get("why", "") for r in g1.get("exclude", [])}
        out: dict[str, tuple[str, str, str]] = {}
        for c in doc["candidates"]:
            cid = c["id"]
            if cid in g3.get("to_implementation", []):
                out[cid] = ("G3", "handed_off", "交实现线，导入后填档号")
            elif cid in g3.get("hold", {}):
                out[cid] = ("G3", "", f"搁置：{g3['hold'][cid] or '未写理由'}")
            elif cid in g3.get("exclude", {}):
                out[cid] = ("G3", "excluded", g3["exclude"][cid])
            elif cid in self.x.get("dropped", []):
                out[cid] = ("G2", "", "第 2 次确认时放弃")
            elif cid in g1_excl:
                out[cid] = ("G1", "excluded", g1_excl[cid])
            else:
                out[cid] = ("G1", "", "第 1 次确认时没有选")
        return out

    def _handoff(self) -> Delivery:
        doc = self.get("candidates.json")
        g3 = self.x["g3"]
        order = self.get("order.json")
        arts = self.state["artifacts"]
        held = [dict(h) for h in order["held"]]
        for cid, why in g3["hold"].items():
            if any(h["candidate"] == cid for h in held):
                continue
            row: dict[str, Any] = next((o for o in order["order"] if o["candidate"] == cid), {})
            waits = [w for w in row.get("waits_for", []) if w in g3["to_implementation"] or w.startswith("炼档")]
            if waits:
                note = f"第 3 次确认时搁置：{why or '等前一个定论'}；等 {'、'.join(waits)} 定论后做映射复核"
                held.append({"candidate": cid, "why": "slot_locked", "note": note[:300]})
        items = []
        for cid in g3["to_implementation"]:
            c = next(x for x in doc["candidates"] if x["id"] == cid)
            ess = self.get(f"essence:{cid}")
            p = self.get(f"placement:{cid}")
            items.append(
                {
                    "candidate": cid,
                    "decision": "to_implementation",
                    "seed": c["seed"],
                    "cuiyi": handoff.render_cuiyi(ess, self.cfg.by),
                    "essence": ess,
                    "placement": p,
                    "artifacts": {
                        "candidates": arts["candidates.json"],
                        "essence": arts[f"essence:{cid}"],
                        "placement": arts[f"placement:{cid}"],
                        "report": arts["report:G3"],
                    },
                }
            )
        essences = {c: self.get(f"essence:{c}") for c in self.x.get("confirmed", [])}
        updates = handoff.bang_updates(
            self.cfg.bang,
            doc,
            run=self.cfg.run,
            mode="formal",
            date=self.cfg.date,
            fates=self._fates(doc),
            essences=essences,
            artifacts=[arts["candidates.json"], arts["order.json"]],
        )
        proposals = [
            {"dim": g["dim"], "change": "add_dim", "why": f"{c['title']}：外部有、剖面里没有这一维"[:300]}
            for c in doc["candidates"]
            for g in c["gaps"]
            if g["type"] == "new_dim"
        ]
        g3_gate = next(g for g in reversed(self.state["gates"]) if g["gate"] == "G3")
        h: dict[str, Any] = {
            "v": 1,
            "run": self.cfg.run,
            "basis": doc["basis"],
            "decided_by": self.cfg.by,
            "date": self.cfg.date,
            "g3_follow_up_seq": g3_gate["follow_up_seq"],
            "order": order["order"],
            "held": held,
            "items": items,
            "bang_updates": updates,
            "profile_proposals": proposals,
            "library_import": g3["library_import"],
            "validator": [{"id": f"V{i}", "ok": True} for i in range(1, 13)],
        }
        h["validator"] = handoff.v_handoff(h, self.context(), g3["to_implementation"])
        sha = self.put("handoff.json", h)
        text_ = report_handoff(h)
        rsha = self.put("report:S6", {"v": 1, "gate": "S6", "markdown": text_})
        self.state["step"] = "done"
        self._save_state()
        needs = []
        if items:
            needs.append("交实现线的做法：在主仓库的工作分支跑 uv run python scripts/lianhua.py import <交接包>")
        if g3["library_import"]:
            needs.append("报告存进资料库：由界面以你的身份导入（只作参考，不作依据）")
        passed = checks.hard_ok(h["validator"])
        if not passed:
            needs.insert(0, "交接包校验未过：" + "；".join(c["id"] for c in h["validator"] if not c["ok"]))
        return Delivery(None, "answered", text_, {"handoff.json": sha, "report:S6": rsha}, needs, passed=passed)

    # ------------------------------------------------------------ 试算（09 §3）

    def _dry_run(self) -> Delivery:
        doc = self.get("candidates.json")
        if "picked" not in self.x:
            self.x["picked"] = [c["id"] for c in doc["candidates"][:DRY_RUN_PICK]]
            self.state["step"] = "S4"
            self._save_state()
        if self.state["step"] in ("S3", "S4"):
            cut = self._cuiyi_units()
            if cut is not None:
                return cut
            self.x["confirmed"] = list(self.x["picked"])
            self.state["step"] = "S5"
            self._save_state()
        return self._ruwei()

    def _dry_report(self) -> Delivery:
        doc = self.get("candidates.json")
        ctx = self.context()
        items = []
        for cid in self.x["picked"]:
            ess = self.get(f"essence:{cid}")
            p = self.get(f"placement:{cid}")
            outcome, why = ruwei.likely_outcome(ess, p)
            items.append(
                {
                    "candidate": cid,
                    "essence_draft": ess["masked"],
                    "slot": p["fire"]["slot"],
                    "group_slots": [g["slot"] for g in p["group"]],
                    "replaces": p["replaces"],
                    "conflicts": ruwei.conflict_lines(p),
                    "kernel_forecast": ruwei.kernel_areas(p),
                    "difficulty": p["difficulty"]["value"],
                    "likely_outcome": outcome,
                    "why": why,
                    "checks": ess["checks"],
                }
            )
        tiers = [self.get(f"snapshot:{sid}")["size_tier"] for sid in self._snaps]
        tier = max(tiers, key=lambda t: ["S", "M", "L", "XL"].index(t))
        est = estimate(self.cfg.prior, tier, len(items))
        lic = doc["basis"]["snapshots"][0]["license"]
        report: dict[str, Any] = {
            "v": 1,
            "mode": "dry_run",
            "run": self.cfg.run,
            "candidates": doc,
            "auto_picked": list(self.x["picked"]),
            "items": items,
            "estimate": est,
            "plain_summary": dry_summary(items, est, lic),
        }
        vres = checks.v_dry_run(report, ctx)
        sha = self.put("dry_run.json", report)
        self.put("dry_run.v", vres)
        fates = {c: ("S5", "dry_run", "预评估过") for c in self.x["picked"]}
        updates = handoff.bang_updates(
            self.cfg.bang,
            doc,
            run=self.cfg.run,
            mode="dry_run",
            date=self.cfg.date,
            fates=fates,
            essences={c: self.get(f"essence:{c}") for c in self.x["picked"]},
            artifacts=[sha],
        )
        # 产物登记只收 JSON 对象（kernel.product_errors）：更新列表放在 bang_updates 键下，与交接包同一个键名，
        # `lianhua bang apply` 两种形状都认
        usha = self.put(
            "bang_updates.json",
            {"v": 1, "run": self.cfg.run, "mode": "dry_run", "bang_updates": updates},
        )
        self.state["step"] = "done"
        self._save_state()
        needs = ["这是预评估：单稿、不盲审、不写实现步骤，不能直接交实现线；要正式走一遍就复用这次的快照与观察重开一题"]
        bad = [c["id"] for c in vres if not c["ok"]]
        if bad:
            needs.insert(0, f"校验未过（只标不拦）：{', '.join(bad)}")
        arts = {"dry_run.json": sha, "bang_updates.json": usha}
        return Delivery(None, "answered", report_dry_run(report), arts, needs, passed=not bad)

    # ------------------------------------------------------------ 续做

    def resume(self) -> Delivery:
        """从 run.json 的当前步接着做。"""
        return self._guard(self._resume)

    def _resume(self) -> Delivery:
        step = self.state.get("step")
        if step in ("failed", "done"):
            raise EngineError(f"这次运行已停在 {step}")
        if step == "paused_budget":
            cut = [u for u in self.state["units"] if u["state"] == "budget_cut"]
            step = self.x.pop("paused_from", None) or (cut[0]["step"] if cut else "S3")
            for u in cut:
                u["state"] = "todo"
            self.state["step"] = step
        self._snapshot()
        if not self._done("candidates"):
            return self._shihuo()
        if self.state["mode"] == "dry_run":
            return self._dry_run()
        if step in ("G1", "S3"):  # S3：清单已建好、还没来得及交付就被打断
            return self._deliver_g1()
        if step == "S4":
            return self._cuiyi()
        if step == "G2":
            return self._deliver_g2()
        if step == "S5":
            return self._ruwei()
        if step == "G3":
            return self._deliver_g3()
        if step == "S6":
            return self._handoff()
        raise EngineError(f"不认识的步：{step}")

    def add_budget(self, usd_milli: int) -> None:
        """追问里带的追加预算（`budget_add_usd_milli`）。"""
        self.x["budget_usd_milli"] = int(self.x["budget_usd_milli"]) + usd_milli
        self._save_state()


# ---------------------------------------------------------------- 人读报告（用常规技术词）


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def report_g1(doc: Mapping[str, Any]) -> str:
    lines = ["# 方案分析：候选做法", "", doc["plain_summary"], ""]
    bad = [c for c in doc["checks"] if not c["ok"]]
    if bad:
        lines += ["> **校验未过**：" + "；".join(f"{c['id']} {c.get('detail', '')}" for c in bad), ""]
    lic = doc["basis"]["snapshots"][0]["license"]
    reuse = "只借思路，不参考原码" if lic.get("reuse") == "idea_only" else "可参考原码"
    lines += [f"来源许可证：{lic.get('spdx') or lic['status']}（{reuse}）", ""]
    lines += [
        "| 编号 | 做法 | 主要位置 | 价值 | 置信 | 难度 | 风险 | 优先级 | 建议 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    level = {"recommend": "推荐", "optional": "可选", "not_recommended": "不推荐"}
    for c in doc["candidates"]:
        nums = f"{c['value']:g} | {_pct(c['confidence'])} | {c['difficulty']} | {c['risk']} | {c['priority']:g}"
        rec = f"{level[c['recommend']['level']]}：{c['recommend']['why']}"
        lines.append(f"| {c['id']} | {c['title']} | {c['slot']} | {nums} | {rec} |")
    if doc["already_have"]:
        lines += ["", "**我们已有且不弱的**："]
        lines += [f"- {a['dim']}：我们 {a['ours']} 级，对方 {a['theirs']} 级" for a in doc["already_have"]]
    if doc["not_fire"]:
        lines += ["", "**只是功能点，不是可复用的做法**："]
        lines += [f"- {n['what']}：{n['why']}" for n in doc["not_fire"]]
    if doc["unseen_slots"]:
        lines += ["", f"**没找到东西的位置**：{', '.join(doc['unseen_slots'])}（读了哪些、为什么停见覆盖报告）"]
    return "\n".join(lines)


def report_g2(essences: Sequence[Mapping[str, Any]]) -> str:
    lines = ["# 方案分析：核心做法", ""]
    for e in essences:
        m = e["masked"]
        bad = [c["id"] for c in e["checks"] if not c["ok"] and not c.get("advisory")]
        lines += [f"## {e['candidate']}：{m['statement']}", "", e.get("plain_summary", ""), ""]
        if bad:
            lines += [f"> **检验未过**：{', '.join(bad)}", ""]
        lines += [
            "新指标："
            + "；".join(
                f"{x['dim']}（{'结构' if x['measure'] == 'structural' else '运行'}，门槛 {x['gate']}）"
                for x in m["fusion"]["emergent"]
            )
        ]
        if e["drafts"].get("disagreements"):
            lines += ["", "三稿分歧：" + "；".join(e["drafts"]["disagreements"])]
        lines.append("")
    return "\n".join(lines)


KIND_ZH = {"新生": "新增", "异火": "外部方案优势", "本火": "基线保障", "共有": "通用"}
ARM_ZH = {"B": "基线", "A1": "外部方案移植", "F": "融合方案", "B1": "基线复跑", "A0": "外部原版"}
RES_ZH = {
    "coexist": "并存",
    "param": "作为参数暴露",
    "partition": "按条件分开用",
    "replace": "替换",
    "reject": "不收",
    "fused_away": "已在设计里化解",
    "split_to_kernel": "拆成单独的内核修订",
}
REL_ZH = {"compatible": "互不影响", "sequential": "有先后", "depends_on": "依赖", "exclusive": "二选一"}
HELD_ZH = {
    "exclusive_pending": "二选一待你定",
    "waits_structural": "要先定新模块槽",
    "waits_kernel_split": "要先做内核修订",
    "cycle": "先后关系成环",
    "slot_locked": "模块槽占用，排队",
}
OUTCOME_ZH = {
    "promising_huolian": "有望带来新能力",
    "at_most_helian": "最多是全面提升",
    "maybe_binghuo": "可能没有增益",
}


def _placement_card(p: Mapping[str, Any]) -> list[str]:
    f = p["fire"]
    lines = [
        f"## {p['candidate']}：{f['id']}（模块槽 {f['slot']}）",
        "",
        p.get("plain_summary", ""),
        "",
        f"- 兼及：{'、'.join(f.get('also_touches', [])) or '无'}；模块组："
        + ("、".join(f"{g['id']}（{g['slot']}）" for g in p["group"]) or "无"),
        f"- 替换：{p['replaces'] or '无，与现有模块并存'}" + ("（被替换的留作对照）" if p["replaces"] else ""),
        f"- 内核改动：0 行（预判{'为空' if not p['kernel_forecast'] else '：' + '、'.join(p['kernel_forecast'])}）；"
        f"难度 {p['difficulty']['value']}",
    ]
    if p.get("arms"):
        lines += ["", "**对照组**：" + "；".join(f"{ARM_ZH.get(k, k)}：{v}" for k, v in p["arms"].items())]
    if p.get("readings"):
        lines += ["", "| 指标 | 类别 | 方向 | 门槛 | 怎么量 |", "| --- | --- | --- | --- | --- |"]
        for r in p["readings"]:
            how = r.get("test") or r.get("run") or "—"
            must = "（必登）" if r.get("mandatory") else ""
            arrow = "↑" if r["dir"] == "up" else "↓"
            lines.append(
                f"| {r['dim']}{must} | {KIND_ZH.get(r['kind'], r['kind'])} | {arrow} | {r.get('gate', '—')} | {how} |"
            )
    if p.get("steps"):
        lines += ["", "**实现步骤**："]
        lines += [
            f"{s['n']}. {s['do']}（{s['slot']}，{'、'.join(s['where'])}；验收：{s['accept']}）" for s in p["steps"]
        ]
    conf = p["conflicts"]
    rows = [f"{c['fire']}：{RES_ZH.get(c['resolution'], c['resolution'])}" for c in conf["fires"]]
    rows += [f"内核 {c['kernel']}：{RES_ZH.get(c['resolution'], c['resolution'])}" for c in conf["kernel"]]
    rows += [f"{c['other']}：{REL_ZH.get(c['relation'], c['relation'])}" for c in conf["candidates"]]
    rows += [f"{lk['slot']} 被在途的集成记录 {lk['dossier']} 占用" for lk in conf["slot_locks"]]
    if rows:
        lines += ["", "**冲突**：" + "；".join(rows)]
    bad = [c["id"] for c in p.get("checks", []) if not c["ok"]]
    if bad:
        lines += ["", f"> **校验未过**：{', '.join(bad)}"]
    lines.append("")
    return lines


def report_g3(placements: Sequence[Mapping[str, Any]], order: Mapping[str, Any], candidates: Mapping[str, Any]) -> str:
    titles = {c["id"]: c["title"] for c in candidates["candidates"]}
    lines = ["# 方案分析：映射与集成顺序", "", "## 集成顺序", ""]
    for o in order["order"]:
        waits = f"；等 {'、'.join(o['waits_for'])}" if o.get("waits_for") else ""
        lines.append(f"{o['position']}. {o['candidate']} {titles.get(o['candidate'], '')}：{o['why']}{waits}")
    for h in order["held"]:
        lines.append(f"- 暂缓 {h['candidate']}：{HELD_ZH.get(h['why'], h['why'])}（{h.get('note', '')}）")
    lines.append("")
    for p in placements:
        lines += _placement_card(p)
    return "\n".join(lines)


def report_handoff(h: Mapping[str, Any]) -> str:
    lines = ["# 方案分析：交接", ""]
    if h["items"]:
        lines.append("交给实现线的做法（按集成顺序串行导入，前一个定论后再导入下一个）：")
        for it in h["items"]:
            f, plain = it["placement"]["fire"], it["placement"]["plain_summary"]
            lines.append(f"- {it['candidate']} {it['seed']['title']}：{f['id']}（{f['slot']}），{plain}")
    else:
        lines.append("这次没有交给实现线的做法。")
    if h.get("held"):
        lines += ["", "暂缓："] + [f"- {x['candidate']}：{HELD_ZH.get(x['why'], x['why'])}" for x in h["held"]]
    lic = h["basis"]["snapshots"][0]["license"]
    if lic.get("reuse") == "idea_only":
        lines += ["", f"来源许可证 {lic.get('spdx') or lic['status']}：实现时不得打开原码，只借思路。"]
    lines += ["", f"候选方案的变化 {len(h['bang_updates'])} 条，由导入命令写入、随 PR 审。"]
    bad = [c["id"] for c in h["validator"] if not c["ok"]]
    lines += ["", "交接包校验 V1–V12 " + ("全过。" if not bad else f"未过：{', '.join(bad)}。")]
    return "\n".join(lines)


def report_dry_run(r: Mapping[str, Any]) -> str:
    lines = [
        "# 预评估",
        "",
        r["plain_summary"],
        "",
        "| 编号 | 核心机制 | 模块槽 | 替换 | 内核 | 难度 | 可能的结局 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for it in r["items"]:
        kern = "、".join(it["kernel_forecast"]) or "不改"
        lines.append(
            f"| {it['candidate']} | {it['essence_draft']['statement']} | {it['slot']} | {it['replaces'] or '无'} | "
            f"{kern} | {it.get('difficulty', '—')} | {OUTCOME_ZH[it['likely_outcome']]}：{it['why']} |"
        )
    e = r["estimate"]
    tok = "；".join(
        f"{ {'light': '轻量', 'mid': '标准', 'heavy': '高性能'}[k] } 入 {v['in']:,} 出 {v['out']:,}"
        for k, v in e["tokens"].items()
    )
    lines += ["", f"正式走一遍的预估：{tok}；约 {e['minutes']} 分钟机器时间（占位估算）。"]
    lines += ["", "预评估是单稿、不盲审、不写实现步骤，不能直接交实现线。"]
    return "\n".join(lines)


def estimate(prior: budget.Prior, size_tier: str, n: int) -> dict[str, Any]:
    """试算报告里“正式走一遍”的预估：按预算先验的 token 表，S4、S5 按候选数乘。"""
    tokens: dict[str, dict[str, int]] = {}
    for key, (tin, tout) in prior.tokens(size_tier).items():
        step, tier = key.split(".")
        k = n if step in ("S4", "S5") else 1
        row = tokens.setdefault(tier, {"in": 0, "out": 0})
        row["in"] += tin * k
        row["out"] += tout * k
    ordered = {t: tokens[t] for t in READ_TIERS if t in tokens}
    total_in = sum(v["in"] for v in ordered.values())
    return {
        "tokens": ordered,
        "minutes": -(-total_in // 50_000),
        "budget_usd_milli": budget.run_budget(prior, size_tier, max(1, n)),
    }


def dry_summary(items: Sequence[Mapping[str, Any]], est: Mapping[str, Any], lic: Mapping[str, Any]) -> str:
    good = sum(1 for it in items if it["likely_outcome"] == "promising_huolian")
    kern = sum(1 for it in items if it["kernel_forecast"])
    head = f"预评估：自动取了优先级最高的 {len(items)} 个做法，{good} 个有望带来新能力"
    head += "，内核都不用改。" if not kern else f"，{kern} 个可能要先做内核修订。"
    tail = f"正式走一遍预计约 {est['minutes']} 分钟机器时间，外加你三次确认。"
    if lic.get("reuse") == "idea_only":
        tail += f"来源是 {lic.get('spdx') or lic['status']}，只借思路。"
    return (head + tail)[:600]
