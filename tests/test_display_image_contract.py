from __future__ import annotations

import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import pytest
from pytaruix import BindingError, get_runtime_info
from pytaruix.dpi import PhysicalPosition, PhysicalRect, PhysicalSize
from pytaruix.ffi.image import Image
from pytaruix.ffi.window import Monitor

samples = Path(__file__).resolve().parents[1] / "examples" / "display_image" / "icons"
alpha = bytes((255, 0, 0, 255, 0, 255, 0, 128, 0, 0, 255, 0, 12, 34, 56, 64))


def test_rect_signed_snapshot() -> None:
    rect = PhysicalRect(PhysicalPosition(-1920, -240), PhysicalSize(1920, 1080))
    assert (rect.position.x, rect.position.y, rect.size.width, rect.size.height) == (-1920, -240, 1920, 1080)
    with pytest.raises(AttributeError):
        rect.position = PhysicalPosition(0, 0)  # type: ignore[misc]
    assert isinstance(Monitor.name, property) or hasattr(Monitor.name, "__get__")


@pytest.mark.parametrize("format_name", ["png", "ico"])
def test_native_encoded_pixels(format_name: str) -> None:
    path = samples / f"alpha.{format_name}"
    formats = get_runtime_info().image_formats
    if format_name not in formats:
        code = "feature_unavailable"
        with pytest.raises(BindingError, match=code):
            Image.from_bytes(path.read_bytes())
        code = "feature_unavailable"
        with pytest.raises(BindingError, match=code):
            Image.from_path(path)
        return
    for image in (Image.from_bytes(path.read_bytes()), Image.from_path(path)):
        assert (image.width, image.height, image.rgba) == (2, 2, alpha)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(image.rgba == alpha for image in pool.map(Image.from_path, [path] * 16))


@pytest.mark.parametrize(
    "data", [b"", b"\x89PNG\r\n\x1a\n", b"\x00\x00\x01\x00\x01\x00", b"GIF89a", b"\xff\xd8\xffbad"]
)
def test_decode_errors(data: bytes) -> None:
    formats = get_runtime_info().image_formats
    disabled = (
        not formats
        or (data.startswith(b"\x89PNG\r\n\x1a\n") and "png" not in formats)
        or (data.startswith(b"\x00\x00\x01\x00") and "ico" not in formats)
    )
    code = "feature_unavailable" if disabled else "image_decode_failed"
    with pytest.raises(BindingError, match=code):
        Image.from_bytes(data)


def test_ico_transitive_bmp_decoder_not_exposed(tmp_path: Path) -> None:
    bitmap = bytearray((samples / "alpha.ico").read_bytes()[22:78])
    struct.pack_into("<i", bitmap, 8, 2)
    encoded = struct.pack("<2sIHHI", b"BM", 14 + len(bitmap), 0, 0, 54) + bytes(bitmap)
    code = "image_decode_failed" if get_runtime_info().image_formats else "feature_unavailable"
    with pytest.raises(BindingError, match=code):
        Image.from_bytes(encoded)
    path = tmp_path / "supported-transitively.bmp"
    path.write_bytes(encoded)
    code = "image_load_failed" if get_runtime_info().image_formats else "feature_unavailable"
    with pytest.raises(BindingError, match=code):
        Image.from_path(path)


def test_decode_paths(tmp_path: Path) -> None:
    code = "image_load_failed" if get_runtime_info().image_formats else "feature_unavailable"
    for path in (tmp_path / "missing.png", tmp_path):
        with pytest.raises(BindingError, match=code):
            Image.from_path(path)
    path = tmp_path / "中文图像.data"
    path.write_bytes((samples / "alpha.png").read_bytes())
    if "png" in get_runtime_info().image_formats:
        assert Image.from_path(path).rgba == alpha
    path.write_bytes(b"damaged")
    with pytest.raises(BindingError, match=code):
        Image.from_path(path)


def test_decode_types_and_capabilities() -> None:
    for value in ("bytes", bytearray(b"test"), memoryview(b"test")):
        with pytest.raises(TypeError):
            Image.from_bytes(cast(bytes, value))
    for value in ("image.png", b"image.png", None):
        with pytest.raises(TypeError):
            Image.from_path(cast(Path, value))
    info = get_runtime_info()
    assert set(info.image_formats) <= {"png", "ico"}
    assert all(("image." + name in info.capabilities) == (name in info.image_formats) for name in ("png", "ico"))
    assert "window.monitors" in info.capabilities
    assert "dpi.physical_rect" in info.capabilities
    assert Image(bytes((1, 2, 3, 4)), 1, 1).rgba == bytes((1, 2, 3, 4))
