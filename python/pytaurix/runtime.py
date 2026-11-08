# ============================================================
# PyTauriX
# 文件作用：公开当前运行时身份和已绑定能力，避免依赖猜测。
# 公开接口：RuntimeInfo、get_runtime_info。
# ============================================================
from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from importlib.metadata import version

from . import _native


@dataclass(frozen=True, slots=True)
class RuntimeInfo:
    """
    保存当前发行包、原生绑定版本和明确可用的原型能力。

    capabilities 描述已绑定接口，不表示上游 feature 的完整覆盖或平台验收。
    """

    package_version: str
    tauri_version: str
    pyo3_version: str
    python_version: str
    platform: str
    dialog_version: str | None = None
    fs_version: str | None = None
    window_state_version: str | None = None
    capabilities: tuple[str, ...] = (
        (
            "app.run_return",
            "app.handle",
            "app.setup",
            "ipc.sync",
            "ipc.async_portal",
            "ipc.pydantic",
            "ipc.app_handle",
            "ipc.webview_window",
            "ipc.state",
            "ipc.headers",
            "ipc.bytes",
            "ipc.channel",
            "ipc.channel_model",
            "ipc.channel_close",
            "event.emit",
            "event.emit_to_label",
            "event.targets",
            "event.raw_json",
            "event.listen",
            "event.once",
            "event.unlisten",
            "event.window_scope",
            "event.listen_any",
            "event.once_any",
            "dispatch.main_thread",
            "lifecycle.prevent_exit",
            "lifecycle.ready_exit",
            "window.lookup",
            "window.set_title",
            "window.set_focus",
            "window.close",
            "window.build",
            "window.build_async",
            "window.from_config",
            "window.enumerate",
            "window.geometry",
            "window.monitors",
            "dpi.physical_rect",
            "window.visibility",
            "window.selected_attributes",
            "window.extended_attributes",
            "window.events_scale_theme_drag_drop",
            "window.title_changed",
            "window.download",
            "window.lifecycle",
            "webview.data_directory",
            "webview.new_window_policy",
            "webview.permission_request",
            "webview.web_resource_request",
            "webview.navigation",
            "webview.page_load",
            "webview.reference",
            "image.rgba",
            "acl.local_window_labels",
            "config.toml",
            "config.platform_override",
            "config.dev_url",
            "config.host_icon",
            "acl.host_capabilities",
            "path.resolve",
            "path.parse",
            "path.directories",
            "process.current_pid",
            "process.current_binary",
            "process.restart",
            "plugin.register",
        )
        + (("plugin.dialog",) if _native.plugin_dialog_available else ())
        + (("plugin.fs",) if _native.plugin_fs_available else ())
        + (("plugin.global_shortcut",) if _native.plugin_global_shortcut_available else ())
        + (("plugin.notification",) if _native.plugin_notification_available else ())
        + (("plugin.opener",) if _native.plugin_opener_available else ())
        + (("plugin.single_instance",) if _native.plugin_single_instance_available else ())
        + (("plugin.window_state",) if _native.plugin_window_state_available else ())
        + (("tray.icon", "tray.builder", "tray.events", "tray.close") if _native.tray_available else ())
        + (("webview.devtools.open",) if _native.devtools_available else ())
        + (
            ("webview.devtools.close", "webview.devtools.state")
            if _native.devtools_available and sys.platform != "win32"
            else ()
        )
        + (
            ("menu.items", "menu.attach", "menu.popup", "menu.events", "menu.callback_clear")
            if _native.menu_available
            else ()
        )
        + tuple("image." + image_format for image_format in _native.image_decode_formats)
    )
    image_formats: tuple[str, ...] = tuple(_native.image_decode_formats)


def get_runtime_info() -> RuntimeInfo:
    """
    返回当前运行时信息，不创建窗口或初始化原生事件循环。

    :return: 不可变运行时能力快照
    """
    return RuntimeInfo(
        package_version=version("pytaurix"),
        tauri_version=_native.tauri_version,
        pyo3_version=_native.pyo3_version,
        python_version=platform.python_version(),
        platform=sys.platform,
        dialog_version="2.8.1" if _native.plugin_dialog_available else None,
        fs_version="2.6.0" if _native.plugin_fs_available else None,
        window_state_version=("2.4.0" if _native.plugin_window_state_available else None),
    )
