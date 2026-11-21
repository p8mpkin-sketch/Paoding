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
import os
from collections.abc import Mapping
from functools import cache
from importlib import resources
from pathlib import Path
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


GONGFA_ENV = "PAODING_FENJUE_GONGFA"  # 换一套功法：指一份功法文件（体质试炼 trials.py --gongfa 用它）


def _gongfa_source() -> dict[str, Any]:
    path = os.environ.get(GONGFA_ENV)
    if not path:
        return _read("gongfa.json")
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


def fire_at(r: str) -> dict[str, Any]:
    """按 "id@ver" 取一团火的清单：当前版本在 fires/，旧版本在 archive/fires/（存档只增不改）。"""
    fid, ver = _unref(r)
    try:
        f = fire(fid)
    except FileNotFoundError:
        f = None
    if f is not None and f["ver"] == ver:
        return f
    return _archived_fire(r)


@cache
def _archived_fire(r: str) -> dict[str, Any]:
    try:
        f = _read(f"archive/fires/{r}.json")
    except FileNotFoundError:
        raise KeyError(f"没有 {r} 的清单：既不是当前版本，存档里也没有") from None
    if _unref(r) != (f.get("id"), f.get("ver")):
        raise ValueError(f"存档 {r}.json 的 id@ver 对不上")
    return f


def _validate(g: dict[str, Any]) -> dict[str, Any]:
    """校验一套功法并带上算出的摘要。"""
    for part in ("fires", "holdout"):
        for slot, refs in (g.get(part) or {}).items():
            for r in refs:
                try:
                    ok = fire_at(r)["slot"] == slot
                except KeyError:
                    ok = False
                if not ok:
                    raise ValueError(f"功法里 {slot} 的 {r} 与清单不符")
    for slot, refs in (g.get("holdout") or {}).items():
        for r in refs:  # 留出的火要顶替恰好一团生效的火（那团火的出身里有它）
            hid = _unref(r)[0]
            n = sum(hid in fire_at(x)["lineage"]["from"] for x in g["fires"].get(slot, []))
            if n != 1:
                raise ValueError(f"留出的 {r} 顶替了 {n} 团生效的火（要恰好一团）")
    pm = g.get("holdout_permille", 0)
    if not isinstance(pm, int) or not 0 <= pm <= 1000:
        raise ValueError("holdout_permille 是 0–1000 的整数（千分比）")
    return {**g, "digest": gongfa_digest(g)}


@cache
def gongfa() -> dict[str, Any]:
    """此刻生效的功法（包内 gongfa.json；环境变量 PAODING_FENJUE_GONGFA 指了文件就用那份），带算出的摘要。
    换了功法，摘要随之变，开题事件里记下的就是换过的那套（F3），所以换没换、换成什么都可查。
    火的清单始终来自包内：换功法只是换一种组合，不能凭空多出一团没有清单的火。"""
    return _validate(_gongfa_source())


def gongfa_digest(g: dict[str, Any]) -> str:
    body = {k: v for k, v in g.items() if k != "digest"}
    refs = sorted({r for rs in [*g["fires"].values(), *(g.get("holdout") or {}).values()] for r in rs})
    return digest({"gongfa": body, "fires": {r: fire_digest(fire_at(r)) for r in refs}})


# ---------------------------------------------------------------- 一套功法的视图；按题锁定开题时的功法（FJ6）
#
# 开题时功法摘要进了事件（F3）。在跑的题后续每一次派工、每一个会话，都要按这个摘要取功法，而不是取此刻最新的：
# 散火或换火只影响之后新开的题，在跑的题按开题时的版本跑完（02 §8、FJ6）。
# 为此每一版上线过的功法按摘要存档（archive/gongfa/<摘要>.json），连同它引用的每团火（archive/fires/<id>@<ver>.json）
# 与火的资产（archive/assets/<sha256>，即提示词原文）。存档只增不改，CI 核对（tests/fenjue/test_archive.py）。


class View:
    """一套功法：火位上生效的火、常设留出、形态与参数、资产原文。"""

    def __init__(self, g: dict[str, Any], pinned: bool = True) -> None:
        self.g = g
        self.digest: str = g["digest"]
        self.pinned = pinned  # False：题开在存档里找不到的功法下（或焚决之前），退回此刻的功法

    def holdout_permille(self) -> int:
        return int(self.g.get("holdout_permille", 0))

    def in_holdout(self, pid: str, slot: str) -> bool:
        """这道题在这个火位上是否分给留出的火。按火位加盐：同一道题不会在每个火位上都落进留出。"""
        if not self.g.get("holdout", {}).get(slot):
            return False
        h = int(hashlib.sha256(f"{slot}:{pid}".encode()).hexdigest()[:8], 16)
        return h % 1000 < self.holdout_permille()

    def stand_ins(self, slot: str) -> dict[str, dict[str, Any]]:
        """被顶替的那团生效的火 → 留出的火：生效的火的 lineage.from 里提到它。"""
        out = {}
        for r in self.g.get("holdout", {}).get(slot, []):
            h = fire_at(r)
            for f in [fire_at(x) for x in self.g["fires"].get(slot, [])]:
                if h["id"] in f["lineage"]["from"]:
                    out[f["id"]] = h
        return out

    def active(self, slot: str, pid: str | None = None) -> list[dict[str, Any]]:
        """火位上生效的火；给了题号且这道题分在留出，被顶替的那团换成留出的火。"""
        fs = [fire_at(r) for r in self.g["fires"].get(slot, [])]
        if pid is None or not self.in_holdout(pid, slot):
            return fs
        sub = self.stand_ins(slot)
        return [sub.get(f["id"], f) for f in fs]

    def form(self, seat: str, pid: str | None = None) -> dict[str, Any]:
        """H1：这个席位上的会话形态（工具、提示词、收尾与接力规则）。席位没有形态时报 KeyError。"""
        for f in self.active("H1", pid):
            if seat in f["params"].get("forms", {}):
                return {"fire": f["id"], "ref": f"{f['id']}@{f['ver']}", **f["params"]["forms"][seat]}
        raise KeyError(f"功法里没有绑定席位 {seat} 的会话形态")

    def params(self, slot: str, fid: str | None = None, pid: str | None = None) -> dict[str, Any]:
        """H2–H8：某个火位上那团火的参数；同一火位有几团火时用 fid 指名。
        给了题号且这道题分在留出时，指名的那团火若被顶替，给的是留出的那团的参数。"""
        if pid is not None and fid is not None and self.in_holdout(pid, slot) and fid in self.stand_ins(slot):
            return dict(self.stand_ins(slot)[fid]["params"])
        fs = [f for f in self.active(slot) if fid is None or f["id"] == fid]
        if len(fs) != 1:
            raise KeyError(f"{slot} 上{'没有' if not fs else '不止一团'}火{f' {fid}' if fid else ''}")
        p: dict[str, Any] = fs[0]["params"]
        return p

    def asset(self, r: str, name: str) -> bytes:
        """火 r（"id@ver"）的资产 name 在这一版里的原文：按清单里的 sha256 从存档取。"""
        for a in fire_at(r)["assets"]:
            if a["name"] == name:
                return asset_bytes(a["sha256"])
        raise KeyError(f"{r} 没有资产 {name}")


def asset_bytes(sha: str) -> bytes:
    data = resources.files(__package__).joinpath(f"archive/assets/{sha}").read_bytes()
    if hashlib.sha256(data).hexdigest() != sha:
        raise ValueError(f"存档里的资产 {sha} 内容对不上摘要")
    return data


def current() -> View:
    return View(gongfa())


@cache
def at(dg: str) -> View | None:
    """按摘要取存档里的那一版功法；没存档时 None。取出来重算一遍摘要，对不上就报错（存档被改过）。"""
    try:
        g = _read(f"archive/gongfa/{dg}.json")
    except FileNotFoundError:
        return None
    v = _validate(g)
    if v["digest"] != dg:
        raise ValueError(f"存档 {dg} 重算出的摘要是 {v['digest']}：存档被改过")
    return View(v)


def for_problem(problem: Mapping[str, Any] | None) -> View:
    """一道题该用的功法：开题时记下的那一版（锁定，FJ6）。焚决之前开的题（没有摘要）与存档里找不到的摘要，
    退回此刻的功法，View.pinned 为 False。"""
    stamp = (problem or {}).get("gongfa")
    if stamp and stamp.get("digest"):
        if stamp["digest"] == gongfa()["digest"]:
            return current()
        v = at(stamp["digest"])
        if v is not None:
            return v
    return View(gongfa(), pinned=False)


# 此刻的功法上的同名函数（新题、不针对某道题的读端用它们）


def holdout_permille() -> int:
    return current().holdout_permille()


def in_holdout(pid: str, slot: str) -> bool:
    return current().in_holdout(pid, slot)


def stand_ins(slot: str) -> dict[str, dict[str, Any]]:
    return current().stand_ins(slot)


def active(slot: str, pid: str | None = None) -> list[dict[str, Any]]:
    return current().active(slot, pid)


def form(seat: str, pid: str | None = None) -> dict[str, Any]:
    return current().form(seat, pid)


def params(slot: str, fid: str | None = None, pid: str | None = None) -> dict[str, Any]:
    return current().params(slot, fid, pid)


def arm_of(problem: dict[str, Any], slot: str) -> str | None:
    """读端：一道题在这个火位上用的是哪一臂（"main" 或 "holdout"），按它开题时的那一版功法算。
    焚决之前开的题（没有摘要）与存档里找不到的摘要给 None。"""
    stamp = problem.get("gongfa")
    if not stamp or not stamp.get("digest"):
        return None
    v = current() if stamp["digest"] == gongfa()["digest"] else at(stamp["digest"])
    if v is None:
        return None
    return "holdout" if v.in_holdout(problem["id"], slot) else "main"


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
