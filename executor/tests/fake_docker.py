#!/usr/bin/env python3
"""假的容器命令行：测“建容器的请求迟迟不返回、客户端超时之后容器才出现”与“容器服务整个无响应”用。

状态放在环境变量 FAKE_DOCKER_STATE 指的目录里（containers/、networks/ 各一个 JSON 一条记录），
行为由同一目录下的 plan.json 定：
  create_after_s  建容器的请求收到之后过多久容器才真的出现（“容器服务稍后还是把它建了出来”）
  stall_until     这个时刻（time.time()）之前，所有命令都不返回（“容器服务整个无响应”）
  stall_from_run  为真时，无响应从收到 run 的那一刻算起，持续 stall_s 秒
只实现执行层起沙箱、拆沙箱、清扫用到的那几条子命令。不是 Docker，不要拿它当 Docker 的行为依据。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

S = Path(os.environ["FAKE_DOCKER_STATE"])
(S / "containers").mkdir(parents=True, exist_ok=True)
(S / "networks").mkdir(parents=True, exist_ok=True)


def plan() -> dict:
    f = S / "plan.json"
    return json.loads(f.read_text()) if f.exists() else {}


def log(*a: object) -> None:
    with (S / "calls.log").open("a") as f:
        f.write(f"{time.time():.2f} " + " ".join(str(x) for x in a) + "\n")


def stalled() -> None:
    """容器服务无响应：命令挂着，直到被客户端超时杀掉，或无响应结束。"""
    until = plan().get("stall_until", 0)
    while time.time() < until:
        time.sleep(0.02)


def opts(args: list[str], name: str) -> list[str]:
    return [args[i + 1] for i, a in enumerate(args[:-1]) if a == name]


def labels_of(args: list[str]) -> dict[str, str]:
    return dict(v.split("=", 1) for v in opts(args, "--label"))


def match(rec: dict, filters: list[str]) -> bool:
    for f in filters:
        if not f.startswith("label="):
            continue
        k, eq, v = f[6:].partition("=")
        if k not in rec["labels"] or (eq and rec["labels"][k] != v):
            return False
    return True


def render(fmt: str, name: str, rec: dict) -> str:
    """--format 的那一点点模板：{{.Names}}、{{.Name}}、{{.Label "键"}}。"""
    out = fmt.replace("{{.Names}}", name).replace("{{.Name}}", name)
    return re.sub(r'\{\{\.Label "([^"]+)"\}\}', lambda m: rec["labels"].get(m.group(1), ""), out)


def records(kind: str) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text()) for p in sorted((S / kind).glob("*.json"))}


def main(argv: list[str]) -> int:
    log(*argv[: 4 if argv[0] == "rm" else 3])
    if argv[0] == "__create_later":  # 脱离客户端的那一半：扮“容器服务”，到点把容器建出来
        _, delay, name, labels = argv
        time.sleep(float(delay))
        (S / "containers" / f"{name}.json").write_text(json.dumps({"labels": json.loads(labels), "state": "created"}))
        log("daemon: container appears", name)
        return 0
    if argv[0] == "run":
        p = plan()
        if p.get("stall_from_run"):
            p.pop("stall_from_run")
            p["stall_until"] = time.time() + p["stall_s"]
            (S / "plan.json").write_text(json.dumps(p))
        name = opts(argv, "--name")[0]
        # 请求已经到了容器服务手里：它会在 create_after_s 之后把容器建出来，客户端死活与它无关
        subprocess.Popen(
            [
                sys.executable,
                __file__,
                "__create_later",
                str(p.get("create_after_s", 0)),
                name,
                json.dumps(labels_of(argv)),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        # 客户端这一半：等“建好”再发“启动”。等的过程中被超时杀掉，“启动”就永远不会发出去
        f = S / "containers" / f"{name}.json"
        while not f.exists():
            time.sleep(0.02)
        stalled()
        rec = json.loads(f.read_text())
        rec["state"] = "running"
        f.write_text(json.dumps(rec))
        print(name)
        return 0
    stalled()
    if argv[:2] == ["network", "create"]:
        (S / "networks" / f"{argv[-1]}.json").write_text(json.dumps({"labels": labels_of(argv)}))
        return 0
    if argv[:2] == ["network", "ls"]:
        fmt = opts(argv, "--format")[0]
        for n, r in records("networks").items():
            if match(r, opts(argv, "--filter")):
                print(render(fmt, n, r))
        return 0
    if argv[:2] == ["network", "inspect"]:
        return 0 if (S / "networks" / f"{argv[-1]}.json").exists() else 1
    if argv[:2] == ["network", "rm"]:
        f = S / "networks" / f"{argv[-1]}.json"
        if not f.exists():
            return 1
        f.unlink()
        return 0
    if argv[0] == "ps":
        fmt = opts(argv, "--format")[0]
        for n, r in records("containers").items():
            if match(r, opts(argv, "--filter")):
                print(render(fmt, n, r))
        return 0
    if argv[0] == "rm":
        f = S / "containers" / f"{argv[-1]}.json"
        if not f.exists():
            print(f"Error: No such container: {argv[-1]}", file=sys.stderr)
            return 1
        f.unlink()
        return 0
    if argv[0] == "inspect":
        f = S / "containers" / f"{argv[-1]}.json"
        if not f.exists():
            return 1
        r = json.loads(f.read_text())
        fmt = opts(argv, "--format")[0] if "--format" in argv else ""
        if "State.Running" in fmt:
            print("true" if r["state"] == "running" else "false")
        elif "Labels" in fmt:
            print(f"{r['labels'].get('paoding.sandbox', '')}|{r['labels'].get('paoding.owner', '')}")
        return 0
    print(f"fake docker: 没实现 {argv[:2]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
