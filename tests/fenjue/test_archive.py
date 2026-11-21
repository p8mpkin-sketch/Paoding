"""功法存档（FJ6：任务锁定开题时的功法版本）。

开题事件记下功法摘要（F3）；在跑的题后续每次派工、每个会话都按这个摘要取功法（paoding_fenjue.for_problem），
所以每一版上线过的功法都要能按摘要取回来：archive/gongfa/<摘要>.json，连同它引用的每团火
archive/fires/<id>@<ver>.json 与火的资产 archive/assets/<sha256>（提示词原文）。

这里核：此刻的功法已存档；每份存档按文件名的摘要重算得出、引用的火与资产都在；存档只增不改（与此刻清单同版本的，
内容一字不差；资产的文件名就是内容的 sha256）。改了功法或修订了一团火，跑 scripts/lianhua.py archive 补存档。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from paoding_fenjue.contract import at, fire, fire_digest, fire_ids, gongfa

ARCHIVE = Path(__file__).resolve().parents[2] / "fenjue" / "src" / "paoding_fenjue" / "archive"
GONGFAS = sorted(p.stem for p in (ARCHIVE / "gongfa").glob("*.json"))
FIRES = sorted(p.stem for p in (ARCHIVE / "fires").glob("*.json"))
ASSETS = sorted(p.name for p in (ARCHIVE / "assets").iterdir())


def test_the_live_gongfa_is_archived():
    dg = gongfa()["digest"]
    assert dg in GONGFAS, f"此刻的功法 {dg[:12]} 没有存档：跑 scripts/lianhua.py archive（在跑的题要能按摘要取回它）"


@pytest.mark.parametrize("dg", GONGFAS, ids=lambda d: d[:12])
def test_each_archived_gongfa_comes_back_whole(dg: str):
    v = at(dg)  # 重算摘要，对不上就报错
    assert v is not None and v.digest == dg
    refs = {r for rs in [*v.g["fires"].values(), *(v.g.get("holdout") or {}).values()] for r in rs}
    assert sorted(refs - set(FIRES)) == [], "存档的功法引用了没存档的火"
    fires = [json.loads((ARCHIVE / "fires" / f"{r}.json").read_text(encoding="utf-8")) for r in refs]
    shas = {a["sha256"] for f in fires for a in f["assets"]}
    assert sorted(shas - set(ASSETS)) == [], "存档的火引用了没存档的资产"


@pytest.mark.parametrize("r", FIRES)
def test_archived_fires_are_never_rewritten(r: str):
    f = json.loads((ARCHIVE / "fires" / f"{r}.json").read_text(encoding="utf-8"))
    assert f"{f['id']}@{f['ver']}" == r
    if f["id"] in fire_ids() and fire(f["id"])["ver"] == f["ver"]:
        assert fire_digest(fire(f["id"])) == fire_digest(f), f"{r} 的清单改了却没升 ver：存档只增不改"


@pytest.mark.parametrize("sha", ASSETS, ids=lambda s: s[:12])
def test_archived_assets_are_what_their_name_says(sha: str):
    assert hashlib.sha256((ARCHIVE / "assets" / sha).read_bytes()).hexdigest() == sha
