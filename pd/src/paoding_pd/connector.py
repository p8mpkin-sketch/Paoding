"""pd connector：从平台导入（external-verdict §5.8 的主入口），走运行中的全栈的 HTTP。

    pd connector list                         已登记的平台（档案 id、版本、判官、凭据槽位是否已设）
    pd connector tasks <平台>                  平台任务清单（不领题）
    pd connector import <平台> <任务号> [--usd 美元] [--minutes 分钟] [--yes]
                                              领题（平台此刻开始计时）→ 确认卡 → 回车开题

平台凭据只在全栈的钥匙环里，pd 不碰它；领题、排版都在服务端，pd 只打印确认卡、写 Blob、提交批次（人的令牌）。
外部判定的题永远要人确认：--yes 只省去回车，确认卡照样打印。
"""

from __future__ import annotations

from typing import Any

from paoding_qicao.contract import render_view


def add_parser(sp: Any) -> None:
    c = sp.add_parser("connector", help="从平台导入").add_subparsers(dest="sub", required=True)
    c.add_parser("list")
    c.add_parser("tasks").add_argument("connector")
    i = c.add_parser("import")
    i.add_argument("connector")
    i.add_argument("task")
    i.add_argument("--usd", type=float, help="成本上限（美元）；不给按先验")
    i.add_argument("--minutes", type=float, help="花费墙钟上限（分钟）；不给按先验。平台时限另进截止时刻")
    i.add_argument("--yes", action="store_true")


def _fail(w: Any, code: int, out: dict[str, Any]) -> int:
    w(f"[证据] 被拒：{code} {out.get('code', '')}：{out.get('detail', '')}\n")
    return 1


def cmd_connector(r: Any, a: Any, w: Any, read: Any) -> int:
    if a.sub == "list":
        code, out = r.call("GET", "/v1/connectors")
        if code != 200:
            return _fail(w, code, out)
        if not out["items"]:
            w("[人] 没有登记任何平台：连接器档案放在 judgebox/connectors.d/\n")
        for c in out["items"]:
            slot = "已设" if c["slot_set"] else f"未设（pd keys set {c['slot']}）"
            w(f"{c['id']}@{c['version']}  判官 {','.join(c['judges']) or '—'}  凭据槽位 {c['slot']} {slot}\n")
        return 0
    if a.sub == "tasks":
        code, out = r.call("GET", f"/v1/connectors/{a.connector}/tasks")
        if code != 200:
            return _fail(w, code, out)
        for t in out["items"]:
            extra = []
            if "time_limit_s" in t:
                extra.append(f"时限 {t['time_limit_s']} 秒")
            if "max_submissions" in t:
                extra.append(f"最多交 {t['max_submissions']} 次")
            w(f"{t['task']}  {t['title']}" + (f"  （{'，'.join(extra)}）" if extra else "") + "\n")
        return 0
    budget: dict[str, int] = {}
    if a.usd is not None:
        budget["usd_milli"] = round(a.usd * 1000)
    if a.minutes is not None:
        budget["wall_s"] = round(a.minutes * 60)
    code, view = r.call(
        "POST", f"/v1/connectors/{a.connector}/import", {"task": a.task, **({"budget": budget} if budget else {})}
    )
    if code != 200:
        return _fail(w, code, view)
    w(render_view(view))
    if not a.yes and read("已领题。按回车开题，输入 n 放弃：").strip().lower() in ("n", "no", "否"):
        w("[人] 已放弃，没有开题（平台那边的领题计时不受影响）\n")
        return 1
    for b in view["blobs"]:
        code, out = r.put("/v1/blobs", b["text"].encode())
        if code // 100 != 2:
            return _fail(w, code, out)
    code, out = r.call(
        "POST", "/v1/problems", {"id": view["pid"], "idem_key": f"pd-import:{view['pid']}", "ops": view["ops"]}
    )
    if code // 100 != 2 or not out.get("ok"):
        bad = [x for x in out.get("results", []) if not x.get("ok")]
        w("[证据] 开题被拒：" + "；".join(f"{x.get('code')}：{x.get('detail', '')}" for x in bad) + "\n")
        return 1
    w(f"[证据] 已开题 {view['pid']}（外部判定 · 平台 {a.connector}）\n")
    return 0
