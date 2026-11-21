"""材料定版（docs/design/fenjue/13-kernel.md §4）：把一份材料的原始字节解成快照目录。确定性，零 token。

材料到引擎手里是一份原始字节：人上传的归档或单个文件（内核的 input 类 Artifact），或沙箱按固定命令抓回来的归档
（仓库地址、文档地址）。这里只做一件事：把它变成 `survey.load_snapshot` 认的目录。归档来自外部，按不可信数据处理：

- 只取普通文件；符号链接、硬链接、设备、管道一律跳过并记数，所以解出来的目录里没有指到目录外面的东西；
- 路径规整后必须落在目标目录里：绝对路径、带 `..` 的、带控制字符或过长的条目跳过；
- 三道上限（文件数、单个文件大小、总大小）到了就停，记 `truncated`：压缩炸弹解不出超过上限的字节；
- 不执行任何东西，不看文件权限位，写出的文件一律普通权限。

同一份字节解两次，目录内容逐字节相同（按条目在归档里的顺序写，重名的后者不覆盖前者）；`manifest.json` 之外不写别的。
本模块在模型容器里由驱动程序调用（宿主只把原始字节拷进工作区，不解析它），不发请求、不起进程。
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tarfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

MARK = ".material.json"  # 快照目录旁的记号：这份目录是从哪份字节解出来的（同一份就不再解）


@dataclass(frozen=True)
class Limits:
    files: int = 20_000
    file_bytes: int = 2_000_000
    total_bytes: int = 200_000_000
    path_chars: int = 240
    scan_factor: int = 4  # 扫过的条目数、条目声明的字节数至多是上限的这么多倍；超了就停（不为跳过的条目无限解压）


class BadMaterial(ValueError):
    """材料解不开（归档损坏，或里面没有一个可读的普通文件）。"""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def kind_of(head: bytes) -> str:
    """按文件头认种类：zip | tar（含各种压缩）| file。只看字节，不信文件名与媒体类型。"""
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        return "zip"
    if head[:2] == b"\x1f\x8b" or head[:3] == b"BZh" or head[:6] == b"\xfd7zXZ\x00":
        return "tar"
    if len(head) >= 262 and head[257:262] == b"ustar":
        return "tar"
    return "file"


def _clean(name: str, lim: Limits) -> str | None:
    """归档条目名 → 目录内的相对路径；不该要的返回 None。"""
    name = name.replace("\\", "/")
    if not name or len(name) > lim.path_chars or name.startswith("/") or any(ord(c) < 32 for c in name):
        return None
    parts = [p for p in PurePosixPath(name).parts if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts) or (len(parts[0]) == 2 and parts[0][1] == ":"):
        return None
    return "/".join(parts)


def _tar_members(blob: Path, lim: Limits, note: dict[str, int]) -> Iterator[tuple[str, bytes]]:
    try:
        with tarfile.open(blob, mode="r|*") as tf:  # 流式：不回头找
            seen = entries = 0
            for m in tf:
                # 流式读要把上一个条目的字节解完才到下一个：声明的字节数累计超限就此打住，
                # 否则一个“被跳过”的巨大条目照样能让解压跑到天荒地老（压缩炸弹）
                entries += 1
                seen += max(0, int(m.size))
                if seen > lim.total_bytes * lim.scan_factor or entries > lim.files * lim.scan_factor:
                    note["truncated"] = 1
                    break
                if not m.isfile():
                    if not m.isdir():
                        note["skipped_special"] += 1
                    continue
                if m.size > lim.file_bytes:
                    note["skipped_large"] += 1
                    continue
                f = tf.extractfile(m)
                if f is None:
                    continue
                yield m.name, f.read(lim.file_bytes + 1)
    except (tarfile.TarError, EOFError, OSError) as e:
        raise BadMaterial(f"归档读不下去：{type(e).__name__}") from None


def _zip_members(blob: Path, lim: Limits, note: dict[str, int]) -> Iterator[tuple[str, bytes]]:
    try:
        with zipfile.ZipFile(blob) as zf:
            infos = zf.infolist()
            if len(infos) > lim.files * lim.scan_factor:
                note["truncated"] = 1
                infos = infos[: lim.files * lim.scan_factor]
            for info in infos:
                if info.is_dir():
                    continue
                if (info.external_attr >> 16) & 0o170000 == 0o120000:  # 符号链接
                    note["skipped_special"] += 1
                    continue
                if info.file_size > lim.file_bytes:
                    note["skipped_large"] += 1
                    continue
                with zf.open(info) as f:
                    yield info.filename, f.read(lim.file_bytes + 1)
    except (zipfile.BadZipFile, EOFError, OSError, RuntimeError, NotImplementedError) as e:
        raise BadMaterial(f"归档读不下去：{type(e).__name__}") from None


def unpack(
    blob: Path, dest: Path, *, single_name: str = "material.txt", limits: Limits | None = None
) -> dict[str, Any]:
    """把 blob 解到 dest（先清空）。归档只有一个顶层目录时去掉这一层（常见的仓库归档）。
    不是归档就当单个文件，名字用 single_name。返回清单并写在 dest 旁的记号文件里。"""
    lim = limits or Limits()
    sha = sha256_file(blob)
    mark = dest.parent / (dest.name + MARK)
    if dest.is_dir() and mark.exists():
        try:
            old: dict[str, Any] = json.loads(mark.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
        if old.get("sha256") == sha and old.get("single_name") == single_name:
            return old
    with blob.open("rb") as f:
        kind = kind_of(f.read(512))
    note = {"skipped_special": 0, "skipped_large": 0, "skipped_path": 0, "skipped_duplicate": 0, "truncated": 0}
    files: dict[str, bytes] = {}
    total = 0
    truncated = False
    if kind == "file":
        data = blob.read_bytes() if blob.stat().st_size <= lim.total_bytes else b""
        if not data:
            raise BadMaterial("材料是空的，或单个文件超过上限")
        files[_clean(single_name, lim) or "material.txt"] = data
        total = len(data)
    else:
        members = _tar_members(blob, lim, note) if kind == "tar" else _zip_members(blob, lim, note)
        for name, data in members:
            rel = _clean(name, lim)
            if rel is None:
                note["skipped_path"] += 1
                continue
            if len(data) > lim.file_bytes:
                note["skipped_large"] += 1
                continue
            if rel in files:
                note["skipped_duplicate"] += 1
                continue
            if len(files) >= lim.files or total + len(data) > lim.total_bytes:
                truncated = True
                break
            files[rel] = data
            total += len(data)
        truncated = truncated or bool(note.pop("truncated", 0))
        if not files:
            raise BadMaterial("归档里没有可读的普通文件")
        tops = {p.split("/", 1)[0] for p in files}
        if len(tops) == 1 and all("/" in p for p in files):  # 只有一个顶层目录：去掉这一层
            files = {p.split("/", 1)[1]: b for p, b in files.items()}
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    elif dest.exists():
        shutil.rmtree(dest)
    root = dest.resolve()
    for rel, data in files.items():
        p = (dest / rel).resolve()
        if root not in p.parents:  # 规整过的路径不该越界；再查一次，查不过就不写
            note["skipped_path"] += 1
            continue
        if p.parent.is_file():  # 归档里同一个名字既当文件又当目录：后来的不写
            note["skipped_duplicate"] += 1
            continue
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except (FileExistsError, NotADirectoryError):
            note["skipped_duplicate"] += 1
            continue
        if p.is_dir():
            note["skipped_duplicate"] += 1
            continue
        p.write_bytes(data)
    manifest: dict[str, Any] = {
        "v": 1,
        "sha256": sha,
        "kind": kind,
        "single_name": single_name,
        "files": len(files),
        "bytes": total,
        "truncated": truncated,
        **{k: v for k, v in note.items() if v and k != "truncated"},
    }
    mark.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def pack(root: Path) -> bytes:
    """把一个目录打成确定性的 tar.gz（按路径排序，时间与属主清零）。开题脚本与测试用它把材料目录变成一份字节。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6, format=tarfile.PAX_FORMAT) as tf:
        for p in sorted(x for x in root.rglob("*") if x.is_file() and not x.is_symlink()):
            data = p.read_bytes()
            info = tarfile.TarInfo(p.relative_to(root).as_posix())
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            tf.addfile(info, io.BytesIO(data))
    raw = buf.getvalue()
    return raw[:4] + b"\x00\x00\x00\x00" + raw[8:]  # gzip 头里的时间戳清零：同一目录恒得同一份字节
