"""接进内核的会话编排（docs/design/fenjue/13-kernel.md §3）：一个求解会话里，引擎从哪里接着做、做到哪里交付。

内核眼里，一次方案分析就是一道开放道的题：原话与材料在开题事件里，三个闸点是三次交付，cz 的决定是追问
（`follow_up`）的正文，每一轮由司南派一个求解会话。会话里跑的不是自由对话的智能体，而是这里的 `run`：

1. 向宿主要这道题的简报（`intake` 工具）：立项单、材料的原始字节、追问、预算、异火榜与火位锁、各档位的模型与价；
2. 把材料定版成快照目录（上传的解包；地址类来源经 `fetch` 工具在沙箱里按固定命令抓，授权不够就申请、等人批）；
3. 按工作区里的检查点决定做什么：没开始就立项；停在闸点且有新的追问就把它当决定块；其余接着做；
4. 引擎走到下一次交付为止；每份结构化产物经 `check` 工具登记成 Artifact，报告经 `deliver` 工具交付。

本模块是纯逻辑：不开网络、不起进程，宿主的四个工具与模型都从外面递进来（`Tools`、`Dan`），所以同一段编排既在
模型容器里由驱动程序跑（`paoding_adapter.tunshi_cli`），也在测试里对着替身跑。信任边界不在这里：哪些来源登记过、
哪个地址能连、什么能登记成 Artifact、交付收不收，都由宿主一侧的工具与内核判。
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from . import budget, data, materials, schema, survey
from .dan import Dan, Memo, Unavailable
from .run import Config, Delivery, Engine, EngineError

ANALYSIS = "analysis"  # 工作区里引擎的目录：run.json、engine.json、obs.jsonl、artifacts/、calls.jsonl
MATERIALS = "materials"  # 工作区里定版的材料：s<编号>/ 是快照目录
NEEDS_MAX, NEED_CHARS = 32, 1000  # 内核对交付的上限（reducer/deliver.py）
CLAIM_CHARS = 1000
INTAKE_MEDIA = "application/vnd.paoding.fenjue.intake+json"
SINGLE_NAME = {
    "description": "statement.txt",
    "docs": "material.md",
    "code": "material.txt",
    "service": "material.json",
}
ADDRESS_VIAS = ("repo_url", "doc_url", "service_url")


class Tools(Protocol):
    """宿主一侧的工具（适配器的工具端点）。返回工具的结果；`ok: False` 表示被拒。"""

    def call(self, name: str, args: Mapping[str, Any]) -> dict[str, Any]: ...


@dataclass
class Outcome:
    """一个会话的结局：delivered（已交付）| relay（没交付，检查点留着，下一个会话接着做）。"""

    status: str
    detail: str = ""
    delivery: Delivery | None = None
    result: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HostPrior:
    """预算先验的价格一栏换成宿主价目表里各档位模型的真实单价；每步的 token 上限仍取占位表（09 §5）。"""

    prices: Mapping[str, tuple[int, int]]

    def tokens(self, tier: str) -> dict[str, tuple[int, int]]:
        return budget.Placeholder().tokens(tier)

    def price(self) -> dict[str, tuple[int, int]]:
        base = budget.Placeholder().price()
        return {t: tuple(self.prices.get(t, base[t])) for t in base}  # type: ignore[misc]


def derive_intake(
    statement: str,
    materials_: list[Mapping[str, Any]],
    *,
    by: str,
    date: str,
) -> dict[str, Any]:
    """没有随题给出立项单时的缺省：每份材料一个上传来源，形态按媒体类型分（文本与 Markdown 是文档，其余当代码归档）；
    一份材料也没有，原话本身就是描述形态的来源。正式模式。要别的模式或地址类来源，就随题附一份立项单。"""
    sources: list[dict[str, Any]] = []
    for i, m in enumerate(materials_, 1):
        mt = str(m.get("media_type", "")).split(";")[0].strip().lower()
        form = "docs" if mt in ("text/plain", "text/markdown", "application/pdf", "text/html") else "code"
        sources.append({"no": i, "form": form, "via": "upload", "artifact": str(m["id"])})
    if not sources:
        sources.append({"no": 1, "form": "description", "via": "statement"})
    return {
        "v": 1,
        "mode": "formal",
        "statement": statement.strip()[:1000] or "（无原话）",
        "sources": sources,
        "requested_by": by,
        "date": date,
    }


def intake_errors(doc: Any, material_ids: set[str]) -> list[str]:
    """随题给出的立项单合不合用：Schema、来源编号不重复、上传与资料库来源指的材料确在这道题的材料里、
    地址类来源写了地址（仓库还要写提交或标签，不抓会漂的默认分支）。宿主与驱动程序用同一份规则。"""
    errs = schema.errors(doc, "intake")
    if errs:
        return [f"立项单不合 Schema：{e}" for e in errs[:8]]
    out: list[str] = []
    nos = [s["no"] for s in doc["sources"]]
    if len(set(nos)) != len(nos):
        out.append("来源编号有重复")
    for s in doc["sources"]:
        via = s["via"]
        if via in ("upload", "library"):
            if s.get("artifact") not in material_ids:
                out.append(f"来源 {s['no']}：材料 {s.get('artifact')!r} 不在这道题的材料里")
        elif via in ADDRESS_VIAS:
            url = str(s.get("url", ""))
            if not url.startswith("https://") and not url.startswith("http://"):
                out.append(f"来源 {s['no']}：地址类来源要写 http(s) 地址")
            if via == "repo_url" and not s.get("ref") and not url.endswith((".tar.gz", ".tgz", ".zip")):
                out.append(f"来源 {s['no']}：仓库地址要写提交哈希或标签（ref），不抓默认分支")
            if via == "service_url" and not str(s.get("probe_plan", "")).strip():
                out.append(f"来源 {s['no']}：服务地址要附探测计划（逐条 GET 路径）")
        elif via == "statement" and s["form"] != "description":
            out.append(f"来源 {s['no']}：只有描述形态的来源可以“就在原话里”")
    if doc["mode"] not in ("formal", "dry_run"):
        out.append(f"这一期做正式与试算两种模式，不做 {doc['mode']}")
    return out


def product_kind(name: str) -> str | None:
    """产物名 → 它的 Schema 名；报告与榜更新没有独立的 Schema（None：只查它是 JSON 对象）。"""
    if name == "candidates.json":
        return "candidates"
    if name.startswith("essence:") and not name.endswith(".v"):
        return "essence"
    if name.startswith("placement:"):
        return "placement"
    if name == "handoff.json":
        return "handoff"
    if name == "dry_run.json":
        return "dry-run"
    return None


def product_errors(name: str, obj: Any) -> list[str]:
    """`check` 工具登记一份产物之前的检查（08 §4.4 D5 的第一道）：是 JSON 对象，合它的 Schema。
    校验器的各项结论（K1–K8、V1–V12）写在产物自己的 `checks` 里，过不过由引擎标给 cz，不在这里拦。"""
    if not isinstance(obj, dict):
        return ["产物须是 JSON 对象"]
    kind = product_kind(name)
    if kind is None:
        return []
    return schema.errors(obj, kind)[:8]


def _clip(items: list[str], n: int = NEEDS_MAX, chars: int = NEED_CHARS) -> list[str]:
    out = [str(x).strip()[:chars] for x in items if str(x).strip()]
    if len(out) > n:
        out = [*out[: n - 1], f"（另有 {len(out) - n + 1} 条，见报告）"]
    return out


class Session:
    """一个求解会话里的编排。`brief` 是宿主 `intake` 工具交回的简报。"""

    def __init__(
        self,
        workspace: Path,
        brief: Mapping[str, Any],
        dan: Dan,
        tools: Tools,
        *,
        closing: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        say: Callable[[str], None] = lambda s: None,
    ) -> None:
        self.ws, self.brief, self.tools = workspace, brief, tools
        self.closing, self.sleep, self.clock, self.say = closing, sleep, clock, say
        self.root = workspace / ANALYSIS
        self.root.mkdir(parents=True, exist_ok=True)
        self.dan: Dan = Memo(dan, self.root / "calls.jsonl")
        self.evidence: dict[str, str] = {}  # 来源编号 → 支撑“这份材料就是它”的 Artifact（材料本身，或抓取的执行留档）
        self._registered: dict[str, str] = self._load("registered.json") or {}

    # ------------------------------------------------------------ 小工具

    def _load(self, name: str) -> Any:
        p = self.root / name
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        except ValueError:
            return None

    def _intake(self) -> dict[str, Any]:
        stored = self._load("intake.json")  # 立过项就以当时存下的为准：之后的会话看到的来源与第一次相同
        if isinstance(stored, dict):
            return stored
        doc = self.brief.get("intake")
        if not isinstance(doc, dict):
            raise EngineError("这道题没有可用的立项单：" + "；".join(self.brief.get("intake_errors") or ["缺立项单"]))
        return doc

    def artifact_id(self, name: str, sha: str) -> str:
        """交付里的产物对照表：每份产物经 `check` 登记成 Artifact，表里写内核给的编号。"""
        if sha in self._registered:
            return self._registered[sha]
        r = self.tools.call("check", {"name": name, "path": f"{ANALYSIS}/artifacts/{sha}.json"})
        if r.get("ok") is False or not r.get("artifact"):
            raise EngineError(f"产物 {name} 没有登记成：{r.get('detail') or r.get('errors') or r}")
        self._registered[sha] = str(r["artifact"])
        (self.root / "registered.json").write_text(
            json.dumps(self._registered, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        return self._registered[sha]

    # ------------------------------------------------------------ 材料定版

    def materialize(self, intake: Mapping[str, Any]) -> tuple[dict[str, Path], list[str], list[str]]:
        """把立项单里的来源定版成快照目录。返回 (材料表, 做不下去的原因, 在等人批的地址)。
        命中拒收表的来源不碰（不解包、不抓取）：引擎立项时会把它记进拒收清单。"""
        out: dict[str, Path] = {}
        problems: list[str] = []
        waiting: list[str] = []
        given: Mapping[str, Any] = self.brief.get("materials") or {}
        for s in intake["sources"]:
            no, form, via = int(s["no"]), str(s["form"]), str(s["via"])
            key = str(s.get("artifact") or f"source:{no}")
            dest = self.ws / MATERIALS / f"s{no}"
            if survey.refusal(s, None):
                continue
            try:
                if via in ("upload", "library"):
                    m = given.get(str(s.get("artifact")))
                    if m is None or not m.get("path"):
                        why = (m or {}).get("error") or "不在这道题的材料里"
                        problems.append(f"来源 {no}：材料 {s.get('artifact')} {why}")
                        continue
                    materials.unpack(self.ws / str(m["path"]), dest, single_name=SINGLE_NAME[form])
                    self.evidence[str(no)] = str(s["artifact"])
                elif via == "statement":
                    dest.mkdir(parents=True, exist_ok=True)
                    # 原话逐字（简报里那份，即开题登记的原文）；立项单里的 statement 栏有长度上限，只作标题用
                    said = str(self.brief.get("statement") or intake["statement"])
                    (dest / "statement.txt").write_text(said, encoding="utf-8")
                    if self.brief.get("statement_ref"):
                        self.evidence[str(no)] = str(self.brief["statement_ref"])
                else:
                    state, detail = self._fetch(no, form, dest)
                    if state == "pending":
                        waiting.append(detail)
                        continue
                    if state != "ok":
                        problems.append(f"来源 {no}：{detail}")
                        continue
            except materials.BadMaterial as e:
                problems.append(f"来源 {no}：{e}")
                continue
            missing = _missing(form, dest)
            if missing:
                problems.append(f"来源 {no}：{missing}")
                continue
            out[key] = dest
        return out, problems, waiting

    def _fetch(self, no: int, form: str, dest: Path) -> tuple[str, str]:
        """地址类来源：`fetch` 工具在沙箱里按固定命令抓。没有授权时它发出扩权申请并交回 pending；在这里等人批
        （每隔几秒问一次，至多等 access_wait_s），等不到就让调用方交付“受阻”。抓过的不再抓。"""
        note = self.root / f"fetched.s{no}.json"
        done = self._load(note.name)
        if isinstance(done, dict) and dest.is_dir() and done.get("artifact"):
            self.evidence[str(no)] = str(done["artifact"])
            return "ok", ""
        wait_s = 0.0 if self.closing else float(self.brief.get("access_wait_s", 600))
        poll_s = float(self.brief.get("access_poll_s", 5))
        t0 = self.clock()
        said = False
        while True:
            r = self.tools.call("fetch", {"source": no})
            st = r.get("status")
            if st == "fetched":
                break
            if st == "pending":
                targets = "、".join(r.get("targets") or [])
                if not said:
                    self.say(f"来源 {no} 需要访问 {targets}，已发出访问申请，等待批准")
                    said = True
                if self.clock() - t0 >= wait_s:
                    return "pending", targets
                self.sleep(poll_s)
                continue
            if st == "denied":
                return "denied", f"访问申请被拒绝（{'、'.join(r.get('targets') or [])}）：{r.get('detail', '')}"[:300]
            return "failed", f"没有抓到：{r.get('detail') or r.get('code') or '原因不明'}"[:300]
        if r.get("dir"):
            src = self.ws / str(r["dir"])
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            for name in ("plan.json", "responses.json"):  # 行为形态：只认这两份 JSON，别的不拷
                f = src / name
                if f.is_file() and f.stat().st_size <= materials.Limits().file_bytes:
                    json.loads(f.read_text(encoding="utf-8"))  # 不是 JSON 就当没抓到
                    (dest / name).write_bytes(f.read_bytes())
        else:
            materials.unpack(self.ws / str(r["path"]), dest, single_name=SINGLE_NAME[form])
        if r.get("artifact"):
            self.evidence[str(no)] = str(r["artifact"])
        note.write_text(json.dumps({"artifact": r.get("artifact"), "sha256": r.get("sha256")}) + "\n", encoding="utf-8")
        return "ok", ""

    # ------------------------------------------------------------ 一个会话

    def engine(self, intake: Mapping[str, Any], mats: Mapping[str, Path]) -> Engine:
        b = self.brief
        prices = {t: (int(v[0]), int(v[1])) for t, v in (b.get("prices") or {}).items()}
        cfg = Config(
            run=str(b["run"]),
            source_label=str(b.get("title") or "外部系统")[:40],
            date=str(intake["date"]),
            bang=list(b.get("bang") or []),
            pains=list(b.get("pains") or []),
            canaries=list(b.get("canaries") or []),
            prior=HostPrior(prices) if prices else budget.Placeholder(),
            budget_usd_milli=int((b.get("budget") or {}).get("usd_milli") or 0) or None,
            by=str(intake.get("requested_by") or b.get("by") or "cz"),
            locks=list(b.get("locks") or []),
            artifact_id=self.artifact_id,
        )
        return Engine(self.root, self.dan, mats, cfg)

    def run(self) -> Outcome:
        try:
            d = self._advance()
        except EngineError as e:
            d = Delivery(None, "blocked", f"这一步做不下去：{e}", {}, [str(e)], passed=False)
        except Unavailable as e:
            if int(self.brief.get("relays_left", 0)) > 0:
                return Outcome("relay", f"模型端点暂时调不通（{e}）；检查点留着，下一个会话接着做")
            msg = f"模型端点调不通（{e}）；检查点留着，恢复后追问一句“继续”即可接着做"
            d = Delivery(None, "blocked", msg, {}, [msg], passed=False)
        if d is None:
            return Outcome("relay", "这一轮没有新的交付")
        if d.stop == "budget:task" and int(self.brief.get("relays_left", 0)) > 0 and self._money_left():
            # 只是这个会话的预留用完，题的预算还有不少：不交付，下一个会话从检查点接着做
            return Outcome("relay", d.needs[0] if d.needs else "会话预留用完", d)
        if d.stop == "budget:task":  # 预留用完而题里也没剩多少：光说“继续”接不下去，要先追加预算
            d.needs = [*d.needs[:1], "这道题的预算已基本用完：追加预算后追问一句“继续”"]
        return self._deliver(d)

    def _money_left(self) -> bool:
        """题的预算是否还够再开一个会话（至少剩一成，且不少于 0.2 美元）。求解会话的预留通常就是题里剩下的全部，
        预留用完多半等于题的预算用完；那时接力只会空转，应当把已有的结果交给人，由人决定追加。"""
        fresh = self.tools.call("intake", {})
        b = fresh.get("budget") or {}
        total, spent = int(b.get("usd_milli") or 0), int(b.get("spent_usd_milli") or 0)
        return total - spent >= max(200, total // 10)

    def _advance(self) -> Delivery | None:
        if self.closing == "relay":
            return None  # 上一轮没交付就结束了：检查点已经在工作区，什么都不用做
        intake = self._intake()
        mats, problems, waiting = self.materialize(intake)
        started = (self.root / "run.json").exists()
        if waiting and not problems and self.closing is None:
            msg = f"还没有获准访问 {'、'.join(waiting)}：请在权限申请卡上批准或拒绝，然后追问一句“继续”"
            return Delivery(None, "blocked", "分析还没有开始：" + msg, {}, [msg], passed=False)
        if problems or waiting:
            if self.closing is not None:
                return None
            rows = [*problems, *([f"等待访问 {'、'.join(waiting)}"] if waiting else [])]
            needs = _clip([*rows, "补齐后追问一句“继续”"])
            return Delivery(None, "blocked", "材料没有备齐：" + "；".join(rows), {}, needs, passed=False)
        eng = self.engine(intake, mats)
        total = int((self.brief.get("budget") or {}).get("usd_milli") or 0)
        if started:
            eng.set_budget(total)
        step = eng.state.get("step")
        if self.closing == "budget":
            return eng.pause("soft_line") if started and step not in STILL else None
        if not started:
            self.say("立项，开始读材料")
            seen = max((int(f["seq"]) for f in self.brief.get("follow_ups") or []), default=0)
            first = eng.start(intake)
            eng.note(follow_up_seen=seen)
            return first
        seen = int(eng.x.get("follow_up_seen", 0))
        pending = sorted(
            (f for f in self.brief.get("follow_ups") or [] if int(f["seq"]) > seen), key=lambda f: int(f["seq"])
        )
        d: Delivery | None = None
        ignored: list[str] = []
        for f in pending:
            step = eng.state.get("step")
            if step in ("G1", "G2", "G3"):
                self.say(f"收到第 {step[1]} 次确认的决定，继续")
                d = eng.follow_up(str(f["text"]), follow_up_seq=int(f["seq"]))
            elif decision_like(str(f["text"])):
                where = STEP_ZH.get(str(step), str(step))
                ignored.append(f"追问 {f['seq']} 里带着决定块，但现在不在确认点上（{where}），没有采用")
            eng.note(follow_up_seen=int(f["seq"]))
        if d is None:
            if eng.state.get("step") in ("done", "failed"):
                d = final(eng)
            else:  # 接力、追加预算后的“继续”，或上一个会话走到闸点却没来得及交付：从检查点接着做
                self.say("从检查点接着做")
                d = eng.resume()
        if d is not None and ignored:
            d.needs = [*ignored, *d.needs]
        return d

    def _deliver(self, d: Delivery) -> Outcome:
        answer = self.root / "answer.md"
        answer.write_text(d.answer, encoding="utf-8")
        ids = sorted({self.artifact_id(n, s) for n, s in d.artifacts.items()})
        args: dict[str, Any] = {
            "outcome": d.outcome,
            "answer_path": f"{ANALYSIS}/answer.md",
            "needs": _clip(d.needs),
            "claims": self.claims(),
            "artifacts": ids,
        }
        if d.outcome != "blocked" and not d.answer.strip():
            args["outcome"] = "blocked"
        if args["outcome"] == "blocked" and not args["needs"]:
            args["needs"] = ["见报告"]
        r = self.tools.call("deliver", args)
        if r.get("ok") is False:
            raise EngineError(f"交付被拒：{r.get('code')} {r.get('detail')}")
        return Outcome("delivered", d.outcome, d, r)

    def claims(self) -> list[dict[str, Any]]:
        """交付里的主张：每个来源一条“分析依据的是这份定版材料”，引用材料本身（input）或抓取的执行留档（exec）。
        分析结论本身是设计提议，不是可由留档证明的事实，所以不写成主张；它们各带出处（观察 → 片段的 sha256）。"""
        run = self._load("run.json") or {}
        out = []
        for i, s in enumerate(self._sources(), 1):
            sha = run.get("artifacts", {}).get(f"snapshot:s{i}")
            snap = self._load(f"artifacts/{sha}.json") if sha else None
            ref = self.evidence.get(str(s["no"]))
            if not snap or not ref:
                continue
            ident = "，".join(f"{k}={str(v)[:16]}" for k, v in sorted(snap["identity"].items()))
            lic = snap["license"]
            text = (
                f"来源 {s['no']}（{data.FORM_ZH[snap['form']]}）按这份定版材料分析：{ident}；"
                f"许可证 {lic.get('spdx') or lic['status']}（{lic.get('detected', '')}）"
            )
            out.append({"text": text[:CLAIM_CHARS], "refs": [ref]})
        return out

    def _sources(self) -> list[dict[str, Any]]:
        intake = self._load("intake.json") or {}
        x = self._load("engine.json") or {}
        keep = set(x.get("sources", []))
        return [s for s in intake.get("sources", []) if s["no"] in keep]


STILL = ("G1", "G2", "G3", "done", "failed", "paused_budget", "halted")  # 停着等人的步
STEP_ZH = {
    "S3": "正在识别候选",
    "S4": "正在提炼要点",
    "S5": "正在做归位与实验设计",
    "S6": "正在出交接包",
    "paused_budget": "因预算暂停",
    "done": "已结束",
    "failed": "立项没有成",
}


def decision_like(text: str) -> bool:
    return "【决定" in text


def final(eng: Engine) -> Delivery:
    """运行已经结束后又来了追问：把最后一次的结果原样再交一次，说明这次分析已经收尾。"""
    arts = eng.state.get("artifacts", {})
    if eng.state.get("step") == "failed":
        msg = "这次分析立项没有成（来源都被拒收），没有可继续的步骤；换一份材料请新开一题"
        return Delivery(None, "blocked", msg, {}, [msg], passed=False)
    keep = {k: v for k, v in arts.items() if k in ("handoff.json", "report:S6", "dry_run.json", "bang_updates.json")}
    name = "report:S6" if "report:S6" in arts else None
    body = eng.get(name)["markdown"] if name else "这次分析已经结束。"
    note = "这次分析已经结束，下面是最后一次交付的内容；要重新分析请新开一题。\n\n"
    return eng.finish(Delivery(None, "answered", note + body, keep, ["这次分析已经结束；要重新分析请新开一题"]))


def _missing(form: str, dest: Path) -> str | None:
    """快照目录合不合这种形态的约定（survey.load_snapshot 之前先看，免得读到一半才报错）。"""
    if not dest.is_dir() or not any(p.is_file() for p in dest.rglob("*")):
        return "材料里没有可读的文件"
    if form == "description" and not (dest / "statement.txt").is_file():
        return "描述形态的材料要是一段文字（statement.txt）"
    if form == "service":
        for name in ("plan.json", "responses.json"):
            try:
                json.loads((dest / name).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return f"行为形态的材料要有 {name}（探测计划与逐条响应）"
    return None
