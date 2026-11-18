"""三个代理工具（§3.4.2）：exec 转执行层，submit 转图服务，show 读图服务。Worker 对外的全部通道。

一个 ToolHost 对应一个会话（= 一个任务 = 一个租约）。它持有该会话的令牌，模型看不见令牌，
只看见工具。这里不做规划、不做重试策略、不解释领域内容（3.4.6）。

Op 到内核操作的翻译：
- `*_path`：工作区里的文件，读出后登记为 authored 类，再把 ArtifactId 填进 body_ref / spec_ref。
  路径须落在工作区内，解析符号链接后越界即拒（schema_error）。
- `claim_done`：不是内核操作。登记候选（authored），再提交 request_judge，判官取登记判据时的那一个。
  候选可以是工作区里的文件（candidate_path），也可以直接是答案字符串（candidate）；两样都给时以文件为准。
- `tmp_id`：本次 submit 内，后一条可用前一条的 tmp_id 指代它的 id。
- 同一操作连续被拒 3 次后不再转发（3.4.4），直接返回上次的拒绝码。

工具入参是模型写的、未经校验的 JSON：只经解析层的 `Obj` 读，形状不对抛 `BadBody`，`call` 与 `_one`
只接这一种异常并转成 `schema_error`。其余异常（KeyError、TypeError 等）是本组件或下游的缺陷，原样抛出，
由会话层按任务失败处理，不说成是模型的输入错误。
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paoding_executor.contract import ExecPort
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

MAX_SAME_REJECT = 3
SHOW_RANGE_MAX = 8 * 1024
LATER_OPS = {"escalate_intent": "M1", "add_support": "完整版", "add_contradiction": "完整版"}
FINAL_OUTCOMES = ("found", "nothing", "failed", "unsolved")


@dataclass
class Session:
    """一个会话的身份与边界。token 是图服务签给该租约的会话令牌，只在容器外。"""

    pid: str
    lease_id: str
    role: str  # bootstrap | reason | explore
    token: str
    workspace: Path
    tools: tuple[Any, ...] = ("exec", "submit", "show")
    sandbox_id: str | None = None  # 执行容器；reason 不起执行容器（§3.4.2）
    calls: list[Any] = field(default_factory=list)  # 会话记录：每次工具调用的入参与结果
    final: dict[str, Any] | None = None
    submitted: bool = False


def _err(code: str, detail: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "detail": detail}


class ToolHost:
    def __init__(
        self, s: Session, graph: GraphPort, reader: GraphReader, blobs: BlobPort, executor: ExecPort | None = None
    ):
        self.s, self.graph, self.reader, self.blobs, self.executor = s, graph, reader, blobs, executor
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
        r = self.executor.exec(
            self.s.sandbox_id,
            cmd,
            self.s.pid,
            f"exec:{self.s.lease_id}:{self._nonce}:{self._n}",
            timeout_s=a.integer("timeout_s", 60),
            cwd=a.text("cwd", "/workspace"),
        )
        return {"artifact": r.artifact, "exit_code": r.exit_code, "output": r.output, "truncated": r.truncated}

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
            for k in ("expected_gain", "needs_scope"):
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

    _TOOLS = {"exec": _exec, "submit": _submit, "show": _show}


def tool_schemas(tools: tuple[Any, ...]) -> list[dict[str, Any]]:
    """MCP tools/list 的条目。参数 Schema 由工具定义强制（3.4.4）。"""
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
    return [{"name": n, **s[n]} for n in ("exec", "submit", "show") if n in tools]


def as_text(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)
