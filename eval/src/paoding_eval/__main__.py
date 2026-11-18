"""评测台命令行：在一道题上跑一种模式，产出一条记录。

    # baseline（单 CLI 直连），干跑（假 CLI + 假上游，不需要 Docker、不需要密钥）
    uv run python -m paoding_eval baseline --dryrun --out runs

    # baseline，真 CLI 直连（红线 5：仍经端点代理计量）
    uv run python -m paoding_eval baseline --problem eval/problems.d/q1-login.yaml \
        --program claude --upstream https://api.deepseek.com/anthropic \
        --api-key-env DEEPSEEK_API_KEY --model deepseek-chat --out runs

    # full（全栈流程），真后端（栈配置里写 backend.kind=real 及密钥环境变量名）
    uv run python -m paoding_eval full --problem eval/problems.d/q1-login.yaml \
        --config eval/stack-real.yaml --out runs

记录落在 <out>/<时间戳>-<模式>-<题目>-<次>/record.json（<out> 缺省 runs/）。答案与密钥从不写进产物目录。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

from .runner import run_baseline, run_full
from .spec import DRYRUN, load


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paoding_eval", description="庖丁评测台：baseline 与 full 两种模式")
    ap.add_argument("mode", choices=("baseline", "full"))
    ap.add_argument("--problem", type=Path, help="题目清单（YAML）；缺省用内建干跑题")
    ap.add_argument("--dryrun", action="store_true", help="内建干跑题（假后端）")
    ap.add_argument("--run", type=int, default=1, help="同一配置的第几次（从 1 起）")
    ap.add_argument("--out", type=Path, default=Path("runs"), help="产物根目录")
    ap.add_argument("--timeout", type=float, default=300)
    # baseline 真实直连
    ap.add_argument("--program", help="baseline 的真 CLI 命令（按 shell 规则切分）")
    ap.add_argument("--upstream", default="", help="baseline 的真模型端点")
    ap.add_argument("--api-key-env", default="", help="baseline 的真密钥所在的环境变量名")
    ap.add_argument("--model", default="", help="模型名（价目表里的名字）")
    # full 栈配置
    ap.add_argument("--config", type=Path, help="full 模式的栈配置（YAML）")
    ap.add_argument("--port", type=int, default=0, help="full 模式的图服务端口；0 取临时端口")
    a = ap.parse_args(argv)

    spec = DRYRUN if (a.dryrun or a.problem is None) else load(a.problem)
    a.out.mkdir(parents=True, exist_ok=True)

    if a.mode == "baseline":
        if a.program:
            import shlex

            key = os.environ.get(a.api_key_env, "") if a.api_key_env else ""
            if not key:
                print(f"baseline 真实直连要密钥：环境变量 {a.api_key_env!r} 没有设", file=sys.stderr)
                return 2
            rec = run_baseline(
                spec,
                a.run,
                out_root=a.out,
                model=a.model,
                real_program=shlex.split(a.program),
                upstream_url=a.upstream,
                api_key=key,
                timeout_s=a.timeout,
            )
        else:
            rec = run_baseline(spec, a.run, out_root=a.out, model=a.model, timeout_s=a.timeout)
    else:
        if not a.config:
            print("full 模式要栈配置：--config <YAML>", file=sys.stderr)
            return 2
        config = yaml.safe_load(a.config.read_text(encoding="utf-8")) or {}
        rec = run_full(spec, a.run, out_root=a.out, config=config, port=a.port, model=a.model, timeout_s=a.timeout)

    print(json.dumps(rec.as_dict(), ensure_ascii=False))
    return 0 if rec.terminal == "solved" else 1


if __name__ == "__main__":
    sys.exit(main())
