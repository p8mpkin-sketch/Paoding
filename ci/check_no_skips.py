"""CI 守门：Docker 测试在 CI 里跳过即失败（审计阶段一第 5 项）。

本地没有 Docker 时这些测试自动跳过，方便开发；但 CI 里 Docker 一定在。要是 CI 镜像哪天缺了 Docker，
隔离类测试会全部变成"跳过"而流水线仍是绿的。本脚本读 pytest 的 JUnit XML，凡是跳过原因里提到 Docker 的，
一律判失败。

用法：
    uv run pytest --junitxml=pytest.xml ...
    python ci/check_no_skips.py pytest.xml
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET


def docker_skips(path: str) -> list[str]:
    out = []
    for case in ET.parse(path).getroot().iter("testcase"):
        sk = case.find("skipped")
        if sk is None:
            continue
        reason = (sk.get("message") or "") + " " + (sk.text or "")
        if "docker" in reason.lower():
            out.append(f"{case.get('classname')}::{case.get('name')} — {reason.strip()[:120]}")
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法：python ci/check_no_skips.py <junit.xml>")
        return 2
    hits = docker_skips(argv[1])
    for h in hits:
        print(f"Docker 测试被跳过：{h}")
    if hits:
        print(f"{len(hits)} 条 Docker 测试在 CI 里被跳过：CI 里必须有 Docker，隔离类测试不许静默跳过。")
        return 1
    print("Docker 测试：没有被跳过的。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
