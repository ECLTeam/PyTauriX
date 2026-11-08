# ============================================================
# PyTauriX
# 文件作用：单实例插件入口，第二个进程把参数交给已有实例。
# 公开接口：init。
# ============================================================
from __future__ import annotations

from collections.abc import Callable

from ... import _native
from ...errors import BindingError
from ...ffi import AppHandle
from ...plugin import Plugin

__all__ = ["init"]

SingleInstanceHandler = Callable[[AppHandle, tuple[str, ...], str], object]


def init(handler: SingleInstanceHandler) -> Plugin:
    """
    创建一次性单实例插件描述符。

    回调在第二个进程启动时执行，参数为应用句柄、命令行参数与工作目录；
    回调应为同步函数，返回 awaitable 或抛异常会结束应用并由 run_return 重抛。
    该插件应尽量靠前登记，构建器已把用户插件排在桥接插件之前。

    :param handler: 同步回调
    :return: 传给 Builder.build(plugins=...) 的原生插件
    :raises BindingError: 当前构建未包含该插件，或 handler 不可调用
    """
    if not _native.plugin_single_instance_available:
        raise BindingError("unsupported_capability: Build with the plugin-single-instance feature")
    if not callable(handler):
        raise BindingError("invalid_callback: single-instance handler must be callable")
    return _native.single_instance_init(handler)
