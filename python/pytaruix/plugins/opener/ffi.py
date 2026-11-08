# ============================================================
# PytaruiX
# 文件作用：用系统默认程序打开链接、文件或定位条目。
# 公开接口：Opener、init。
# ============================================================
from __future__ import annotations

from pathlib import Path

from ... import _native
from ...errors import BindingError
from ...ffi import AppHandle
from ...plugin import Plugin

__all__ = ["Opener", "init"]


def init() -> Plugin:
    """
    创建一次性 opener 插件描述符，不初始化 GUI。

    :return: 传给 Builder.build(plugins=...) 的原生插件
    :raises BindingError: 当前构建未包含该插件
    """
    if not _native.plugin_opener_available:
        raise BindingError("unsupported_capability: Build with the plugin-opener feature")
    return _native.opener_init()


def _path(value: str | Path) -> str:
    """
    把 str/Path 归一为字符串路径。

    :raises TypeError: 不是 str 或 Path
    :raises ValueError: 空路径
    """
    if isinstance(value, Path):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        raise TypeError("path must be str or Path")
    if not text:
        raise ValueError("path must not be empty")
    return text


class Opener:
    """
    调用系统默认程序；必须在构建时注册 opener 插件后使用。

    返回 None 只表示请求已提交，不确认外部程序已经启动。
    """

    def __init__(self, handle: AppHandle) -> None:
        if not isinstance(handle, AppHandle):
            raise TypeError("Opener requires an AppHandle")
        if not _native.plugin_opener_available:
            raise BindingError("unsupported_capability: Build with the plugin-opener feature")
        self._inner = _native.OpenerApi(handle)

    def open_url(self, url: str, /, *, with_app: str | None = None) -> None:
        """
        用默认浏览器打开链接。

        :raises BindingError: opener_failed 或 plugin_missing
        :raises TypeError: url 或 with_app 类型不符
        """
        if not isinstance(url, str) or not url:
            raise TypeError("url must be a non-empty str")
        if with_app is not None and not isinstance(with_app, str):
            raise TypeError("with_app must be str or None")
        self._inner.open_url(url, with_app=with_app)

    def open_path(self, path: str | Path, /, *, with_app: str | None = None) -> None:
        """
        用默认程序打开文件或目录。

        :raises BindingError: opener_failed 或 plugin_missing
        """
        if with_app is not None and not isinstance(with_app, str):
            raise TypeError("with_app must be str or None")
        self._inner.open_path(_path(path), with_app=with_app)

    def reveal_item_in_dir(self, path: str | Path, /) -> None:
        """
        在系统文件管理器中定位并选中条目。

        :raises BindingError: opener_failed 或 plugin_missing
        """
        self._inner.reveal_item_in_dir(_path(path))
