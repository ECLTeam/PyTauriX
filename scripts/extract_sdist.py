# ============================================================
# PyTauriX
# 文件作用：安全解压当前源包，刷新变更文件时间以防 Cargo 复用旧绑定。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import sys
import tarfile
from pathlib import Path


def main() -> None:
    """
    仅向项目 artifacts 子目录解压普通文件，保留相同文件以复用无关依赖缓存。
    """
    root = Path(__file__).resolve().parents[1]
    destination = Path(sys.argv[2]).resolve()
    allowed = (root / "artifacts").resolve()
    if not destination.is_relative_to(allowed) or destination == allowed:
        raise ValueError("Source extraction must target a subdirectory of project artifacts")
    changed: list[tarfile.TarInfo] = []
    with tarfile.open(sys.argv[1]) as archive:
        for member in archive.getmembers():
            path = (destination / member.name).resolve()
            if not path.is_relative_to(destination):
                raise ValueError("Archive path escapes extraction directory")
            if member.isdir():
                if not path.is_dir():
                    changed.append(member)
                continue
            if not member.isfile():
                raise ValueError("Only regular files/directories are accepted")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("Archive member has no content")
            if not path.is_file() or path.read_bytes() != source.read():
                changed.append(member)
        archive.extractall(destination, members=changed, filter="data")
        for member in changed:
            if member.isfile():
                # 可复现源包采用固定时间；内容变化必须对 Cargo 的 mtime 检测可见。
                (destination / member.name).touch()
    print(f"SDIST_EXTRACTED_CHANGED {len(changed)}")


if __name__ == "__main__":
    main()
