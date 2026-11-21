"""吞噬引擎的工作流（docs/design/fenjue/09-engine.md §2、§4、§6）：S0 立项 → S3 识火 → G1 → S4 萃意 → G2。

这一期是**最小版本**：识火与萃意走到闸点 2，在合成夹具上用录好的丹输出过线（E1 的量具 + E3/E4 的流程骨架）。
还没有接进内核：交付（`Delivery`）就是将来 `deliver` 的内容（人读报告 + 结构化产物的 sha256 + needs），
闸点的决定块就是将来 cz `follow_up` 的正文。入位与火序（S5）、交接（S6）、试算模式下一期做。

状态外置：工作区里的 `run.json`（run.schema.json）是检查点，`obs.jsonl` 是只追加的观察库，`artifacts/<sha256>.json`
是内容寻址的产物。任何时候中断，新的 `Engine` 读 `run.json` 从第一个未完成的单元接着做；已完成的单元不重做，
已登记的观察不重读（09 §6）。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..shapes import digest
from . import budget, checks, cuiyi, data, decision, schema, shihuo, survey, text
from .dan import Dan, new_nonce

ENGINE_FIRE = "h1.tunshi@1"


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


@dataclass
class Delivery:
    """一次交付：`answer` 是人读报告，`artifacts` 是结构化产物的 sha256，`needs` 是给 cz 的话。"""

    gate: str | None
    outcome: str
    answer: str
    artifacts: dict[str, str]
    needs: list[str]
    passed: bool = True


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
        (self.ws / "run.json").write_text(json.dumps(self.state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (self.ws / "engine.json").write_text(json.dumps(self.x, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def put(self, name: str, obj: Any) -> str:
        sha = digest(obj)
        p = self.ws / "artifacts" / f"{sha}.json"
        if not p.exists():
            p.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
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
        sp = self.state["spent"]
        cost = budget.cost_usd_milli(self.cfg.prior, tier, tin, tout)
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

    def start(self, intake: dict[str, Any]) -> Delivery:
        """S0–S3：立项、快照、勘察、识火，交付闸点 1。已有 run.json 就接着做。"""
        if not self.state:
            errs = schema.errors(intake, "intake")
            if errs:
                raise EngineError(f"立项单不合 Schema：{errs[:3]}")
            if intake["mode"] != "formal":
                raise EngineError("这一期只做正式模式；试算模式随入位一起做")
            refused = list(intake.get("refused", []))
            keep = []
            for s in intake["sources"]:
                mat = self.materials.get(s.get("artifact", ""))
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
            self._save_state()
        return self.resume()

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
            mat = self.materials.get(s.get("artifact", ""))
            if mat is None:
                raise EngineError(f"来源 {s['no']} 的材料没有定版（地址类来源要先经扩权卡抓取）")
            snap = survey.load_snapshot(sid, s["form"], mat)
            self._snaps[sid] = snap
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
            self.x["budget_usd_milli"] = self.cfg.budget_usd_milli or budget.run_budget(self.cfg.prior, tier, min(n, 3))
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
            for attempt in range(1, shihuo.ATTEMPTS + 1):
                self._mark("candidates", "S3", "doing", attempts=attempt)
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
            self.put(
                "candidates.needs",
                shihuo.needs(doc, inp, proposal) + ([] if passed else [f"未过：{e}" for e in errors]),
            )
            self._mark("candidates", "S3", "done", output=self.state["artifacts"]["candidates.json"])
        return self._deliver_g1()

    def _budget_cut(self, step: str, uid: str) -> Delivery:
        self._mark(uid, step, "budget_cut")
        self.state["step"] = "paused_budget"
        self._save_state()
        msg = f"{step} 的预算份额用完，停在单元 {uid}；追加预算后从这里接着做（已完成的单元不重做）"
        return Delivery(
            None, "partial", msg, dict(self.state["artifacts"]), [msg, "追加预算继续，或缩小范围"], passed=False
        )

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
        """cz 的追问正文（带决定块）。G1 之后进萃意，G2 之后停在入位之前（下一期）。"""
        step = self.state.get("step")
        if step not in ("G1", "G2"):
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
        gate = next(g for g in reversed(self.state["gates"]) if g["gate"] == step)
        gate["decision"] = dec
        gate["follow_up_seq"] = follow_up_seq if follow_up_seq is not None else self._next_seq()
        self._save_state()
        if step == "G1":
            return self._apply_g1(dec)
        return self._apply_g2(dec, gate["follow_up_seq"])

    def _redeliver(self, step: str, problems: list[str]) -> Delivery:
        d = self._deliver_g1() if step == "G1" else self._deliver_g2()
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
            self._save_state()
            return self.resume()
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
        return self.resume()

    # ------------------------------------------------------------ S4 萃意

    def _cuiyi(self) -> Delivery:
        doc = self.get("candidates.json")
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
            res = cuiyi.distill(self.dan, cand, obs, ctx, rnd=int(rounds.get(cid, 1)))
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
        return self._deliver_g2()

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
        needs.append("请逐个确认火意，或逐栏修改、退回重做、放弃（闸点 2）")
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
            return self.resume()
        confirmed = [c for c in dec.get("confirm", []) if c in self.x["picked"]]
        pending = [c for c in self.x["picked"] if c not in confirmed]
        self.x["confirmed"] = confirmed
        if pending:
            self.state["gates"][-1].pop("decision", None)
            self._save_state()
            return self._redeliver("G2", [f"还没有确认：{', '.join(pending)}"])
        self.state["step"] = "S5"
        self._save_state()
        arts = {f"essence:{c}": self.state["artifacts"][f"essence:{c}"] for c in confirmed}
        msg = f"已确认 {', '.join(confirmed)} 的核心做法。下一步是落位、排序与交接，这一期还没有实现。"
        return Delivery(None, "partial", msg, arts, ["落位与排序在下一期实现（09 §2.1 的 S5）"])

    # ------------------------------------------------------------ 续做

    def resume(self) -> Delivery:
        """从 run.json 的当前步接着做。"""
        step = self.state.get("step")
        if step in ("failed", "S5", "done"):
            raise EngineError(f"这次运行已停在 {step}")
        if step == "paused_budget":
            cut = [u for u in self.state["units"] if u["state"] == "budget_cut"]
            step = cut[0]["step"] if cut else "S3"
            for u in cut:
                u["state"] = "todo"
            self.state["step"] = step
        self._snapshot()
        if not self._done("candidates"):
            return self._shihuo()
        if step == "G1":
            return self._deliver_g1()
        if step == "S4":
            return self._cuiyi()
        if step == "G2":
            return self._deliver_g2()
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
