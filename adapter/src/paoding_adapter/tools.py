"""代理工具（§3.4.2）：exec 转执行层，submit 转图服务，show 读图服务；运行时扩权开着时另有 request_access
（docs/design/runtime-grants/ §6）转图服务的 request_scope。Worker 对外的全部通道。

一个 ToolHost 对应一个会话（= 一个任务 = 一个租约）。它持有该会话的令牌，模型看不见令牌，
只看见工具。这里不做规划、不做重试策略、不解释领域内容（3.4.6）。

Op 到内核操作的翻译：
- `*_path`：工作区里的文件，读出后登记为 authored 类，再把 ArtifactId 填进 body_ref / spec_ref。
  路径须落在工作区内，解析符号链接后越界即拒（schema_error）。
- `claim_done`：不是内核操作。登记候选（authored），再提交 request_judge，判官取登记判据时的那一个。
  候选可以是工作区里的文件（candidate_path），也可以直接是答案字符串（candidate）；两样都给时以文件为准。
- `tmp_id`：本次 submit 内，后一条可用前一条的 tmp_id 指代它的 id。
- 同一操作连续被拒 3 次后不再转发（3.4.4），直接返回上次的拒绝码。
- `deliver`（开放道的求解会话，docs/design/open-lane/ §3.4）：答案是文字或工作区文件，登记为 authored，
  再提交内核的 deliver；主张与自检的依据只填执行留档或材料的编号，内核逐个查真伪。

工具入参是模型写的、未经校验的 JSON：只经解析层的 `Obj` 读，形状不对抛 `BadBody`，`call` 与 `_one`
只接这一种异常并转成 `schema_error`。其余异常（KeyError、TypeError 等）是本组件或下游的缺陷，原样抛出，
由会话层按任务失败处理，不说成是模型的输入错误。
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from paoding_executor.contract import ExecPort
from paoding_fenjue.contract import View, current
from paoding_graph.contract import (
    BadBody,
    BlobPort,
    GraphPort,
    GraphReader,
    JCSError,
    Obj,
    canonicalize,
    node_levels,
)

from . import creds

MAX_SAME_REJECT = 3
KB_SEARCH_MAX = 40  # 每个会话至多检索 40 次、读 200 段（资料库设计“执行中检索”：检索不花钱，但占上下文）
KB_READ_MAX = 200
KB_K_MAX = 20
SHOW_RANGE_MAX = 8 * 1024
LATER_OPS = {"escalate_intent": "M1", "add_support": "完整版", "add_contradiction": "完整版"}
FINAL_OUTCOMES = ("found", "nothing", "failed", "unsolved")


@dataclass
class Session:
    """一个会话的身份与边界。token 是图服务签给该租约的会话令牌，只在容器外。"""

    pid: str
    lease_id: str
    role: str  # bootstrap | reason | explore | solve
    token: str
    workspace: Path
    tools: tuple[Any, ...] = ("exec", "submit", "show")
    sandbox_id: str | None = None  # 执行容器；reason 不起执行容器（§3.4.2）
    calls: list[Any] = field(default_factory=list)  # 会话记录：每次工具调用的入参与结果
    final: dict[str, Any] | None = None
    submitted: bool = False
    delivered: str | None = None  # 开放道：最近一次交付的 outcome（answered | partial | blocked）
    reviewed: bool = False  # 开放道的复核会话：读数已交回（体质修炼 002）
    secrets: tuple[str, ...] = ()  # 原话里认出的凭据（creds.found）：扩权申请与交付写出去之前逐字遮盖
    kb_cite: str = "grounds"  # 会话形态（功法 H1）：资料段落能进交付的 refs（refs），还是只能拿来找方向（grounds）
    tool_order: tuple[str, ...] | None = None  # 工具面的顺序（功法 H3），取自这道题开题时的那一版功法（FJ6）


class KnowledgePort(Protocol):
    """会话查资料的端口（资料库第二期）。实现方是组装根里的书库一角（scripts/knowledge_hub.py），本组件不 import 书库。

    范围由任务的 prefs.knowledge 决定，端口自己读；会话只给题号与租约。查询词进来之前已遮盖凭据。"""

    def available(self, pid: str) -> bool:
        """这个任务现在有没有可查的资料（知识选项为“不用”或范围里没有可检索的资料：False，不挂工具）。"""
        ...

    def search(self, pid: str, lease: str, query: str, k: int) -> dict[str, Any]:
        """{hits: [{chunk, source_name, locator, snippet, score}], via}；同时记一条 kb_query。"""
        ...

    def read(self, pid: str, lease: str, chunk: str) -> dict[str, Any]:
        """{artifact, text, source_name, locator, revision}：段落登记为本题的 knowledge 类；
        不在范围里或不存在：{ok: False, code, detail}。"""
        ...


def _mask_deep(x: Any, secrets: tuple[str, ...]) -> tuple[Any, bool]:
    """把结构里每一段文字的凭据遮掉（交付的主张、自检、未验证项、需要人提供的）。"""
    if not secrets:
        return x, False
    if isinstance(x, str):
        return creds.mask(x, secrets)
    if isinstance(x, list):
        pairs = [_mask_deep(y, secrets) for y in x]
        return [p[0] for p in pairs], any(p[1] for p in pairs)
    if isinstance(x, dict):
        kv = {k: _mask_deep(v, secrets) for k, v in x.items()}
        return {k: v[0] for k, v in kv.items()}, any(v[1] for v in kv.values())
    return x, False


def _err(code: str, detail: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "detail": detail}


class ToolHost:
    def __init__(
        self,
        s: Session,
        graph: GraphPort,
        reader: GraphReader,
        blobs: BlobPort,
        executor: ExecPort | None = None,
        access: Callable[[], Any] | None = None,
        knowledge: KnowledgePort | None = None,
    ):
        """access：把本会话在跑的沙箱对齐到当前授权范围（会话运行器的 reconcile），request_access 批下来时调用。
        knowledge：查资料的端口；会话有 kb_search / kb_read 工具时才用。"""
        self.s, self.graph, self.reader, self.blobs, self.executor = s, graph, reader, blobs, executor
        self.access, self.knowledge = access, knowledge
        self._kb = {"search": 0, "read": 0}
        self._asked: dict[str, str] = {}  # 本会话提过的扩权申请 → 上次告诉模型的状态
        self._n = 0
        self._nonce = secrets.token_hex(4)  # 幂等键带宿主实例号：同一租约换了宿主也不会撞上旧结果
        self._rejects: dict[str, tuple[int, dict[str, Any]]] = {}

    # ---------- 入口 ----------

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self._n += 1
        if name not in self.s.tools:
            out = _err("forbidden_op", f"本会话没有工具 {name}")
        else:
            try:
                out = self._TOOLS[name](self, Obj(args if isinstance(args, dict) else {}, "args"))
            except BadBody as e:
                out = _err("schema_error", str(e))
        self.s.calls.append({"n": self._n, "tool": name, "args": args, "result": out})
        return out

    # ---------- exec ----------

    def _exec(self, a: Obj) -> dict[str, Any]:
        if self.executor is None or self.s.sandbox_id is None:
            return _err("forbidden_op", "本会话没有执行容器")
        cmd = a.string("cmd")
        if not cmd:
            raise BadBody("cmd 须为非空字符串")
        news = self._access_news()  # 先对齐：刚批下来的地址这条命令就能用
        r = self.executor.exec(
            self.s.sandbox_id,
            cmd,
            self.s.pid,
            f"exec:{self.s.lease_id}:{self._nonce}:{self._n}",
            timeout_s=a.integer("timeout_s", 60),
            cwd=a.text("cwd", "/workspace"),
        )
        out: dict[str, Any] = {
            "artifact": r.artifact,
            "exit_code": r.exit_code,
            "output": r.output,
            "truncated": r.truncated,
        }
        if news:
            out["access"] = news
        return out

    # ---------- request_access（运行时扩权，docs/design/runtime-grants/ §6） ----------

    def _request_access(self, a: Obj) -> dict[str, Any]:
        """申请访问一个 host:port。申请不是授权：图服务查风险表定风险，练习道白名单内的当场自动批，
        其余进人的待办。批下来的规则由会话运行器热加进在跑的沙箱，返回时闸门已就绪。"""
        extra = a.keys() - {"target", "why"}
        if extra:  # 风险、动作都不由申请方给：风险查表，动作只有 connect
            raise BadBody(f"request_access 只收 target 与 why，多了 {sorted(extra)}")
        target, why = a.string("target").strip(), a.text("why").strip()
        if not why:
            raise BadBody("why 须写明为什么需要这个地址")
        if creds.mask(target, self.s.secrets)[1]:
            raise BadBody("target 里带着原话里的凭据：地址只写 host:port，凭据只在执行的命令里用")
        why, masked = creds.mask(why, self.s.secrets)  # 扩权卡给人看、进事件账：凭据不上卡
        rule = {"resource": "net", "pattern": target, "actions": ["connect"]}
        st = self.reader.state
        if any(_same(r, rule) for r in st["problems"][self.s.pid]["scope"] if "revoked" not in r):
            return self._granted(None, target)
        out = self.graph.submit(
            self.s.token,
            self.s.pid,
            f"access:{self.s.lease_id}:{self._nonce}:{self._n}",
            [{"op": "request_scope", "body": {"rules": [rule], "why": why}}],
        )
        r = out["results"][0]
        if not r.get("ok"):
            if r.get("code") == "forbidden_op":
                return {"status": "denied", "target": target, "detail": r.get("detail", "")}
            return _err(r.get("code", "schema_error"), r.get("detail", ""))
        rid = r["id"]
        req = self.reader.state.get("scope_requests", {})[rid]
        if req["status"] == "granted":  # 练习道白名单：同一批里已自动批准
            return self._granted(rid, target)
        self._asked[rid] = req["status"]
        out = {
            "status": "pending",
            "request": rid,
            "target": target,
            "detail": "已进人的待办。可以先做不需要这个地址的事；批下来后 exec 的返回里会带 access 告诉你。",
        }
        if masked:
            out["masked"] = "理由里有原话里的凭据，已遮盖后再送审；以后不要把凭据写进理由"
        return out

    def _granted(self, rid: str | None, target: str) -> dict[str, Any]:
        if rid:
            self._asked[rid] = "granted"
        ready = self.access() if self.access else None
        rule = next(
            r
            for r in reversed(self.reader.state["problems"][self.s.pid]["scope"])
            if r["pattern"] == target and "revoked" not in r
        )
        out: dict[str, Any] = {"status": "granted", "target": target, "risk": rule["risk"]}
        if rid:
            out["request"] = rid
        if not self.s.sandbox_id:
            out["detail"] = "已批准；本会话没有执行容器，之后的任务起沙箱时带上它"
        elif not self._compiled(target):
            out["detail"] = "已批准，但它的风险高于本任务的风险上限，本任务的沙箱里不开"
        elif ready is None:
            out["detail"] = "已批准；本执行器不支持热加，下一个任务起沙箱时生效"
        return out

    def _compiled(self, target: str) -> bool:
        lease = self.reader.state["leases"].get(self.s.lease_id)
        iid = lease.get("target") if lease else None
        ceiling = (
            self.reader.state["intents"][iid]["risk"]
            if iid and iid in self.reader.state["intents"]
            else solve_ceiling(lease)
        )
        rank = {"r0": 0, "r1": 1, "r2": 2}
        return any(
            r["pattern"] == target and "revoked" not in r and rank[r["risk"]] <= rank[ceiling]
            for r in self.reader.state["problems"][self.s.pid]["scope"]
        )

    def _access_news(self) -> list[dict[str, Any]]:
        """本会话提过的申请里，状态有变化的（人批了或拒了）。"""
        reqs = self.reader.state.get("scope_requests", {})
        news = []
        for rid, told in list(self._asked.items()):
            x = reqs.get(rid)
            if x is None or x["status"] == told:
                continue
            self._asked[rid] = x["status"]
            item: dict[str, Any] = {"request": rid, "status": x["status"], "target": x["rules"][0]["pattern"]}
            if x.get("reason"):
                item["reason"] = x["reason"]
            news.append(item)
        if any(n["status"] == "granted" for n in news) and self.access:
            self.access()
        return news

    # ---------- deliver（开放道） ----------

    def _deliver(self, a: Obj) -> dict[str, Any]:
        """交付（open-lane §3.4）。答案：answer（文字）或 answer_path（工作区文件），登记为 authored。
        其余字段原样交内核校验：依据不存在、类别不可采信、受阻却不写 needs，都由内核拒绝并说明。"""
        allowed = {"outcome", "answer", "answer_path", "claims", "self_check", "unverified", "needs"}
        extra = a.keys() - allowed
        if extra:
            raise BadBody(f"deliver 只收 {sorted(allowed)}，多了 {sorted(extra)}")
        keys = ("outcome", "claims", "self_check", "unverified", "needs")
        body: dict[str, Any] = {k: a.get(k) for k in keys if k in a}
        body, masked = _mask_deep(body, self.s.secrets)  # 交付进事件账、给人看：凭据不进交付（creds.py）
        ops: list[dict[str, Any]] = []
        data: bytes | None = None
        if a.get("answer_path") is not None:
            data = self._read_ws(a.string("answer_path"))
        elif a.get("answer") is not None:
            data = a.text("answer").encode("utf-8")
        if data is not None and self.s.secrets:
            text, hit = creds.mask(data.decode("utf-8", "replace"), self.s.secrets)
            if hit:
                data, masked = text.encode("utf-8"), True
        if data is not None:
            ops.append(
                {
                    "op": "register_artifact",
                    "body": {
                        "hash": self.blobs.put(data),
                        "size": len(data),
                        "media_type": "text/plain; charset=utf-8",
                        "class": "authored",
                    },
                }
            )
            body["answer"] = "$0"
        ops.append({"op": "deliver", "body": body})
        self.s.submitted = True
        out = self.graph.submit(self.s.token, self.s.pid, f"deliver:{self.s.lease_id}:{self._nonce}:{self._n}", ops)
        if not out["ok"]:
            r = next(r for r in out["results"] if not r.get("ok"))
            return _err(r.get("code", "schema_error"), r.get("detail", ""))
        self.s.delivered = str(a.get("outcome"))
        res: dict[str, Any] = {
            "ok": True,
            "id": out["results"][-1]["id"],
            "detail": "已交付。人会看到你的答案、证据和没验证的部分；本会话可以结束了。",
        }
        if data is not None:
            res["answer"] = out["results"][0]["id"]  # 答案的产物编号（authored：它不是证据，不能当主张的依据）
        if masked:
            res["masked"] = "交付里有原话里的凭据，已遮盖"
        return res

    # ---------- review（开放道的复核会话） ----------

    def _review(self, a: Obj) -> dict[str, Any]:
        """交回复核读数（open-lane §3.6，体质修炼 002）。对的是租约的目标那次交付，会话不用自己填；
        其余字段原样交内核校验：主张漏核或重复、依据不存在或类别不可采信、说重跑了却没附留档，都由内核拒绝并说明。"""
        allowed = {"claims", "reruns", "counterexamples", "summary"}
        extra = a.keys() - allowed
        if extra:
            raise BadBody(f"review 只收 {sorted(allowed)}，多了 {sorted(extra)}")
        lease: Mapping[str, Any] = self.reader.state["leases"].get(self.s.lease_id) or {}
        body: dict[str, Any] = {"delivery": lease.get("target"), **{k: a.get(k) for k in allowed if k in a}}
        body, masked = _mask_deep(body, self.s.secrets)
        self.s.submitted = True
        out = self.graph.submit(
            self.s.token,
            self.s.pid,
            f"review:{self.s.lease_id}:{self._nonce}:{self._n}",
            [{"op": "review", "body": body}],
        )
        if not out["ok"]:
            r = out["results"][0]
            return _err(r.get("code", "schema_error"), r.get("detail", ""))
        self.s.reviewed = True
        res: dict[str, Any] = {
            "ok": True,
            "id": out["results"][0]["id"],
            "detail": "读数已交回。人看结果时会看到它；本会话可以结束了。",
        }
        if masked:
            res["masked"] = "读数里有原话里的凭据，已遮盖"
        return res

    # ---------- kb_search / kb_read（资料库第二期） ----------

    def _kb_quota(self, what: str, cap: int) -> dict[str, Any] | None:
        if self.knowledge is None:
            return _err("forbidden_op", "本任务没有可查的资料")
        if self._kb[what] >= cap:
            return _err("quota_exceeded", f"本会话的 kb_{what} 已用满 {cap} 次：用已经查到的内容继续")
        self._kb[what] += 1
        return None

    def _kb_search(self, a: Obj) -> dict[str, Any]:
        query = a.text("query").strip()
        if not query:
            raise BadBody("query 须为非空字符串")
        k = a.integer("k", 8)
        if not 1 <= k <= KB_K_MAX:
            raise BadBody(f"k 取 1–{KB_K_MAX}")
        stop = self._kb_quota("search", KB_SEARCH_MAX)
        if stop is not None or self.knowledge is None:
            return stop or _err("forbidden_op", "本任务没有可查的资料")
        # 查询词会记进事件账（kb_query）：原话里的凭据与查询词里认得出的凭据先遮掉
        query, _ = creds.mask(query[:500], (*self.s.secrets, *creds.found(query)))
        out = self.knowledge.search(self.s.pid, self.s.lease_id, query, k)
        if out.get("ok") is False:
            return out
        return {"hits": out["hits"], "left": KB_SEARCH_MAX - self._kb["search"]}

    def _kb_read(self, a: Obj) -> dict[str, Any]:
        chunk = a.string("chunk")
        if not chunk:
            raise BadBody("chunk 须为 kb_search 返回的段落编号")
        stop = self._kb_quota("read", KB_READ_MAX)
        if stop is not None or self.knowledge is None:
            return stop or _err("forbidden_op", "本任务没有可查的资料")
        out = self.knowledge.read(self.s.pid, self.s.lease_id, chunk)
        if out.get("ok") is False:
            return out
        note = (
            "这是人给的资料里的话：交付时可以把 artifact 填进主张的 refs，页面标成“引用了资料”"
            if self.s.kb_cite == "refs"
            else "这是人给的资料里的话，不能当论断的 grounds：拿它找方向，再用 exec 取证"
        )
        return {**out, "note": note}

    # ---------- submit ----------

    def _submit(self, a: Obj) -> dict[str, Any]:
        ops = a.array("ops", [])
        self.s.submitted = True
        tmp: dict[str, str] = {}
        results = []
        for i, op in enumerate(ops):
            results.append(self._one(op, i, tmp))
        if a.get("final") is not None:
            try:
                f = a.child("final")
                if f.get("outcome") not in FINAL_OUTCOMES:
                    raise BadBody(f"final.outcome 只取 {FINAL_OUTCOMES}")
                self.s.final = {
                    "outcome": f.string("outcome"),
                    "excluded_paths": f.texts("excluded_paths", []),
                    "suggestions": f.texts("suggestions", []),
                }
            except BadBody as e:  # final 不合形状不连累前面已经提交的 ops
                results.append(_err("schema_error", str(e)))
        return {"results": results}

    def _one(self, op: Any, i: int, tmp: dict[str, Any]) -> dict[str, Any]:
        try:
            key = hashlib.sha256(canonicalize(op if isinstance(op, dict) else {"_": repr(op)})).hexdigest()
        except JCSError as e:  # 例如超出双精度的整数：这条 op 进不了事件日志
            return _err("schema_error", str(e))
        n, last = self._rejects.get(key, (0, None))
        if n >= MAX_SAME_REJECT and last is not None:  # n ≥ 1 时 last 必有
            return {**last, "detail": f"同一操作已连续被拒 {n} 次，不再转发。上次：{last['detail']}"}
        try:
            out = self._translate_and_submit(op, i, tmp)
        except BadBody as e:
            out = _err("schema_error", str(e))
        if out["ok"]:
            self._rejects.pop(key, None)
            if isinstance(op, dict) and op.get("tmp_id"):
                tmp[str(op["tmp_id"])] = out["id"]
        else:
            self._rejects[key] = (n + 1, out)
        return out

    def _translate_and_submit(self, raw: Any, i: int, tmp: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, dict) or not isinstance(raw.get("op"), str):
            raise BadBody("每条 op 须为带 op 字段的对象")
        op = Obj(raw, "op")
        kind = op.string("op")
        if kind in LATER_OPS:
            return _err("schema_error", f"{kind} 属于{LATER_OPS[kind]}，M0 未启用")

        def sub(v: Any) -> Any:  # 同一批里的 tmp_id 换成已登记的 id
            return tmp.get(v, v) if isinstance(v, str) else v

        def subl(vs: Any) -> list[Any]:
            return [sub(v) for v in (vs or [])]

        batch: list[dict[str, Any]] = []

        def authored(rel: str | None, inline: str | None = None) -> str:
            if inline is not None:
                data = inline.encode("utf-8")
            elif rel is not None:
                data = self._read_ws(rel)
            else:
                raise BadBody("既没有路径也没有内联内容")
            h = self.blobs.put(data)
            batch.append(
                {
                    "op": "register_artifact",
                    "body": {
                        "hash": h,
                        "size": len(data),
                        "media_type": "text/plain; charset=utf-8",
                        "class": "authored",
                    },
                }
            )
            return f"${len(batch) - 1}"

        if kind == "add_fact":
            body = {
                "title": op.req("title"),
                "summary": op.get("summary", ""),
                "claim_type": op.req("claim_type"),
                "premises": subl(op.array("premises", [])),
                "grounds": subl(op.array("grounds", [])),
            }
            if op.get("body_path"):
                body["body_ref"] = authored(op.string("body_path"))
            if op.get("check") is not None:
                c = op.child("check")
                check = {"judge_id": c.req("judge_id"), "expect": c.get("expect", {})}
                if c.get("spec_path"):
                    check["spec_ref"] = authored(c.string("spec_path"))
                if "inputs" in c:  # 规格缝隙，见 docs/m0/dissent-002-adapter.md
                    return _err("schema_error", "check.inputs 在 M0 内核的判据里没有对应字段，暂不接受")
                extra = c.keys() - {"judge_id", "expect", "spec_path", "control"}
                if extra:
                    raise BadBody(f"check 多余字段 {sorted(extra)}")
                if c.get("control") is not None:  # 对照判据（§3.3.3）：工作区文件登记为 authored，或直接给 ArtifactId
                    ctl = c.child("control")
                    if ctl.keys() - {"input_paths", "inputs"}:
                        raise BadBody("control 只有 input_paths 与 inputs")
                    paths = [authored(x) for x in ctl.strings("input_paths", [])]
                    check["control"] = {"inputs": paths + subl(ctl.array("inputs", []))}
                body["check"] = check
            batch.append({"op": "add_fact", "body": body})
        elif kind == "add_intent":
            body = {
                "title": op.req("title"),
                "summary": op.get("summary", ""),
                "premises": subl(op.array("premises", [])),
                "risk": op.req("risk"),
                "budget": op.get("budget_hint") or {"usd_milli": 500, "wall_s": 600},
            }
            for k in ("expected_gain", "needs_scope", "touches"):
                if op.get(k) is not None:
                    body[k] = op.get(k)
            for k in ("follows", "rollback"):
                if op.get(k) is not None:
                    body[k] = op.get(k)  # 交内核按里程碑拒绝，不在此替它判断
            if op.get("done") is not None:
                d = op.child("done")
                done = {
                    "judge_id": d.req("judge_id"),
                    "expect": d.get("expect", {}),
                    "max_attempts": d.integer("max_attempts", 2),
                }
                if d.get("spec_path"):
                    done["spec_ref"] = authored(d.string("spec_path"))
                for k in d.keys() - {"judge_id", "expect", "max_attempts", "spec_path"}:
                    done[k] = d.get(k)  # 例如 tests：交内核拒绝
                body["done"] = done
            batch.append({"op": "add_intent", "body": body})
        elif kind == "abandon_intent":
            batch.append(
                {"op": "abandon_intent", "body": {"intent": sub(op.req("intent")), "reason": op.req("reason")}}
            )
        elif kind == "claim_done":
            target = sub(op.string("target"))
            if "candidate_path" not in op and op.opt_string("candidate") is not None:
                cand = authored(None, op.string("candidate"))  # 答案字符串直接给（提示词的写法），同样登记为 authored
            else:
                cand = authored(op.string("candidate_path"))
            judge = self._registered_judge(target)
            if judge is None:
                return _err("unknown_ref", f"{target} 不是本题带判据的对象")
            batch.append({"op": "request_judge", "body": {"target": target, "judge_id": judge, "candidate": cand}})
        elif kind == "request_judge":
            target = sub(op.string("target"))
            judge = op.get("judge_id") or self._registered_judge(target)
            if judge is None:
                return _err("unknown_ref", f"{target} 不是本题带判据的对象")
            batch.append({"op": "request_judge", "body": {"target": target, "judge_id": judge}})
        else:
            return _err("schema_error", f"未知操作 {kind}")
        out = self.graph.submit(
            self.s.token, self.s.pid, f"submit:{self.s.lease_id}:{self._nonce}:{self._n}:{i}", batch
        )
        last = out["results"][-1] if out["ok"] else next(r for r in out["results"] if not r.get("ok"))
        if not out["ok"]:
            return _err(last.get("code", "schema_error"), last.get("detail", ""))
        return {"ok": True, "id": last["id"]}

    def _registered_judge(self, target: str) -> str | None:
        st = self.reader.state
        if target == "goal":
            p = st["problems"].get(self.s.pid)
            return p["goal"]["check"]["judge_id"] if p else None
        f = st["facts"].get(target)
        if f is not None and f["problem_id"] == self.s.pid and f.get("check"):
            return f["check"]["judge_id"]
        it = st["intents"].get(target)
        if it is not None and it["problem_id"] == self.s.pid and it.get("done"):
            return it["done"]["judge_id"]
        return None

    def _read_ws(self, rel: str) -> bytes:
        """工作区内的文件。解析符号链接后仍须落在工作区里（与 CLI 的 --restricted 同一条边界）。"""
        root = self.s.workspace.resolve()
        try:
            p = (root / rel).resolve()
            inside = p == root or root in p.parents
            is_file = inside and p.is_file()
        except (ValueError, OSError):  # 路径里有 NUL、过长、成环的符号链接
            raise BadBody(f"路径 {rel!r} 不合法") from None
        if not inside:
            raise BadBody(f"路径 {rel} 越出工作区")
        if not is_file:
            raise BadBody(f"工作区里没有文件 {rel}")
        return p.read_bytes()

    # ---------- show ----------

    def _show(self, a: Obj) -> dict[str, Any]:
        st, pid = self.reader.state, self.s.pid
        aid, nid = a.opt_string("artifact"), a.opt_string("id")
        if aid:
            art = st["artifacts"].get(aid)
            if art is None or art["problem_id"] != pid:
                return _err("unknown_ref", "没有这个 Artifact")
            if art["class"] == "judge" and any(
                str(t).startswith("vault:") for t in art.get("exec", {}).get("touched", [])
            ):
                return _err("forbidden_op", "读过保密库的判官输出不向会话开放")
            rng = a.array("range", [0, SHOW_RANGE_MAX]) or [0, SHOW_RANGE_MAX]
            if len(rng) != 2 or not all(isinstance(x, int) and not isinstance(x, bool) for x in rng):
                raise BadBody("range 须为两个整数 [起, 止]")
            lo = max(0, rng[0])
            hi = min(rng[1], lo + SHOW_RANGE_MAX)
            data = self.blobs.get(art["hash"], lo, hi)
            return {
                "artifact": aid,
                "range": [lo, lo + len(data)],
                "size": art["size"],
                "class": art["class"],
                "text": data.decode("utf-8", "replace"),
            }
        lv = node_levels(st, pid)
        if nid:
            node: Mapping[str, Any] | None = st["facts"].get(nid) or st["intents"].get(nid)
            if node is None or node["problem_id"] != pid:
                return _err("unknown_ref", f"本题没有 {nid}")
            keep = ("id", "title", "summary", "claim_type", "premises", "risk", "check", "done")
            out = {k: node[k] for k in keep if k in node}
            out["level"] = lv.get(nid)
            if a.get("layer") == "evidence":
                out["grounds"] = [
                    {"id": g, "class": st["artifacts"][g]["class"], "size": st["artifacts"][g]["size"]}
                    for g in node.get("grounds", [])
                ]
                if node.get("body_ref"):
                    out["body_ref"] = node["body_ref"]
            return out
        lst = a.string("list", "frontier")
        if lst not in ("frontier", "all", "hints", "budget"):
            raise BadBody("list 只取 frontier|all|hints|budget")
        if lst == "budget":
            return dict(self.reader.budget(pid))
        if lst == "hints":
            return {
                "hints": [
                    {"id": h["id"], "text": h["text"]}
                    for h in st["hints"].values()
                    if h["problem_id"] == pid and not h.get("closed")
                ]
            }
        nodes = [n for c in ("facts", "intents") for n in st[c].values() if n["problem_id"] == pid]
        nodes.sort(key=lambda n: int(n["id"][2:]))  # id 带 seq，按创建顺序
        items = [{"id": n["id"], "title": n["title"], "level": lv.get(n["id"])} for n in nodes]
        if lst == "frontier":
            items = [x for x in items if x["level"] not in ("E3", "X")]
        return {"list": lst, "items": items}

    _TOOLS = {
        "exec": _exec,
        "submit": _submit,
        "show": _show,
        "request_access": _request_access,
        "deliver": _deliver,
        "review": _review,
        "kb_search": _kb_search,
        "kb_read": _kb_read,
    }


def tool_schemas(tools: tuple[Any, ...], order: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """MCP tools/list 的条目。参数 Schema 由工具定义强制（3.4.4）。
    order：工具面的顺序；会话给的是它这道题锁定的那一版功法的 H3（FJ6），不给就用此刻的功法。"""
    s = {
        "exec": {
            "description": "在执行容器里运行一条命令。返回 ArtifactId、退出码与回显；回显超过 8 KB 只给头尾，"
            "全文用 show 按区间读。这是取得可采信证据的唯一途径。",
            "inputSchema": {
                "type": "object",
                "required": ["cmd"],
                "additionalProperties": False,
                "properties": {"cmd": {"type": "string"}, "timeout_s": {"type": "integer"}, "cwd": {"type": "string"}},
            },
        },
        "submit": {
            "description": "把论断、Intent、候选提交给图服务。逐条返回 id 或拒绝码；被拒的在本会话内改正后重交。"
            "后一条可用前一条的 tmp_id 指代它。final 声明本任务的结局。",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ops": {"type": "array", "items": {"type": "object", "required": ["op"]}},
                    "final": {
                        "type": "object",
                        "required": ["outcome"],
                        "properties": {
                            "outcome": {"enum": list(FINAL_OUTCOMES)},
                            "excluded_paths": {"type": "array", "items": {"type": "string"}},
                            "suggestions": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
        },
        "show": {
            "description": "只读：按 id 看节点（layer=summary|evidence），列清单（list=frontier|all|hints|budget），"
            "或按区间读 Artifact 正文（artifact + range）。",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "layer": {"enum": ["summary", "evidence"]},
                    "list": {"enum": ["frontier", "all", "hints", "budget"]},
                    "artifact": {"type": "string"},
                    "range": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
                },
            },
        },
    }
    s["request_access"] = {
        "description": "需要访问授权范围之外的外部地址时用它申请，写明为什么需要。"
        "返回 granted（已开通，可以直接连）、pending（等人批，先做别的；批下来后 exec 的返回里会带 access）"
        "或 denied（人拒了，本任务里不能再申请这个地址）。连不上一个地址时先申请，不要猜别的地址或换端口重试。",
        "inputSchema": {
            "type": "object",
            "required": ["target", "why"],
            "additionalProperties": False,
            "properties": {
                "target": {"type": "string", "description": "host:port，端口必须写明"},
                "why": {"type": "string"},
            },
        },
    }
    ref_list = {"type": "array", "items": {"type": "string"}, "description": "执行留档或材料的编号，形如 a_123"}
    s["deliver"] = {
        "description": "交付（开放道）：交出答案，附上支撑它的执行留档编号、自检结果、没验证的部分。"
        "做完了 outcome=answered；只做完一部分 partial；做不下去 blocked，并在 needs 里写需要人提供什么。"
        "refs 只填 exec 返回的 artifact 编号或题目材料的编号（主张另可填 kb_read 返回的资料编号，自检不行）；"
        "没有依据的主张 refs 留空。",
        "inputSchema": {
            "type": "object",
            "required": ["outcome"],
            "additionalProperties": False,
            "properties": {
                "outcome": {"enum": ["answered", "partial", "blocked"]},
                "answer": {"type": "string", "description": "答案正文；长的写进工作区文件，用 answer_path"},
                "answer_path": {"type": "string", "description": "工作区里的答案文件（相对 /workspace）"},
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["text"],
                        "additionalProperties": False,
                        "properties": {"text": {"type": "string"}, "refs": ref_list},
                    },
                },
                "self_check": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["what", "result"],
                        "additionalProperties": False,
                        "properties": {
                            "what": {"type": "string", "description": "查了什么、怎么查的"},
                            "result": {"enum": ["pass", "fail", "skipped"]},
                            "refs": ref_list,
                            "item": {"type": "string", "description": "对应题目里必做自检项的编号（c1、c2…）"},
                        },
                    },
                },
                "unverified": {"type": "array", "items": {"type": "string"}},
                "needs": {"type": "array", "items": {"type": "string"}},
            },
        },
    }
    s["review"] = {
        "description": "交回复核读数（开放道的复核会话）：交付的每条主张核一次（claim 是主张的序号，从 0 起），"
        "verdict 取 supported（引用确实支撑）、unsupported（引用与主张不符）、unclear（看不出）；"
        "自检能重跑的重跑（check 是自检的序号，从 0 起），重跑了 refs 必须填这次 exec 的留档编号，跑不了写 not_rerun。"
        "读数不改变任务的状态，只给看结果的人参考。",
        "inputSchema": {
            "type": "object",
            "required": ["claims", "summary"],
            "additionalProperties": False,
            "properties": {
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["claim", "verdict", "note"],
                        "additionalProperties": False,
                        "properties": {
                            "claim": {"type": "integer", "minimum": 0},
                            "verdict": {"enum": ["supported", "unsupported", "unclear"]},
                            "note": {"type": "string", "description": "你看到了什么，一两句话"},
                            "refs": ref_list,
                        },
                    },
                },
                "reruns": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["check", "result"],
                        "additionalProperties": False,
                        "properties": {
                            "check": {"type": "integer", "minimum": 0},
                            "result": {"enum": ["pass", "fail", "not_rerun"]},
                            "note": {"type": "string"},
                            "refs": ref_list,
                        },
                    },
                },
                "counterexamples": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string", "description": "依据整体怎样，一两句话；不打分"},
            },
        },
    }
    s["kb_search"] = {
        "description": "查人导入的资料（手册、说明、笔记）。返回段落编号、资料名、位置、开头约 200 字与得分；"
        f"k 缺省 8、至多 {KB_K_MAX}。本会话至多 {KB_SEARCH_MAX} 次。",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "additionalProperties": False,
            "properties": {"query": {"type": "string"}, "k": {"type": "integer", "minimum": 1, "maximum": KB_K_MAX}},
        },
    }
    s["kb_read"] = {
        "description": "读一段资料的全文，并把它登记为本任务的一条资料引用，返回 artifact 编号。"
        f"资料是人给的说法，不是这次任务里验证过的事实。本会话至多 {KB_READ_MAX} 次。",
        "inputSchema": {
            "type": "object",
            "required": ["chunk"],
            "additionalProperties": False,
            "properties": {"chunk": {"type": "string", "description": "kb_search 返回的段落编号，形如 k_…"}},
        },
    }
    if order is None:
        order = tool_order(current())
    return [{"name": n, **s[n]} for n in order if n in tools]


def solve_ceiling(lease: Mapping[str, Any] | None) -> str:
    """不服务于 Intent 的会话编译授权时的风险上限：bootstrap 取 r0；开放道的 solve 取 r1——它碰得到的规则只有
    人在扩权卡上批过的（开题零出站），r2 仍要逐次批准，solve 不编入（open-lane §3.2、§9）。
    复核会话（verify）与求解会话同一个上限：重跑自检要碰得到求解时用过的那些规则，碰不到更多。"""
    return "r1" if lease is not None and lease.get("kind") in ("solve", "verify") else "r0"


def _same(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return (a["resource"], a["pattern"], sorted(a["actions"])) == (b["resource"], b["pattern"], sorted(b["actions"]))


def as_text(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def tool_order(gf: View) -> tuple[str, ...]:
    """一版功法的工具面顺序（H3：基础工具面，接资料库的两样）。"""
    return (*gf.params("H3", "h3.base")["order"], *gf.params("H3", "h3.kb")["tools"])
