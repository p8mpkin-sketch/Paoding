"""验收②（cz 2026-11-20）：切分确定性单独跑一轮。同一段文本、同一切分器版本，得到同一组段落与 id。

单独一个文件，可以只跑它：uv run --frozen pytest -q shuku/tests/test_chunk_determinism.py
"""

from __future__ import annotations

import hashlib
import random
import subprocess
import sys
from pathlib import Path

from paoding_graph.contract import BlobStore
from paoding_shuku.chunk import CHUNKER, chunk
from paoding_shuku.service import Shuku

SAMPLES = {
    "md": "# 部署\n\n部署前先跑全量测试。\n\n## 回滚\n\n"
    + "回滚用上一个标签重新发布。" * 80
    + "\n\n# 监控\n\n延迟超过 300ms 报警。\n",
    "code": "\n\n".join(f"def f{i}(x):\n    return x * {i}\n" for i in range(60)),
    "long-line": "这是一句没有句号的很长的话" * 200,
    "mixed": "Rollback steps.\n\n" + "第一步：停写入. 第二步：切流量；第三步：回滚。\n" * 50,
    "empty-ish": "\n\n\n   \n",
}


def fingerprint(text: str, key: str) -> list[tuple[str, str, int, int, str]]:
    cs = chunk(key, text, "doc.md")
    return [(c.id, c.heading, c.start, c.end, hashlib.sha256(c.text.encode()).hexdigest()) for c in cs]


def test_same_input_same_ids_repeated() -> None:
    for name, text in SAMPLES.items():
        key = hashlib.sha256(text.encode()).hexdigest()
        first = fingerprint(text, key)
        for _ in range(5):
            assert fingerprint(text, key) == first, name


def test_same_ids_in_a_fresh_interpreter() -> None:
    """换一个进程（不同的哈希随机种子）也一样：id 不依赖 Python 的 hash() 或字典顺序。"""
    text = SAMPLES["md"]
    key = hashlib.sha256(text.encode()).hexdigest()
    code = (
        "import sys, json; from paoding_shuku.chunk import chunk; "
        "t = sys.stdin.read(); print(json.dumps([c.id for c in chunk(sys.argv[1], t, 'doc.md')]))"
    )
    ids = []
    for seed in ("1", "2"):
        out = subprocess.run(
            [sys.executable, "-c", code, key],
            input=text,
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": ""},
        )
        ids.append(out.stdout.strip())
    assert ids[0] == ids[1]
    assert ids[0] == str([c.id for c in chunk(key, text, "doc.md")]).replace("'", '"')


def test_ids_change_with_text_or_chunker_but_not_with_order_of_calls() -> None:
    a, b = SAMPLES["md"], SAMPLES["mixed"]
    ka, kb = (hashlib.sha256(x.encode()).hexdigest() for x in (a, b))
    order = [(a, ka), (b, kb)] * 3
    random.Random(7).shuffle(order)
    seen: dict[str, list[str]] = {}
    for text, key in order:
        ids = [c.id for c in chunk(key, text)]
        assert seen.setdefault(key, ids) == ids
    assert not set(seen[ka]) & set(seen[kb])
    assert CHUNKER == "c1"  # 改规则要换版本号，id 随之变；这里提醒改测试的人


def test_rebuild_and_reimport_keep_ids(tmp_path: Path) -> None:
    """服务层：重建索引、同样的字节再导入一次，段落 id 都不变。"""
    blobs = BlobStore(tmp_path / "blobs")
    sk = Shuku(tmp_path / "shuku", blobs)
    data = SAMPLES["md"].encode()
    f = {"hash": blobs.put(data), "size": len(data), "media_type": "", "name": "doc.md"}
    s1 = sk.put_source("一", "file", "all", f)
    s2 = sk.put_source("二", "file", "all", f)
    for _ in range(4):
        sk.tick()

    def ids(sid: str) -> list[str]:
        return sorted(h["id"] for h in sk.search("回滚 部署 监控", k=20, pick=[sid])["hits"])

    before = (ids(s1), ids(s2))
    assert before[0] and before[0] == before[1]  # 同样的字节 → 同样的纯文本哈希 → 同样的 id
    sk.rebuild()
    assert (ids(s1), ids(s2)) == before
    sk.close()
