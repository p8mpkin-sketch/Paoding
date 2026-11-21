"""三个验收用例在真外部系统上试算（docs/design/fenjue/13-kernel.md §7；手册 scripts/trial/README.md）。

    python scripts/trial/trial.py setup  --url http://127.0.0.1:8200 --token-file ~/paoding-analysis/human.token
    python scripts/trial/trial.py open   --url … --token-file … [--cases scripts/trial/cases.json] [--only trial-b]
    python scripts/trial/trial.py report --url … --home ~/paoding-analysis

setup：写一版设置：关开放道复核（cz 2026-11-21 接受的建议），把 codeload.github.com:443 的连接标成 r1（要人批）。
open：每个用例先钉住提交（`git ls-remote`，标签取它指向的提交），再经 GitHub 的接口核对许可证；许可证不清楚
（没有、NOASSERTION、OTHER）的不开题。然后在你这边下载那个提交的源码归档，以试算模式随题上传开题（scripts/tunshi.py）；
执行层（M0）只能连本机的题目容器、连不了互联网上的主机，所以缺省不让分析会话自己去抓（--via repo 才那样做）。
钉住的提交、许可证与归档的摘要记在 <当前目录>/trial-record.json。重跑用 --tag 换题号。
report：读每道题的交付、花费与导出的工作区，写 trial-report.md（读数回给 Claude 整理）。

只用标准库；在你自己的电脑上跑，联网（git、api.github.com）也在你这边。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
UNCLEAR = {None, "", "NOASSERTION", "OTHER"}
RISK_ROW = {"resource": "net", "pattern": "codeload.github.com:443", "actions": ["connect"], "risk": "r1"}
SHA = re.compile(r"^[0-9a-f]{40}$")


def http(url: str, method: str = "GET", body: object = None, token: str | None = None) -> dict:
    headers = {"User-Agent": "paoding-trial", "Accept": "application/json"}
    data = None
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out: dict = json.loads(r.read())
            return out
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {url} 被拒：{e.code} {e.read().decode('utf-8', 'replace')[:400]}") from None


def token_of(path: str) -> str:
    return Path(path).expanduser().read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------- setup


def setup(a: argparse.Namespace) -> int:
    tok = token_of(a.token_file)
    doc = http(a.url + "/v1/settings", token=tok)
    s = doc["settings"]
    s["lanes"] = {**s.get("lanes", {"open": True}), "review": False}
    s["risk"] = [RISK_ROW, *[r for r in s.get("risk", []) if r["pattern"] != RISK_ROW["pattern"]]]
    s.setdefault("grants", {"runtime": True, "auto": {"practice": True}})["runtime"] = True
    out = http(a.url + "/v1/settings", "PUT", {"base_digest": doc["digest"], "settings": s}, tok)
    print(
        json.dumps(
            {"ok": True, "version": out.get("version"), "lanes": s["lanes"], "risk": s["risk"][:1]}, ensure_ascii=False
        )
    )
    return 0


# ---------------------------------------------------------------- open


def pin(repo: str, ref: str | None) -> tuple[str, str]:
    """钉住提交：返回 (提交哈希, 它是怎么来的)。标签取它指向的提交（附注标签的 ^{}）。"""

    def ls(*args: str) -> list[tuple[str, str]]:
        r = subprocess.run(["git", "ls-remote", *args, repo], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise SystemExit(f"git ls-remote {repo} 失败：{r.stderr.strip()[:300]}")
        return [tuple(x.split("\t", 1)) for x in r.stdout.splitlines() if "\t" in x]  # type: ignore[misc]

    if ref and SHA.match(ref):
        return ref, f"提交 {ref[:12]}"
    if ref:
        rows = ls("--tags", "--heads")
        want = {f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}", f"refs/heads/{ref}"}
        hits = dict((n, s) for s, n in rows if n in want)
        sha = hits.get(f"refs/tags/{ref}^{{}}") or hits.get(f"refs/tags/{ref}") or hits.get(f"refs/heads/{ref}")
        if not sha:
            raise SystemExit(f"{repo} 没有 {ref} 这个标签或分支")
        return sha, f"{ref} → {sha[:12]}"
    tags = ls("--tags", "--sort=-v:refname")
    peeled = {n[: -len("^{}")]: s for s, n in tags if n.endswith("^{}")}
    for s, n in tags:
        if not n.endswith("^{}"):
            t = n.removeprefix("refs/tags/")
            return peeled.get(n, s), f"最新标签 {t} → {peeled.get(n, s)[:12]}"
    (head,) = [s for s, n in ls() if n == "HEAD"] or [None]
    if not head:
        raise SystemExit(f"{repo} 取不到 HEAD")
    return head, f"没有标签，默认分支此刻的提交 {head[:12]}"


def license_of(repo: str, sha: str) -> dict:
    m = re.match(r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", repo)
    if not m:
        raise SystemExit(f"{repo}：只认 https://github.com/<owner>/<repo>")
    try:
        doc = http(f"https://api.github.com/repos/{m[1]}/{m[2]}/license?ref={sha}")
    except SystemExit as e:
        return {"spdx": None, "detail": str(e)}
    lic = doc.get("license") or {}
    return {"spdx": lic.get("spdx_id"), "name": lic.get("name"), "path": doc.get("path"), "url": doc.get("html_url")}


ARCHIVE_MAX = 200_000_000  # 与材料定版的总字节上限一致（paoding_fenjue.engine.materials.Limits）


def download(repo: str, sha: str, cache: Path) -> tuple[Path, str]:
    """下载钉住的提交的源码归档（GitHub 的 codeload，按提交哈希取，不会漂）。已下载过、摘要对得上就不再下。"""
    m = re.match(r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", repo)
    if not m:
        raise SystemExit(f"{repo}：只认 https://github.com/<owner>/<repo>")
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / f"{m[1]}-{m[2]}-{sha[:12]}.tar.gz"
    note = f.with_suffix(".sha256")
    if f.exists() and note.exists():
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        if digest == note.read_text().strip():
            return f, digest
    url = f"https://codeload.github.com/{m[1]}/{m[2]}/tar.gz/{sha}"
    req = urllib.request.Request(url, headers={"User-Agent": "paoding-trial"})
    h, n = hashlib.sha256(), 0
    tmp = f.with_suffix(".part")
    with urllib.request.urlopen(req, timeout=300) as r, tmp.open("wb") as out:
        while chunk := r.read(1 << 20):
            n += len(chunk)
            if n > ARCHIVE_MAX:
                tmp.unlink(missing_ok=True)
                raise SystemExit(f"{repo}@{sha[:12]} 的归档超过 {ARCHIVE_MAX // 1_000_000} MB，换一个小一点的仓库")
            h.update(chunk)
            out.write(chunk)
    tmp.replace(f)
    note.write_text(h.hexdigest() + "\n")
    return f, h.hexdigest()


def open_cases(a: argparse.Namespace) -> int:
    cases = json.loads(Path(a.cases).read_text(encoding="utf-8"))["cases"]
    if a.only:
        cases = [c for c in cases if c["id"] in a.only]
    rec_path = Path("trial-record.json")
    record = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.exists() else {}
    bad = 0
    for c in cases:
        sha, how = pin(c["repo"], c.get("ref"))
        lic = license_of(c["repo"], sha)
        row = {**c, "commit": sha, "pinned": how, "license": lic, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        if lic.get("spdx") in UNCLEAR:
            row["skipped"] = "许可证不清楚，不开题"
            print(
                f"{c['id']}：{c['repo']} 的许可证不清楚（{lic}），跳过；换一个仓库或写明许可证后再开", file=sys.stderr
            )
            bad += 1
        else:
            pid = c["id"] + (f"-{a.tag}" if a.tag else "")
            row["pid"] = pid
            if a.via == "upload":  # 缺省：在你这边下载钉住的那个提交的归档，随题上传（执行层连不了互联网上的主机）
                f, digest = download(c["repo"], sha, Path(a.cache))
                row["archive"] = {"file": str(f), "sha256": digest, "bytes": f.stat().st_size}
                src = ["--upload", str(f), "--upload-origin", f"{c['repo']}@{sha}"]
            else:  # 让分析会话在沙箱里抓（要执行层能连 codeload.github.com:443）
                src = ["--repo", f"{c['repo']}@{sha}"]
            short = re.sub(r"^https://github\.com/", "", c["repo"]).rstrip("/")
            r = subprocess.run(
                [
                    sys.executable, str(HERE.parent / "tunshi.py"), "--url", a.url, "--token-file",
                    str(Path(a.token_file).expanduser()), "--pid", pid, "--title",
                    f"试算：{c['case']}（{short}@{sha[:12]}）", "--statement", c["statement"], *src,
                    "--dry-run", "--usd", str(a.usd),
                ],
                capture_output=True, text=True, timeout=600,
            )  # fmt: skip
            row["opened"] = r.returncode == 0
            if r.returncode != 0:
                row["error"] = (r.stderr or r.stdout).strip()[:500]
                bad += 1
            done = f"已开题 {pid}" if r.returncode == 0 else "开题失败：" + row["error"]
            print(f"{c['id']}：{how}，许可证 {lic['spdx']}，{done}")
        record[row.get("pid", c["id"])] = row
        rec_path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 1 if bad else 0


# ---------------------------------------------------------------- report


def report(a: argparse.Namespace) -> int:
    home = Path(a.home).expanduser()
    rec_path = Path("trial-record.json")
    record = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.exists() else {}
    lines = ["# 方案分析试算读数", "", f"生成于 {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    for pid, row in sorted(record.items()):
        lines += [f"## {pid}：{row.get('case', '')}", ""]
        lines.append(f"- 仓库：{row['repo']}，{row.get('pinned', '')}，许可证 {row.get('license', {}).get('spdx')}")
        if row.get("skipped") or not row.get("opened"):
            lines += [f"- 没开题：{row.get('skipped') or row.get('error')}", ""]
            continue
        evs = http(f"{a.url}/v1/problems/{pid}/events?after=0&limit=5000")["events"]
        budget = http(f"{a.url}/v1/problems/{pid}/budget")
        kinds: dict[str, int] = {}
        for e in evs:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        lines.append(
            f"- 花费：{budget['spent']['usd_milli'] / 1000:.3f} 美元（上限 {budget['cap']['usd_milli'] / 1000:.0f}）"
        )
        lines.append(f"- 事件：{json.dumps(kinds, ensure_ascii=False, sort_keys=True)}")
        for e in evs:
            if e["kind"] == "deliver":
                b = e.get("body") or {}
                lines.append(
                    f"- 交付（序号 {e['seq']}）：{b.get('outcome')}；需要：{'；'.join(b.get('needs') or [])[:600]}"
                )
            elif e["kind"] == "request_scope":
                rules = json.dumps(e.get("body", {}).get("rules"), ensure_ascii=False)[:300]
                lines.append(f"- 访问申请（序号 {e['seq']}）：{rules}")
        ws = home / "analyses" / pid
        run_f = ws / "run.json"
        if run_f.exists():
            run = json.loads(run_f.read_text(encoding="utf-8"))
            lines.append(f"- 工作区：步骤 {run.get('step')}，产物 {sorted(run.get('artifacts', {}))}")
            dr = (run.get("artifacts") or {}).get("dry_run.json")
            if dr and (ws / "artifacts" / f"{dr}.json").exists():
                d = json.loads((ws / "artifacts" / f"{dr}.json").read_text(encoding="utf-8"))
                lines.append(f"- 试算结论：{d.get('plain_summary')}")
                lines.append(
                    f"- 自动选中：{d.get('auto_picked')}；估算：{json.dumps(d.get('estimate'), ensure_ascii=False)}"
                )
            snap = ws / "artifacts"
            lics = set()
            for f in snap.glob("*.json"):
                try:
                    j = json.loads(f.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                if isinstance(j, dict) and isinstance(j.get("license"), dict):
                    lics.add(json.dumps(j["license"], ensure_ascii=False, sort_keys=True))
            lines.append(f"- 产物里记的许可证：{sorted(lics) or '（没找到）'}")
        else:
            lines.append("- 工作区还没导出（会话还没跑完第一轮）")
        lines.append("")
    Path("trial-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("写好了 trial-report.md")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="方案分析试算")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("setup", "open", "report"):
        p = sub.add_parser(name)
        p.add_argument("--url", required=True)
        if name != "report":
            p.add_argument("--token-file", required=True)
        else:
            p.add_argument("--home", required=True)
        if name == "open":
            p.add_argument("--cases", default=str(HERE / "cases.json"))
            p.add_argument("--only", action="append", default=[])
            p.add_argument("--usd", type=float, default=20, help="每道题的预算（美元）〔占位〕；试算只用其中一半的份额")
            p.add_argument(
                "--via",
                choices=("upload", "repo"),
                default="upload",
                help="upload（缺省）：在你这边下载钉住的提交的归档随题上传；repo：让分析会话在沙箱里抓（执行层要能连外网）",
            )
            p.add_argument("--tag", default="", help="题号后缀：重跑时题号不能重复，例如 --tag 2 开出 trial-a-2")
            p.add_argument("--cache", default="trial-cache", help="下载的归档放在这里（可重复使用）")
    a = ap.parse_args()
    return {"setup": setup, "open": open_cases, "report": report}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
