# ============================================================
# PyTauriX
# 文件作用：封装 Python 主线程启动、配置与应用生命周期。
# 公开接口：App、Builder、context_factory、builder_factory。
# ============================================================
from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from . import _native
from .configuration import _merge_config as _merge_config
from .configuration import _prepare_context
from .events import ExitRequestApi, RunEvent, RunEventType
from .ffi import AppHandle, BindingError, Context
from .plugin import Plugin

if TYPE_CHECKING:
    from .tray import TrayIconEventType


class InvokeHandler(Protocol):
    def __call__(
        self,
        command_name: str,
        payload_json: str | bytes,
        app_handle: AppHandle,
        webview_window: _native.WebviewWindow | None = None,
        headers: list[tuple[bytes, bytes]] | None = None,
        request: _native.Request | None = None,
    ) -> str | bytes: ...


RunCallback = Callable[[AppHandle, RunEventType], None]
SetupCallback = Callable[[AppHandle], object]


def _require_main_thread() -> None:
    if threading.current_thread() is not threading.main_thread():
        raise BindingError("wrong_thread: GUI must run on the Python main thread")


class App:
    """
    拥有一次性原生应用，在主线程运行事件循环。

    build 创建原生应用；配置窗口和 setup 遵循上游，在事件循环 Ready 时执行。
    事件循环结束时释放监听器与共享状态，已有句柄的资源操作随后报错。
    """

    def __init__(self, native_app: _native.App) -> None:
        self._native_app = native_app

    def handle(self) -> AppHandle:
        """
        在主线程取得可跨线程使用的应用句柄，运行前即可调用。

        :return: 应用句柄
        :raises BindingError: 非主线程或应用已关闭
        """
        _require_main_thread()
        return self._native_app.handle()

    def run_return(self, callback: RunCallback | None = None, /) -> int:
        """
        在 Python 主线程运行事件循环，退出后归还控制权。

        回调异常触发有序退出，并在事件循环退出后重新抛出原异常。
        主循环期间释放 GIL，每个进程仅支持一次原生事件循环。

        :param callback: 接收应用句柄和生命周期事件的同步回调
        :return: 原生应用退出代码
        :raises BindingError: 线程错误、重复运行或原生启动失败
        """
        _require_main_thread()

        def receive_event(handle: AppHandle, event_name: str, code: int | None, api: ExitRequestApi | None) -> None:
            if callback is not None:
                if event_name == "exit_requested":
                    if api is None:
                        raise BindingError("invalid_event: Exit request API is missing")
                    callback(handle, RunEvent.ExitRequested(code, api))
                else:
                    callback(handle, RunEvent.Ready() if event_name == "ready" else RunEvent.Exit())

        return self._native_app.run_return(receive_event if callback is not None else None)


class Builder:
    """
    构建主线程使用的原生应用。

    plugins 只接受本绑定提供的原生插件描述符，成功构建时消费其所有权。
    """

    def build(
        self,
        *,
        context: Context,
        invoke_handler: InvokeHandler,
        setup: SetupCallback | None = None,
        plugins: Sequence[Plugin] = (),
        protocols: Sequence[_native.Protocol] = (),
        on_tray_icon_event: Callable[[AppHandle, TrayIconEventType], None] | None = None,
    ) -> App:
        """
        构建原生应用，窗口及 setup 在事件循环 Ready 时创建/执行。

        :param context: 资源快照和运行配置
        :param invoke_handler: Commands.generate_handler 生成的处理器
        :param setup: 同步初始化回调，异常会退出并由 run_return 重抛
        :param plugins: 原生插件序列；不修改输入，插件不能重复消费
        :param protocols: create_protocol 生成的协议描述符；构建时消费
        :param on_tray_icon_event: 应用级同步托盘事件回调，需 tray-icon feature
        :return: 尚未启动的应用
        :raises BindingError: 线程错误、处理器不可调用或协议名称重复
        """
        _require_main_thread()
        if on_tray_icon_event is not None:
            from .ffi.tray import _handler

            _handler(on_tray_icon_event)
            if not _native.tray_available:
                raise BindingError("unsupported_capability: Build with the desktop tray-icon feature")
            original_setup = setup

            def setup_with_tray(handle: AppHandle) -> object:
                handle.on_tray_icon_event(on_tray_icon_event)
                if original_setup is not None:
                    return original_setup(handle)

            setup = setup_with_tray
        try:
            prepared = list(plugins)
        except TypeError as error:
            raise BindingError("invalid_plugin: Expected a sequence of native plugins") from error
        if any(not isinstance(plugin, Plugin) for plugin in prepared):
            raise BindingError("invalid_plugin: Expected native Plugin descriptors")
        try:
            schemes = list(protocols)
        except TypeError as error:
            raise BindingError("invalid_protocol: Expected a sequence of protocols") from error
        if any(not isinstance(protocol, _native.Protocol) for protocol in schemes):
            raise BindingError("invalid_protocol: Expected create_protocol descriptors")
        return App(
            _native.builder_factory().build(
                context=context,
                invoke_handler=invoke_handler,
                setup=setup,
                plugins=prepared,
                protocols=schemes,
            )
        )


def builder_factory() -> Builder:
    """
    创建独立应用构建器，不依赖隐式扩展发现或全局运行时选择。

    :return: 新的构建器
    """
    return Builder()


def context_factory(
    resource_path: Path, /, *, tauri_config: Mapping[str, object] | None = None, dev: bool = False
) -> Context:
    """
    读取宿主 JSON/TOML 配置及 capabilities，创建应用资源和权限快照。

    JSON 优先于 Tauri.toml；合并平台文件后应用调用方覆盖。目录资源相对宿主根目录。
    dev=True 显式选择 devUrl；默认使用 frontendDist，HTTP(S) 来源也可显式配置。
    宿主能力完整替换示例权限，未授权外部页面不能调用 IPC；CSP/隔离尚未实现。

    :param resource_path: 含 tauri.conf.json 或 Tauri.toml 的宿主根目录
    :param tauri_config: 递归合并到文件配置的覆盖字段
    :param dev: 是否显式使用开发服务器，不启动或管理服务器进程
    :return: 运行配置与启动时的资源快照
    :raises BindingError: 无效配置、不支持的配置或资源读取失败
    """
    prepared = _prepare_context(resource_path.resolve(), tauri_config, dev)
    return _native.context_factory(
        prepared.asset_root,
        json.dumps(prepared.config, allow_nan=False),
        capabilities_json=json.dumps(prepared.capabilities, allow_nan=False),
        host_capabilities=prepared.host_capabilities,
        icon=prepared.icon,
    )
