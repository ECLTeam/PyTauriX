# ============================================================
# PytaruiX
# 文件作用：封装 tauri-plugin-fs 的桌面文件读写与路径校验。
# 公开接口：Fs、init。
# ============================================================
from __future__ import annotations

from pathlib import Path

from ... import _native
from ...errors import BindingError
from ...ffi import AppHandle
from ...plugin import Plugin

__all__ = ["Fs", "init"]


def init() -> Plugin:
    """
    创建一次性 fs 插件描述符，不初始化 GUI。

    只有构建时启用 `plugin-fs` feature 才可用。

    :return: 传给 Builder.build(plugins=...) 的原生插件
    :raises BindingError: 当前构建未包含 fs 插件
    """
    if not _native.plugin_fs_available:
        raise BindingError("unsupported_capability: Build with the plugin-fs feature")
    return _native.fs_init()


def _path(value: str | Path) -> str:
    """
    把 str/Path 归一为原生接受的字符串路径，不做规范化或存在性检查。

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


class Fs:
    """
    通过 fs 插件读写文件；必须在构建时注册 fs 插件后使用。

    上游 Rust API 只是 `std::fs` 的薄封装，**不经过 capability scope 校验**，
    因此这里不提供受限访问；需要沙箱时请自行校验路径。目录遍历、删除与重命名
    在上游只存在于前端命令层，Python 侧直接用 `pathlib` 更直接。
    """

    def __init__(self, handle: AppHandle) -> None:
        if not isinstance(handle, AppHandle):
            raise TypeError("Fs requires an AppHandle")
        if not _native.plugin_fs_available:
            raise BindingError("unsupported_capability: Build with the plugin-fs feature")
        self._inner = _native.Fs(handle)

    def read_text(self, path: str | Path, /) -> str:
        """
        读取 UTF-8 文本；原生读盘释放 GIL。

        :raises BindingError: fs_failed 或 plugin_missing
        """
        return self._inner.read_text(_path(path))

    def read_bytes(self, path: str | Path, /) -> bytes:
        """
        读取原始字节，返回 ArrayBuffer。

        :raises BindingError: fs_failed 或 plugin_missing
        """
        return self._inner.read_bytes(_path(path))

    def write_text(self, path: str | Path, contents: str, /) -> None:
        """
        创建或截断文件后写入文本，不追加、不改权限。

        :raises BindingError: fs_failed 或 plugin_missing
        :raises TypeError: contents 不是 str
        """
        if not isinstance(contents, str):
            raise TypeError("contents must be str")
        self._inner.write_text(_path(path), contents)

    def write_bytes(self, path: str | Path, data: bytes, /) -> None:
        """
        创建或截断文件后写入字节。

        :raises BindingError: fs_failed 或 plugin_missing
        :raises TypeError: data 不是 bytes
        """
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        self._inner.write_bytes(_path(path), data)
