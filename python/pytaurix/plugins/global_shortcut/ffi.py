# ============================================================
# PyTauriX
# 文件作用：全局快捷键插件，注册系统级热键并回调 Python。
# 公开接口：GlobalShortcut、init。
# ============================================================
from __future__ import annotations

from collections.abc import Callable

from ... import _native
from ...errors import BindingError
from ...ffi import AppHandle
from ...plugin import Plugin

__all__ = ["GlobalShortcut", "ShortcutHandler", "init"]

ShortcutHandler = Callable[[AppHandle, str], object]


def init() -> Plugin:
    """
    创建一次性全局快捷键插件描述符，不初始化 GUI。

    :return: 传给 Builder.build(plugins=...) 的原生插件
    :raises BindingError: 当前构建未包含该插件
    """
    if not _native.plugin_global_shortcut_available:
        raise BindingError("unsupported_capability: Build with the plugin-global-shortcut feature")
    return _native.global_shortcut_init()


def _accelerator(value: str) -> str:
    """
    校验快捷键字符串；只接受非空字符串，具体语法由上游解析。

    :raises TypeError: 不是 str
    :raises ValueError: 空字符串
    """
    if not isinstance(value, str):
        raise TypeError("accelerator must be str")
    if not value:
        raise ValueError("accelerator must not be empty")
    return value


class GlobalShortcut:
    """
    注册系统级快捷键；必须在构建时注册 global-shortcut 插件后使用。

    回调只在按键按下时触发，接收应用句柄与规范化后的快捷键文本。
    同一快捷键注册两次由上游拒绝（`shortcut_failed`）。
    """

    def __init__(self, handle: AppHandle) -> None:
        if not isinstance(handle, AppHandle):
            raise TypeError("GlobalShortcut requires an AppHandle")
        if not _native.plugin_global_shortcut_available:
            raise BindingError("unsupported_capability: Build with the plugin-global-shortcut feature")
        self._inner = _native.GlobalShortcutApi(handle)

    def register(self, accelerator: str, handler: ShortcutHandler, /) -> None:
        """
        注册快捷键并在按下时调用 handler。

        :raises BindingError: shortcut_failed、plugin_missing 或 invalid_callback
        """
        if not callable(handler):
            raise TypeError("handler must be callable")
        self._inner.register(_accelerator(accelerator), handler)

    def unregister(self, accelerator: str, /) -> None:
        """
        注销快捷键；未注册时由上游返回错误。

        :raises BindingError: shortcut_failed 或 plugin_missing
        """
        self._inner.unregister(_accelerator(accelerator))

    def unregister_all(self) -> None:
        """
        注销本应用注册的全部快捷键。
        """
        self._inner.unregister_all()

    def is_registered(self, accelerator: str, /) -> bool:
        """
        查询快捷键是否已注册。
        """
        return self._inner.is_registered(_accelerator(accelerator))
