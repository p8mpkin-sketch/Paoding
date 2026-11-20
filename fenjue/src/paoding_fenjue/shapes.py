"""火与功法的形状、装载与摘要（焚决 F2，docs/design/fenjue/01-boundary.md §8）。

一团火是一份清单（`fires/<id>.json`），确定性数据：规范化（JCS）后取 sha256 即火的摘要。
功法（`gongfa.json`）记此刻生效的整套火：品阶、每个火位装着哪几团火；功法摘要把各火的摘要一并算进去，
所以任何一团火的清单改一个字，功法摘要就变。

与 01 §8 的两处出入（随 F2 修订设计稿）：
- `Gongfa.fires` 的值是火的列表：07 §3 里同一火位本来就并存几团火（H1 的三段式、独行、召回各绑定不同席位）。
- H1 的火用 `seats` 而不是 `seat`：三段式一团火绑定 bootstrap、reason、explore 三个席位，每个席位一个形态，
  写在 `params.forms` 里。

本模块只读清单、不碰事件账，也不做任何 I/O 之外的事：装载器是纯函数加读包内文件。
"""

from __future__ import annotations

import hashlib
import json
from functools import cache
from importlib import resources
from typing import Any

from paoding_graph.contract import canonicalize

from .tables import PORTS, SEATS

SLOTS = ("H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8")
ORGANS = ("感知官", "量具")
FIRE_KEYS = ("id", "ver", "slot", "ports", "params", "assets", "organ", "lineage", "switch")

# 工具 → 它要提交的事件（经脉越界一检：形态给的工具，所绑定的席位必须都能提交）
TOOL_EVENTS: dict[str, tuple[str, ...]] = {
    "exec": (),  # 执行结果由执行层登记（M2），不经会话令牌
    "show": (),  # 只读（M4）
    "submit": ("add_fact",),
    "deliver": ("deliver",),
    "request_access": ("request_scope",),
    "kb_search": (),  # 查询词由书库记进事件账（M7），不经会话令牌
    "kb_read": (),
}


def digest(obj: Any) -> str:
    return hashlib.sha256(canonicalize(obj)).hexdigest()


def fire_digest(fire: dict[str, Any]) -> str:
    return digest({k: v for k, v in fire.items() if k != "digest"})


def _read(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(resources.files(__package__).joinpath(name).read_text(encoding="utf-8"))
    return data


@cache
def fire(fid: str) -> dict[str, Any]:
    """一团火的清单（包内 fires/<id>.json）。"""
    f = _read(f"fires/{fid}.json")
    if f.get("id") != fid:
        raise ValueError(f"清单 {fid}.json 的 id 是 {f.get('id')!r}")
    return f


def fire_ids() -> list[str]:
    root = resources.files(__package__).joinpath("fires")
    return sorted(p.name.removesuffix(".json") for p in root.iterdir() if p.name.endswith(".json"))


def ref(fid: str) -> str:
    return f"{fid}@{fire(fid)['ver']}"


def _unref(r: str) -> tuple[str, int]:
    fid, _, ver = r.partition("@")
    return fid, int(ver)


@cache
def gongfa() -> dict[str, Any]:
    """此刻生效的功法（包内 gongfa.json），带算出的摘要。"""
    g = _read("gongfa.json")
    for slot, refs in g["fires"].items():
        for r in refs:
            fid, ver = _unref(r)
            if fire(fid)["slot"] != slot or fire(fid)["ver"] != ver:
                raise ValueError(f"功法里 {slot} 的 {r} 与清单不符")
    return {**g, "digest": gongfa_digest(g)}


def gongfa_digest(g: dict[str, Any]) -> str:
    body = {k: v for k, v in g.items() if k != "digest"}
    refs = sorted({r for rs in [*g["fires"].values(), *(g.get("holdout") or {}).values()] for r in rs})
    return digest({"gongfa": body, "fires": {r: fire_digest(fire(_unref(r)[0])) for r in refs}})


def active(slot: str) -> list[dict[str, Any]]:
    return [fire(_unref(r)[0]) for r in gongfa()["fires"].get(slot, [])]


@cache
def form(seat: str) -> dict[str, Any]:
    """H1：这个席位上的会话形态（工具、提示词、收尾与接力规则）。席位没有形态时报 KeyError。"""
    for f in active("H1"):
        if seat in f["params"].get("forms", {}):
            return {"fire": f["id"], **f["params"]["forms"][seat]}
    raise KeyError(f"功法里没有绑定席位 {seat} 的会话形态")


def params(slot: str, fid: str | None = None) -> dict[str, Any]:
    """H2–H8：某个火位上那团火的参数；同一火位有几团火时用 fid 指名。"""
    fs = [f for f in active(slot) if fid is None or f["id"] == fid]
    if len(fs) != 1:
        raise KeyError(f"{slot} 上{'没有' if not fs else '不止一团'}火{f' {fid}' if fid else ''}")
    p: dict[str, Any] = fs[0]["params"]
    return p


def check(f: dict[str, Any]) -> list[str]:
    """静态验体（02 §6.1）里只看清单就能判的几检：形状、经脉越界、入库四问。资产寻址要读文件，由调用方做。"""
    errs = []
    missing = [k for k in FIRE_KEYS if k not in f]
    if missing:
        return [f"{f.get('id')}: 缺 {missing}"]
    fid = f["id"]
    if f["slot"] not in SLOTS or not fid.startswith(f["slot"].lower() + "."):
        errs.append(f"{fid}: 火位 {f['slot']} 与 id 不符")
    if not isinstance(f["ver"], int) or f["ver"] < 1:
        errs.append(f"{fid}: ver 须为正整数")
    for p in f["ports"]:
        if p.split(":")[0] not in PORTS:
            errs.append(f"{fid}: 没有经脉 {p}")
    o = f["organ"]
    if o.get("class") not in ORGANS:
        errs.append(f"{fid}: organ.class 只能是感知官或量具（守门官不进功法）")
    if not o.get("enable_when") or not o.get("control_arm"):
        errs.append(f"{fid}: 入库四问的启用条件与对照臂不能空")
    if o.get("class") == "感知官" and not o.get("retire_signal"):
        errs.append(f"{fid}: 感知官要写退役信号")
    if not isinstance(f["lineage"].get("from"), list):
        errs.append(f"{fid}: lineage.from 须为列表")
    if f["slot"] == "H1":
        forms = f["params"].get("forms", {})
        if sorted(forms) != sorted(f.get("seats", [])):
            errs.append(f"{fid}: seats 与 params.forms 的席位不一致")
        m1 = {p.split(":", 1)[1] for p in f["ports"] if p.startswith("M1:")}
        for seat, fm in forms.items():
            if seat not in SEATS:
                errs.append(f"{fid}: 没有席位 {seat}（新席位是体质修炼）")
                continue
            for t in fm.get("tools", []):
                for ev in TOOL_EVENTS.get(t, ("?",)):
                    if ev not in SEATS[seat]:
                        errs.append(f"{fid}: 席位 {seat} 不能提交 {ev}，形态却给了工具 {t}")
                    elif ev not in m1:
                        errs.append(f"{fid}: 工具 {t} 要用 M1:{ev}，清单没申请")
    return errs


# ---------------------------------------------------------------- 读端的缺省（F3，01 §9）

# 旧租约没有 form：按席位推出形态。只在读端推，不写回日志，也不进状态哈希
SEAT_FORMS = {
    "bootstrap": "h1.triad",
    "reason": "h1.triad",
    "explore": "h1.triad",
    "solve": "h1.solo",
    "recall": "h1.recall",
}


def gongfa_of(problem: dict[str, Any]) -> dict[str, Any]:
    """一道题开在哪一套功法之下。焚决之前开的题没有这个字段，读作第 0 阶（旧法），摘要为空。"""
    g = problem.get("gongfa")
    return {"jie": g["jie"], "digest": g["digest"]} if g else {"jie": 0, "digest": None}


def form_of(lease: dict[str, Any]) -> str | None:
    """一个会话用的形态 id（不带修订号）。新租约记在事件里；旧租约按席位推；判官的租约没有形态。"""
    f = lease.get("form")
    return f.partition("@")[0] if f else SEAT_FORMS.get(lease["kind"])


def kernel_config() -> dict[str, Any]:
    """组装根抄给内核 Config 的两样：功法 (品阶, 摘要) 与席位 → 形态 "id@ver"。内核只抄不解释。"""
    g = gongfa()
    forms = tuple(sorted((seat, ref(f["id"])) for f in active("H1") for seat in f["seats"]))
    return {"gongfa": (g["jie"], g["digest"]), "forms": forms}
