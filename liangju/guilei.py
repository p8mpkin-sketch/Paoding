"""归类器：发现记录由系统机械地归类与去重（现行设计 7.3、13.6）。没有人在环节里，版本固定，可以重放。

类别登记簿里每个类别只有三样：编号、代表句（落进这一类的第一条发现的那句话）、至多三条例句。类别没有名字。
归类是一次固定版本的模型调用：输入是新发现的那句话与登记簿，输出只有两种，归入第几号，或新类别。发现按记录哈希
的顺序逐条处理。它是一次语义判断，不是词表或正则；唯一的例外是逐字相同的两句话直接归到一起，不再问一遍。

人可以读登记簿，可以给类别加 `label`（只用于显示，这里不读它，也不进计数）；不能手改某一条的归属。要合要拆，只能改
归类器的版本（提示词、例句条数、换题重现集），然后全部记录按新版本重算：换一个新的登记簿文件，把历次批次按顺序给上。

启用之前先在换题重现集上测（`evaluate`），四项都合格才启用：同机制的对落进同一类、不同机制的对不落进同一类、
打乱顺序后的一致率（只数至少有一遍被放进同一类的对，打乱三次取最低的一次），三个比例都不低于合格线（90%，P3）；
同样的输入算两遍划分相同。没有合格的测试记录，`classify`
拒绝启动。每批另混入两条已知答案的金丝雀（一条已有类别的换述、一条确实全新的），判错则这一批的曲线点不作数；
新句在登记簿里已经有同类时单独报「测不了增类」，不算判错。

登记簿留在跑的那台机器上（里面有发现的那句话）。写进批次目录的 `classes.json` 只有类别编号与计数，汇总从它取数。

    python -m liangju.guilei version
    python -m liangju.guilei evaluate --model model.json --out <目录>/guilei_eval.json
    python -m liangju.guilei classify --batch <批次目录> [--batch …] --registry <登记簿文件> --model model.json \\
        --eval <目录>/guilei_eval.json
"""

from __future__ import annotations

import argparse
import copy
import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any

from liangju import tici
from liangju.common import Refused, read_json, read_jsonl, sha, write_json
from liangju.model import Client, HttpClient, JudgeModel, Ledger, ModelError

HERE = Path(__file__).resolve().parent
LINE = 0.90  # 合格线（P3）：换题重现集上两项比例与顺序稳定的一致率的下限
EXAMPLES = 3  # 每个类别至多留这么多条例句
SHUFFLES = 3  # 顺序稳定：打乱几次
STAGE = "guilei"


def prompt() -> str:
    return (HERE / "prompts" / "guilei.md").read_text(encoding="utf-8")


def test_set() -> dict[str, Any]:
    doc = read_json(HERE / "guilei_set.json")
    return {"groups": doc["groups"], "canary": doc["canary"]}


def version() -> dict[str, Any]:
    """归类器的版本：提示词、每类例句条数、换题重现集与金丝雀。任何一样变了都是另一个版本，全部记录要重算。"""
    return {"prompt": sha(prompt().encode("utf-8")), "examples": EXAMPLES, "shuffles": SHUFFLES, "set": sha(test_set())}


def version_id() -> str:
    return sha(version())[:16]


class ClassifyFailed(Exception):
    """归类器自己没做成（端点调不通、两次都没给出合规的输出）。"""


def tidy(text: Any) -> str:
    return " ".join(str(text or "").split())


def new_registry(cfg: JudgeModel) -> dict[str, Any]:
    return {
        "v": 1,
        "classifier": version(),
        "model": cfg.name,
        "model_version": cfg.version,
        "classes": [],
        "texts": {},  # 逐字相同的那句话 → 类别编号
        "assigned": {},  # 记录哈希 → 归属与定位
        "unsentenced": 0,  # 没有写那句话的发现：没法归类，单独计数
        "questions": [],  # 累计跑过的新题（题集代号/题号）
        "batches": [],
    }


def _book(classes: list[dict[str, Any]]) -> str:
    rows = []
    for c in classes:
        more = "".join(f"\n  例句：{e}" for e in c["examples"])
        rows.append(f"{c['id']} 号\n  代表句：{c['rep']}{more}")
    return "\n".join(rows)


def ask(text: str, classes: list[dict[str, Any]], client: Client, ledger: Ledger) -> int | None:
    """一次归类调用。回类别编号；新类别回 None。登记簿是空的就不用问。"""
    if not classes:
        return None
    user = f"【新发现】\n{text}\n\n【登记簿】\n{_book(classes)}"
    ids = {c["id"] for c in classes}
    err = ""
    for _ in range(2):
        try:
            turn = client.chat(prompt(), [{"role": "user", "text": user + err}])
        except ModelError as e:
            raise ClassifyFailed(str(e)) from None
        ledger.add(STAGE, sha(text.encode("utf-8"))[:20], turn)
        m = re.search(r"\{.*\}", turn.text, re.S)
        try:
            got = json.loads(m.group(0))["class"] if m else "没有 JSON 对象"
        except (ValueError, KeyError, TypeError):
            got = "不是要求的 JSON 对象"
        if got == "new":
            return None
        if isinstance(got, int) and not isinstance(got, bool) and got in ids:
            return got
        err = f'\n\n（上一次的输出不合要求：{got}。只输出 {{"class": 编号}} 或 {{"class": "new"}}，编号要在登记簿里。）'
    raise ClassifyFailed("两次都没有给出合规的输出")


def assign(reg: dict[str, Any], text: str, client: Client, ledger: Ledger) -> tuple[int, bool]:
    """把一句话归进登记簿。回 (类别编号, 是不是新开的类别)。"""
    if text in reg["texts"]:
        return reg["texts"][text], False
    got = ask(text, reg["classes"], client, ledger)
    if got is None:
        got = len(reg["classes"]) + 1
        reg["classes"].append({"id": got, "rep": text, "examples": []})
        reg["texts"][text] = got
        return got, True
    c = reg["classes"][got - 1]
    if len(c["examples"]) < EXAMPLES:
        c["examples"].append(text)
    reg["texts"][text] = got
    return got, False


def partition(texts: list[str], client: Client, ledger: Ledger) -> list[int]:
    """从空登记簿起，按给的顺序逐条归类。回每句话的类别编号。"""
    reg: dict[str, Any] = {"classes": [], "texts": {}}
    return [assign(reg, t, client, ledger)[0] for t in texts]


# ---------------------------------------------------------------- 换题重现集上的四项


def _together(part: list[int]) -> set[tuple[int, int]]:
    return {(i, j) for i, j in itertools.combinations(range(len(part)), 2) if part[i] == part[j]}


def evaluate(client: Client, ledger: Ledger) -> dict[str, Any]:
    """换题重现集上的前三项。

    顺序稳定怎么算：把处理顺序打乱 `SHUFFLES` 次（每次的顺序由句子的哈希定，固定），各自从空登记簿重算。一致率只数
    「至少有一遍被放进同一类」的对：两遍都同类的对数，除以至少一遍同类的对数。两遍都不同类的对不算进去，它们占
    绝大多数、本来就会一致，算进去会把一致率垫高。几次打乱里最低的那一次不低于合格线才算合格。"""
    items = sorted(
        ((g["id"], tidy(s)) for g in test_set()["groups"] for s in g["sentences"]), key=lambda x: sha(x[1].encode())
    )
    texts = [t for _, t in items]
    base = partition(texts, client, ledger)
    again = partition(texts, client, ledger)  # 重复稳定：同样的输入算两遍
    pairs = list(itertools.combinations(range(len(texts)), 2))
    truth = {(i, j) for i, j in pairs if items[i][0] == items[j][0]}
    first = _together(base)
    same_ok, diff_ok = len(truth & first), len(pairs) - len(truth) - len(first - truth)
    shuffles = []
    for k in range(SHUFFLES):
        order = sorted(range(len(texts)), key=lambda i, k=k: sha(f"shuffle{k}|{texts[i]}".encode()))
        moved = partition([texts[i] for i in order], client, ledger)
        back = [0] * len(texts)
        for pos, i in enumerate(order):
            back[i] = moved[pos]
        other = _together(back)
        either = first | other
        shuffles.append(
            {
                "both": len(first & other),
                "either": len(either),
                "agreement": round(len(first & other) / len(either), 4) if either else 1.0,
                "same_rate": round(len(truth & other) / len(truth), 4),  # 读数：这个顺序下同机制的对落进同一类的比例
                "classes": len(set(back)),
            }
        )
    worst = min(shuffles, key=lambda x: x["agreement"])
    rates = {"same": same_ok / len(truth), "different": diff_ok / (len(pairs) - len(truth))}
    return {
        "v": 2,
        "classifier": version(),
        "line": LINE,
        "sentences": len(texts),
        "pairs": {"same": [same_ok, len(truth)], "different": [diff_ok, len(pairs) - len(truth)]},
        "split_error": round(1 - rates["same"], 4),  # 拆多了：同机制的对没落进同一类
        "merged_error": round(1 - rates["different"], 4),  # 并多了：不同机制的对落进了同一类
        "order_agreement": worst["agreement"],  # 几次打乱里最低的一次；只数至少有一遍同类的对
        "shuffles": shuffles,
        "repeat_identical": base == again,
        "classes": len(set(base)),
        "ok": all(r >= LINE for r in rates.values()) and worst["agreement"] >= LINE and base == again,
    }


def canary(reg: dict[str, Any], client: Client, ledger: Ledger) -> dict[str, Any]:
    """两条已知答案的记录，在登记簿的一份拷贝上判：换述不该增类，全新的该增类。登记簿本身不动。

    三种状态。`passed`：换述没有增类，新句增了类。`wrong`：换述被拆开了，或新句被并进了种子那一类（已知它们不是
    同一个机制）。`untestable`：新句落进了登记簿里原来就有的另一个类别，说明这个机制已经在登记簿里出现过，
    「全新」不再成立，这一批测不了增类；这不算判错，要换那一句（一次归类器的版本改动）。"""
    scratch = copy.deepcopy(reg)
    c = {k: tidy(v) for k, v in test_set()["canary"].items()}
    home, _ = assign(scratch, c["seed"], client, ledger)
    para, para_new = assign(scratch, c["paraphrase"], client, ledger)
    where, novel_new = assign(scratch, c["novel"], client, ledger)
    kept = para == home and not para_new
    novel = "added" if novel_new else ("merged_with_seed" if where == home else "class_exists")
    state = "wrong" if not kept or novel == "merged_with_seed" else ("passed" if novel == "added" else "untestable")
    return {"paraphrase_kept": kept, "novel": novel, "state": state}


# ---------------------------------------------------------------- 整批


def _gate(cfg: JudgeModel, eval_path: Path, reg: dict[str, Any] | None) -> dict[str, Any]:
    if not eval_path.exists():
        raise Refused(f"没有归类器的测试记录（{eval_path}）：先跑 evaluate，四项都合格才启用")
    ev = read_json(eval_path)
    mine = (ev.get("model"), ev.get("model_version"), ev.get("classifier")) == (cfg.name, cfg.version, version())
    if not (ev.get("ok") and mine):
        raise Refused("归类器的测试记录不是这个模型、这个版本的，或四项没有全部合格：不启用")
    if reg is not None:
        same = (reg.get("model"), reg.get("model_version"), reg.get("classifier")) == (
            cfg.name,
            cfg.version,
            version(),
        )
        if not same:
            raise Refused(
                "登记簿是另一个版本的归类器（或另一个模型）做的：不能接着用。换一个新的登记簿文件，"
                "把历次批次按顺序都给上，全部记录按新版本重算"
            )
    return dict(ev)


def _tally(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[int, int] = {}
    for r in rows:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    singles = sum(1 for n in counts.values() if n == 1)
    return {
        "classes": len(counts),
        "singletons": singles,
        "findings": len(rows),
        # 下一次失败属于没见过的类别的概率，约等于只出现过一次的类别数除以发现总数
        "unseen_probability": round(singles / len(rows), 4) if rows else None,
    }


def classify_batch(
    reg: dict[str, Any], batch_dir: Path, client: Client, ledger: Ledger, ev: dict[str, Any]
) -> dict[str, Any]:
    """一个批次的发现记录归进登记簿（改的是传进来的 `reg`）。回写进批次目录的那份只有编号与计数的结果。"""
    batch = read_json(batch_dir / "batch.json")
    bid, code = str(batch.get("id")), str((batch.get("question_set") or {}).get("code"))
    if bid in reg["batches"]:
        raise Refused(f"批次 {bid} 已经归过类：一批只归一次")
    before = len(reg["classes"])
    seen_here: dict[int, dict[str, set[str]]] = {}
    unsentenced = 0
    for f in sorted(read_jsonl(batch_dir / "findings.jsonl"), key=lambda r: str(r.get("hash"))):
        if f["hash"] in reg["assigned"]:
            continue
        text = tidy(f.get("text"))
        if not text:
            unsentenced += 1
            continue
        cls, _ = assign(reg, text, client, ledger)
        at = f["at"]
        reg["assigned"][f["hash"]] = {
            "class": cls,
            "arm": at["arm"],
            "question": f"{code}/{at['question']}",
            "batch": bid,
        }
        here = seen_here.setdefault(cls, {"questions": set(), "arms": set()})
        here["questions"].add(str(at["question"]))
        here["arms"].add(str(at["arm"]))
    reg["unsentenced"] += unsentenced
    ran = {f"{code}/{a.question}" for a in tici.load_all(batch_dir)}
    reg["questions"] = sorted(set(reg["questions"]) | ran)
    reg["batches"].append(bid)
    check = canary(reg, client, ledger)
    rows = list(reg["assigned"].values())
    arms = sorted({r["arm"] for r in rows})
    return {
        "v": 1,
        "batch": bid,
        "classifier": version_id(),
        "model": [reg["model"], reg["model_version"]],
        "classes": [
            {
                "id": cls,
                "questions": len(here["questions"]),
                "arms": sorted(here["arms"]),
                "new_in_batch": cls > before,
            }
            for cls, here in sorted(seen_here.items())
        ],
        "cumulative": {**_tally(rows), "questions": len(reg["questions"])},
        "per_arm": {a: _tally([r for r in rows if r["arm"] == a]) for a in arms},
        "unsentenced_in_batch": unsentenced,
        "canary": check,
        "curve_point_counts": check["state"] != "wrong",  # 金丝雀判错：这一批的曲线点不作数
        "evaluation": {
            **{k: ev[k] for k in ("split_error", "merged_error", "order_agreement", "repeat_identical")},
            "shuffles": len(ev["shuffles"]),
        },
    }


def run_evaluate(a: argparse.Namespace, client: Client | None = None) -> int:
    cfg = JudgeModel.load(read_json(Path(a.model)))
    out = Path(a.out)
    doc = evaluate(client or HttpClient(cfg), Ledger(out.with_name("guilei_eval_calls.jsonl")))
    write_json(out, {**doc, "model": cfg.name, "model_version": cfg.version})
    print(
        f"同机制的对落进同一类 {doc['pairs']['same'][0]}/{doc['pairs']['same'][1]}，"
        f"不同机制的对分开 {doc['pairs']['different'][0]}/{doc['pairs']['different'][1]}，"
        f"打乱 {len(doc['shuffles'])} 次里最低的一致率 {doc['order_agreement']}（只数至少有一遍同类的对），"
        f"两遍划分{'相同' if doc['repeat_identical'] else '不同'}"
    )
    print("归类器合格" if doc["ok"] else f"归类器不合格（合格线 {LINE}）：不启用")
    return 0 if doc["ok"] else 1


def run_classify(a: argparse.Namespace, client: Client | None = None) -> int:
    cfg = JudgeModel.load(read_json(Path(a.model)))
    path = Path(a.registry)
    reg = read_json(path) if path.exists() else None
    ev = _gate(cfg, Path(a.eval), reg)
    reg = reg if reg is not None else new_registry(cfg)
    client = client or HttpClient(cfg)
    ledger = Ledger(path.with_name("guilei_calls.jsonl"))
    results = []
    try:
        for b in a.batch:
            results.append((Path(b), classify_batch(reg, Path(b), client, ledger, ev)))
    except ClassifyFailed as e:
        raise Refused(f"归类没做成（{e}）：登记簿没有动，这几批都没有落") from None
    for bdir, doc in results:  # 全部做成了才落盘：登记簿与各批的结果要么都写，要么都不写
        write_json(bdir / "classes.json", doc)
    write_json(path, reg)
    for _, doc in results:
        c = doc["cumulative"]
        flag = {
            "passed": "",
            "wrong": "；金丝雀判错，这一批的曲线点不作数",
            "untestable": "；金丝雀里的新句在登记簿里已有同类，这一批测不了增类，要换那一句（版本改动）",
        }[doc["canary"]["state"]]
        print(f"批次 {doc['batch']}：累计 {c['classes']} 类，只出现过一次的 {c['singletons']} 类，", end="")
        print(f"发现 {c['findings']} 条{flag}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="liangju.guilei")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version")
    e = sub.add_parser("evaluate", help="换题重现集上的四项")
    e.add_argument("--model", required=True)
    e.add_argument("--out", required=True)
    c = sub.add_parser("classify")
    c.add_argument("--batch", action="append", required=True)
    for name in ("registry", "model", "eval"):
        c.add_argument(f"--{name}", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "version":
        print(json.dumps({"id": version_id(), **version()}, ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    try:
        return {"evaluate": run_evaluate, "classify": run_classify}[a.cmd](a)
    except Refused as x:
        print(f"拒绝：{x}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
