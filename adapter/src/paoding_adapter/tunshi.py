"""方案分析会话的宿主工具（docs/design/fenjue/13-kernel.md §4）：`intake`、`fetch`、`check`，与交付前的一道闸。

方案分析会话里跑的是固定流程的驱动程序（`tunshi_cli.py`，在模型容器里），不是自由对话的智能体。驱动程序只有
任务令牌与这几个工具；凡是碰信任边界的动作都在这里、在宿主一侧做，驱动程序说什么都只是请求：

- `intake`：这道题的简报。立项单以事件账为准（随题登记的那份，或按材料推出的缺省），材料的原始字节从 Blob 仓库
  原样拷进工作区（宿主不解析外部归档，解包在容器里做），再带上追问、预算、还能接力几次、各档位的模型与价；
- `fetch`：抓一个地址类来源。入参只有来源编号：抓哪个地址、连哪个 host:port 由宿主从事件账里的立项单推出，
  驱动程序给不了地址。没有授权就提扩权申请（走运行时扩权那条路，人在卡上批），批下来后在沙箱里跑一条固定的
  下载命令（Python 标准库，不跟到别的主机，有大小上限），留下 exec 类的执行留档；
- `check`：把一份结构化产物登记成 Artifact 之前的检查。读工作区里的文件，核对文件名里的摘要、产物的 Schema、
  有没有带着原话里的凭据，过了才登记（authored 类）；
- 交付闸：分析会话的 `deliver` 多收一栏 `artifacts`，里面的编号必须是这道题经 `check` 登记过的产物。

宿主不调模型、不读外部材料的内容、不替引擎做任何判断；引擎的六步在驱动程序里，后三步是确定性代码。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlsplit

from paoding_fenjue.contract import analysis, digest, materials, source_refusal
from paoding_graph.contract import BadBody, Obj

from . import creds

if TYPE_CHECKING:
    from .tools import ToolHost

PRODUCT_MEDIA = "application/vnd.paoding.fenjue.product+json"
OPEN_RELAYS = 5  # 与内核 work.OPEN_RELAYS 同值（契约没有导出它；tests/integration/test_tunshi.py 守着两边相等）
INTAKE_BYTES = 256 * 1024
PRODUCT_BYTES = 4 * 1024 * 1024
FETCH_BYTES = materials.Limits().total_bytes  # 一份抓取的归档至多这么大
PROBE_ITEMS, PROBE_BODY = 20, 256 * 1024
FETCH_TIMEOUT_S = 600
FETCH_MAX, CHECK_MAX = 16, 400  # 一个会话至多真的下载这么多次、登记这么多份产物
FETCH_DIR = f"{analysis.MATERIALS}/fetch"
# 执行层（M0）只能连本机的题目容器，连不了互联网上的主机：那时请人把定版的归档下载下来随题上传
UPLOAD_INSTEAD = "可以把这个版本的归档下载下来随题上传（scripts/trial/trial.py 缺省就这样开题），再追问一句“继续”"
_REF = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
_NAME = re.compile(r"^[A-Za-z0-9_.:\-]{1,80}$")
_PRODUCT_PATH = re.compile(rf"^{analysis.ANALYSIS}/artifacts/([0-9a-f]{{64}})\.json$")
_PROBE_LINE = re.compile(r"^GET\s+(/[^\s]{0,500})$")
_ARCHIVES = (".tar.gz", ".tgz", ".zip")

# 沙箱里跑的下载程序。只用标准库；不走环境里的代理；跳转只跟同一个 host:port（别的主机没有授权，也连不到）；
# 超过上限就停。末行输出一个 JSON 对象，宿主据此判断成没成，再自己核一遍文件。
FETCH_PY = r"""
import hashlib, json, sys, urllib.error, urllib.parse, urllib.request

def site(u):
    p = urllib.parse.urlsplit(u)
    return (p.scheme, p.hostname, p.port or (443 if p.scheme == "https" else 80))

class Same(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if site(newurl) != site(req.full_url):
            raise urllib.error.HTTPError(req.full_url, code, "redirect to " + newurl[:200], headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Same)
opener.addheaders = [("user-agent", "paoding-fetch/1"), ("accept", "*/*")]

def get(url, cap, sink):
    n, h = 0, hashlib.sha256()
    with opener.open(url, timeout=60) as r:
        status, ctype = r.status, r.headers.get("content-type", "")
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            n += len(chunk)
            if n > cap:
                raise ValueError("larger than %d bytes" % cap)
            h.update(chunk)
            sink(chunk)
    return status, ctype, n, h.hexdigest()

def main():
    mode = sys.argv[1]
    if mode == "file":
        url, dest, cap = sys.argv[2], sys.argv[3], int(sys.argv[4])
        with open(dest, "wb") as f:
            status, ctype, n, sha = get(url, cap, f.write)
        return {"ok": True, "status": status, "size": n, "sha256": sha}
    plan_path, out_path, cap = sys.argv[2], sys.argv[3], int(sys.argv[4])
    plan = json.load(open(plan_path, encoding="utf-8"))
    rows = []
    for item in plan["items"]:
        buf = []
        row = {"item": item["no"]}
        try:
            status, ctype, n, sha = get(plan["base"].rstrip("/") + item["path"], cap, buf.append)
            raw = b"".join(buf)
            row.update(status=status, content_type=ctype[:100], sha256=sha)
        except urllib.error.HTTPError as e:
            raw = e.read(cap) or b""
            row.update(status=e.code, error=str(e.reason)[:200])
        except Exception as e:
            raw = b""
            row.update(status=0, error=(type(e).__name__ + ": " + str(e))[:200])
        text = raw.decode("utf-8", "replace")
        try:
            row["body"] = json.loads(text)
        except ValueError:
            row["body"] = text
        rows.append(row)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"responses": rows}, f, ensure_ascii=False, indent=1, sort_keys=True)
    return {"ok": True, "items": len(rows)}

try:
    out = main()
except urllib.error.HTTPError as e:
    out = {"ok": False, "detail": "HTTP %s %s" % (e.code, str(e.reason)[:200])}
except Exception as e:
    out = {"ok": False, "detail": (type(e).__name__ + ": " + str(e))[:300]}
print(json.dumps(out))
sys.exit(0 if out.get("ok") else 1)
"""


@dataclass
class Analysis:
    """一个方案分析会话在宿主一侧的状态。profile：组装根给的“这道题的分析参数”（榜、火位锁、痛点、金丝雀、
    各档位的模型与单价、等人批的时限），都是配置层的数据，不从会话里来。"""

    form_ref: str
    profile: Callable[[str], Mapping[str, Any]] = lambda pid: {}
    phase: str | None = None  # 收尾轮：budget（软线，立即交付）| relay（上一轮没交付就结束了）
    fetches: int = 0
    checks: int = 0
    checked: set[str] = field(default_factory=set)


def is_product(art: Mapping[str, Any] | None, pid: str) -> bool:
    return art is not None and art["problem_id"] == pid and art.get("media_type") == PRODUCT_MEDIA


# ---------------------------------------------------------------- 立项单与材料（以事件账为准）


def _media(a: Mapping[str, Any]) -> str:
    return str(a.get("media_type", "")).split(";")[0].strip().lower()


def intake_of(h: ToolHost) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
    """这道题的立项单：随题登记的那一份（媒体类型为立项单的材料），没有就按材料推出缺省。
    返回 (立项单或 None, 不合用的原因, 其余材料 id → Artifact)。同一道题每次算出来都一样：只读开题事件里的东西。"""
    st = h.reader.state
    p, arts = st["problems"][h.s.pid], st["artifacts"]
    given: Mapping[str, Any] | None = None
    mats: dict[str, Any] = {}
    for aid in p["origin"]["materials"]:
        a = arts[aid]
        if _media(a) == analysis.INTAKE_MEDIA and given is None:
            given = a
        else:
            mats[aid] = a
    if given is None:
        by = str((h.analysis.profile(h.s.pid) if h.analysis else {}).get("by") or "cz")
        date = time.strftime("%Y-%m-%d", time.gmtime(int(p["opened_ts"]) / 1000))
        rows: list[Mapping[str, Any]] = [{"id": aid, "media_type": a.get("media_type", "")} for aid, a in mats.items()]
        return analysis.derive_intake(str(p["goal"]["statement"]), rows, by=by, date=date), [], mats
    if int(given["size"]) > INTAKE_BYTES:
        return None, [f"立项单超过 {INTAKE_BYTES // 1024} KB"], mats
    try:
        doc = json.loads(h.blobs.get(given["hash"]).decode("utf-8"))
    except ValueError:  # 含 UnicodeDecodeError
        return None, ["立项单不是合法的 JSON"], mats
    errs = analysis.intake_errors(doc, set(mats))
    return (None, errs, mats) if errs else (doc, [], mats)


def _relays_left(h: ToolHost) -> int:
    """这一轮还能再接力几个求解会话（内核 open_work 的同一条规则：从最后一次追问起算，至多 OPEN_RELAYS 个）。"""
    st = h.reader.state
    p = st["problems"][h.s.pid]
    start = max(int(p["opened_seq"]), max((int(f["seq"]) for f in p.get("follow_ups") or []), default=-1))
    solves = [
        x
        for x in st["leases"].values()
        if x["problem_id"] == h.s.pid and x["kind"] == "solve" and x["issued_seq"] > start
    ]
    return max(0, OPEN_RELAYS - len(solves))


def _round_start(h: ToolHost) -> int:
    p = h.reader.state["problems"][h.s.pid]
    return max((int(f["seq"]) for f in p.get("follow_ups") or []), default=int(p["opened_seq"]))


def intake(h: ToolHost, a: Obj) -> dict[str, Any]:
    """简报。材料的原始字节拷进工作区的 `materials/<Artifact id>.blob`；已经在的（接力拷来的）核对摘要后不重拷。"""
    if a.keys():
        raise BadBody(f"intake 不收参数，多了 {sorted(a.keys())}")
    an = _analysis(h)
    st, pid = h.reader.state, h.s.pid
    p = st["problems"][pid]
    doc, errs, mats = intake_of(h)
    files: dict[str, Any] = {}
    root = h.s.workspace / analysis.MATERIALS
    root.mkdir(parents=True, exist_ok=True)
    for aid, art in mats.items():
        row: dict[str, Any] = {"media_type": art.get("media_type", ""), "size": int(art["size"]), "sha256": art["hash"]}
        if int(art["size"]) > FETCH_BYTES:
            row["error"] = f"材料超过 {FETCH_BYTES // 1_000_000} MB"
        else:
            dest = root / f"{aid}.blob"
            if dest.is_symlink() or not dest.is_file() or materials.sha256_file(dest) != _plain(art["hash"]):
                if dest.is_symlink() or dest.exists():
                    dest.unlink()
                tmp = root / f".{aid}.tmp"
                tmp.write_bytes(h.blobs.get(art["hash"]))
                os.replace(tmp, dest)
            row["path"] = f"{analysis.MATERIALS}/{aid}.blob"
        files[aid] = row
    prof = dict(an.profile(pid))
    budget = h.reader.budget(pid)
    out: dict[str, Any] = {
        "ok": True,
        "run": pid,
        "title": str(p.get("title", "")),
        "statement": str(p["goal"]["statement"]),
        "statement_ref": p["origin"]["statement_ref"],
        "form": an.form_ref,
        "materials": files,
        "follow_ups": [{"seq": int(f["seq"]), "text": str(f["text"])} for f in p.get("follow_ups") or []],
        "deliveries": len(p.get("deliveries") or []),
        "budget": {"usd_milli": int(p["budget"]["usd_milli"]), "spent_usd_milli": int(budget["spent"]["usd_milli"])},
        "relays_left": _relays_left(h),
        "closing": an.phase,
        "bang": list(prof.get("bang") or []),
        "locks": list(prof.get("locks") or []),
        "pains": list(prof.get("pains") or []),
        "canaries": list(prof.get("canaries") or []),
        "models": dict(prof.get("models") or {}),
        "prices": {k: list(v) for k, v in (prof.get("prices") or {}).items()},
        "access_wait_s": float(prof.get("access_wait_s", 600)),
        "access_poll_s": float(prof.get("access_poll_s", 5)),
    }
    for k in ("model_idle_s", "model_call_s"):  # 模型调用的两条时限（13 §3.2）；没配就用驱动程序的缺省
        if prof.get(k) is not None:
            out[k] = float(prof[k])
    if doc is not None:
        out["intake"] = doc
    else:
        out["intake_errors"] = errs
    return out


def _plain(h: str) -> str:
    return h.split(":", 1)[1] if ":" in h else h


def _analysis(h: ToolHost) -> Analysis:
    if h.analysis is None:
        raise BadBody("本会话不是方案分析会话")
    return h.analysis


# ---------------------------------------------------------------- fetch：地址类来源


class BadSource(ValueError):
    """立项单里的这个来源抓不了（地址不合规、缺提交或标签、探测计划不合规）。"""


def _site(url: str) -> tuple[str, str, int]:
    u = urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise BadSource("地址须是 http(s) 地址")
    if u.username is not None or u.password is not None:
        raise BadSource("地址里不能带用户名或口令")
    try:
        port = u.port or (443 if u.scheme == "https" else 80)
    except ValueError:
        raise BadSource("地址里的端口不合法") from None
    return u.scheme, u.hostname.lower(), port


def fetch_plan(source: Mapping[str, Any]) -> dict[str, Any]:
    """一个地址类来源怎么抓：下载哪个地址（或按探测计划逐条 GET）、要连哪个 host:port。纯函数，由立项单确定。

    仓库地址换成“这个提交或标签的归档”：github.com 取 codeload 的 tar.gz（网页地址会跳到它，直接取少申请一个
    主机）；gitlab.com 取 `/-/archive/`；其余按 Gitea / Forgejo 一类的 `/archive/<ref>.tar.gz`。地址本身就是归档
    文件（.tar.gz、.tgz、.zip）时原样取。不克隆、不执行仓库里的任何东西。"""
    via, url = str(source["via"]), str(source.get("url", "")).strip()
    scheme, host, port = _site(url)
    u = urlsplit(url)
    if via == "service_url":
        items: list[dict[str, Any]] = []
        for line in str(source.get("probe_plan", "")).splitlines():
            if not line.strip():
                continue
            m = _PROBE_LINE.match(line.strip())
            if m is None:
                raise BadSource("探测计划只收逐条的 “GET /路径”")
            items.append({"no": len(items) + 1, "method": "GET", "path": m.group(1)})
        if not 1 <= len(items) <= PROBE_ITEMS:
            raise BadSource(f"探测计划要有 1 到 {PROBE_ITEMS} 条")
        base = f"{scheme}://{u.netloc}{u.path.rstrip('/')}"
        return {"kind": "probe", "base": base, "items": items, "targets": [f"{host}:{port}"]}
    get = url
    if via == "repo_url" and not u.path.lower().endswith(_ARCHIVES):
        ref = str(source.get("ref", ""))
        if not _REF.match(ref) or ".." in ref or ref.startswith(("/", "-")):
            raise BadSource("仓库地址要写提交哈希或标签（ref），只含字母、数字与 . _ / -")
        path = u.path.rstrip("/").removesuffix(".git")
        parts = [x for x in path.split("/") if x]
        if not parts:
            raise BadSource("仓库地址里没有仓库路径")
        q = quote(ref, safe="/")
        if host == "github.com":
            if len(parts) != 2:
                raise BadSource("github.com 的仓库地址形如 https://github.com/<所有者>/<仓库>")
            get = f"https://codeload.github.com/{quote(parts[0])}/{quote(parts[1])}/tar.gz/{q}"
        elif host == "gitlab.com":
            name = quote(parts[-1])
            get = f"{scheme}://{u.netloc}{path}/-/archive/{q}/{name}-{quote(ref.replace('/', '-'))}.tar.gz"
        else:
            get = f"{scheme}://{u.netloc}{path}/archive/{q}.tar.gz"
    s2, h2, p2 = _site(get)
    return {"kind": "file", "url": get, "targets": [f"{h2}:{p2}"]}


def _rule(target: str) -> dict[str, Any]:
    return {"resource": "net", "pattern": target, "actions": ["connect"]}


def _same(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return (a["resource"], a["pattern"], sorted(a["actions"])) == (b["resource"], b["pattern"], sorted(b["actions"]))


def _access(h: ToolHost, target: str, no: int, url: str) -> tuple[str, str]:
    """这个 host:port 现在能不能连：granted | pending | denied | failed，与一句说明。没有授权也没有在等的申请时
    提一条扩权申请（理由写明是哪个来源、要取什么）。同一轮里被拒过或被撤销过的不再申请；人追问之后可以再申请一次。"""
    st, pid = h.reader.state, h.s.pid
    rule, start = _rule(target), _round_start(h)
    scope = st["problems"][pid]["scope"]
    if any(_same(r, rule) and "revoked" not in r for r in scope):
        return "granted", ""
    if any(_same(r, rule) and int(r.get("revoked", -1)) > start for r in scope):
        return "denied", "这个地址的访问授权已被撤销"
    mine = [
        x
        for x in st.get("scope_requests", {}).values()
        if x["problem_id"] == pid and any(_same(r, rule) for r in x["rules"])
    ]
    last = max(mine, key=lambda x: int(x["seq"]), default=None)
    if last is not None and last["status"] == "pending":
        return "pending", str(last["id"])
    if last is not None and last["status"] == "denied" and int(last.get("decided_seq", last["seq"])) > start:
        return "denied", str(last.get("reason") or "访问申请被拒绝")
    why = f"方案分析要读取立项登记的来源 {no}（{url[:300]}）的定版材料：只下载、不执行；需要连接 {target}"
    why, _ = creds.mask(why, h.s.secrets)
    out = h.graph.submit(
        h.s.token,
        pid,
        f"fetch-access:{h.s.lease_id}:{h._nonce}:{h._n}:{target}",
        [{"op": "request_scope", "body": {"rules": [rule], "why": why}}],
    )
    r = out["results"][0]
    if not r.get("ok"):
        if r.get("code") == "forbidden_op":
            return "denied", str(r.get("detail", ""))
        return "failed", f"访问申请没有提成：{r.get('code')} {r.get('detail', '')}"
    req = h.reader.state.get("scope_requests", {})[r["id"]]
    return ("granted", "") if req["status"] == "granted" else ("pending", str(r["id"]))


def _ready(h: ToolHost, target: str) -> str | None:
    """批下来的地址在这个会话的沙箱里是不是真的开了。开了返回 None，否则是原因。"""
    hot = h.access() if h.access else None
    if not h._compiled(target):
        return f"{target} 已批准，但它的风险高于本会话的风险上限，沙箱里不开"
    if hot is not None and hot.get("unsupported"):
        return f"{target} 已批准，但执行层开不了这个出站目标（{hot['unsupported']}）。{UPLOAD_INSTEAD}"
    if hot is not None:
        return None
    st = h.reader.state
    lease = st["leases"][h.s.lease_id]
    rule = next(r for r in reversed(st["problems"][h.s.pid]["scope"]) if _same(r, _rule(target)) and "revoked" not in r)
    granted: Mapping[str, Any] = rule.get("granted") or {}
    if int(granted.get("seq", -1)) > int(lease["issued_seq"]):
        return f"{target} 已批准；本执行器不支持会话中途生效，追问一句“继续”后由下一个会话抓取"
    return None  # 起沙箱时就在授权范围里


def _ws_file(h: ToolHost, rel: str, cap: int) -> Path:
    """沙箱写出来的文件：必须是工作区里的普通文件（不认符号链接），大小在上限内。"""
    root = h.s.workspace.resolve()
    p = h.s.workspace / rel
    if p.is_symlink() or not p.is_file() or root not in p.resolve().parents:
        raise BadSource(f"沙箱没有留下文件 {rel}")
    if p.stat().st_size > cap:
        raise BadSource(f"{rel} 超过 {cap} 字节")
    return p


def fetch(h: ToolHost, a: Obj) -> dict[str, Any]:
    extra = a.keys() - {"source"}
    if extra:  # 地址、提交、要连的主机都不由调用方给：宿主从事件账里的立项单推
        raise BadBody(f"fetch 只收 source（来源编号），多了 {sorted(extra)}")
    an = _analysis(h)
    no = a.integer("source")
    doc, errs, _ = intake_of(h)
    if doc is None:
        return {"status": "failed", "detail": "这道题没有可用的立项单：" + "；".join(errs)[:400]}
    src = next((s for s in doc["sources"] if int(s["no"]) == no), None)
    if src is None:
        raise BadBody(f"立项单里没有来源 {no}")
    if src["via"] not in analysis.ADDRESS_VIAS:
        raise BadBody(f"来源 {no} 不是地址类来源，不需要抓取")
    refused = source_refusal(src, None)
    if refused:
        return {"status": "refused", "detail": refused}
    if h.executor is None or h.s.sandbox_id is None:
        no_box = f"执行容器起不来（{h.s.no_box}）" if h.s.no_box else "本会话没有执行容器"
        return {"status": "failed", "detail": f"{no_box}，抓不了地址类来源。{UPLOAD_INSTEAD}"}
    try:
        plan = fetch_plan(src)
    except BadSource as e:
        return {"status": "failed", "detail": str(e)}
    targets: list[str] = plan["targets"]
    states = [(_access(h, t, no, str(src.get("url", ""))), t) for t in targets]
    for want in ("failed", "denied", "pending"):
        hit = [(s, t) for s, t in states if s[0] == want]
        if hit:
            out: dict[str, Any] = {"status": want, "targets": [t for _, t in hit], "detail": hit[0][0][1]}
            if want == "pending":
                out["requests"], out["detail"] = [s[1] for s, _ in hit], "已进人的待办，等批准"
            return out
    for t in targets:
        why = _ready(h, t)
        if why:
            return {"status": "failed", "targets": targets, "detail": why}
    an.fetches += 1
    if an.fetches > FETCH_MAX:
        return {"status": "failed", "detail": f"本会话的抓取次数已到上限（{FETCH_MAX}）"}
    fdir = h.s.workspace / FETCH_DIR
    fdir.mkdir(parents=True, exist_ok=True)
    fdir.chmod(0o777)  # 沙箱里的进程丢了全部能力，靠目录权限写
    if plan["kind"] == "file":
        rel = f"{FETCH_DIR}/s{no}.blob"
        _clear(h.s.workspace / rel)
        argv = ["python3", "-I", "-c", FETCH_PY, "file", plan["url"], f"/workspace/{rel}", str(FETCH_BYTES)]
    else:
        rel = f"{FETCH_DIR}/s{no}"
        sub = h.s.workspace / rel
        _clear(sub)
        sub.mkdir()
        sub.chmod(0o777)
        body = {"base": plan["base"], "items": plan["items"]}
        (sub / "plan.json").write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        argv = [
            "python3",
            "-I",
            "-c",
            FETCH_PY,
            "probe",
            f"/workspace/{rel}/plan.json",
            f"/workspace/{rel}/responses.json",
            str(PROBE_BODY),
        ]
    r = h.executor.exec(
        h.s.sandbox_id,
        " ".join(shlex.quote(x) for x in argv),
        h.s.pid,
        f"fetch:{h.s.lease_id}:{h._nonce}:{h._n}",
        timeout_s=FETCH_TIMEOUT_S,
        cwd="/workspace",
    )
    said = _last_json(r.output)
    if r.exit_code != 0 or not said.get("ok"):
        detail = said.get("detail") or f"下载命令退出码 {r.exit_code}"
        return {"status": "failed", "targets": targets, "artifact": r.artifact, "detail": str(detail)[:300]}
    try:
        if plan["kind"] == "file":
            f = _ws_file(h, rel, FETCH_BYTES)
            sha = materials.sha256_file(f)
            if sha != said.get("sha256"):  # 沙箱自报的摘要只是提示，以宿主自己算的为准；对不上说明文件被动过
                raise BadSource("下载的文件与下载命令报告的摘要对不上")
            return {
                "status": "fetched",
                "path": rel,
                "artifact": r.artifact,
                "sha256": sha,
                "size": f.stat().st_size,
                "targets": targets,
            }
        plan_file = _ws_file(h, f"{rel}/plan.json", INTAKE_BYTES)
        if json.loads(plan_file.read_text(encoding="utf-8")) != body:
            raise BadSource("探测计划在抓取过程中被改动")
        resp = _ws_file(h, f"{rel}/responses.json", PROBE_ITEMS * PROBE_BODY * 8)
        return {
            "status": "fetched",
            "dir": rel,
            "artifact": r.artifact,
            "sha256": materials.sha256_file(resp),
            "size": resp.stat().st_size,
            "targets": targets,
        }
    except (BadSource, ValueError) as e:
        return {"status": "failed", "targets": targets, "artifact": r.artifact, "detail": str(e)[:300]}


def _clear(p: Path) -> None:
    if p.is_symlink() or p.is_file():
        p.unlink()
    elif p.is_dir():
        for x in sorted(p.rglob("*"), reverse=True):
            x.unlink() if x.is_symlink() or x.is_file() else x.rmdir()
        p.rmdir()


def _last_json(output: str) -> dict[str, Any]:
    for line in reversed(output.strip().splitlines()):
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return {}


# ---------------------------------------------------------------- check：产物登记前的检查


def check(h: ToolHost, a: Obj) -> dict[str, Any]:
    extra = a.keys() - {"name", "path"}
    if extra:
        raise BadBody(f"check 只收 name 与 path，多了 {sorted(extra)}")
    an = _analysis(h)
    name, rel = a.string("name"), a.string("path")
    if not _NAME.match(name):
        raise BadBody("name 只含字母、数字与 . _ : -，至多 80 字")
    m = _PRODUCT_PATH.match(rel)
    if m is None:
        raise BadBody(f"path 须是 {analysis.ANALYSIS}/artifacts/<sha256>.json")
    data = h._read_ws(rel)
    if len(data) > PRODUCT_BYTES:
        return {"ok": False, "code": "schema_error", "detail": f"产物超过 {PRODUCT_BYTES // 1024} KB"}
    try:
        text = data.decode("utf-8")
        obj = json.loads(text)
    except ValueError:
        return {"ok": False, "code": "schema_error", "detail": "产物不是合法的 UTF-8 JSON"}
    errors = analysis.product_errors(name, obj)
    if not errors and digest(obj) != m.group(1):
        errors = ["文件名里的摘要与内容对不上"]
    if not errors and creds.mask(text, h.s.secrets)[1]:
        errors = ["产物里带着原话里的凭据：凭据不进产物"]
    if errors:
        return {"ok": False, "code": "schema_error", "detail": "；".join(errors)[:800], "errors": errors}
    an.checks += 1
    if an.checks > CHECK_MAX:
        return {"ok": False, "code": "quota_exceeded", "detail": f"本会话登记的产物已到上限（{CHECK_MAX}）"}
    sha = hashlib.sha256(data).hexdigest()
    out = h.graph.submit(
        h.s.token,
        h.s.pid,
        f"check:{h.s.lease_id}:{sha}",
        [
            {
                "op": "register_artifact",
                "body": {
                    "hash": h.blobs.put(data),
                    "size": len(data),
                    "media_type": PRODUCT_MEDIA,
                    "class": "authored",
                },
            }
        ],
    )
    r = out["results"][0]
    if not r.get("ok"):
        return {"ok": False, "code": r.get("code", "schema_error"), "detail": r.get("detail", "")}
    an.checked.add(str(r["id"]))
    return {"ok": True, "artifact": r["id"], "name": name, "sha256": m.group(1)}


def gate(h: ToolHost, ids: Any) -> list[str]:
    """交付闸：`artifacts` 里的编号须是这道题经 check 登记过的产物（本会话的，或接力前的会话登记的）。"""
    if not isinstance(ids, list) or len(ids) > 64 or not all(isinstance(x, str) for x in ids):
        raise BadBody("artifacts 须是至多 64 个 Artifact 编号")
    arts = h.reader.state["artifacts"]
    bad = [x for x in ids if not is_product(arts.get(x), h.s.pid)]
    if bad:
        raise BadBody(f"artifacts 里有没经 check 登记的编号：{bad[:5]}")
    return list(ids)
