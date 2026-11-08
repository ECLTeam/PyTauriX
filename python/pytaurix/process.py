# ============================================================
# PyTauriX
# 文件作用：查询当前进程身份与可执行文件，并提供重启入口。
# 公开接口：current_pid、current_binary、restart。
# ============================================================
from __future__ import annotations

from pathlib import Path
from typing import NoReturn

from . import _native
from .manager import ManagerType, _handle

__all__ = ["current_binary", "current_pid", "restart"]


def current_pid() -> int:
    """
    返回当前进程标识，不需要应用实例。

    :return: 进程 ID
    """
    return _native.current_pid()


def current_binary(manager: ManagerType) -> Path:
    """
    返回当前可执行文件路径，Linux AppImage 与 macOS 符号链接差异沿用上游实现。

    :param manager: 应用、应用句柄或窗口
    :return: 可执行文件绝对路径
    :raises BindingError: 平台查询失败、路径非 UTF-8 或应用已关闭
    """
    return Path(_handle(manager).current_binary())


def restart(manager: ManagerType) -> NoReturn:
    """
    派生新进程后立即退出当前进程，不执行 Python 监听器与资源清理。

    需要有序退出、回收资源和返回退出码时改用 `AppHandle.exit`。

    :param manager: 应用、应用句柄或窗口
    :raises BindingError: 应用已关闭
    """
    _handle(manager).restart()
    raise RuntimeError("process_restart_returned: native restart returned unexpectedly")
