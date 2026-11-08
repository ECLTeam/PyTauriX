from __future__ import annotations

import pytest
from pytaurix import BindingError, _native, get_runtime_info
from pytaurix.plugins.global_shortcut import GlobalShortcut
from pytaurix.plugins.global_shortcut import init as global_shortcut_init
from pytaurix.plugins.global_shortcut.ffi import _accelerator
from pytaurix.plugins.notification import Notification
from pytaurix.plugins.notification import init as notification_init
from pytaurix.plugins.notification.ffi import _text
from pytaurix.plugins.opener import Opener
from pytaurix.plugins.opener import init as opener_init
from pytaurix.plugins.opener.ffi import _path
from pytaurix.plugins.single_instance import init as single_instance_init


def test_availability_flags_are_bools() -> None:
    for flag in (
        _native.plugin_global_shortcut_available,
        _native.plugin_notification_available,
        _native.plugin_opener_available,
        _native.plugin_single_instance_available,
    ):
        assert isinstance(flag, bool)


@pytest.mark.parametrize(
    ("available", "entry", "capability"),
    [
        (_native.plugin_global_shortcut_available, global_shortcut_init, "plugin.global_shortcut"),
        (_native.plugin_notification_available, notification_init, "plugin.notification"),
        (_native.plugin_opener_available, opener_init, "plugin.opener"),
        (_native.plugin_single_instance_available, single_instance_init, "plugin.single_instance"),
    ],
)
def test_capability_report_matches_build(available: bool, entry: object, capability: str) -> None:
    info = get_runtime_info()
    assert (capability in info.capabilities) is available


def test_unavailable_plugins_reject_init() -> None:
    if _native.plugin_global_shortcut_available:
        pytest.skip("global-shortcut 已编译进当前构建")
    with pytest.raises(BindingError) as failure:
        global_shortcut_init()
    assert "unsupported_capability" in str(failure.value)


def test_accelerator_validation() -> None:
    assert _accelerator("Ctrl+Shift+K") == "Ctrl+Shift+K"
    with pytest.raises(TypeError):
        _accelerator(1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        _accelerator("")


def test_notification_text_validation() -> None:
    assert _text("标题", "title") == "标题"
    with pytest.raises(TypeError, match="body must be str"):
        _text(b"body", "body")


def test_opener_path_validation() -> None:
    assert _path("a.txt") == "a.txt"
    with pytest.raises(ValueError):
        _path("")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: GlobalShortcut(object()),  # type: ignore[arg-type]
        lambda: Notification(object()),  # type: ignore[arg-type]
        lambda: Opener(object()),  # type: ignore[arg-type]
    ],
)
def test_wrappers_require_app_handle(factory: object) -> None:
    with pytest.raises(TypeError, match="requires an AppHandle"):
        factory()  # type: ignore[operator]
