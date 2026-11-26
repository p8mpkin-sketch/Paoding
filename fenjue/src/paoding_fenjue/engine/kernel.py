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
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .. import shapes
from . import budget, data, materials, schema, survey
from .dan import Dan, Memo, Reply, ReplyDefect, Unavailable
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
ATTEMPTS_FILE = "attempts.json"  # 尝试台账：每个没走到交付的会话留一行（为什么没做成），下一个会话读它
REGISTER_RETRIES = 2  # 同一份产物登记被拒后，最多重产再登记这么多次（总共至多 3 次登记）
ATTEMPT_KIND_ZH = {"defect": "程序出错", "unavailable": "模型端点调不通", "refused": "产物登记被拒"}


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


class ProductRefused(EngineError):
    """一份产物重产重登记之后仍被拒：`history` 逐次写明期望什么、实际是什么、宿主怎么说。"""

    def __init__(self, name: str, history: list[dict[str, Any]]) -> None:
        last = history[-1]
        super().__init__(f"产物 {name} 没有登记成：{'；'.join(last['errors'])}")
        self.name, self.history = name, history


def describe_shape(obj: Any) -> str:
    if isinstance(obj, dict):
        return f"JSON 对象（键 {sorted(obj)[:12]}）"
    if isinstance(obj, list):
        return f"JSON 列表（{len(obj)} 项）"
    return f"{type(obj).__name__}"


def refusal_info(name: str, obj: Any, r: Mapping[str, Any]) -> dict[str, Any]:
    """宿主拒收一份产物的原因，整理成回喂用的机器可读形状：期望什么、实际拿到什么、宿主逐条怎么说。"""
    kind = product_kind(name)
    errs = [str(e) for e in (r.get("errors") or [])] or [str(r.get("detail") or r.get("code") or r)]
    return {
        "name": name,
        "code": r.get("code"),
        "expected": "JSON 对象" + (f"，合 {kind} Schema" if kind else ""),
        "got": describe_shape(obj),
        "errors": errs[:8],
    }


def reproduce_product(name: str, obj: Any, info: Mapping[str, Any]) -> dict[str, Any] | None:
    """按拒收原因重产一份。产物都是引擎按 Schema 造出来的（模型的输出先过 Schema 才成产物），没有哪一份由模型直接写，
    所以重产是确定性的：形状错（不是对象）就把原内容放进对象里；内容错（Schema、凭据）没有办法自动改，交还 None。"""
    if isinstance(obj, dict):
        return None
    key = "bang_updates" if name == "bang_updates.json" else "items"
    return {"v": 1, "name": name, key: obj}


class Feedback:
    """带着上几次尝试的失败原因调模型：台账里记着哪个单元没做成，那个单元的调用多带一栏 `prior_failures`。
    输入变了，调用备忘（Memo）就不会拿上一次的回答原样充数——这正是 trial-b-2 五次原样重来的缺口。
    只有带 `note` 的行才带：程序出错而错不在解析这个单元回答的代码里时，台账不留给模型看的话（`Session._defect`）。"""

    def __init__(self, inner: Dan, rows: Callable[[], list[dict[str, Any]]]) -> None:
        self.inner, self.rows = inner, rows

    def call(self, role: str, key: str, payload: Mapping[str, Any]) -> Reply:
        notes = [str(r["note"]) for r in self.rows() if r.get("note") and _unit_owns(str(r.get("unit") or ""), key)]
        if notes:
            payload = {**payload, "prior_failures": notes[-5:]}
        return self.inner.call(role, key, payload)


def _unit_owns(unit: str, key: str) -> bool:
    """台账里的单元（run.json 的 units）与调用键的对应：入位与提炼按“单元号:”开头，识别候选的键以 shihuo 开头，
    片段阅读（read:<火位>）按键里倒数第二段的火位认。别的火位的阅读、别的单元的调用输入都不变（备忘照常命中）。"""
    if unit.startswith(("ruwei:", "cuiyi:")):
        return key.startswith(unit + ":")
    if unit.startswith("read:"):  # 片段阅读：键是 read:<片段键>:<火位>:<次数>，片段键里也有冒号，所以从尾部数
        parts = key.split(":")
        return len(parts) >= 4 and parts[0] == "read" and parts[-2] == unit.partition(":")[2]
    return unit == "candidates" and key.startswith("shihuo:")


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
        self._repaired: dict[str, str] = self._load("repaired.json") or {}  # 被拒的原 sha → 重产登记的 sha
        self._eng: Engine | None = None
        doc = self._load(ATTEMPTS_FILE)
        self.attempts: list[dict[str, Any]] = list(doc["rows"]) if isinstance(doc, dict) else []
        self.attempt_no = max((int(r.get("attempt", 0)) for r in self.attempts), default=0) + 1  # 本会话是第几次

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
        """交付里的产物对照表：每份产物经 `check` 登记成 Artifact，表里写内核给的编号。

        被拒不立刻放弃：把拒收原因整理成“期望什么、实际什么”，能重产就重产再登记（最多 REGISTER_RETRIES 次）；
        还是不行才报 ProductRefused，交付里写明重试了几次、每次错在哪。"""
        if sha in self._registered:
            return self._registered[sha]
        history: list[dict[str, Any]] = []
        cur = sha
        for tries in range(REGISTER_RETRIES + 1):
            r = self.tools.call("check", {"name": name, "path": f"{ANALYSIS}/artifacts/{cur}.json"})
            if r.get("ok") is not False and r.get("artifact"):
                self._registered[sha] = self._registered[cur] = str(r["artifact"])
                (self.root / "registered.json").write_text(
                    json.dumps(self._registered, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
                )
                if cur != sha:
                    self._repaired[sha] = cur
                    (self.root / "repaired.json").write_text(
                        json.dumps(self._repaired, indent=1, sort_keys=True) + "\n", encoding="utf-8"
                    )
                if history:
                    self.say(f"产物 {name} 第 {tries + 1} 次登记通过（前 {tries} 次被拒，已按原因重产）")
                return self._registered[sha]
            info = refusal_info(name, self._load(f"artifacts/{cur}.json"), r)
            history.append(info)
            if tries == REGISTER_RETRIES:
                break
            fixed = reproduce_product(name, self._load(f"artifacts/{cur}.json"), info)
            if fixed is None:
                info["reproduce"] = "这类错误没有自动重产的办法"
                break
            cur = self._write_product(name, fixed)
            info["reproduce"] = f"已重产为 {cur[:12]}，再登记"
        self._note_attempt(
            "refused", unit=None, reason=f"产物 {name} 登记被拒 {len(history)} 次：{history[-1]['errors'][0]}"
        )
        raise ProductRefused(name, history)

    def final_of(self, name: str, sha: str) -> tuple[str, str | None]:
        """交付里的产物表：sha256 必须是那个 Artifact 编号实际登记的内容。重产过的给新的，并附一行说明。"""
        new = self._repaired.get(sha)
        if new is None:
            return sha, None
        return new, f"{name}：原 {sha[:12]} 被拒，已按原因重产（{new[:12]}）"

    def _write_product(self, name: str, obj: Any) -> str:
        """重产的产物落盘（与引擎自己存产物的格式相同），并让引擎的检查点改认它。"""
        sha = shapes.digest(obj)
        path = self.root / "artifacts" / f"{sha}.json"
        if not path.exists():
            path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if self._eng is not None:
            self._eng.adopt(name, sha)
        return sha

    # ------------------------------------------------------------ 尝试台账（没走到交付的会话为什么没做成）

    def _note_attempt(self, kind: str, *, unit: str | None, reason: str, note: str | None = None) -> None:
        run = self._load("run.json") or {}
        self.attempts.append(
            {
                "attempt": self.attempt_no,
                "kind": kind,
                "step": run.get("step"),
                "unit": unit,
                "reason": reason[:400],
                **({"note": note[:500]} if note else {}),
            }
        )
        (self.root / ATTEMPTS_FILE).write_text(
            json.dumps({"v": 1, "rows": self.attempts}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )

    def _log_defect(self) -> None:
        """缺陷的调用栈：只给排错用，写在工作区的 defects.log，不进台账里给模型看的话，也不进交付。"""
        with (self.root / "defects.log").open("a", encoding="utf-8") as f:
            f.write(f"=== 第 {self.attempt_no} 次尝试 ===\n{traceback.format_exc()}\n")

    def _doing_unit(self) -> str | None:
        """出事时正在做的单元（run.json 里停在 doing 的那个）。"""
        run = self._load("run.json") or {}
        return next((u["id"] for u in run.get("units", []) if u.get("state") == "doing"), None)

    def _give_up(
        self, kind: str, why: str, *, unit: str | None = None, note: str | None = None, hopeless: bool = False
    ) -> Delivery | Outcome:
        """这个会话没法往下做。还有接力次数：记台账、留检查点，下一个会话带着原因接着做；
        次数用完了：交一份 blocked，写明共试了几次、各败在哪里——不无声地停。
        `hopeless`：再接力也是原样重演（同一处同样的程序错误已经出过），有次数也不再试，当场交 blocked。"""
        self._note_attempt(kind, unit=unit, reason=why, note=note)
        if not hopeless and int(self.brief.get("relays_left", 0)) > 0:
            return Outcome("relay", f"{why}；检查点留着，下一个会话{'带着原因' if note else ''}接着做")
        rows = self.attempts
        lines = [
            f"第 {r['attempt']} 次：{ATTEMPT_KIND_ZH.get(str(r['kind']), r['kind'])}"
            f"{'（' + str(r['unit']) + '）' if r.get('unit') else ''}：{r['reason']}"
            for r in rows
        ]
        tries = len({r["attempt"] for r in rows})
        how = "同一处出了同样的程序错误，再试也是原样重演，不再接着试" if hopeless else "次数用完仍没做成"
        head = f"共尝试 {tries} 次，{how}：{why}；检查点留着，修好之后追问一句“继续”即可接着做"
        needs = _clip([head, *lines])
        return Delivery(None, "blocked", head + "\n\n" + "\n".join(f"- {x}" for x in lines), {}, needs, passed=False)

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
            artifact_final=self.final_of,
            statement=str(b.get("statement") or "") or None,
            question_led=_form_ver(b.get("form")) >= 2 and bool(b.get("question_led", True)),
            question_led_off="form" if _form_ver(b.get("form")) < 2 else "switch",
            own_urls=tuple(str(u) for u in ([b["own_repo"]] if b.get("own_repo") else [])),
            parallel=max(1, min(8, int(b.get("parallel") or 1))),
        )
        self._eng = Engine(self.root, Feedback(self.dan, lambda: self.attempts), mats, cfg)
        return self._eng

    def run(self) -> Outcome:
        try:
            d = self._advance()
        except ProductRefused as e:
            tries = [
                f"第 {i} 次：期望 {h['expected']}，实际 {h['got']}；宿主说：{'；'.join(h['errors'])}"
                f"{'；' + h['reproduce'] if h.get('reproduce') else ''}"
                for i, h in enumerate(e.history, 1)
            ]
            msg = f"这一步做不下去：{e}（登记 {len(e.history)} 次，重试 {len(e.history) - 1} 次）"
            d = Delivery(
                None, "blocked", msg + "\n\n" + "\n".join(f"- {t}" for t in tries), {}, [msg, *tries], passed=False
            )
        except EngineError as e:
            d = Delivery(None, "blocked", f"这一步做不下去：{e}", {}, [str(e)], passed=False)
        except Unavailable as e:
            g = self._give_up("unavailable", f"模型端点暂时调不通（{e}）", unit=self._doing_unit())
            if isinstance(g, Outcome):
                return g
            d = g
        except Exception as e:  # noqa: BLE001  引擎自己的缺陷：不能让会话崩掉（崩了就是原样重跑、最后无声地停）
            self._log_defect()
            g = self._defect(e)
            if isinstance(g, Outcome):
                return g
            d = g
        if d is None:
            return Outcome("relay", "这一轮没有新的交付")
        if d.stop == "budget:task" and int(self.brief.get("relays_left", 0)) > 0 and self._money_left():
            # 只是这个会话的预留用完，题的预算还有不少：不交付，下一个会话从检查点接着做
            return Outcome("relay", d.needs[0] if d.needs else "会话预留用完", d)
        if d.stop == "budget:task":  # 预留用完而题里也没剩多少：光说“继续”接不下去，要先追加预算
            d.needs = [*d.needs[:1], "这道题的预算已基本用完：追加预算后追问一句“继续”"]
        try:
            return self._deliver(d)
        except ProductRefused as e:  # 交付表里的产物登记不上：照样交一份写明原因的 blocked
            return self._deliver(
                Delivery(
                    None,
                    "blocked",
                    f"这一步做不下去：{e}",
                    {},
                    [str(e), *[x for h in e.history for x in h["errors"]]],
                    passed=False,
                )
            )

    def _defect(self, e: Exception) -> Delivery | Outcome:
        """程序出错之后怎么办，先分清错出在哪里（dan.reading 圈出的是“解析这一步模型回答”的代码）：

        - 出在解析这一步回答的代码里（`ReplyDefect`）：多半是回答的形状出乎意料。台账里给这个单元记一句给模型看的话，
          下一个会话带着它重问——输入变了，备忘不会拿旧回答充数；
        - 出在别处（读上一步的产物、算难度、写报告……）：与这一步的回答无关。不给模型留话、不重问（备忘照常命中，
          不多花一次调用），也不把责任记在这个单元的回答上。接力一次以防偶发；同一处同样的错第二次出现就不再试。"""
        unit = self._doing_unit()
        where = unit or (self._load("run.json") or {}).get("step") or "启动"
        if isinstance(e, ReplyDefect):
            what = str(e)
            return self._give_up(
                "defect",
                f"{where} 处理模型的回答（{e.key}）时程序出错：{what}",
                unit=unit,
                note=f"上一次会话在 {unit or '这一步'} 处理你的输出时程序报错（{what[:200]}）。"
                "多半是输出的形状不对：检查应是对象的字段有没有写成字符串、应是列表的有没有写成单个值，按输出形状重写。",
            )
        what = f"{type(e).__name__}: {e}"
        why = (
            f"{where} 处理时程序出错：{what[:240]}"
            "（出错的地方不在解析这一步模型回答的代码里：是程序自己的缺陷，或上一步的产物有问题；没有让模型重写）"
        )
        again = any(r["kind"] == "defect" and r.get("unit") == unit and r["reason"] == why[:400] for r in self.attempts)
        return self._give_up("defect", why, unit=unit, hopeless=again)

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
        # 快照按外部来源的次序编号（s1、s2…）；我们自己那份对照材料不在其中，它不是被分析的来源
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


def _form_ver(ref: Any) -> int:
    """会话形态的版本号（`h1.tunshi@2` → 2）。按题读的提示词从第 2 版才有：锁在第 1 版上的在途题照旧走通用勘察。
    简报里没有形态（直接驱动引擎的测试与脚本）按当前版本算。"""
    _, _, ver = str(ref or "").partition("@")
    return int(ver) if ver.isdigit() else 2


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
