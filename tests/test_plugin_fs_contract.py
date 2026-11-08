from __future__ import annotations

from pathlib import Path

import pytest
from pytaruix import BindingError, _native, get_runtime_info
from pytaruix.plugins.fs import Fs, init
from pytaruix.plugins.fs.ffi import _path


@pytest.mark.parametrize(("value", "expected"), [("a.txt", "a.txt"), (Path("a.txt"), "a.txt")])
def test_path_accepts_str_and_path(value: str | Path, expected: str) -> None:
    assert _path(value) == expected


@pytest.mark.parametrize("value", [b"a.txt", 3, None, ["a"]])
def test_path_rejects_other_types(value: object) -> None:
    with pytest.raises(TypeError, match="path must be str or Path"):
        _path(value)  # type: ignore[arg-type]


def test_path_rejects_empty_string() -> None:
    with pytest.raises(ValueError, match="path must not be empty"):
        _path("")


def test_fs_requires_app_handle() -> None:
    with pytest.raises(TypeError, match="Fs requires an AppHandle"):
        Fs(object())  # type: ignore[arg-type]


def test_runtime_reports_fs_capability_consistently() -> None:
    info = get_runtime_info()
    if _native.plugin_fs_available:
        assert "plugin.fs" in info.capabilities
        assert info.fs_version == "2.6.0"
    else:
        assert "plugin.fs" not in info.capabilities
        assert info.fs_version is None


@pytest.mark.skipif(_native.plugin_fs_available, reason="fs 插件已编译进当前构建")
def test_init_reports_missing_feature() -> None:
    with pytest.raises(BindingError) as failure:
        init()
    assert "unsupported_capability" in str(failure.value)
