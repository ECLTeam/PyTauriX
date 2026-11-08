# ============================================================
# PyTauriX
# 文件作用：核验源包包含当前绑定、桥、文档、测试和示例且未混入二进制。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import sys
import tarfile
from pathlib import Path


def main() -> None:
    """
    读取指定源包并逐字节比较项目源文件；缺失、过期或二进制文件导致失败。
    """
    root = Path(__file__).resolve().parents[1]
    archive_path = Path(sys.argv[1])
    expected: list[Path] = []
    for directory in ("python", "crates", "examples", "scripts", "tests", "docs"):
        for file in (root / directory).rglob("*"):
            relative = file.relative_to(root)
            if not file.is_file() or "gen" in relative.parts or "__pycache__" in relative.parts:
                continue
            if (
                file.suffix in {".py", ".pyi", ".rs", ".js", ".html", ".json", ".toml", ".ps1", ".png", ".ico", ".md"}
                or file.name == "py.typed"
            ):
                expected.append(relative)
    expected.extend([Path("frontend/bridge.js"), Path("AGENTS.md"), Path("uv.lock")])
    expected.extend(file.relative_to(root) for file in (root / ".github/workflows").glob("*.yml"))
    with tarfile.open(archive_path) as archive:
        names = archive.getnames()
        assert not any(name.endswith((".pyd", ".pdb", ".pyc")) for name in names)
        prefix = names[0].split("/")[0]
        for relative in expected:
            member = archive.extractfile(prefix + "/" + relative.as_posix())
            assert member is not None, relative
            # 行尾无关比较：Windows 检出是 CRLF，maturin 打包统一为 LF。
            assert member.read().replace(b"\r\n", b"\n") == (root / relative).read_bytes().replace(b"\r\n", b"\n"), (
                relative
            )
    print(f"SDIST_CURRENT_FILES_OK {len(expected)}")


if __name__ == "__main__":
    main()
