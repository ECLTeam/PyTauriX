# ============================================================
# PyTauriX
# 文件作用：生成首轮构建使用的几何开发图标，不依赖第三方素材。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import struct
import zlib
from pathlib import Path


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def main() -> None:
    """
    在构建资源目录生成 32 像素 PNG 和 ICO 开发图标。
    """
    size = 32
    pixels = b"".join(b"\0" + bytes((38, 105, 150, 255)) * size for _ in range(size))
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += _png_chunk(b"IDAT", zlib.compress(pixels)) + _png_chunk(b"IEND", b"")
    root = Path(__file__).resolve().parents[1] / "crates" / "bindings" / "icons"
    root.mkdir(parents=True, exist_ok=True)
    (root / "icon.png").write_bytes(png)
    ico = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(png), 22) + png
    (root / "icon.ico").write_bytes(ico)


if __name__ == "__main__":
    main()
