"""炼化命令（焚决 F5）：一次吞噬从识火走到定阶或散火，每一步一条命令，炼档的 .json 与 .md 都由命令写。

    uv run python scripts/lianhua.py new <短名> --title … --source … --phenomenon … --gap … --is-fire …
    uv run python scripts/lianhua.py cuiyi <档号> --yi … --premise … --cost … --overlap … --conflict … \\
        --hypothesis … --split … --masked …
    uv run python scripts/lianhua.py ruwei <档号> --fire 清单草稿.json [--replaces 上一团火] \\
        --arm B=… --arm A1=… --arm F=… --arm B1=… --reading '{"dim":…,"kind":"新生","dir":"up","gate":1,"test":…}'
    uv run python scripts/lianhua.py approve <档号> --by cz            # 设计 PR 裁决：值得炼
    uv run python scripts/lianhua.py yanti <档号> [--base origin/main]   # 体质改动行数、静态验体、换上这团火跑 T1–T5
    uv run python scripts/lianhua.py ronghuo <档号> --set '维:F=1' … [--run-tests]   # 填读数、判结局
    uv run python scripts/lianhua.py jue <档号> --by cz --outcome huolian [--condition …]   # 定阶，改功法
    uv run python scripts/lianhua.py sanhuo <档号> --by cz --why …     # 散火：火位指回上一团火
    uv run python scripts/lianhua.py status [<档号>]                    # 每份炼档走到哪一步、下一步是什么
    uv run python scripts/lianhua.py render <档号>                      # 由 JSON 重新生成 .md

数据操作都在 paoding_fenjue.lianhua（纯函数，有单测）；这里只读写文件、跑 git 与测试。
入位时清单草稿写进 fenjue/src/paoding_fenjue/fires/<id>.json（还不在功法里，开关缺省关）；定阶时才改 gongfa.json。
不读本机题库与校准目录：试火的读数由 --set 填（来自可插拔的炉题数据源或 CI 里的结构测试），命令不去找数据。
"""

from __future__ import annotations

import argparse
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
from paoding_fenjue.contract import check

ROOT = Path(__file__).resolve().parents[1]
DOSSIERS = ROOT / "docs" / "design" / "fenjue" / "dossiers"
PKG = ROOT / "fenjue" / "src" / "paoding_fenjue"
GONGFA = PKG / "gongfa.json"


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
    out = _git("diff", "--numstat", base, "--", *lh.KERNEL_PATHS)
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
    d = lh.new(a.no or next_no(), a.name, a.title, a.date or _today(), shihuo)
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
    d = lh.ruwei(d, f, a.replaces, _kv(a.arm), readings, a.preregistered or "")
    dest = PKG / "fires" / f"{f['id']}.json"
    if dest.exists() and json.loads(dest.read_text(encoding="utf-8")) != f:
        raise SystemExit(f"{dest.relative_to(ROOT)} 已有一份不同的清单：同 id 的火改了就升 ver、另开一份")
    _write_json(dest, f)
    print(f"入位 → {save(d).relative_to(ROOT)}；清单草稿 → {dest.relative_to(ROOT)}（不在功法里）")
    print("前三节写完了：开设计 PR 交裁决，通过后 approve")


def cmd_approve(a: argparse.Namespace) -> None:
    d = lh.approve_design(load(a.no), a.by, a.date or _today(), a.note or "")
    print(f"设计已裁 → {save(d).relative_to(ROOT)}；下一步：yanti {d['dossier']}")


def cmd_yanti(a: argparse.Namespace) -> None:
    d = load(a.no)
    on_disk = PKG / "fires" / f"{d['fire']['id']}.json"
    f = json.loads(on_disk.read_text(encoding="utf-8")) if on_disk.exists() else d["fire"]
    errs = static_errors(f)
    n = kernel_lines(a.base)
    cand = candidate(d)
    trials: dict[str, dict[str, Any]] = {}
    for t in lh.TRIALS:
        if a.skip_trials:
            trials[t] = {"ok": False, "summary": "没跑（--skip-trials）"}
            continue
        ok, summary = _run([sys.executable, "tests/fenjue/trials.py", "--gongfa", str(cand), t], None)
        trials[t] = {"ok": ok, "summary": summary}
        print(f"{t}：{'过' if ok else '不过'}  {summary}")
    d = lh.yanti(d, n, errs, trials, _git("rev-parse", "--short", "HEAD"))
    print(
        f"体质改动行数 {n}；静态验体 {'全过' if not errs else errs}；验体{'通过' if d['yanti']['passed'] else '不过'}"
    )
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
    if a.run_tests:  # 结构读数：出处测试在换上这团火的功法下过了，合火臂即 1
        cand = candidate(d)
        for r in d["readings"]:
            if r.get("test") and "F" not in values.get(r["dim"], {}):
                ok, summary = _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", r["test"]], cand)
                values.setdefault(r["dim"], {})["F"] = 1 if ok else 0
                print(f"{r['dim']}：F={'1' if ok else '0'}  {summary}")
    d = lh.ronghuo(d, values, gongfa_raw()["jie"])
    print(f"结局提议：{lh.OUTCOMES[d['outcome_proposed']]}；品阶提议：{d['jie_proposed']}")
    for w in d["outcome_why"]:
        print("  " + w)
    print(f"融火 → {save(d).relative_to(ROOT)}；交裁决：jue {d['dossier']} --by … --outcome …")


def cmd_jue(a: argparse.Namespace) -> None:
    d, g = lh.jue(load(a.no), gongfa_raw(), a.by, a.date or _today(), a.outcome, a.condition)
    save(d)
    if g != gongfa_raw():
        _write_json(GONGFA, g)
        print(f"功法 → 第 {g['jie']} 阶；{d['fire']['slot']} = {g['fires'][d['fire']['slot']]}")
    print(f"裁决：{lh.OUTCOMES[a.outcome]} → {path_of(d['dossier']).relative_to(ROOT)}")


def cmd_sanhuo(a: argparse.Namespace) -> None:
    d, g = lh.sanhuo(load(a.no), gongfa_raw(), a.by, a.date or _today(), a.why)
    save(d)
    _write_json(GONGFA, g)
    print(f"散火：{d['fire']['slot']} = {g['fires'][d['fire']['slot']]}；功法 → 第 {g['jie']} 阶")


def cmd_status(a: argparse.Namespace) -> None:
    for p in sorted(DOSSIERS.glob("[0-9][0-9][0-9]-*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if a.no and d["dossier"] != a.no:
            continue
        step = lh.next_step(d) if d.get("generated") else None
        hint = f"下一步：{step}" if step else ("手写（首炼）" if not d.get("generated") else "")
        print(f"{d['dossier']} {d['title']}：{d['status']}  {hint}")


def cmd_render(a: argparse.Namespace) -> None:
    print(f"→ {save(load(a.no)).with_suffix('.md').relative_to(ROOT)}")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="lianhua", description="炼化命令：识火、萃意、入位、验体、融火、定阶、散火")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new", help="① 识火：开一份炼档")
    p.add_argument("name", help="短名（英文，连字符）")
    p.add_argument("--no", help="档号；缺省取下一个")
    p.add_argument("--date")
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
    p.set_defaults(fn=cmd_ruwei)
    p = sub.add_parser("approve", help="设计 PR 的裁决：值得炼")
    p.add_argument("no")
    p.add_argument("--by", required=True)
    p.add_argument("--date")
    p.add_argument("--note")
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
    p.set_defaults(fn=cmd_ronghuo)
    p = sub.add_parser("jue", help="定阶：记裁决；收下时改功法、上一团火进常设留出")
    p.add_argument("no")
    p.add_argument("--by", required=True)
    p.add_argument("--outcome", required=True, choices=list(lh.OUTCOMES))
    p.add_argument("--condition", action="append", default=[])
    p.add_argument("--date")
    p.set_defaults(fn=cmd_jue)
    p = sub.add_parser("sanhuo", help="⑥ 散火：火位指回上一团火")
    p.add_argument("no")
    p.add_argument("--by", required=True)
    p.add_argument("--why", required=True)
    p.add_argument("--date")
    p.set_defaults(fn=cmd_sanhuo)
    p = sub.add_parser("status", help="每份炼档走到哪一步")
    p.add_argument("no", nargs="?")
    p.set_defaults(fn=cmd_status)
    p = sub.add_parser("render", help="由 JSON 重新生成 .md")
    p.add_argument("no")
    p.set_defaults(fn=cmd_render)
    return ap


def main(argv: list[str]) -> int:
    a = parser().parse_args(argv)
    try:
        a.fn(a)
    except lh.StepError as e:
        print(f"做不了：{e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
