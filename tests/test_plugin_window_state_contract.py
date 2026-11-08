from __future__ import annotations

import pytest
from pytaruix import BindingError, _native, get_runtime_info
from pytaruix.plugins.window_state import WindowState, init
from pytaruix.plugins.window_state.ffi import _flags, _labels


def test_flags_accept_known_names() -> None:
    assert _flags(["size", "position"]) == ("size", "position")


def test_flags_default_to_none() -> None:
    assert _flags(None) is None


def test_flags_reject_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown state flag: always_on_top"):
        _flags(["always_on_top"])


def test_flags_reject_plain_string() -> None:
    with pytest.raises(TypeError, match="not a single string"):
        _flags("size")  # type: ignore[arg-type]


def test_flags_reject_non_string_entry() -> None:
    with pytest.raises(TypeError, match="flag names must be str"):
        _flags([1])  # type: ignore[list-item]


def test_labels_reject_plain_string() -> None:
    with pytest.raises(TypeError, match="not a single string"):
        _labels("main", "denylist")  # type: ignore[arg-type]


def test_labels_reject_empty_entry() -> None:
    with pytest.raises(ValueError, match="denylist entries must not be empty"):
        _labels(["  "], "denylist")


def test_labels_normalize_to_tuple() -> None:
    assert _labels(("a", "b"), "skip_initial") == ("a", "b")
    assert _labels(None, "skip_initial") == ()


def test_window_state_requires_app_handle() -> None:
    with pytest.raises(TypeError, match="WindowState requires an AppHandle"):
        WindowState(object())  # type: ignore[arg-type]


def test_runtime_reports_window_state_capability_consistently() -> None:
    info = get_runtime_info()
    if _native.plugin_window_state_available:
        assert "plugin.window_state" in info.capabilities
        assert info.window_state_version == "2.4.0"
    else:
        assert "plugin.window_state" not in info.capabilities
        assert info.window_state_version is None


def test_init_validates_filename_before_build() -> None:
    if not _native.plugin_window_state_available:
        pytest.skip("window-state 插件未编译进当前构建")
    with pytest.raises(ValueError, match="filename must not be empty"):
        init(filename=" ")
    with pytest.raises(TypeError, match="filename must be str"):
        init(filename=1)  # type: ignore[arg-type]


@pytest.mark.skipif(_native.plugin_window_state_available, reason="window-state 插件已编译进当前构建")
def test_init_reports_missing_feature() -> None:
    with pytest.raises(BindingError) as failure:
        init()
    assert "unsupported_capability" in str(failure.value)
