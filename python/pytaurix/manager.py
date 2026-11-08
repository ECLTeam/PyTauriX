# ============================================================
# PyTauriX
# 文件作用：提供共享状态、窗口查询与事件的静态入口。
# 公开接口：Manager、Emitter、Listener。
# ============================================================
from __future__ import annotations

import json
from collections.abc import Callable
from typing import TypeAlias, TypeVar, cast

from pydantic import BaseModel

from .application import App
from .errors import BindingError
from .event_target import EventTargetType
from .events import Event
from .ffi import AppHandle, WebviewWindow
from .ffi import Emitter as FfiEmitter
from .ipc import JsonValue
from .path import PathResolver

ManagerType: TypeAlias = App | AppHandle | WebviewWindow
StateType = TypeVar("StateType")


def _handle(manager: ManagerType) -> AppHandle:
    if isinstance(manager, App):
        return manager.handle()
    if isinstance(manager, WebviewWindow):
        return manager.app_handle()
    return manager


def _payload_json(payload: BaseModel | JsonValue) -> str:
    return payload.model_dump_json() if isinstance(payload, BaseModel) else json.dumps(payload, allow_nan=False)


def _event_manager(manager: ManagerType) -> AppHandle | WebviewWindow:
    return manager.handle() if isinstance(manager, App) else manager


class Manager:
    """
    通过应用或窗口句柄查询窗口，并按具体 Python 类型管理共享状态。
    """

    @staticmethod
    def webview_windows(manager: ManagerType) -> dict[str, WebviewWindow]:
        """
        返回应用中现存 WebView 窗口映射，已销毁窗口不再列出。

        :param manager: 应用、应用句柄或窗口
        :return: 按标签索引的窗口句柄快照
        :raises BindingError: 应用已关闭
        """
        return _handle(manager).webview_windows()

    @staticmethod
    def path(manager: ManagerType) -> PathResolver:
        """
        返回绑定到该应用句柄的路径解析器。

        解析器只读取应用身份，不创建目录；应用退出后调用明确报错。

        :param manager: 应用、应用句柄或窗口
        :return: 路径解析器
        """
        return PathResolver(_handle(manager))

    @staticmethod
    def get_webview_window(manager: ManagerType, label: str) -> WebviewWindow | None:
        """
        查询指定标签的 WebView 窗口，配置窗口在 Ready 后可用。

        :param manager: 应用、应用句柄或窗口
        :param label: 窗口标签
        :return: 存在的窗口或 None
        """
        return _handle(manager).get_webview_window(label)

    @staticmethod
    def manage(manager: ManagerType, value: object) -> bool:
        """
        注册共享对象，相同具体类型重复注册返回 False 并保留原对象。

        :param manager: 应用、应用句柄或窗口
        :param value: 共享对象，内部并发访问由调用方同步
        :return: 是否首次注册
        :raises BindingError: 应用已关闭
        """
        return _handle(manager).manage(value)

    @staticmethod
    def try_state(manager: ManagerType, state_type: type[StateType]) -> StateType | None:
        """
        取得指定类型的原始共享对象，不进行继承匹配或复制。

        :param manager: 应用、应用句柄或窗口
        :param state_type: 具体 Python 类型
        :return: 原始对象，未注册返回 None
        """
        return cast(StateType | None, _handle(manager).try_state(state_type))

    @staticmethod
    def state(manager: ManagerType, state_type: type[StateType]) -> StateType:
        """
        取得必须存在的共享对象。

        :param manager: 应用、应用句柄或窗口
        :param state_type: 具体 Python 类型
        :return: 原始对象
        :raises BindingError: 状态未注册或应用已关闭
        """
        state = Manager.try_state(manager, state_type)
        if state is None:
            raise BindingError("state_missing: Managed state is not registered")
        return state


class Emitter:
    """
    将模型或 JSON 值序列化为 Tauri 事件。
    """

    @staticmethod
    def emit(manager: ManagerType, event: str, payload: BaseModel | JsonValue, /) -> None:
        """
        向应用的原生监听器和前端发送事件。

        :param manager: 应用、应用句柄或窗口
        :param event: 事件名
        :param payload: 模型或 JSON 值
        :raises BindingError: 名称非法、应用关闭或发送失败
        """
        FfiEmitter.emit_str(manager, event, _payload_json(payload))

    @staticmethod
    def emit_to(
        manager: ManagerType, target: EventTargetType | str, event: str, payload: BaseModel | JsonValue, /
    ) -> None:
        """
        按明确类型或字符串标签发送事件，保留上游六种目标的路由语义。

        :param manager: 应用、应用句柄或窗口
        :param target: 事件目标；字符串等价于 AnyLabel
        :param event: 事件名
        :param payload: 模型或 JSON 值
        :raises BindingError: 名称非法、应用关闭或发送失败
        """
        FfiEmitter.emit_str_to(manager, target, event, _payload_json(payload))


class Listener:
    """
    按应用或窗口作用域管理原生监听器，回调异常有序退出并归还 Python。
    """

    @staticmethod
    def listen(manager: ManagerType, event: str, handler: Callable[[Event], object], /) -> int:
        """
        注册同步监听器，回调可在发出事件的线程执行，需要自行同步共享对象。

        :param manager: 应用或应用句柄采用应用作用域，窗口采用该窗口作用域
        :param event: 事件名
        :param handler: 接收 Event 的同步函数
        :return: 用于 unlisten 的监听编号
        :raises BindingError: 无效名称、回调或已关闭应用
        """
        return _event_manager(manager).listen(event, handler)

    @staticmethod
    def once(manager: ManagerType, event: str, handler: Callable[[Event], object], /) -> int:
        """
        注册所属应用或窗口只调用一次的同步监听器，调用前取走回调。

        :param manager: 应用、应用句柄或窗口
        :param event: 事件名
        :param handler: 接收 Event 的同步函数
        :return: 监听编号
        """
        return _event_manager(manager).listen(event, handler, once=True)

    @staticmethod
    def unlisten(manager: ManagerType, id: int, /) -> None:
        """
        注销监听编号，重复注销是无副作用的操作；应用退出时清理剩余监听器。

        :param manager: 应用、应用句柄或窗口
        :param id: 监听编号
        :raises BindingError: 应用或窗口已关闭，或编号仍由其他窗口代次拥有
        """
        _event_manager(manager).unlisten(id)

    @staticmethod
    def listen_any(manager: ManagerType, event: str, handler: Callable[[Event], object], /) -> int:
        """
        监听任意目标，回调仍由提交的应用或具体窗口代次拥有。

        :param manager: 应用、应用句柄或窗口；窗口销毁清理其监听
        :param event: 合法事件名称
        :param handler: 同步事件回调，不能返回 awaitable
        :return: 注销编号
        :raises BindingError: 无效参数或资源已关闭
        """
        return _event_manager(manager).listen(event, handler, any_target=True)

    @staticmethod
    def once_any(manager: ManagerType, event: str, handler: Callable[[Event], object], /) -> int:
        """
        监听任意目标一次，执行前注销并释放登记中的回调。

        :param manager: 监听所有者，窗口代次在销毁后失效
        :param event: 合法事件名称
        :param handler: 同步回调
        :return: 注销编号，重复注销无副作用
        :raises BindingError: 参数无效或所有者已关闭
        """
        return _event_manager(manager).listen(event, handler, once=True, any_target=True)
