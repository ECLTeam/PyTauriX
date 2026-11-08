# PyTauriX
# 文件作用：用标准库生成可逐像素验证的 PNG 与 DIB ICO 样本。
# 公开接口：无。
from __future__ import annotations

import struct
import zlib
from pathlib import Path


def write_samples(root: Path) -> None:
    """
    生成透明度样本和两种图标；ICO 使用 DIB，避免仅 ICO 构建依赖 PNG 解码。
    """
    root.mkdir(parents=True, exist_ok=True)

    def png(width: int, height: int, rgba: bytes) -> bytes:
        def chunk(kind: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

        rows = b"".join(b"\0" + rgba[y * width * 4 : (y + 1) * width * 4] for y in range(height))
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows))
            + chunk(b"IEND", b"")
        )

    def ico(width: int, height: int, rgba: bytes) -> bytes:
        pixels = b"".join(
            bytes((rgba[i + 2], rgba[i + 1], rgba[i], rgba[i + 3]))
            for y in reversed(range(height))
            for x in range(width)
            for i in [4 * (y * width + x)]
        )
        mask = bytes(((width + 31) // 32) * 4 * height)
        bitmap = struct.pack("<IiiHHIIiiII", 40, width, height * 2, 1, 32, 0, len(pixels), 0, 0, 0, 0)
        payload = bitmap + pixels + mask
        return struct.pack("<HHHBBBBHHII", 0, 1, 1, width, height, 0, 0, 1, 32, len(payload), 22) + payload

    alpha = bytes((255, 0, 0, 255, 0, 255, 0, 128, 0, 0, 255, 0, 12, 34, 56, 64))
    (root / "alpha.png").write_bytes(png(2, 2, alpha))
    (root / "alpha.ico").write_bytes(ico(2, 2, alpha))
    first = bytes(value for y in range(32) for x in range(32) for value in (x * 7, y * 7, 41, 255))
    second = bytes(value for y in range(32) for x in range(32) for value in (31, x * 7, y * 7, 255))
    (root / "builder.png").write_bytes(png(32, 32, first))
    (root / "updated.ico").write_bytes(ico(32, 32, second))


if __name__ == "__main__":
    write_samples(Path(__file__).resolve().parents[1] / "examples" / "display_image" / "icons")
