# ============================================================
# PyTauriX
# 文件作用：验证插件所有权、迁移类型和无 GUI 参数边界。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pytaurix import BindingError
from pytaurix.plugin import Plugin
from pytaurix.plugins.dialog import MessageDialogButtons, MessageDialogKind, init
from pytaurix.plugins.dialog.ffi import _callback, _options


def test_descriptor_is_native_readonly_and_does_not_initialize_gui() -> None:
    descriptor = init()
    assert isinstance(descriptor, Plugin)
    assert descriptor.name == "dialog" and not descriptor.consumed
    with pytest.raises(TypeError):
        Plugin()
    with pytest.raises(AttributeError):
        object.__setattr__(descriptor, "name", "fake")


@pytest.mark.parametrize(
    "options",
    [
        {"wrong": True},
        {"set_title": 42},
        {"set_file_name": "bad\0name"},
        {"set_directory": []},
        {"set_can_create_directories": 1},
        {"add_filter": ("Text", "txt")},
        {"add_filter": ("Text", [42])},
        {"add_filter": ("Text",)},
        {"set_parent": object()},
    ],
)
def test_invalid_file_options_do_not_show_dialogs(options: dict[str, object]) -> None:
    with pytest.raises(BindingError, match=r"invalid_(dialog_option|parent)"):
        _options(options)


@pytest.mark.parametrize("options", [{"kind": "Info"}, {"buttons": "Ok"}, {"title": None}, {"unknown": 1}])
def test_message_options_require_typed_variants(options: dict[str, object]) -> None:
    with pytest.raises(BindingError, match="invalid_dialog_option"):
        _options(options, message=True)


def test_options_preserve_paths_false_filters_and_custom_tuple_contract() -> None:
    encoded, parent = _options(
        {
            "set_directory": Path("中文") / "目录",
            "set_can_create_directories": False,
            "add_filter": ("Text", ("txt", "md")),
            "set_file_name": "目标.txt",
        }
    )
    assert parent is None
    assert json.loads(encoded) == {
        "set_directory": str(Path("中文") / "目录"),
        "set_can_create_directories": False,
        "add_filter": ["Text", ["txt", "md"]],
        "set_file_name": "目标.txt",
    }
    buttons = MessageDialogButtons.OkCancelCustom("确定", "取消")
    assert tuple(buttons) == (buttons._0, buttons._1) == ("确定", "取消")
    encoded, _ = _options({"kind": MessageDialogKind.Warning, "buttons": buttons}, message=True)
    assert json.loads(encoded) == {"kind": "Warning", "buttons": {"OkCancelCustom": ["确定", "取消"]}}


@pytest.mark.parametrize("value", [None, 42, "callback"])
def test_noncallable_cannot_fall_through_to_blocking(value: object) -> None:
    with pytest.raises(BindingError, match="invalid_callback"):
        _callback(value)


def test_build_rejection_preserves_input_and_runtime_before_consumption() -> None:
    code = """
from pathlib import Path
from pytaurix import BindingError, Commands, builder_factory, context_factory
from pytaurix.plugins.dialog import DialogExt, MessageDialogButtons, init
context = context_factory(Path("examples/minimal"))
handler = Commands().generate_handler()
plugin = init()
plugins = [plugin]
invalid_cases = [
    ([object()], "invalid_plugin"), ([plugin, init()], "duplicate_plugin"),
    ([plugin, plugin], "duplicate_plugin"), (None, "invalid_plugin"),
]
for invalid, expected in invalid_cases:
    try:
        builder_factory().build(context=context, invoke_handler=handler, plugins=invalid)
    except BindingError as error:
        assert expected in str(error), str(error)
    else:
        raise AssertionError("Invalid plugins accepted")
    assert not plugin.consumed
app = builder_factory().build(context=context, invoke_handler=handler, plugins=plugins)
assert plugins == [plugin] and plugin.consumed
DialogExt.file(app)
operations = [
    (lambda: DialogExt.file(app).blocking_pick_file(), "app_not_running"),
    (lambda: builder_factory().build(context=context, invoke_handler=handler, plugins=plugins), "plugin_consumed"),
    (lambda: DialogExt.message(app, "test").blocking_show(buttons=MessageDialogButtons.OkCustom(r"\\u0000")),
     "app_not_running"),
]
for operation, expected in operations:
    try:
        operation()
    except BindingError as error:
        assert expected in str(error), str(error)
    else:
        raise AssertionError("Invalid lifetime accepted")
del app
print("PLUGIN_OWNERSHIP_OK")
"""
    _process(code, "PLUGIN_OWNERSHIP_OK")


def test_unregistered_plugin_returns_error_instead_of_native_panic() -> None:
    code = """
from pathlib import Path
from pytaurix import BindingError, Commands, builder_factory, context_factory
from pytaurix.plugins.dialog import DialogExt
app = builder_factory().build(
    context=context_factory(Path("examples/minimal")), invoke_handler=Commands().generate_handler()
)
try:
    DialogExt.file(app.handle())
except BindingError as error:
    assert "plugin_missing" in str(error)
else:
    raise AssertionError("Unregistered dialog was exposed")
print("PLUGIN_MISSING_OK")
"""
    _process(code, "PLUGIN_MISSING_OK")


def test_unrun_application_can_finalize_with_plugin_and_state() -> None:
    code = """
from pathlib import Path
from pytaurix import Commands, Manager, builder_factory, context_factory
from pytaurix.plugins.dialog import init
app = builder_factory().build(
    context=context_factory(Path("examples/minimal")),
    invoke_handler=Commands().generate_handler(), plugins=[init()],
)
class Shared:
    pass
Manager.manage(app, Shared())
print("PLUGIN_FINALIZATION_OK")
"""
    _process(code, "PLUGIN_FINALIZATION_OK")


def _process(code: str, marker: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, PYTHONUTF8="1"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "panicked" not in result.stderr and "PanicException" not in result.stderr, result.stderr
    assert marker in result.stdout
