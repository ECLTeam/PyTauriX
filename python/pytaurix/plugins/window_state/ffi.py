# ============================================================
# PyTauriX
# 文件作用：封装 tauri-plugin-window-state 的窗口几何持久化。
# 公开接口：WindowState、init。
# ============================================================
from __future__ import annotations

from collections.abc import Iterable

from ... import _native
from ...errors import BindingError
from ...ffi import AppHandle, WebviewWindow
from ...plugin import Plugin

__all__ = ["WindowState", "init"]

# 与原生侧一一对应的标志名；顺序即文档顺序。
_STATE_FLAGS = (
    "size",
    "position",
    "maximized",
    "visible",
    "decorations",
    "fullscreen",
)


def _labels(values: Iterable[object] | None, field: str) -> tuple[str, ...]:
    """
    归一标签序列，只做类型与空值检查，不校验标签是否存在。

    :raises TypeError: 不是可迭代对象或元素不是 str
    :raises ValueError: 标签为空
    """
    if values is None:
        return ()
    if isinstance(values, str):
        raise TypeError(f"{field} must be a sequence of labels, not a single string")
    try:
        prepared = tuple(values)
    except TypeError as error:
        raise TypeError(f"{field} must be a sequence of labels") from error
    checked: list[str] = []
    for value in prepared:
        if not isinstance(value, str):
            raise TypeError(f"{field} entries must be str")
        if not value.strip():
            raise ValueError(f"{field} entries must not be empty")
        checked.append(value)
    return tuple(checked)


def _flags(values: Iterable[object] | None) -> tuple[str, ...] | None:
    """
    校验标志名，拒绝未知项；None 表示沿用上游默认（全部标志）。

    :raises ValueError: 存在未知标志
    """
    if values is None:
        return None
    if isinstance(values, str):
        raise TypeError("flags must be a sequence of flag names, not a single string")
    try:
        prepared = tuple(values)
    except TypeError as error:
        raise TypeError("flags must be a sequence of flag names") from error
    checked: list[str] = []
    for value in prepared:
        if not isinstance(value, str):
            raise TypeError("flag names must be str")
        if value not in _STATE_FLAGS:
            raise ValueError(f"unknown state flag: {value}")
        checked.append(value)
    return tuple(checked)


def init(
    *,
    filename: str | None = None,
    flags: Iterable[object] | None = None,
    denylist: Iterable[object] | None = None,
    skip_initial: Iterable[object] | None = None,
) -> Plugin:
    """
    创建窗口状态插件描述符；注册后由插件在窗口事件中自动保存与恢复。

    只有构建时启用 `plugin-window-state` feature 才可用。

    :param filename: 状态文件名，默认沿用上游的 `.window-state.json`
    :param flags: 参与保存/恢复的标志，默认全部
    :param denylist: 不参与持久化的窗口标签
    :param skip_initial: 首次创建时不恢复的窗口标签
    :return: 传给 Builder.build(plugins=...) 的原生插件
    :raises BindingError: 当前构建未包含该插件
    """
    if not _native.plugin_window_state_available:
        raise BindingError("unsupported_capability: Build with the plugin-window-state feature")
    if filename is not None and not isinstance(filename, str):
        raise TypeError("filename must be str")
    if filename is not None and not filename.strip():
        raise ValueError("filename must not be empty")
    prepared_flags = _flags(flags)
    return _native.window_state_init(
        filename=filename,
        flags=list(prepared_flags) if prepared_flags is not None else None,
        denylist=list(_labels(denylist, "denylist")),
        skip_initial=list(_labels(skip_initial, "skip_initial")),
    )


class WindowState:
    """
    运行期入口：手动保存全部窗口状态，或恢复一个已存在的窗口。

    新建窗口的恢复由插件在创建时自行完成，这里只处理"已经存在的窗口"。
    未注册插件时所有方法报 `plugin_missing`。
    """

    def __init__(self, handle: AppHandle) -> None:
        if not isinstance(handle, AppHandle):
            raise TypeError("WindowState requires an AppHandle")
        self._native = _native.WindowStateApi(handle)

    def save(self, *, flags: Iterable[object] | None = None) -> None:
        """
        把当前所有打开窗口的状态写入配置文件。

        :raises BindingError: 插件未注册、应用已退出或写入失败
        """
        prepared = _flags(flags)
        self._native.save(flags=list(prepared) if prepared is not None else None)

    def restore(self, window: WebviewWindow, *, flags: Iterable[object] | None = None) -> None:
        """
        按持久化内容恢复指定窗口。

        :raises BindingError: 插件未注册、窗口已销毁或恢复失败
        :raises TypeError: window 不是 WebviewWindow
        """
        if not isinstance(window, WebviewWindow):
            raise TypeError("restore requires a WebviewWindow")
        prepared = _flags(flags)
        self._native.restore(window, flags=list(prepared) if prepared is not None else None)

    @property
    def filename(self) -> str:
        """
        插件当前使用的状态文件名。

        :raises BindingError: 插件未注册或应用已退出
        """
        return self._native.filename
