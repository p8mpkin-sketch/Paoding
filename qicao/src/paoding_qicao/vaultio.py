"""答案写保密库（规格 3.3.2 含密级资产；设计 §2.5）。键是随机的：不能由答案推出，也不能拿来离线比对。"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from paoding_judgebox.contract import Vault


def write_answer(vault_dir: str | Path, answer: str) -> dict[str, Any]:
    return Vault(vault_dir).put("kt-" + secrets.token_hex(12), answer.encode())
