"""回收站过期后只清会话目录，不动别的题，重复调用无害。"""

from __future__ import annotations

from pathlib import Path

from paoding_adapter.purge import TRASH_MS, purge_workspaces


def test_purge_only_expired_trash(tmp_path: Path) -> None:
    for lid in ("l_1", "l_2", "l_3"):
        (tmp_path / lid / "workspace").mkdir(parents=True)
    state = {
        "problems": {
            "old": {"shelf": {"state": "trash", "seq": 9, "ts": 0}},
            "fresh": {"shelf": {"state": "trash", "seq": 9, "ts": 1000}},
            "kept": {},
        },
        "leases": {
            "l_1": {"problem_id": "old"},
            "l_2": {"problem_id": "fresh"},
            "l_3": {"problem_id": "kept"},
            "l_4": {"problem_id": "old"},  # 目录不在
        },
    }
    assert purge_workspaces(state, tmp_path, TRASH_MS) == ["l_1"]
    assert not (tmp_path / "l_1").exists() and (tmp_path / "l_2").exists() and (tmp_path / "l_3").exists()
    assert purge_workspaces(state, tmp_path, TRASH_MS) == []
