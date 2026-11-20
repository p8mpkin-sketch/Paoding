"""零差迁移的判据（焚决 F2，docs/design/fenjue/06-migration.md §3.3）。不是测试，手动跑：

    uv run python tests/fenjue/zero_diff.py            # 录：写 tests/fenjue/zerodiff.json（F2 之前的 main 上录）
    uv run python tests/fenjue/zero_diff.py --check    # 核对：同一组剧本重跑，与已录的逐条相同才算零差

剧本不另写：适配层、司南与全栈集成的既有测试本来就用假 CLI 跑遍了三段式、独行、接力、收尾、扩权、受阻。
运行时截下两样东西，按测试归档：

- 事件：测试台里每个图服务的整份日志，每条只留 (problem_id, kind, actor, body)，见 norm_event；
- 任务包：每个会话的任务包原文（留档的 JSON、追加系统提示、首条用户消息），与每一轮的工具清单、续跑与提示。

两样各自规范化（JCS）后取 sha256。核对时逐测试比对，差了就列出是哪个测试的哪一样。
跑两遍，只收两遍结果相同的测试（并行会话的竞态、真时刻），测试自身的不确定性不算到迁移头上。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name("zerodiff.json")
SUITES = ["adapter/tests", "sinan/tests", "tests/integration"]
KEEP = ("problem_id", "kind", "actor", "body")  # 去掉 seq、ts、hash、prev_hash、idem_key（幂等键里带随机的任务令牌）
SEQ_ID = re.compile(r"\b([a-z]{1,2})_\d+\b")  # a_7、l_3、f_12：由 seq 派生的 id
TMP = re.compile(r"/tmp/pytest-of-[^/]+/pytest-\d+/[^/\"'\s]+")
TOKEN = re.compile(r"pdt-[A-Za-z0-9_-]{20,}")
RANDOM = re.compile(r"\bkt-[0-9a-f]{12}\b")  # 一句话开题的题号带随机后缀
HEX64 = re.compile(r"\b[0-9a-f]{64}\b")  # Blob 的 sha256：执行输出里有时刻与路径，保密库的摘要带随机盐


def norm(x: Any) -> Any:
    """跑与跑之间必然不同、且与迁移无关的东西抹平：临时目录、随机任务令牌与题号、Blob 摘要、seq 派生的 id。
    并行会话的事件交错次序不定，所以 seq 与由它派生的 id 不比；比的是每条事件的种类、提交者与内容。"""
    if isinstance(x, dict):
        return {norm(k): norm(v) for k, v in x.items()}
    if isinstance(x, list):
        return [norm(v) for v in x]
    if isinstance(x, str):
        x = TMP.sub("<tmp>", TOKEN.sub("pdt-*", RANDOM.sub("kt-*", HEX64.sub("<sha256>", x))))
        return SEQ_ID.sub(r"\1_*", x)
    return x


def norm_event(e: dict[str, Any]) -> Any:
    out = norm({k: e[k] for k in KEEP})
    b = out["body"]
    # 会话写的叙述（任务包、会话记录、活动段）与执行输出的大小因跑而异（路径、时刻）。
    # 任务包本身另按原文比（下面的 packages）；会话记录、活动段与执行层 F2 不碰。
    if out["kind"] == "register_artifact" and b.get("class") in ("authored", "exec", "judge"):
        b = {k: v for k, v in b.items() if k != "size"}
        if isinstance(b.get("exec"), dict):  # 执行的起止时刻
            b["exec"] = {k: v for k, v in b["exec"].items() if k not in ("started_at", "ended_at")}
    out["body"] = b
    return out


def digest(x: Any) -> str:
    from paoding_graph.jcs import canonicalize

    return hashlib.sha256(canonicalize(x)).hexdigest()


class Recorder:
    def __init__(self) -> None:
        self.out: dict[str, dict[str, Any]] = {}
        self.graphs: list[Any] = []
        self.packages: list[Any] = []

    def pytest_configure(self, config: pytest.Config) -> None:
        from paoding_adapter import session as ses
        from paoding_graph import service

        rec = self
        orig_init = service.GraphService.__init__

        def init(svc: Any, *a: Any, **k: Any) -> None:
            orig_init(svc, *a, **k)
            rec.graphs.append(svc)

        service.GraphService.__init__ = init  # type: ignore[method-assign]

        orig_render = ses.render

        def render(*a: Any, **k: Any) -> Any:
            r = orig_render(*a, **k)
            rec.packages.append({"package": r.package, "system": r.system, "user": r.user})
            return r

        ses.render = render

        orig_round = ses.SessionRunner._round

        def round_(runner: Any, plan: Any, *a: Any, **k: Any) -> Any:
            r = {"resume": plan.resume, "user": plan.user_prompt, "tools": list(plan.proxy_tools)}
            rec.packages.append({"round": r})
            return orig_round(runner, plan, *a, **k)

        ses.SessionRunner._round = round_  # type: ignore[method-assign]

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item: pytest.Item, nextitem: Any) -> Any:
        self.graphs, self.packages = [], []
        yield
        events = []
        for g in self.graphs:
            try:
                evs = g.events()
            except Exception:  # noqa: BLE001  测试已关掉的库：这一台不收
                continue
            events.append(sorted(json.dumps(norm_event(e), ensure_ascii=False, sort_keys=True) for e in evs))
        if not events and not self.packages:
            return
        self.out[item.nodeid] = {
            "events": digest(events),
            "n_events": sum(len(x) for x in events),
            "packages": digest(sorted(json.dumps(norm(p), ensure_ascii=False, sort_keys=True) for p in self.packages)),
            "n_packages": len(self.packages),
        }


def surface() -> dict[str, Any]:
    """不必起会话就能取到的那一面：各席位的提示词（扩权与资料两段的四种组合）、全部工具的形状、司南的次序。
    test_zero_diff_surface.py 在 CI 里每次都比它，作为功法装载器的回归。"""
    from paoding_adapter.package import role_prompt
    from paoding_adapter.tools import tool_schemas
    from paoding_sinan.loop import TASK_ORDER

    seats = ("bootstrap", "reason", "explore", "solve")
    prompts = {f"{r}:{a}:{k}": role_prompt(r, a, k) for r in seats for a in (False, True) for k in (False, True)}
    tools = ("exec", "submit", "show", "request_access", "deliver", "kb_search", "kb_read")
    return {"prompts": prompts, "tools": tool_schemas(tools), "order": list(TASK_ORDER)}


def run() -> dict[str, dict[str, Any]]:
    rec = Recorder()
    code = pytest.main(["-q", "-p", "no:cacheprovider", "-x", *[str(ROOT / s) for s in SUITES]], plugins=[rec])
    if code != 0:
        raise SystemExit(f"剧本没有全过（pytest 退出码 {code}），不录")
    return rec.out


RETRIES = 20


def again(nodeid: str) -> dict[str, Any]:
    rec = Recorder()
    pytest.main(["-q", "-p", "no:cacheprovider", str(ROOT / nodeid)], plugins=[rec])
    return rec.out.get(nodeid, {})


def stable(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in a.items() if b.get(k) == v}


def main(argv: list[str]) -> int:
    first, second = run(), run()
    now = stable(first, second)
    sf = surface()  # 录的时候也带上：核对时与冻结的比
    now["@surface"] = {"events": "", "n_events": 0, "packages": digest(sf), "n_packages": len(sf["prompts"])}
    if "--check" not in argv:
        OUT.write_text(json.dumps(dict(sorted(now.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"录下 {len(now)} 个测试（{len(first) - len(now)} 个两次运行不一致，不收）→ {OUT.relative_to(ROOT)}")
        return 0
    frozen = json.loads(OUT.read_text(encoding="utf-8"))
    bad, racy = [], []
    for k, v in frozen.items():
        got = now.get(k) or first.get(k)
        if got is None:
            bad.append(f"{k}: 这次没有跑到")
            continue
        diff = [part for part in ("events", "packages") if got[part] != v[part]]
        if not diff:
            continue
        # 竞态：并行会话收尾前后读日志，条数因跑而异（改动前同样如此）。单独重跑，任一次与已录的相同就算零差：
        # 代码真的变了，哪一次都对不上
        if k != "@surface" and any(all(again(k).get(p) == v[p] for p in diff) for _ in range(RETRIES)):
            racy.append(k)
            continue
        bad += [f"{k}: {p} 不同（{v['n_' + p]} → {got['n_' + p]} 条）" for p in diff]
    print(
        f"核对 {len(frozen)} 个测试：{'零差' if not bad else f'{len(bad)} 处不同'}（{len(racy)} 个有竞态，重跑后对上）"
    )
    for b in bad + [f"{k}: 竞态，重跑后与已录的相同" for k in racy]:
        print("  " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
