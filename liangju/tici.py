"""题次记录：一条臂、一道题、一次运行留下的东西，写成与臂无关的同一种形状。

盲判与汇总只认这种形状，不认任何一条臂自己的导出。每条臂各有一个转换（这里只有我们自己的引擎这一种：
`from_export`），转换只读运行结束之后的导出：工作区导出目录、这道题的事件、这道题的预算视图、交付的回答。

    <批次目录>/attempts/<臂>/<题号>/<第几次>/attempt.json
    <批次目录>/attempts/<臂>/<题号>/<第几次>/answer.md      （交出了回答才有）

`attempt.json` 里 `own` 一栏是这条臂自己才有的读数，只进汇总的「只报告、不进门」那一组；盲判不读这个文件。

用法（引擎这条臂，整批转换）：

    python -m liangju.tici collect --runs runs.json --home ~/paoding-analysis --url http://127.0.0.1:8200 \
        --out <批次目录> [--dump <目录>]

`runs.json` 是一张表：`[{"pid": 题的编号, "arm": 臂名, "question": 题号, "rep": 第几次}]`。给了 `--dump` 时不连服务，
从那个目录读 `<pid>.events.json`、`<pid>.budget.json`、`<pid>.answer.md`（先另行存下的同样三样）。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from liangju.common import Refused, read_json, write_json

STATUSES = ("finished", "watchdog", "over_budget", "model_failure", "unreadable_repo", "other")
ROOT = Path(__file__).resolve().parents[1]
PRICES = ROOT / "adapter" / "config" / "prices.yaml"
TIMELINE = "时间线"  # 引擎写在停下原因里的词（阅读与核对的两条线都带它）


@dataclass
class Attempt:
    arm: str
    question: str
    rep: int
    status: str
    models_seen: list[str]
    usage: dict[str, int]  # input（新输入）、cached_input（命中缓存的输入）、output、calls
    cost_usd_milli: int  # 按同一张价表从用量折算
    price_table: str
    metering: str  # 用量取自哪里
    elapsed_s: float | None
    cap_usd_milli: int | None = None  # 这次运行自己的花费上限（没有试火计划时用它判「在预算内」）
    booked_usd_milli: int | None = None  # 这条臂自己账上记的数，只作对照
    gongfa: str | None = None  # 开题时的功法摘要
    settings: str | None = None  # 开题时的设置摘要
    own: dict[str, Any] = field(default_factory=dict)
    answer: str | None = None  # 不写进 attempt.json，单独放 answer.md

    @property
    def key(self) -> tuple[str, int]:
        return (self.question, self.rep)


def convert_micro(prices: dict[str, Any], model: str, usage: dict[str, int]) -> float:
    """同一张价表折算（百万分之一美元）。价表里没有这个模型就拒绝：量具不猜价。"""
    p = prices["models"].get(model)
    if p is None:
        raise Refused(f"价表 {prices['version']} 里没有模型 {model!r}，先补上这一行再折算")
    return float(usage["input"] * p["input"] + usage["cached_input"] * p["cache_read"] + usage["output"] * p["output"])


def convert(prices: dict[str, Any], model: str, usage: dict[str, int]) -> int:
    """折算成毫美元，向上取整。"""
    return math.ceil(convert_micro(prices, model, usage) / 1000 - 1e-9)


def save(root: Path, a: Attempt) -> Path:
    if a.status not in STATUSES:
        raise Refused(f"运行状态只取 {STATUSES}，不是 {a.status!r}")
    d = root / "attempts" / a.arm / a.question / str(a.rep)
    doc = asdict(a)
    doc.pop("answer")
    doc["v"] = 1
    doc["has_answer"] = a.answer is not None
    write_json(d / "attempt.json", doc)
    if a.answer is not None:
        (d / "answer.md").write_text(a.answer, encoding="utf-8")
    return d


def load_all(root: Path) -> list[Attempt]:
    out = []
    for f in sorted((root / "attempts").glob("*/*/*/attempt.json")):
        doc = read_json(f)
        doc.pop("v", None)
        has = doc.pop("has_answer", False)
        a = Attempt(**doc)
        if has:
            a.answer = (f.parent / "answer.md").read_text(encoding="utf-8")
        out.append(a)
    return out


# ---------------------------------------------------------------- 我们自己的引擎这条臂


def _artifact(export: Path, run: dict[str, Any], name: str) -> Any:
    sha_ = (run.get("artifacts") or {}).get(name)
    f = export / "artifacts" / f"{sha_}.json"
    return read_json(f) if sha_ and f.exists() else None


def _own(export: Path) -> dict[str, Any]:
    """只有我们自己的臂才有的读数。导出里没有的写 None，不估。"""
    own: dict[str, Any] = {"timeline_stop": None, "engine_items": [], "on_defs": None, "checks_first_pass": None}
    ql = read_json(export / "ql.json") if (export / "ql.json").exists() else {}
    run = read_json(export / "run.json") if (export / "run.json").exists() else {}
    ans = _artifact(export, run, "ql:answer") or {}
    own["route"] = ql.get("route")
    if ql.get("route") == "question_led":
        stops = [str((ql.get("read") or {}).get("stop") or ""), *(str(s) for s in ans.get("stops", []))]
        own["timeline_stop"] = any(TIMELINE in s for s in stops)
        own["on_defs"] = sorted(int(v) for v in ((ql.get("stats") or {}).get("on_defs") or {}).values())
    own["engine_items"] = [
        {"text": str(it.get("text", "")), "verdict": str(it.get("verdict", ""))} for it in ans.get("items", [])
    ]
    st = read_json(export / "model_stats.json") if (export / "model_stats.json").exists() else {}
    own["model_calls"] = {k: st.get(k) for k in ("truncated", "upstream_timeouts", "gave_up")}
    return own


def from_export(
    export: Path,
    events: list[dict[str, Any]],
    budget: dict[str, Any],
    answer: str | None,
    *,
    arm: str,
    question: str,
    rep: int,
    prices: dict[str, Any],
) -> Attempt:
    costs = [e["body"] for e in events if e.get("kind") == "cost"]
    models = sorted({str(c.get("model", "")) for c in costs})
    usage = {
        "input": sum(int(c.get("tokens_in", 0)) for c in costs),
        "cached_input": sum(int(c.get("tokens_cached", 0)) for c in costs),
        "output": sum(int(c.get("tokens_out", 0)) for c in costs),
        "calls": len(costs),
    }
    micro = sum(  # 一次运行里用过不止一个模型时逐个模型折算，合计后再取整
        convert_micro(
            prices,
            str(c.get("model", "")),
            {
                "input": int(c.get("tokens_in", 0)),
                "cached_input": int(c.get("tokens_cached", 0)),
                "output": int(c.get("tokens_out", 0)),
            },
        )
        for c in costs
    )
    cost = math.ceil(micro / 1000 - 1e-9)
    spent = int((budget.get("spent") or {}).get("usd_milli") or 0)
    cap = int((budget.get("cap") or {}).get("usd_milli") or 0) or None
    delivers = [e["body"] for e in events if e.get("kind") == "deliver"]
    own = _own(export)
    if cap is not None and spent >= cap:
        status = "over_budget"
    elif answer is not None and delivers and delivers[-1].get("outcome") in ("answered", "partial"):
        status = "finished"
    elif (own["model_calls"].get("gave_up") or 0) > 0:
        status = "model_failure"
    else:
        status = "other"
    ts = [int(e["ts"]) for e in events if isinstance(e.get("ts"), int)]
    opened: dict[str, Any] = next((e["body"] for e in events if e.get("kind") == "open_problem"), {})

    def digest(key: str) -> str | None:
        v = opened.get(key)
        return str(v["digest"]) if isinstance(v, dict) and v.get("digest") else None

    return Attempt(
        arm=arm,
        question=question,
        rep=rep,
        status=status,
        models_seen=models,
        usage=usage,
        cost_usd_milli=cost,
        price_table=str(prices["version"]),
        metering="端点代理的计量事件",
        elapsed_s=round((max(ts) - min(ts)) / 1000, 1) if ts else None,
        cap_usd_milli=cap,
        booked_usd_milli=spent,
        gongfa=digest("gongfa"),
        settings=digest("settings"),
        own=own,
        answer=answer,
    )


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310  只连人给的本机服务地址
        return bytes(r.read())


def fetch(url: str, pid: str) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    """这道题的事件、预算视图、最后一次交付的回答（只读的三个 GET）。"""
    events = json.loads(_get(f"{url}/v1/problems/{pid}/events?after=0&limit=100000"))["events"]
    budget = json.loads(_get(f"{url}/v1/problems/{pid}/budget"))
    aid = next((e["body"].get("answer") for e in reversed(events) if e.get("kind") == "deliver"), None)
    answer = None
    if aid:
        meta = json.loads(_get(f"{url}/v1/artifacts/{aid}"))
        answer = _get(f"{url}/v1/blobs/{meta['hash']}").decode("utf-8", "replace")
    return events, budget, answer


def collect(a: argparse.Namespace) -> int:
    prices = yaml.safe_load(Path(a.prices).read_text(encoding="utf-8"))
    home, out = Path(a.home).expanduser(), Path(a.out)
    n = 0
    for row in read_json(Path(a.runs)):
        pid = str(row["pid"])
        if a.dump:
            d = Path(a.dump)
            events = read_json(d / f"{pid}.events.json")
            events = events["events"] if isinstance(events, dict) else events
            budget = read_json(d / f"{pid}.budget.json")
            f = d / f"{pid}.answer.md"
            answer = f.read_text(encoding="utf-8") if f.exists() else None
        else:
            events, budget, answer = fetch(a.url.rstrip("/"), pid)
        att = from_export(
            home / "analyses" / pid,
            events,
            budget,
            answer,
            arm=str(row["arm"]),
            question=str(row["question"]),
            rep=int(row["rep"]),
            prices=prices,
        )
        save(out, att)
        n += 1
    print(f"整理了 {n} 个题次，写在 {out / 'attempts'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="liangju.tici")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="把引擎的导出整理成题次记录")
    c.add_argument("--runs", required=True)
    c.add_argument("--home", required=True)
    c.add_argument("--url", default="http://127.0.0.1:8200")
    c.add_argument("--dump")
    c.add_argument("--out", required=True)
    c.add_argument("--prices", default=str(PRICES))
    try:
        return collect(ap.parse_args(argv))
    except Refused as e:
        print(f"拒绝：{e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
