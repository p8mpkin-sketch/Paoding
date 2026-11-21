"""开一道方案分析（docs/design/fenjue/13-kernel.md §7）：经 HTTP 向分析实例登记材料与立项单，然后开题。

    python scripts/tunshi.py --url http://127.0.0.1:8100 --token-file <home>/human.token --pid a1 \
        --statement "看看这个系统里有什么值得我们集成的做法" \
        [--repo https://github.com/o/r@<提交或标签>]... [--doc https://…]... \
        [--upload 归档或文件 [--upload-origin https://github.com/o/r@<提交>]]... \
        [--service https://… --probe-plan 计划文件] [--dry-run] [--usd 20]

只上传材料、不要别的模式时不必用它：界面上照常开题、附上材料就行，立项单按材料推出（正式模式、每份材料一个来源）。
要地址类来源（仓库要写提交或标签）、试算模式时用它：它把立项单作为一份材料随题登记，宿主与引擎都以它为准。
开题之后的事都在界面上做：批取材的访问申请、在每次交付后用追问回答确认、看报告与产物。

只用标准库与 paoding_fenjue.contract（在本地先校验立项单，不合用就不开题）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from paoding_fenjue.contract import analysis

DOCS_SUFFIX = (".md", ".txt", ".pdf", ".html", ".htm")
MEDIA = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".htm": "text/html",
    ".zip": "application/zip",
    ".tar": "application/x-tar",
    ".gz": "application/gzip",
    ".tgz": "application/gzip",
}
DEFAULT_USD = 20  # 〔占位〕一次分析的预算（美元）；按档位的预算先验接进来之前由开题的人定


def call(url: str, path: str, token: str, body: object = None, raw: bytes | None = None) -> dict:
    data = raw if raw is not None else json.dumps(body).encode()
    req = urllib.request.Request(
        url + path,
        data=data,
        method="PUT" if raw is not None else "POST",
        headers={
            "Content-Type": "application/octet-stream" if raw is not None else "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out: dict = json.loads(r.read())
            return out
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{path} 被拒：{e.code} {e.read().decode('utf-8', 'replace')[:500]}") from None


def register(url: str, token: str, pid: str, data: bytes, media: str, n: int) -> str:
    h = call(url, "/v1/blobs", token, raw=data)["hash"]
    body = {"problem_id": pid, "idem_key": f"in-{pid}-{n}", "hash": h, "size": len(data), "media_type": media}
    out = call(url, "/v1/artifacts", token, {**body, "class": "input"})
    if not out.get("ok"):
        raise SystemExit(f"材料登记被拒：{json.dumps(out, ensure_ascii=False)}")
    return str(out["id"])


def split_repo(v: str) -> tuple[str, str]:
    """`<地址>@<提交或标签>`：取最后一个 @ 之后的部分（地址里的 @ 只会在用户信息里，宿主本来就拒）。"""
    u, sep, ref = v.rpartition("@")
    if not sep or not u or not ref:
        raise SystemExit(f"--repo 写成 <地址>@<提交或标签>，不抓默认分支：{v}")
    return u, ref


def build(a: argparse.Namespace, uploads: list[tuple[str, str]]) -> dict:
    sources: list[dict] = []
    origins = list(getattr(a, "upload_origin", None) or [])
    if len(origins) > len(uploads):
        raise SystemExit("--upload-origin 比 --upload 多：每个出处对应前面同一位置的一个上传")
    for i, (aid, form) in enumerate(uploads):
        src = {"no": len(sources) + 1, "form": form, "via": "upload", "artifact": aid}
        if i < len(origins):  # 上传的归档从哪来（仓库地址与钉住的提交）：记进立项单，产物与界面能标明来源
            src["url"], src["ref"] = split_repo(origins[i])
        sources.append(src)
    for v in a.repo:
        u, ref = split_repo(v)
        sources.append({"no": len(sources) + 1, "form": "code", "via": "repo_url", "url": u, "ref": ref})
    for u in a.doc:
        sources.append({"no": len(sources) + 1, "form": "docs", "via": "doc_url", "url": u})
    if a.service:
        if not a.probe_plan:
            raise SystemExit("--service 要配 --probe-plan（每行一条 GET /路径，访问申请卡上逐条给人看）")
        plan = Path(a.probe_plan).read_text(encoding="utf-8")
        sources.append(
            {"no": len(sources) + 1, "form": "service", "via": "service_url", "url": a.service, "probe_plan": plan}
        )
    if not sources:
        sources.append({"no": 1, "form": "description", "via": "statement"})
    return {
        "v": 1,
        "mode": "dry_run" if a.dry_run else "formal",
        "statement": a.statement.strip()[:1000],
        "sources": sources,
        "requested_by": a.by,
        "date": time.strftime("%Y-%m-%d"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="开一道方案分析")
    ap.add_argument("--url", required=True)
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--pid", required=True)
    ap.add_argument("--statement", required=True, help="想看这个系统的什么（原话）")
    ap.add_argument("--title", default="")
    ap.add_argument("--repo", action="append", default=[], help="<仓库地址>@<提交或标签>，可重复")
    ap.add_argument("--doc", action="append", default=[], help="文档地址，可重复")
    ap.add_argument("--upload", action="append", default=[], help="本地的归档或文件，可重复")
    ap.add_argument(
        "--upload-origin",
        action="append",
        default=[],
        help="<仓库地址>@<提交>：第 N 个对应第 N 个 --upload，记下那份归档的出处（只登记，不去抓）",
    )
    ap.add_argument("--service")
    ap.add_argument("--probe-plan")
    ap.add_argument("--dry-run", action="store_true", help="试算模式：预算减半，自动取前三个候选")
    ap.add_argument("--usd", type=float, default=DEFAULT_USD)
    ap.add_argument("--by", default="cz")
    a = ap.parse_args()
    if not a.statement.strip():
        raise SystemExit("--statement 不能是空的")
    token = Path(a.token_file).read_text(encoding="utf-8").strip()
    n, uploads = 0, []
    for f in a.upload:
        p = Path(f)
        n += 1
        media = MEDIA.get(p.suffix.lower(), "application/octet-stream")
        aid = register(a.url, token, a.pid, p.read_bytes(), media, n)
        uploads.append((aid, "docs" if p.suffix.lower() in DOCS_SUFFIX else "code"))
    doc = build(a, uploads)
    errs = analysis.intake_errors(doc, {aid for aid, _ in uploads})
    if errs:
        raise SystemExit("立项单不合用：" + "；".join(errs))
    n += 1
    iid = register(a.url, token, a.pid, json.dumps(doc, ensure_ascii=False).encode(), analysis.INTAKE_MEDIA, n)
    st = a.statement.strip().encode()
    h = call(a.url, "/v1/blobs", token, raw=st)["hash"]
    body = {
        "title": a.title or "方案分析",
        "origin": {"statement_ref": "$0", "materials": [aid for aid, _ in uploads] + [iid]},
        "goal": {"statement": a.statement.strip(), "accept": "open"},
        "scope": [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}],
        "budget": {"usd_milli": int(a.usd * 1000), "wall_s": 14_400, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic", "baseline_ref": "base@1"},
        "judges": [],
    }
    reg = {
        "op": "register_artifact",
        "body": {"hash": h, "size": len(st), "media_type": "text/plain; charset=utf-8", "class": "input"},
    }
    out = call(
        a.url,
        "/v1/problems",
        token,
        {"id": a.pid, "idem_key": f"open-{a.pid}", "ops": [reg, {"op": "open_problem", "body": body}]},
    )
    print(
        json.dumps(
            {"ok": out.get("ok"), "pid": a.pid, "intake": doc, "detail": None if out.get("ok") else out},
            ensure_ascii=False,
        )
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
