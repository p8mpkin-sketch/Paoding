"""炼化命令（焚决 F5）：一次吞噬从识火走到定阶或散火，每一步一条命令，炼档的 .json 与 .md 都由命令写。

    uv run python scripts/lianhua.py new <短名> --title … --source … --phenomenon … --gap … --is-fire …
    uv run python scripts/lianhua.py cuiyi <档号> --yi … --premise … --cost … --overlap … --conflict … \\
        --hypothesis … --split … --masked …
    uv run python scripts/lianhua.py ruwei <档号> --fire 清单草稿.json [--replaces 上一团火] \\
        --arm B=… --arm A1=… --arm F=… --arm B1=… --reading '{"dim":…,"kind":"新生","dir":"up","gate":1,"test":…}' \\
        [--arm A0=… --parity equal|ours_or_neutral|theirs --parity-reason …]   # 原形臂与它的条件对等声明
    uv run python scripts/lianhua.py plan <档号> --file 试火计划.json   # 预登记试火计划（003 起；登记之后不能改）
    uv run python scripts/lianhua.py approve <档号> --by cz [--waive-gate 理由]   # 设计 PR 裁决：值得炼
    uv run python scripts/lianhua.py yanti <档号> [--base origin/main]   # 体质与量具的改动行数、静态验体、跑 T1–T5
    uv run python scripts/lianhua.py ronghuo <档号> --set '维:F=1' … [--values 读数.json] [--run-tests]   # 判结局
    uv run python scripts/lianhua.py ronghuo <档号> --record 试火记录.json   # 003 起：读数只从试火记录读入
    uv run python scripts/lianhua.py jue <档号> --by cz --outcome huolian [--condition …] [--record 试火记录.json]
    uv run python scripts/lianhua.py sanhuo <档号> --by cz --why …     # 散火：火位指回上一团火
    uv run python scripts/lianhua.py status [<档号>]                    # 每份炼档走到哪一步、下一步是什么
    uv run python scripts/lianhua.py render <档号>                      # 由 JSON 重新生成 .md
    uv run python scripts/lianhua.py import <交接包.json> [--only C2] [--queue]   # 方案分析的交接包 → 炼档（入位）
    uv run python scripts/lianhua.py bang show | bang apply <交接包或更新列表.json>   # 异火榜（候选方案）

数据操作都在 paoding_fenjue.lianhua（纯函数，有单测）；这里只读写文件、跑 git 与测试。
入位时清单草稿写进 fenjue/src/paoding_fenjue/fires/<id>.json（还不在功法里，开关缺省关）；定阶时才改 gongfa.json。
不读本机题库与校准目录：试火的读数由 --set 填（来自可插拔的炉题数据源或 CI 里的结构测试），命令不去找数据。
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from paoding_fenjue import lianhua as lh
from paoding_fenjue import shapes
from paoding_fenjue.contract import check, digest, fire_digest
from paoding_fenjue.engine import handoff as ho
from paoding_fenjue.shapes import gongfa_digest

ROOT = Path(__file__).resolve().parents[1]
DOSSIERS = ROOT / "docs" / "design" / "fenjue" / "dossiers"
PKG = ROOT / "fenjue" / "src" / "paoding_fenjue"
GONGFA = PKG / "gongfa.json"
BANG = ROOT / "docs" / "design" / "fenjue" / "yihuobang.json"
BANG_SEED = ROOT / "docs" / "design" / "fenjue" / "engine" / "examples" / "yihuobang.seed.json"


def _today() -> str:
    return dt.date.today().isoformat()


def _write_json(p: Path, data: Any) -> None:
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def path_of(no: str) -> Path:
    hits = sorted(DOSSIERS.glob(f"{no}-*.json"))
    if len(hits) != 1:
        raise SystemExit(f"找不到炼档 {no}（{DOSSIERS.relative_to(ROOT)} 下 {no}-*.json）")
    return hits[0]


def load(no: str) -> dict[str, Any]:
    d: dict[str, Any] = json.loads(path_of(no).read_text(encoding="utf-8"))
    if not d.get("generated"):
        raise SystemExit(f"炼档 {no} 是手写的（焚决首炼），命令不改它")
    return d


def save(d: dict[str, Any]) -> Path:
    p = DOSSIERS / f"{d['dossier']}-{d['name']}.json"
    _write_json(p, d)
    p.with_suffix(".md").write_text(lh.render(d), encoding="utf-8")
    return p


def next_no() -> str:
    nos = [int(p.name[:3]) for p in DOSSIERS.glob("[0-9][0-9][0-9]-*.json")]
    return f"{max(nos, default=0) + 1:03d}"


def gongfa_raw() -> dict[str, Any]:
    g: dict[str, Any] = json.loads(GONGFA.read_text(encoding="utf-8"))
    return g


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def kernel_lines(base: str) -> int:
    """对体质组件的改动行数（增加 + 删除），与 base 比；工作区里还没提交的也算。"""
    return _lines(base, lh.KERNEL_PATHS)


def measure_lines(base: str) -> int:
    """对量具路径的改动行数，数法同上。一次炼化这一项必须是 0（03 §3.2）。"""
    return _lines(base, lh.MEASURE_PATHS)


def _lines(base: str, paths: tuple[str, ...]) -> int:
    out = _git("diff", "--numstat", base, "--", *paths)
    n = 0
    for line in out.splitlines():
        a, b, _ = line.split("\t", 2)
        n += (int(a) if a.isdigit() else 0) + (int(b) if b.isdigit() else 0)
    return n


def static_errors(f: dict[str, Any]) -> list[str]:
    errs = check(f)
    for a in f.get("assets", []):
        p = ROOT / a["name"]
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != a["sha256"]:
            errs.append(f"{f['id']}: 资产 {a['name']} 的 sha256 与文件不符")
    return errs


def _fire_file(r: str) -> dict[str, Any]:
    fid, _, ver = r.partition("@")
    p = PKG / "fires" / f"{fid}.json"
    if p.exists():
        f: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
        if f["ver"] == int(ver):
            return f
    a = PKG / "archive" / "fires" / f"{r}.json"
    if not a.exists():
        raise SystemExit(f"没有 {r} 的清单：既不是当前版本，存档里也没有")
    old: dict[str, Any] = json.loads(a.read_text(encoding="utf-8"))
    return old


def archive(g: dict[str, Any]) -> str:
    """把一版功法存档（FJ6）：archive/gongfa/<摘要>.json、它引用的每团火 archive/fires/<id>@<ver>.json、
    火的资产 archive/assets/<sha256>。在跑的题按开题时记下的摘要从这里取功法，所以存档只增不改：
    同名的已经在了，内容必须一样，不一样就停下（多半是改了清单却没升 ver）。返回这版功法的摘要。"""
    refs = sorted({r for rs in [*g["fires"].values(), *(g.get("holdout") or {}).values()] for r in rs})
    fires = {r: _fire_file(r) for r in refs}
    body = {k: v for k, v in g.items() if k != "digest"}
    dg = digest({"gongfa": body, "fires": {r: fire_digest(f) for r, f in fires.items()}})
    root = PKG / "archive"
    for sub in ("gongfa", "fires", "assets"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    for r, f in fires.items():
        p = root / "fires" / f"{r}.json"
        if p.exists():
            if fire_digest(json.loads(p.read_text(encoding="utf-8"))) != fire_digest(f):
                raise SystemExit(f"存档里的 {r} 与此刻的清单不同：清单改了要升 ver，存档只增不改")
        else:
            _write_json(p, f)
        for a in f["assets"]:
            dst = root / "assets" / a["sha256"]
            if dst.exists():
                continue
            src = ROOT / a["name"]
            data = src.read_bytes() if src.exists() else b""
            if hashlib.sha256(data).hexdigest() != a["sha256"]:
                raise SystemExit(f"{r} 的资产 {a['name']} 与清单里的 sha256 不符，存不了档")
            dst.write_bytes(data)
    p = root / "gongfa" / f"{dg}.json"
    if not p.exists():
        _write_json(p, body)
    return dg


def sync_engine(g: dict[str, Any]) -> str:
    """分析实例的功法（gongfa.engine.json）跟着主功法走：由主功法推出、存档、写回。主功法每变一次都要跟一次，
    否则分析实例开的题会锁在旧的一套上（docs/design/fenjue/13-kernel.md §2）。返回它的摘要。"""
    refs = []
    for fid in (shapes.ENGINE_FORM, shapes.ENGINE_TOOLS):
        f = json.loads((PKG / "fires" / f"{fid}.json").read_text(encoding="utf-8"))
        refs.append(f"{fid}@{f['ver']}")
    e = shapes.engine_variant(g, _fire_file, (refs[0], refs[1]))
    dg = archive(e)
    _write_json(PKG / shapes.ENGINE_GONGFA, e)
    return dg


def candidate(d: dict[str, Any]) -> Path:
    """换上这团火的候选功法，写到临时文件：体质试炼与结构读数在它上面跑。"""
    g, _ = lh.install(gongfa_raw(), d)
    fd, tmp = tempfile.mkstemp(prefix=f"gongfa-{d['dossier']}-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(g, fh, ensure_ascii=False)
    return Path(tmp)


def _run(cmd: list[str], gongfa_file: Path | None) -> tuple[bool, str]:
    env = {**os.environ, **({"PAODING_FENJUE_GONGFA": str(gongfa_file)} if gongfa_file else {})}
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    tail = [x for x in (r.stdout + r.stderr).splitlines() if x.strip()]
    return r.returncode == 0, tail[-1] if tail else ""


# ---------------------------------------------------------------- 子命令


def cmd_new(a: argparse.Namespace) -> None:
    shihuo = {"source": a.source, "phenomenon": a.phenomenon, "gap": a.gap, "is_fire": a.is_fire}
    d = lh.new(a.no or next_no(), a.name, a.title, a.date or _today(), shihuo, origin=a.origin)
    print(f"开档 → {save(d).relative_to(ROOT)}；下一步：cuiyi {d['dossier']}")


def cmd_cuiyi(a: argparse.Namespace) -> None:
    fields = {k: getattr(a, k) for k in lh.CUIYI}
    d = lh.cuiyi(load(a.no), fields)
    print(f"萃意 → {save(d).relative_to(ROOT)}")


def _kv(items: list[str]) -> dict[str, str]:
    out = {}
    for it in items:
        k, sep, v = it.partition("=")
        if not sep:
            raise SystemExit(f"{it!r} 要写成 键=值")
        out[k] = v
    return out


def cmd_ruwei(a: argparse.Namespace) -> None:
    d = load(a.no)
    f = json.loads(Path(a.fire).read_text(encoding="utf-8"))
    f.setdefault("lineage", {}).setdefault("dossier", d["dossier"])
    readings = [json.loads(r) for r in a.reading]
    if a.readings:
        readings += json.loads(Path(a.readings).read_text(encoding="utf-8"))
    parity = None
    if a.parity:
        parity = {"class": a.parity, **({"reason": a.parity_reason} if a.parity_reason else {})}
    d = lh.ruwei(d, f, a.replaces, _kv(a.arm), readings, a.preregistered or "", parity=parity)
    dest = PKG / "fires" / f"{f['id']}.json"
    if dest.exists() and json.loads(dest.read_text(encoding="utf-8")) != f:
        raise SystemExit(f"{dest.relative_to(ROOT)} 已有一份不同的清单：同 id 的火改了就升 ver、另开一份")
    _write_json(dest, f)
    print(f"入位 → {save(d).relative_to(ROOT)}；清单草稿 → {dest.relative_to(ROOT)}（不在功法里）")
    print("前三节写完了：开设计 PR 交裁决，通过后 approve")


def _record(path: str | None) -> dict[str, Any] | None:
    """试火记录：试火台写出的那个文件。炼档里只记它的哈希，文件留在跑试火的那台机器上。"""
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else None


def cmd_plan(a: argparse.Namespace) -> None:
    d = lh.dengji(load(a.no), json.loads(Path(a.file).read_text(encoding="utf-8")))
    print(f"试火计划已登记（{d['trial_plan_hash'][:12]}）→ {save(d).relative_to(ROOT)}")
    print(f"交设计裁决：approve {d['dossier']} --by …")


def cmd_approve(a: argparse.Namespace) -> None:
    d = lh.approve_design(load(a.no), a.by, a.date or _today(), a.note or "", a.waive_gate or "")
    print(f"设计已裁 → {save(d).relative_to(ROOT)}；下一步：yanti {d['dossier']}")


def cmd_yanti(a: argparse.Namespace) -> None:
    d = load(a.no)
    on_disk = PKG / "fires" / f"{d['fire']['id']}.json"
    f = json.loads(on_disk.read_text(encoding="utf-8")) if on_disk.exists() else d["fire"]
    errs = static_errors(f)
    n = kernel_lines(a.base)
    nm = measure_lines(a.base)
    cand = candidate(d)
    trials: dict[str, dict[str, Any]] = {}
    try:
        for t in lh.TRIALS:
            if a.skip_trials:
                trials[t] = {"ok": False, "summary": "没跑（--skip-trials）"}
                continue
            ok, summary = _run([sys.executable, "tests/fenjue/trials.py", "--gongfa", str(cand), t], None)
            trials[t] = {"ok": ok, "summary": summary}
            print(f"{t}：{'过' if ok else '不过'}  {summary}")
    finally:
        cand.unlink(missing_ok=True)
    d = lh.yanti(d, n, errs, trials, _git("rev-parse", "--short", "HEAD"), measure_lines=nm)
    print(f"体质改动行数 {n}；量具改动行数 {nm}；静态验体 {'全过' if not errs else errs}")
    print(f"验体{'通过' if d['yanti']['passed'] else '不过'}")
    print(f"验体 → {save(d).relative_to(ROOT)}；下一步：ronghuo {d['dossier']}")


def _parse_set(items: list[str]) -> dict[str, dict[str, Any]]:
    """'维:臂=值'，例 '实时所见可回放率:F=1'。值按 JSON 读（数、null、字符串）。"""
    out: dict[str, dict[str, Any]] = {}
    for it in items:
        dim, sep, rest = it.rpartition(":")
        arm, sep2, val = rest.partition("=")
        if not sep or not sep2:
            raise SystemExit(f"{it!r} 要写成 维:臂=值")
        try:
            v: Any = json.loads(val)
        except ValueError:
            v = val
        out.setdefault(dim, {})[arm] = v
    return out


def cmd_ronghuo(a: argparse.Namespace) -> None:
    d = load(a.no)
    values = _parse_set(a.set)
    if a.values:
        for dim, v in json.loads(Path(a.values).read_text(encoding="utf-8")).items():
            values.setdefault(dim, {}).update(v)
    if lh.needs_plan(d) and values:
        raise lh.StepError("这份炼档的读数只从试火记录读入（--record）；结构读数用 --run-tests 跑出来，不手填")
    if a.run_tests:  # 结构读数：出处测试在换上这团火的功法下过了，合火臂即 1
        cand = candidate(d)
        try:
            for r in d["readings"]:
                if r.get("test") and not r.get("target") and "F" not in values.get(r["dim"], {}):
                    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", r["test"]]
                    ok, summary = _run(cmd, cand)
                    values.setdefault(r["dim"], {})["F"] = 1 if ok else 0
                    print(f"{r['dim']}：F={'1' if ok else '0'}  {summary}")
        finally:
            cand.unlink(missing_ok=True)
    d = lh.ronghuo(d, values, gongfa_raw()["jie"], record=_record(a.record))
    print(f"结局提议：{lh.OUTCOMES[d['outcome_proposed']]}；品阶提议：{d['jie_proposed']}")
    for w in d["outcome_why"]:
        print("  " + w)
    print(f"融火 → {save(d).relative_to(ROOT)}；交裁决：jue {d['dossier']} --by … --outcome …")


def cmd_jue(a: argparse.Namespace) -> None:
    d, g = lh.jue(load(a.no), gongfa_raw(), a.by, a.date or _today(), a.outcome, a.condition, record=_record(a.record))
    save(d)
    if g != gongfa_raw():
        dg = archive(g)  # 先存档再生效：新开的题记下的摘要，存档里一定有
        _write_json(GONGFA, g)
        sync_engine(g)
        print(f"功法 → 第 {g['jie']} 阶；{d['fire']['slot']} = {g['fires'][d['fire']['slot']]}；存档 {dg[:12]}")
    print(f"裁决：{lh.OUTCOMES[a.outcome]} → {path_of(d['dossier']).relative_to(ROOT)}")
    _writeback(d, "jue", a.by, a.date or _today())


def cmd_sanhuo(a: argparse.Namespace) -> None:
    d, g = lh.sanhuo(load(a.no), gongfa_raw(), a.by, a.date or _today(), a.why)
    save(d)
    dg = archive(g)
    _write_json(GONGFA, g)
    sync_engine(g)
    print(f"散火：{d['fire']['slot']} = {g['fires'][d['fire']['slot']]}；功法 → 第 {g['jie']} 阶；存档 {dg[:12]}")
    print("在跑的题照开题时的那一版跑完（FJ6）；之后新开的题用散火后的功法")
    _writeback(d, "sanhuo", a.by, a.date or _today(), a.why)


def _writeback(d: dict[str, Any], event: str, by: str, date: str, why: str = "") -> None:
    """结局回写（12 §5）：异火榜上有这份炼档就改它的状态；没有（手写的、不经方案分析的炼档）不动。"""
    bang = ho.writeback(_bang_doc(), d, event, date, by, why)
    if bang is not None:
        _commit([(BANG, _dump(bang))])
        e = next(x for x in bang["entries"] if x.get("dossier") == d["dossier"])
        print(f"异火榜：{e['id']} → {e['status']}")


def cmd_archive(a: argparse.Namespace) -> None:
    """手改了功法或修订了一团火（本火修订，不走炼档）之后补存档；已经存过的不动。"""
    print(f"存档 {archive(gongfa_raw())}")
    print(f"分析实例的功法 → 存档 {sync_engine(gongfa_raw())}")


def cmd_status(a: argparse.Namespace) -> None:
    for p in sorted(DOSSIERS.glob("[0-9][0-9][0-9]-*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if a.no and d["dossier"] != a.no:
            continue
        step = lh.next_step(d) if d.get("generated") else None
        hint = f"下一步：{step}" if step else ("手写（首炼）" if not d.get("generated") else "")
        print(f"{d['dossier']} {d['title']}：{d['status']}  {hint}")
    if a.no:
        return
    for e in ho.ready_to_import(_bang_doc(), _dossiers()):
        print(f"异火榜 {e['id']} {e['title']}：火位已空出，可以导入（先在方案分析里做一次入位复核，再 import）")


def cmd_render(a: argparse.Namespace) -> None:
    print(f"→ {save(load(a.no)).with_suffix('.md').relative_to(ROOT)}")


def _dossiers() -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(DOSSIERS.glob("[0-9][0-9][0-9]-*.json"))]


def _bang_doc() -> dict[str, Any]:
    src = BANG if BANG.exists() else BANG_SEED
    doc: dict[str, Any] = json.loads(src.read_text(encoding="utf-8"))
    return doc


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def _commit(writes: list[tuple[Path, str]]) -> None:
    """原子写入（12 §2.1 第 7 步）：先全部写临时文件，都成功了再逐个改名；任何一步失败不留半份。"""
    tmps: list[tuple[Path, Path]] = []
    try:
        for path, text in writes:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            tmps.append((Path(tmp), path))
    except BaseException:
        for t, _ in tmps:
            t.unlink(missing_ok=True)
        raise
    for t, path in tmps:
        os.replace(t, path)


def _updates_for(h: dict[str, Any], only: set[str] | None) -> list[dict[str, Any]]:
    """--only 时只写这几个候选的榜更新：add 看 note 里的候选号，set_status 跟着同一条目的 add_run。"""
    if only is None:
        return list(h["bang_updates"])
    owner: dict[str, str] = {}
    for u in h["bang_updates"]:
        if u["op"] == "add_run" and u["run"].get("candidate"):
            owner[u["id"]] = u["run"]["candidate"]
    out = []
    for u in h["bang_updates"]:
        cid = str(u.get("note", "")).removeprefix("候选 ") if u["op"] == "add" else owner.get(str(u.get("id")))
        if cid in only:
            out.append(u)
    return out


QUEUED = "已交实现线（排队：等模块槽释放）"


def cmd_import(a: argparse.Namespace) -> None:
    """方案分析的交接包 → 炼档：校验、火位锁、入位复核、开档到“入位”、清单草稿、异火榜（12 §2.1）。"""
    h = json.loads(Path(a.handoff).read_text(encoding="utf-8"))
    errs = ho.check(h)
    if errs:
        raise SystemExit("拒导入：\n  " + "\n  ".join(errs))
    g = gongfa_raw()
    if h["basis"]["gongfa_digest"] != gongfa_digest(g):
        print("功法摘要与交接包的依据不同：做入位复核")
    only = set(a.only) if a.only else None
    items = [it for it in h["items"] if only is None or it["candidate"] in only]
    if only and len(items) != len(only):
        raise SystemExit(f"交接包里没有 {sorted(only - {it['candidate'] for it in items})}")
    locks = ho.slot_locks(_dossiers())
    queued, ready = [], []
    for it in items:
        held = [f"{s}（炼档 {locks[s]}）" for s in ho.slots_of(it) if s in locks]
        if held and not a.queue:
            raise SystemExit(f"拒导入 {it['candidate']}：火位被在途炼档占着 {held}；加 --queue 只记进异火榜排队")
        problems = ho.recheck(it["placement"], g)
        if problems:
            raise SystemExit(f"拒导入 {it['candidate']}：入位复核不过 {problems}；请以“重新入位”模式只重跑映射")
        (queued if held else ready).append(it)
    writes: list[tuple[Path, str]] = []
    numbers: dict[str, str] = {}
    n = int(next_no())
    for it in ready:
        no = f"{n:03d}"
        n += 1
        d = ho.to_dossier(it, no, run=h["run"], provenance=it["essence"]["provenance"], by=h["decided_by"])
        numbers[it["candidate"]] = no
        writes.append((DOSSIERS / f"{no}-{d['name']}.json", _dump(d)))
        writes.append((DOSSIERS / f"{no}-{d['name']}.md", lh.render(d)))
        for f, _ in lh.members(d):
            dest = PKG / "fires" / f"{f['id']}.json"
            if dest.exists() and json.loads(dest.read_text(encoding="utf-8")) != f:
                raise SystemExit(f"{dest} 已有一份不同的清单：同 id 的火改了就升 ver、另开一份")
            writes.append((dest, _dump(f)))
    updates = copy.deepcopy(_updates_for(h, only))  # 下面改说明，不动交接包本身
    queue_ids = {it["candidate"] for it in queued}
    for u in updates:
        if u["op"] == "set_status" and u.get("status") == "handed_off":
            cid = next(
                (x["run"].get("candidate") for x in updates if x["op"] == "add_run" and x["id"] == u["id"]), None
            )
            if cid in queue_ids:
                u["note"] = QUEUED
        elif u["op"] == "add" and str(u.get("note", "")).removeprefix("候选 ") in queue_ids:
            u["entry"]["history"][-1]["note"] = QUEUED
    bang = ho.apply_bang(_bang_doc(), updates, a.date or _today(), numbers)
    writes.append((BANG, _dump(bang)))
    _commit(writes)
    for it in ready:
        print(f"导入 {it['candidate']} → 炼档 {numbers[it['candidate']]}（入位）；下一步：开设计 PR，裁决后 approve")
    for it in queued:
        print(f"{it['candidate']} 排队：火位被占，只记进异火榜")
    print(f"异火榜 → {BANG.relative_to(ROOT)}（{len(updates)} 条更新）")


def cmd_bang(a: argparse.Namespace) -> None:
    doc = _bang_doc()
    if a.action == "show":
        for e in sorted(doc["entries"], key=lambda e: -float(e.get("priority", 0))):
            print(f"{e['id']} {e['title']}：{e['status']}（{e['slot']}，P={e.get('priority', '—')}）")
        return
    if not a.file:
        raise SystemExit("bang apply 要给交接包或更新列表")
    src = json.loads(Path(a.file).read_text(encoding="utf-8"))
    updates = src["bang_updates"] if isinstance(src, dict) else src
    _commit([(BANG, _dump(ho.apply_bang(doc, updates, a.date or _today())))])
    print(f"异火榜 → {BANG.relative_to(ROOT)}（{len(updates)} 条更新）")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="lianhua", description="炼化命令：识火、萃意、入位、验体、融火、定阶、散火")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new", help="① 识火：开一份炼档")
    p.add_argument("name", help="短名（英文，连字符）")
    p.add_argument("--no", help="档号；缺省取下一个")
    p.add_argument("--date")
    p.add_argument("--origin", choices=list(lh.ORIGINS), help="出身：自炼、手工、修订")
    for k in ("title", "source", "phenomenon", "gap", "is_fire"):
        p.add_argument("--" + k.replace("_", "-"), dest=k, required=True)
    p.set_defaults(fn=cmd_new)
    p = sub.add_parser("cuiyi", help="② 萃意：火意与融合假设")
    p.add_argument("no")
    for k in lh.CUIYI:
        p.add_argument("--" + k)
    p.set_defaults(fn=cmd_cuiyi)
    p = sub.add_parser("ruwei", help="③ 入位：清单草稿、替换谁、各臂、预登记读数")
    p.add_argument("no")
    p.add_argument("--fire", required=True, help="清单草稿（Fire 形状的 JSON 文件）")
    p.add_argument("--replaces")
    p.add_argument("--arm", action="append", default=[], help="臂=说明，臂取 B、B1、A1、F、A0")
    p.add_argument("--reading", action="append", default=[], help="一维读数（JSON）")
    p.add_argument("--readings", help="读数表（JSON 列表文件）")
    p.add_argument("--preregistered")
    p.add_argument("--parity", choices=list(lh.PARITY), help="原形臂的条件对等声明（写下之后不能改）")
    p.add_argument("--parity-reason", help="条件不对等的原因")
    p.set_defaults(fn=cmd_ruwei)
    p = sub.add_parser("plan", help="预登记试火计划（设计裁决之前；登记之后不能改）")
    p.add_argument("no")
    p.add_argument("--file", required=True, help="试火计划（JSON）")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("approve", help="设计 PR 的裁决：值得炼")
    p.add_argument("no")
    p.add_argument("--by", required=True)
    p.add_argument("--date")
    p.add_argument("--note")
    p.add_argument("--waive-gate", help="条件不对等且对原形有利时，对这一份炼档写下的豁免理由：原形门降为参考")
    p.set_defaults(fn=cmd_approve)
    p = sub.add_parser("yanti", help="④ 验体：体质改动行数、静态验体、换上这团火跑体质试炼")
    p.add_argument("no")
    p.add_argument("--base", default="origin/main")
    p.add_argument("--skip-trials", action="store_true")
    p.set_defaults(fn=cmd_yanti)
    p = sub.add_parser("ronghuo", help="⑤ 融火：填各臂读数、判结局")
    p.add_argument("no")
    p.add_argument("--set", action="append", default=[], help="维:臂=值")
    p.add_argument("--values", help="读数（JSON：维 → {臂: 值}）")
    p.add_argument("--run-tests", action="store_true", help="出处是测试的读数：换上这团火跑一遍，过了 F=1")
    p.add_argument("--record", help="试火记录（JSON）：要试火计划的炼档，读数只从它读入")
    p.set_defaults(fn=cmd_ronghuo)
    p = sub.add_parser("jue", help="定阶：记裁决；收下时改功法、上一团火进常设留出")
    p.add_argument("no")
    p.add_argument("--by", required=True)
    p.add_argument("--outcome", required=True, choices=list(lh.OUTCOMES))
    p.add_argument("--condition", action="append", default=[])
    p.add_argument("--date")
    p.add_argument("--record", help="试火记录（JSON）：定阶之前核它的哈希并重算结局")
    p.set_defaults(fn=cmd_jue)
    p = sub.add_parser("sanhuo", help="⑥ 散火：火位指回上一团火")
    p.add_argument("no")
    p.add_argument("--by", required=True)
    p.add_argument("--why", required=True)
    p.add_argument("--date")
    p.set_defaults(fn=cmd_sanhuo)
    p = sub.add_parser("archive", help="把此刻的功法存档（在跑的题按开题时的那一版取功法，FJ6）")
    p.set_defaults(fn=cmd_archive)
    p = sub.add_parser("status", help="每份炼档走到哪一步")
    p.add_argument("no", nargs="?")
    p.set_defaults(fn=cmd_status)
    p = sub.add_parser("render", help="由 JSON 重新生成 .md")
    p.add_argument("no")
    p.set_defaults(fn=cmd_render)
    p = sub.add_parser("import", help="方案分析的交接包 → 炼档（入位状态）、清单草稿、异火榜")
    p.add_argument("handoff")
    p.add_argument("--only", action="append", help="只导入这个候选（可多次）")
    p.add_argument("--queue", action="store_true", help="火位被占时只记进异火榜排队，不拒")
    p.add_argument("--date")
    p.set_defaults(fn=cmd_import)
    p = sub.add_parser("bang", help="异火榜：show 列出；apply 按交接包或更新列表写入")
    p.add_argument("action", choices=["show", "apply"])
    p.add_argument("file", nargs="?")
    p.add_argument("--date")
    p.set_defaults(fn=cmd_bang)
    return ap


def main(argv: list[str]) -> int:
    a = parser().parse_args(argv)
    try:
        a.fn(a)
    except (lh.StepError, ho.ImportRefused) as e:
        print(f"做不了：{e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
