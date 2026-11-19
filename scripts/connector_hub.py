"""组装根里的“从平台导入”（external-verdict §5.8 的主入口）：已登记的连接器档案、平台任务清单、领题生成开题批次。

    GET  /v1/connectors                          已登记的平台：id、版本、摘要、判官、地址表、凭据槽位是否已设（只读）
    GET  /v1/connectors/{id}/tasks               平台任务清单（list 端点，按 items 指针取任务号、题名、时限、额度）
    POST /v1/connectors/{id}/import {task, nonce?, budget?}
                                                 领题（brief 端点：平台此刻开始计时、分配服务地址）→ 确认卡与批次

只接受人的令牌。这里不写图服务、不写保密库：返回的批次与一句话开题同形（qicao 的 import_view），仍由前端或 pd
用人的令牌提交 /v1/problems。平台的凭据取自钥匙环槽位，只放进请求头；错误消息里只有端点名与状态码。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import Any

from paoding_judgebox.contract import Connector, ConnectorCallError, pointer

from paoding_graph.contract import BadBody, GraphHttp
from paoding_qicao.contract import BadRequest, Catalog, Form, KaitiService

ITEM_DEFAULTS = {"id": "/id", "title": "/title"}


def items_of(prof: Mapping[str, Any], raw: Any) -> list[dict[str, Any]]:
    """清单应答 → [{task, title, time_limit_s?, max_submissions?}]。指针取档案的 items（缺省 /id、/title）。"""
    ptrs = {**ITEM_DEFAULTS, **(prof.get("items") or {})}
    rows = raw if isinstance(raw, list) else []
    out = []
    for r in rows:
        task = pointer(r, ptrs["id"])
        if not isinstance(task, (str, int)) or str(task) == "":
            continue
        item: dict[str, Any] = {"task": str(task), "title": str(pointer(r, ptrs["title"]) or task)}
        for k in ("time_limit_s", "max_submissions"):
            v = pointer(r, ptrs[k]) if k in ptrs else None
            if isinstance(v, int) and not isinstance(v, bool):
                item[k] = v
        out.append(item)
    return out


class ConnectorHub:
    def __init__(
        self,
        connectors: Mapping[str, Mapping[str, Any]],
        catalog: Catalog,
        secret: Callable[[str], str | None],
        ready: Callable[[str], bool],
        kaiti: KaitiService,
        clock: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        self.connectors, self.catalog, self.secret, self.ready, self.kaiti = connectors, catalog, secret, ready, kaiti
        self.clock = clock

    def mount(self, http: GraphHttp) -> None:
        http.mount("GET", r"/v1/connectors", self._wrap(self.list), human=True)
        http.mount("GET", r"/v1/connectors/(?P<cid>[^/]+)/tasks", self._wrap(self.tasks), human=True)
        http.mount("POST", r"/v1/connectors/(?P<cid>[^/]+)/import", self._wrap(self.import_), human=True)

    # ---------- 读 ----------

    def list(self, q: Mapping[str, str], body: Any = None) -> dict[str, Any]:
        out = []
        for cid, c in sorted(self.connectors.items()):
            doc = c["doc"]
            slot = doc["credential"]["key_slot"]
            out.append(
                {
                    "id": cid,
                    "version": c["version"],
                    "digest": c["digest"],
                    "judges": [f.judge_id for f in self.catalog.platforms() if f.connector == cid],
                    "hosts": list((doc.get("match") or {}).get("hosts", [])),
                    "deliver": doc.get("deliver", "judge"),
                    "slot": slot,
                    "slot_set": self.ready(slot),
                }
            )
        return {"items": out}

    def _conn(self, cid: str) -> tuple[Connector, Form]:
        c = self.connectors.get(cid)
        form = next((f for f in self.catalog.platforms() if f.connector == cid), None)
        if c is None:
            raise BadRequest(f"没有登记平台 {cid}")
        if form is None:
            raise BadRequest(f"平台 {cid} 没有对应的外部判官（注册表里 params.connector 指向它的条目）")
        return Connector(c["doc"], self.secret), form

    def tasks(self, q: Mapping[str, str], body: Any = None) -> dict[str, Any]:
        conn, _ = self._conn(q.get("cid", ""))
        return {"items": items_of(conn.prof, self._call(conn.tasks))}

    # ---------- 领题 ----------

    def import_(self, q: Mapping[str, str], body: Any) -> dict[str, Any]:
        if not isinstance(body, dict) or not isinstance(body.get("task"), str) or not body["task"]:
            raise BadRequest("请求体是 {task, nonce?, budget?}")
        conn, form = self._conn(q.get("cid", ""))
        task = body["task"]
        listed = {i["task"]: i for i in items_of(conn.prof, self._call(conn.tasks))}
        if task not in listed:
            raise BadRequest(f"平台清单里没有任务 {task}")
        notice = self._call(lambda: conn.notice(task))  # 领题：平台从此刻开始计时
        now = self.clock()
        brief = json.loads(notice)
        item = dict(listed[task])
        for k in ("time_limit_s", "max_submissions"):
            v = conn.field(brief, k)
            if k not in item and isinstance(v, int) and not isinstance(v, bool):
                item[k] = v
        stmt = conn.field(brief, "statement")
        statement = stmt if isinstance(stmt, str) and stmt.strip() else notice.decode()
        nonce = body.get("nonce") or ""
        if not isinstance(nonce, str) or len(nonce) > 64:
            raise BadRequest("nonce 须是不超过 64 字的字符串")
        return self.kaiti.import_view(form, item, statement, notice, now_ms=now, nonce=nonce, budget=body.get("budget"))

    @staticmethod
    def _call(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except ConnectorCallError as e:  # 消息里只有端点名与状态码
            raise BadRequest(f"平台调用失败：{e}") from None

    @staticmethod
    def _wrap(fn: Any) -> Any:
        def route(q: dict[str, str], body: Any) -> Any:
            try:
                return fn(q, body)
            except BadRequest as e:
                raise BadBody(str(e)) from None

        return route
