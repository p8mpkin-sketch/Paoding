"""pd：人的通道（§3.2 命令表的 M0 子集）。

    pd problem open <problem.yaml>
    pd status <pid>          pd report <pid>
    pd profile <pid> [--override <轴>=<值> --reason "<文本>"]
    pd hint add [--node <id>] "<文本>"      pd hint close <hid>
    pd approve <intent> [--yes]             pd deny <intent> --reason "<文本>"
    pd accept [--ref 项=产物] [--note 项=文本] [--yes]       人工验收：清单逐条判过（设计 02 §3.3）
    pd reject --fail 项[,项…] --reason "<文本>" [--ref …] [--note …] [--yes]   拒收：列出不过的项，其余算过
    pd scope list    pd scope grant <申请> [--risk r1,…] [--yes]    pd scope deny <申请> --reason "<文本>"
    pd scope revoke <规则下标> --reason "<文本>"     运行时扩权（docs/design/runtime-grants/）
    pd kaiti "<原文>" [--answer …] [--yes]   一句话开题（确认道；见 kaiti.py）
    pd settings show                        pd settings set <键路径> <值>
    pd keys show    pd keys set <槽>（从标准输入读密钥）    pd keys clear <槽> | --all
    pd connector list    pd connector tasks <平台>    pd connector import <平台> <任务号> [--yes]   从平台导入

pid 取 --pid 或环境变量 PD_PROBLEM。数据目录取 --home 或 PD_HOME（g.sqlite 与 blobs/）。
M0 的骨架以本机进程内方式打开图服务；图服务独立成进程后改走 HTTP/Unix socket 绑定（接口相同，D10）。
settings、keys 与 connector 走运行中的全栈的 HTTP（--url 或 PD_URL，缺省 http://127.0.0.1:8100）：钥匙环只在端点代理的
内存里（宪章 03 §4）。人的令牌取 PD_TOKEN，或 --token-file（缺省 <home>/human.token）。
输出遵守四语域标记、等级词表与判据徽章（render.py）。不存在人填画像三轴的入口：画像只能事后覆盖。
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from paoding_graph.contract import BlobStore, Config, GraphService, TokenRegistry, seen_card

from . import connector, kaiti, render

HUMAN_TOKEN = "pd-local-human"


def default_judges() -> dict:
    """内建判官（异议 001 裁决：只有不含领域词的）。配置判官随 judgebox 落地后从 judges.d 读。"""
    return {
        "structure_check": {"version": "1", "grade": "advisory", "kind": "builtin", "max_cost": 0.0},
        "replay": {"version": "1", "grade": "decisive", "kind": "builtin", "max_cost": 0.01},
        "exact_match": {"version": "1", "grade": "decisive", "kind": "builtin", "max_cost": 0.0},
        "seal_check": {"version": "1", "grade": "decisive", "kind": "builtin", "max_cost": 0.0},
    }


class Local:
    def __init__(self, home: Path, actor: dict, judges: dict | None = None):
        home.mkdir(parents=True, exist_ok=True)
        reg = TokenRegistry()
        reg.issue(actor, HUMAN_TOKEN)
        self.graph = GraphService(home / "g.sqlite", Config(judges=judges or default_judges()), reg)
        self.blobs = BlobStore(home / "blobs")

    def submit(self, pid: str, idem: str, ops: list) -> dict:
        return self.graph.submit(HUMAN_TOKEN, pid, idem, ops)


def _input(local: Local, pid: str, path: Path) -> dict:
    data = path.read_bytes()
    h = local.blobs.put(data)
    return {
        "op": "register_artifact",
        "body": {"hash": h, "size": len(data), "media_type": "text/plain", "class": "input"},
    }


def _fail(out: dict) -> str:
    bad = [r for r in out["results"] if not r.get("ok")]
    return "；".join(f"{r.get('code')}：{r.get('detail', '')}" for r in bad) or "被拒"


def cmd_open(local: Local, a, w) -> int:
    path = Path(a.file)
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    if "profile" in spec:
        w("[人] 拒绝：画像由图服务推出，题目文件里不接受 profile\n")
        return 2
    pid = spec["id"]
    base = path.parent
    ops = [_input(local, pid, base / spec["statement"])]
    ops += [_input(local, pid, base / m) for m in spec.get("materials", [])]
    body = {
        "title": spec["title"],
        "origin": {"statement_ref": "$0", "materials": [f"${k + 1}" for k in range(len(spec.get("materials", [])))]},
        "goal": spec["goal"],
        "scope": spec["scope"],
        "budget": spec["budget"],
        "env": spec["env"],
        "judges": spec["judges"],
    }
    out = local.submit(pid, f"pd-open:{pid}", ops + [{"op": "open_problem", "body": body}])
    if not out["ok"]:
        w(f"[证据] 开题被拒：{_fail(out)}\n")
        return 1
    w(f"[证据] 已开题 {pid}\n")
    w(render.profile(local.graph.state, pid))
    return 0


def _pid(a) -> str:
    pid = a.pid or os.environ.get("PD_PROBLEM")
    if not pid:
        raise SystemExit("需要 --pid 或环境变量 PD_PROBLEM")
    return pid


def _known(local: Local, pid: str, w) -> bool:
    if pid not in local.graph.state["problems"]:
        w(f"[证据] 没有题 {pid}\n")
        return False
    return True


def cmd_status(local: Local, a, w) -> int:
    pid = a.target
    if not _known(local, pid, w):
        return 1
    w(render.status(local.graph.state, pid, local.graph.budget(pid)))
    return 0


def cmd_report(local: Local, a, w) -> int:
    pid = a.target
    if not _known(local, pid, w):
        return 1
    w(render.report(local.graph.state, pid, local.graph.budget(pid)))
    return 0


def cmd_profile(local: Local, a, w) -> int:
    pid = a.target
    if not _known(local, pid, w):
        return 1
    if a.override:
        axis, _, value = a.override.partition("=")
        if not a.reason:
            w("[证据] 覆盖须写理由：--reason\n")
            return 2
        n = len(local.graph.state["problems"][pid].get("profile_overrides", []))
        out = local.submit(
            pid,
            f"pd-override:{pid}:{n}",
            [{"op": "profile_override", "body": {"axis": axis, "value": value, "reason": a.reason}}],
        )
        if not out["ok"]:
            w(f"[证据] 被拒：{_fail(out)}\n")
            return 1
    w(render.profile(local.graph.state, pid))
    return 0


def cmd_hint(local: Local, a, w) -> int:
    pid = _pid(a)
    if a.action == "add":
        body = {"text": a.text, **({"about": a.node} if a.node else {})}
    else:
        body = {"close": a.text}
    n = len(local.graph.state["hints"])
    out = local.submit(pid, f"pd-hint:{a.action}:{n}:{a.text}", [{"op": "hint", "body": body}])
    if not out["ok"]:
        w(f"[证据] 被拒：{_fail(out)}\n")
        return 1
    w(
        f"[证据] {'已加' if a.action == 'add' else '已关闭'} {out['results'][0]['id'] if a.action == 'add' else a.text}\n"  # noqa: E501
    )
    return 0


def cmd_decide(local: Local, a, w, decision: str, read=input) -> int:
    pid = _pid(a)
    st = local.graph.state
    if a.intent not in st["intents"] or st["intents"][a.intent]["problem_id"] != pid:
        w(f"[证据] 本题没有 {a.intent}\n")
        return 1
    w(render.approval_card(st, pid, a.intent))
    if decision == "deny":
        w(f"[人] 拒绝理由：{a.reason}\n")
    if not a.yes:
        ans = read("确认？输入 yes 继续：")
        if ans.strip() != "yes":
            w("[证据] 未确认，未提交\n")
            return 1
    out = local.submit(
        pid,
        f"pd-{decision}:{a.intent}:{st['seq']}",
        [
            {
                "op": "approve",
                "body": {
                    "intent": a.intent,
                    "decision": decision,
                    "seen": seen_card(st, pid, "approval", a.intent),
                    **({"reason": a.reason} if a.reason else {}),
                },
            }
        ],
    )  # seen 取自上面打印的那份快照（H2）
    if not out["ok"]:
        w(f"[证据] 被拒：{_fail(out)}\n")
        if any(r.get("code") == "stale_view" for r in out["results"]):
            w("[证据] 卡片在你查看之后已变化，未提交。最新的卡：\n")
            w(render.approval_card(local.graph.state, pid, a.intent))
        return 1
    w(f"[证据] 已{'批准' if decision == 'approve' else '拒绝'} {a.intent}\n")
    return 0


def cmd_scope(local: Local, a, w, read=input) -> int:
    """运行时扩权的人工一侧：列出申请、批或拒（带 seen，绑定所见）、撤销规则。"""
    pid = _pid(a)
    st = local.graph.state
    reqs = {k: v for k, v in st.get("scope_requests", {}).items() if v["problem_id"] == pid}
    if a.sub == "list":
        p = st["problems"].get(pid)
        if p is None:
            w(f"[证据] 没有任务 {pid}\n")
            return 1
        for k, r in enumerate(p["scope"]):
            mark = "已撤销" if "revoked" in r else ("扩权批准" if "granted" in r else "开题时")
            w(f"[证据] 规则 {k} {r['resource']} {r['pattern']} {','.join(r['actions'])} {r['risk']}（{mark}）\n")
        for rid in sorted(reqs, key=lambda x: reqs[x]["seq"]):
            w(render.scope_card(st, pid, rid))
        if not reqs:
            w("[证据] 没有扩权申请\n")
        return 0
    if a.sub == "revoke":
        body: dict = {"rule": int(a.target), "reason": a.reason}
        op = "revoke_scope"
    else:
        if a.target not in reqs:
            w(f"[证据] 本题没有扩权申请 {a.target}\n")
            return 1
        w(render.scope_card(st, pid, a.target))
        decision = "approve" if a.sub == "grant" else "deny"
        body = {"request": a.target, "decision": decision, "seen": seen_card(st, pid, "scope", a.target)}
        if a.reason:
            body["reason"] = a.reason
        if decision == "approve" and a.risk:
            body["risk"] = [x.strip() for x in a.risk.split(",")]
        op = "grant_scope"
    if not a.yes:
        ans = read("确认？输入 yes 继续：")
        if ans.strip() != "yes":
            w("[证据] 未确认，未提交\n")
            return 1
    # 被拒的结果同样按 idem_key 缓存：改正后重交必须换键（graph/SPEC.md 的调用方惯例），所以键里带上提交体的摘要
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    out = local.submit(pid, f"pd-scope-{a.sub}:{a.target}:{st['seq']}:{digest}", [{"op": op, "body": body}])
    if not out["ok"]:
        w(f"[证据] 被拒：{_fail(out)}\n")
        return 1
    verb = {"grant": "批准", "deny": "拒绝", "revoke": "撤销"}[a.sub]
    w(f"[证据] 已{verb} {a.target}\n")
    return 0


def _pairs(items: list[str] | None, w) -> dict[str, str] | None:
    out: dict[str, str] = {}
    for x in items or []:
        k, sep, v = x.partition("=")
        if not sep or not k.strip():
            w(f"[人] 格式是 项=值：{x}\n")
            return None
        out[k.strip()] = v
    return out


def cmd_accept(local: Local, a, w, decision: str, read=input) -> int:
    """人工验收（accept=human 的题）：打印清单与待验收的交付物，逐条组装 checks，seen 绑定这份快照。"""
    pid = _pid(a)
    st = local.graph.state
    if not _known(local, pid, w):
        return 1
    items = st["problems"][pid]["goal"].get("acceptance")
    if not items:
        w("[证据] 这个任务不由人验收：判定由判官给出\n")
        return 1
    refs, notes = _pairs(a.ref, w), _pairs(a.note, w)
    if refs is None or notes is None:
        return 2
    failed = {x.strip() for x in (a.fail or "").split(",") if x.strip()}
    ids = {i["id"] for i in items}
    unknown = sorted((failed | set(refs) | set(notes)) - ids)
    if unknown:
        w(f"[人] 清单里没有 {'、'.join(unknown)}（清单：{'、'.join(sorted(ids))}）\n")
        return 2
    if decision == "reject" and not failed:
        w("[人] 拒收要用 --fail 列出不过的项\n")
        return 2
    w(render.status(st, pid, local.graph.budget(pid)) if a.full else "")
    o = render.Out()
    render.acceptance(o, st, pid)
    w(o.text())
    checks = [
        {
            "id": i["id"],
            "verdict": "fail" if i["id"] in failed else "pass",
            **({"ref": refs[i["id"]]} if i["id"] in refs else {}),
            **({"note": notes[i["id"]]} if i["id"] in notes else {}),
        }
        for i in items
    ]
    body: dict = {"decision": decision, "checks": checks, "seen": seen_card(st, pid, "closeout", pid)}
    if a.reason:
        body["reason"] = a.reason
        w(f"[人] 理由：{a.reason}\n")
    if not a.yes:
        ans = read("确认？输入 yes 继续：")
        if ans.strip() != "yes":
            w("[证据] 未确认，未提交\n")
            return 1
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    out = local.submit(pid, f"pd-{decision}:{pid}:{st['seq']}:{digest}", [{"op": "accept", "body": body}])
    if not out["ok"]:
        w(f"[证据] 被拒：{_fail(out)}\n")
        if any(r.get("code") == "stale_view" for r in out["results"]):
            w("[证据] 收尾卡在你查看之后已变化，未提交，请重看后再判\n")
        return 1
    if decision == "accept":
        w(f"[证据] 已验收通过；终态 {render.terminal_phrase(local.graph.state, pid)}\n")
    else:
        w(f"[证据] 已拒收 {pid}：任务回到人介入，等新的交付物\n")
    return 0


# ---------- 设置与密钥：经 HTTP 找运行中的全栈 ----------


class Remote:
    def __init__(self, url: str, token: str):
        self.url, self.token = url.rstrip("/"), token

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.url + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def put(self, path: str, data: bytes) -> tuple[int, dict]:
        req = urllib.request.Request(self.url + path, data=data, method="PUT")
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Content-Type", "application/octet-stream")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")


def _remote(a) -> Remote:
    token = os.environ.get("PD_TOKEN", "").strip()
    if not token:
        tf = Path(a.token_file) if a.token_file else Path(a.home) / "human.token"
        token = tf.read_text(encoding="utf-8").strip()
    return Remote(a.url, token)


def _set_path(doc: dict, path: str, value: object) -> None:
    keys = path.split(".")
    cur = doc
    for k in keys[:-1]:
        if not isinstance(cur, dict) or k not in cur:
            raise KeyError(path)
        cur = cur[k]
    if not isinstance(cur, dict) or keys[-1] not in cur:
        raise KeyError(path)
    cur[keys[-1]] = value


def cmd_settings(r: Remote, a, w) -> int:
    code, doc = r.call("GET", "/v1/settings")
    if code != 200:
        w(f"[证据] 读设置失败：{code} {doc.get('detail', '')}\n")
        return 1
    if a.sub == "show":
        w(f"[证据] 设置 v{doc['version']} 摘要 {doc['digest'][:12]}\n")
        w(yaml.safe_dump(doc["settings"], allow_unicode=True, sort_keys=False))
        return 0
    settings = doc["settings"]
    try:
        _set_path(settings, a.key, yaml.safe_load(a.value))
    except KeyError:
        w(f"[人] 没有设置项 {a.key}（用 pd settings show 看键路径）\n")
        return 2
    code, out = r.call("PUT", "/v1/settings", {"base_digest": doc["digest"], "settings": settings})
    if code != 200:
        w(f"[证据] 被拒：{out.get('code')}：{out.get('detail', '')}\n")
        return 1
    w(f"[证据] 已保存：设置 v{out['version']} 摘要 {out['digest'][:12]}\n")
    return 0


def _slot_line(s: dict) -> str:
    if not s["set"]:
        return f"{s['slot']}：未设" + (f"（环境变量 {s['env']}）" if s.get("env") else "")
    return f"{s['slot']}：已设 {s['fingerprint']}，来源 {s['source']}"


def cmd_keys(r: Remote, a, w, read_key) -> int:
    if a.sub == "show":
        code, out = r.call("GET", "/v1/keys")
        if code == 200:
            w("".join(_slot_line(s) + "\n" for s in out["slots"]) + f"[人] {out['note']}\n")
    elif a.sub == "set":
        key = read_key()  # 从标准输入读，不进 shell 历史与进程参数
        code, out = r.call("PUT", f"/v1/keys/{a.slot}", {"key": key})
        if code == 200:
            w(_slot_line(out) + f"\n[人] {out['note']}\n")
    else:
        if not a.all and not a.slot:
            w("[人] pd keys clear <槽>，或 --all 全部锁定\n")
            return 2
        code, out = r.call("DELETE", "/v1/keys" if a.all else f"/v1/keys/{a.slot}")
        if code == 200:
            w("已清除\n")
    if code != 200:
        w(f"[证据] 被拒：{out.get('code')}：{out.get('detail', '')}\n")
        return 1
    return 0


def _read_key() -> str:
    return getpass.getpass("密钥：") if sys.stdin.isatty() else sys.stdin.readline().strip()


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pd", description="庖丁：人的通道")
    ap.add_argument("--home", default=os.environ.get("PD_HOME", ".paoding"))
    ap.add_argument("--pid")
    ap.add_argument("--actor", default=os.environ.get("PD_ACTOR", "human"))
    ap.add_argument("--url", default=os.environ.get("PD_URL", "http://127.0.0.1:8100"))
    ap.add_argument("--token-file")
    sp = ap.add_subparsers(dest="cmd", required=True)
    pr = sp.add_parser("problem").add_subparsers(dest="sub", required=True)
    po = pr.add_parser("open")
    po.add_argument("file")
    for name in ("status", "report"):
        sp.add_parser(name).add_argument("target")
    pf = sp.add_parser("profile")
    pf.add_argument("target")
    pf.add_argument("--override")
    pf.add_argument("--reason")
    hp = sp.add_parser("hint")
    hp.add_argument("action", choices=["add", "close"])
    hp.add_argument("text")
    hp.add_argument("--node")
    for name in ("approve", "deny"):
        d = sp.add_parser(name)
        d.add_argument("intent")
        d.add_argument("--yes", action="store_true")
        d.add_argument("--reason", required=(name == "deny"))
    for name in ("accept", "reject"):
        x = sp.add_parser(name)
        x.add_argument("--ref", action="append", help="项=产物编号（exec 或 input 类），可重复")
        x.add_argument("--note", action="append", help="项=说明，可重复")
        x.add_argument("--reason", required=(name == "reject"))
        x.add_argument("--full", action="store_true", help="先打印整份状态")
        x.add_argument("--yes", action="store_true")
        if name == "reject":
            x.add_argument("--fail", required=True, help="不过的项，逗号分隔")
        else:
            x.set_defaults(fail=None)
    sc = sp.add_parser("scope").add_subparsers(dest="sub", required=True)
    sc.add_parser("list")
    for name in ("grant", "deny", "revoke"):
        x = sc.add_parser(name)
        x.add_argument("target")
        x.add_argument("--yes", action="store_true")
        x.add_argument("--reason", required=(name != "grant"))
        if name == "grant":
            x.add_argument("--risk", help="逐条上调风险，逗号分隔（只可上调）")
    kaiti.add_parser(sp)
    connector.add_parser(sp)
    st = sp.add_parser("settings").add_subparsers(dest="sub", required=True)
    st.add_parser("show")
    ss = st.add_parser("set")
    ss.add_argument("key")
    ss.add_argument("value")
    ks = sp.add_parser("keys").add_subparsers(dest="sub", required=True)
    ks.add_parser("show")
    ks.add_parser("set").add_argument("slot")
    kc = ks.add_parser("clear")
    kc.add_argument("slot", nargs="?")
    kc.add_argument("--all", action="store_true")
    return ap


def main(
    argv: list[str] | None = None, out=None, read=input, judges: dict | None = None, model=None, read_key=None
) -> int:
    a = parser().parse_args(argv)
    w = (out or sys.stdout).write
    if a.cmd == "settings":
        return cmd_settings(_remote(a), a, w)
    if a.cmd == "keys":
        return cmd_keys(_remote(a), a, w, read_key or _read_key)
    if a.cmd == "connector":
        return connector.cmd_connector(_remote(a), a, w, read)
    local = Local(Path(a.home), {"kind": "human", "id": a.actor}, judges)
    if a.cmd == "problem":
        return cmd_open(local, a, w)
    if a.cmd == "kaiti":
        return kaiti.cmd_kaiti(local, a, w, read, model)
    if a.cmd in ("approve", "deny"):
        return cmd_decide(local, a, w, a.cmd, read)
    if a.cmd == "scope":
        return cmd_scope(local, a, w, read)
    if a.cmd in ("accept", "reject"):
        return cmd_accept(local, a, w, a.cmd, read)
    return {"status": cmd_status, "report": cmd_report, "profile": cmd_profile, "hint": cmd_hint}[a.cmd](local, a, w)


if __name__ == "__main__":
    sys.exit(main())
