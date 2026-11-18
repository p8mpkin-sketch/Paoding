"""pd：人的通道（§3.2 命令表的 M0 子集）。

    pd problem open <problem.yaml>
    pd status <pid>          pd report <pid>
    pd profile <pid> [--override <轴>=<值> --reason "<文本>"]
    pd hint add [--node <id>] "<文本>"      pd hint close <hid>
    pd approve <intent> [--yes]             pd deny <intent> --reason "<文本>"

pid 取 --pid 或环境变量 PD_PROBLEM。数据目录取 --home 或 PD_HOME（g.sqlite 与 blobs/）。
M0 的骨架以本机进程内方式打开图服务；图服务独立成进程后改走 HTTP/Unix socket 绑定（接口相同，D10）。
输出遵守四语域标记、等级词表与判据徽章（render.py）。不存在人填画像三轴的入口：画像只能事后覆盖。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

from paoding_graph.contract import BlobStore, Config, GraphService, TokenRegistry, seen_card

from . import render

HUMAN_TOKEN = "pd-local-human"


def default_judges() -> dict:
    """M0 内建判官（异议 001 裁决：只有这三个不含领域词的）。配置判官随 judgebox 落地后从 judges.d 读。"""
    return {
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


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pd", description="庖丁：人的通道")
    ap.add_argument("--home", default=os.environ.get("PD_HOME", ".paoding"))
    ap.add_argument("--pid")
    ap.add_argument("--actor", default=os.environ.get("PD_ACTOR", "human"))
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
    return ap


def main(argv: list[str] | None = None, out=None, read=input, judges: dict | None = None) -> int:
    a = parser().parse_args(argv)
    w = (out or sys.stdout).write
    local = Local(Path(a.home), {"kind": "human", "id": a.actor}, judges)
    if a.cmd == "problem":
        return cmd_open(local, a, w)
    if a.cmd in ("approve", "deny"):
        return cmd_decide(local, a, w, a.cmd, read)
    return {"status": cmd_status, "report": cmd_report, "profile": cmd_profile, "hint": cmd_hint}[a.cmd](local, a, w)


if __name__ == "__main__":
    sys.exit(main())
