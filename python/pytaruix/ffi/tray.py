# PytaruiX
# 文件作用：桌面托盘公开契约、不可变原生事件和可显式关闭的资源。
# 公开接口：TrayIcon、TrayIconBuilder、托盘事件与鼠标枚举。
from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Self, TypeAlias
from uuid import uuid4

from .. import _native
from ..dpi import LogicalPosition, LogicalSize, PhysicalPosition, PhysicalPositionF64, Rect
from ..manager import ManagerType, _handle
from .image import Image
from .menu import Menu, MenuEvent, Submenu, _bool, _text

TrayIconId: TypeAlias = str


class MouseButton(Enum):
    """
    保存原生鼠标按钮名称，不依赖平台枚举整数。

    枚举或事件值不拥有 GUI 资源，可跨线程读取；平台条件参见类型说明。
    """

    Left = "Left"
    Right = "Right"
    Middle = "Middle"


class MouseButtonState(Enum):
    """
    保存原生按钮状态，Up 表示释放，Down 表示按下。

    枚举或事件值不拥有 GUI 资源，可跨线程读取；平台条件参见类型说明。
    """

    Up = "Up"
    Down = "Down"


class TrayIconEvent:
    """
    提供可模式匹配的不可变托盘鼠标事件；Linux 上游不派发。

    枚举或事件值不拥有 GUI 资源，可跨线程读取；平台条件参见类型说明。
    """

    @dataclass(frozen=True, slots=True)
    class Click:
        """
        保存单击的标识、浮点物理位置、矩形、按钮和按下/释放状态。

        枚举或事件值不拥有 GUI 资源，可跨线程读取；平台条件参见类型说明。
        """

        id: TrayIconId
        position: PhysicalPositionF64
        rect: Rect
        button: MouseButton
        button_state: MouseButtonState

    @dataclass(frozen=True, slots=True)
    class DoubleClick:
        """
        保存双击快照；仅 Windows 上游派发。

        枚举或事件值不拥有 GUI 资源，可跨线程读取；平台条件参见类型说明。
        """

        id: TrayIconId
        position: PhysicalPositionF64
        rect: Rect
        button: MouseButton

    @dataclass(frozen=True, slots=True)
    class Enter:
        """
        保存鼠标进入图标区域的快照。

        枚举或事件值不拥有 GUI 资源，可跨线程读取；平台条件参见类型说明。
        """

        id: TrayIconId
        position: PhysicalPositionF64
        rect: Rect

    @dataclass(frozen=True, slots=True)
    class Move:
        """
        保存鼠标在图标区域移动的快照。

        枚举或事件值不拥有 GUI 资源，可跨线程读取；平台条件参见类型说明。
        """

        id: TrayIconId
        position: PhysicalPositionF64
        rect: Rect

    @dataclass(frozen=True, slots=True)
    class Leave:
        """
        保存鼠标离开图标区域的快照。

        枚举或事件值不拥有 GUI 资源，可跨线程读取；平台条件参见类型说明。
        """

        id: TrayIconId
        position: PhysicalPositionF64
        rect: Rect


TrayIconEventType: TypeAlias = (
    TrayIconEvent.Click | TrayIconEvent.DoubleClick | TrayIconEvent.Enter | TrayIconEvent.Move | TrayIconEvent.Leave
)
TrayHandler: TypeAlias = Callable[["TrayIcon", TrayIconEventType], None]
MenuHandler: TypeAlias = Callable[[_native.AppHandle, MenuEvent], None]


def _rect(value: dict[str, Any]) -> Rect:
    position = value["position"]
    size = value["size"]
    if "Physical" in position:
        point = position["Physical"]
        pos = PhysicalPosition(point["x"], point["y"])
    else:
        point = position["Logical"]
        pos = LogicalPosition(point["x"], point["y"])
    if "Physical" in size:
        dimensions = size["Physical"]
        # 构造器拒绝零尺寸，原生快照需要保留其合法零值。
        native_size = _native.physical_size_payload(dimensions["width"], dimensions["height"])
    else:
        dimensions = size["Logical"]
        native_size = LogicalSize(dimensions["width"], dimensions["height"])
    return Rect(pos, native_size)


def _event(payload: str) -> TrayIconEventType:
    value = json.loads(payload)
    kind = value["type"]
    position = PhysicalPositionF64(value["position"]["x"], value["position"]["y"])
    rect = _rect(value["rect"])
    if kind == "Click":
        return TrayIconEvent.Click(
            value["id"], position, rect, MouseButton(value["button"]), MouseButtonState(value["buttonState"])
        )
    if kind == "DoubleClick":
        return TrayIconEvent.DoubleClick(value["id"], position, rect, MouseButton(value["button"]))
    variants = {"Enter": TrayIconEvent.Enter, "Move": TrayIconEvent.Move, "Leave": TrayIconEvent.Leave}
    return variants[kind](value["id"], position, rect)


def _handler(handler: Callable[..., object]) -> None:
    if not callable(handler) or inspect.iscoroutinefunction(handler) or inspect.iscoroutinefunction(handler.__call__):
        raise _native.BindingError("invalid_callback: Expected a synchronous callable")


def _adapt_global(
    handler: Callable[[_native.AppHandle, TrayIconEventType], None],
) -> Callable[[_native.AppHandle, str], None]:
    _handler(handler)

    def receive(handle: _native.AppHandle, payload: str) -> None:
        return handler(handle, _event(payload))

    return receive


def _menu(menu: Menu | Submenu | None) -> _native.MenuResource | None:
    if menu is not None and not isinstance(menu, (Menu, Submenu)):
        raise TypeError("Expected Menu, Submenu or None")
    return None if menu is None else menu._native_menu


def _adapt_tray(handler: TrayHandler) -> Callable[[_native.TrayResource, str], None]:
    _handler(handler)

    def receive(resource: _native.TrayResource, payload: str) -> None:
        return handler(_from_native(resource), _event(payload))

    return receive


def _image(icon: Image | None) -> Image | None:
    if icon is not None and not isinstance(icon, Image):
        raise TypeError("Expected Image or None")
    return icon


class TrayIcon:
    """
    创建应用拥有的托盘；共享句柄通过 close 一起失效。

    :param manager: 应用、应用句柄或存活窗口
    :raises BindingError: feature 未启用、应用未运行、错误线程或 GUI 同步回调重入
    需显式 tray-icon feature。窗口关闭不销毁托盘，释放 Python 句柄不移除应用引用。
    """

    __slots__ = ("__weakref__", "_native_tray")
    _native_tray: _native.TrayResource

    def __init__(self, manager: ManagerType, /) -> None:
        self._native_tray = TrayIconBuilder().build(manager)._native_tray

    @classmethod
    def with_id(cls, manager: ManagerType, id: TrayIconId, /) -> TrayIcon:
        """
        按显式 ID 创建；活跃或已移除但仍存活的同 ID 托盘拒绝重复创建。

        :param manager: 应用、应用句柄或存活窗口，资源归属应用
        :param id: 字符串托盘标识，不允许 NUL 或与存活托盘重复
        :return: TrayIcon
        """
        return _from_native(TrayIconBuilder.with_id(id).build(manager)._native_tray)

    def id(self, /) -> TrayIconId:
        """
        返回稳定标识；关闭后仍可读取，不访问原生 GUI。

        :return: TrayIconId
        """
        return self._native_tray.id()

    def app_handle(self, /) -> _native.AppHandle:
        """
        返回所属应用；应用退出后抛出 BindingError。

        :return: _native.AppHandle
        应用退出后抛出 BindingError；不创建新 GUI 资源。
        """
        return self._native_tray.app_handle()

    @property
    def closed(self) -> bool:
        """
        返回共享资源是否已关闭；不创建 GUI 或等待主线程。

        :return: bool
        """
        return self._native_tray.closed

    def close(self, /) -> None:
        """
        显式移除图标、清空回调并使所有别名失效；幂等，禁止同步 GUI 回调内调用。

        :return: None
        原生操作在 setup 或运行期间等待 GUI 并释放 GIL；失效或禁止的回调重入抛出 BindingError。
        """
        self._native_tray.close()

    def set_icon(self, icon: Image | None, /) -> None:
        """
        设置或移除图像；复制原生 RGBA，释放 GIL，关闭后拒绝。

        :param icon: 自有 RGBA Image，允空的接口以 None 移除图像
        :return: None
        原生操作在 setup 或运行期间等待 GUI 并释放 GIL；失效或禁止的回调重入抛出 BindingError。
        """
        self._native_tray.set_icon(_image(icon))

    def set_icon_with_as_template(self, icon: Image | None, is_template: bool, /) -> None:
        """
        原子设置图像与 macOS 模板状态；其他桌面平台仅更新图像。

        :param icon: 自有 RGBA Image，允空的接口以 None 移除图像
        :param is_template: 严格 bool，模板状态仅 macOS 有效
        :return: None
        原生操作在 setup 或运行期间等待 GUI 并释放 GIL；失效或禁止的回调重入抛出 BindingError。
        """
        self._native_tray.set_icon_with_as_template(_image(icon), _bool(is_template))

    def set_menu(self, menu: Menu | Submenu | None, /) -> None:
        """
        设置上下文菜单；验证所属应用，Linux 移除/替换限制遵循上游。

        :param menu: 同应用的 Menu/Submenu，允空的接口以 None 请求移除
        :return: None
        原生操作在 setup 或运行期间等待 GUI 并释放 GIL；失效或禁止的回调重入抛出 BindingError。
        """
        self._native_tray.set_menu(_menu(menu))

    def set_tooltip(self, tooltip: str | None, /) -> None:
        """
        更新或清除提示；Linux 无原生效果，字符串不得含 NUL。

        :param tooltip: 提示字符串；允空的接口以 None 清除，Linux 无效果
        :return: None
        原生操作在 setup 或运行期间等待 GUI 并释放 GIL；失效或禁止的回调重入抛出 BindingError。
        """
        self._native_tray.set_tooltip(None if tooltip is None else _text(tooltip))

    def set_title(self, title: str | None, /) -> None:
        """
        更新标题；Windows 上游无效果，字符串不得含 NUL。

        :param title: 标题字符串；允空的接口以 None 清除，Windows 无效果
        :return: None
        原生操作在 setup 或运行期间等待 GUI 并释放 GIL；失效或禁止的回调重入抛出 BindingError。
        """
        self._native_tray.set_title(None if title is None else _text(title))

    def set_visible(self, visible: bool, /) -> None:
        """
        显示或隐藏系统图标；释放 GIL并等待 GUI，关闭后拒绝。

        :param visible: 严格 bool，控制系统图标显示状态
        :return: None
        原生操作在 setup 或运行期间等待 GUI 并释放 GIL；失效或禁止的回调重入抛出 BindingError。
        """
        self._native_tray.set_visible(_bool(visible))

    def set_temp_dir_path(self, path: Path | None, /) -> None:
        """
        设置 Linux 图像临时目录；其他桌面平台无效果，不访问导入期 GUI。

        :param path: pathlib.Path，临时图像目录仅 Linux 有效果
        :return: None
        原生操作在 setup 或运行期间等待 GUI 并释放 GIL；失效或禁止的回调重入抛出 BindingError。
        """
        if path is not None and not isinstance(path, Path):
            raise TypeError("Expected Path or None")
        self._native_tray.set_temp_dir_path(path)

    def set_icon_as_template(self, is_template: bool, /) -> None:
        """
        设置 macOS 模板状态；其他桌面平台无效果。

        :param is_template: 严格 bool，模板状态仅 macOS 有效
        :return: None
        原生操作在 setup 或运行期间等待 GUI 并释放 GIL；失效或禁止的回调重入抛出 BindingError。
        """
        self._native_tray.set_icon_as_template(_bool(is_template))

    def set_show_menu_on_left_click(self, enable: bool, /) -> None:
        """
        设置左击菜单开关；默认开启，Linux 上游不支持。

        :param enable: 严格 bool，控制左击菜单；Linux 无效果
        :return: None
        原生操作在 setup 或运行期间等待 GUI 并释放 GIL；失效或禁止的回调重入抛出 BindingError。
        """
        self._native_tray.set_show_menu_on_left_click(_bool(enable))

    def rect(self, /) -> Rect | None:
        """
        读取带显式单位的原生矩形快照；释放 GIL，Linux 返回 None。

        :return: Rect | None
        原生操作在 setup 或运行期间等待 GUI 并释放 GIL；失效或禁止的回调重入抛出 BindingError。
        """
        value = self._native_tray.rect_json()
        return None if value is None else _rect(json.loads(value))

    def on_tray_icon_event(self, handler: TrayHandler, /) -> None:
        """
        替换托盘鼠标回调；同步主线程派发，异常由 run_return 重抛。

        :param handler: 同步 callable，异步回调拒绝；异常由 run_return 重抛
        :return: None
        原生操作在 setup 或运行期间等待 GUI 并释放 GIL；失效或禁止的回调重入抛出 BindingError。
        """
        self._native_tray.on_tray_icon_event(_adapt_tray(handler))

    def on_menu_event(self, handler: MenuHandler, /) -> None:
        """
        累加全应用菜单广播回调，参数为应用与菜单 ID；关闭本托盘时释放。

        :param handler: 同步 callable，异步回调拒绝；异常由 run_return 重抛
        :return: None
        原生操作在 setup 或运行期间等待 GUI 并释放 GIL；失效或禁止的回调重入抛出 BindingError。
        """
        _handler(handler)
        self._native_tray.on_menu_event(handler)

    def clear_event_handlers(self, /) -> None:
        """
        清空本托盘鼠标与菜单回调；允许同步回调内调用，释放 Python 引用。

        :return: None
        原生操作在 setup 或运行期间等待 GUI 并释放 GIL；失效或禁止的回调重入抛出 BindingError。
        """
        self._native_tray.clear_event_handlers()


def _from_native(resource: _native.TrayResource) -> TrayIcon:
    instance = TrayIcon.__new__(TrayIcon)
    instance._native_tray = resource
    return instance


class TrayIconBuilder:
    """
    保存托盘构建选项；build 前不初始化 GUI，链式方法返回当前构建器。

    重复存活 ID 拒绝构建；回调与资源在同一 GUI 事务内注册，避免丢失创建后的早期事件。
    """

    def __init__(self) -> None:
        self._options: dict[str, str | bool | None] = {"id": str(uuid4())}
        self._menu: Menu | Submenu | None = None
        self._icon: Image | None = None
        self._mouse_handler: TrayHandler | None = None
        self._menu_handler: MenuHandler | None = None

    @classmethod
    def new(cls) -> Self:
        """
        创建不初始化 GUI 的构建器，预生成稳定 ID。

        :return: 当前构建器或新建构建器
        """
        return cls()

    @classmethod
    def with_id(cls, id: TrayIconId, /) -> Self:
        """
        创建使用指定字符串 ID 的构建器；不查询运行态。

        :param id: 字符串托盘标识，不允许 NUL 或与存活托盘重复
        :return: 当前构建器或新建构建器
        """
        instance = cls()
        instance._options["id"] = _text(id)
        return instance

    def id(self, /) -> TrayIconId:
        """
        返回 build 将使用的标识，不创建原生资源。

        :return: TrayIconId
        """
        value = self._options["id"]
        assert isinstance(value, str)
        return value

    def menu(self, menu: Menu | Submenu, /) -> Self:
        """
        设置菜单引用；build 时验证应用所有权。

        :param menu: 同应用的 Menu/Submenu，允空的接口以 None 请求移除
        :return: 当前构建器或新建构建器
        仅保存构建选项，不初始化 GUI；参数类型错误抛出 TypeError，异步回调抛出 BindingError。
        """
        if not isinstance(menu, (Menu, Submenu)):
            raise TypeError("Expected Menu or Submenu")
        self._menu = menu
        return self

    def icon(self, icon: Image, /) -> Self:
        """
        设置图像；build 时复制原生数据。

        :param icon: 自有 RGBA Image，允空的接口以 None 移除图像
        :return: 当前构建器或新建构建器
        仅保存构建选项，不初始化 GUI；参数类型错误抛出 TypeError，异步回调抛出 BindingError。
        """
        if not isinstance(icon, Image):
            raise TypeError("Expected Image")
        self._icon = icon
        return self

    def tooltip(self, tooltip: str, /) -> Self:
        """
        设置提示文本；Linux 无效果。

        :param tooltip: 提示字符串；允空的接口以 None 清除，Linux 无效果
        :return: 当前构建器或新建构建器
        仅保存构建选项，不初始化 GUI；参数类型错误抛出 TypeError，异步回调抛出 BindingError。
        """
        self._options["tooltip"] = _text(tooltip)
        return self

    def title(self, title: str, /) -> Self:
        """
        设置托盘标题；Windows 无效果。

        :param title: 标题字符串；允空的接口以 None 清除，Windows 无效果
        :return: 当前构建器或新建构建器
        仅保存构建选项，不初始化 GUI；参数类型错误抛出 TypeError，异步回调抛出 BindingError。
        """
        self._options["title"] = _text(title)
        return self

    def temp_dir_path(self, path: Path, /) -> Self:
        """
        设置 Linux 图像临时目录，要求 pathlib.Path。

        :param path: pathlib.Path，临时图像目录仅 Linux 有效果
        :return: 当前构建器或新建构建器
        仅保存构建选项，不初始化 GUI；参数类型错误抛出 TypeError，异步回调抛出 BindingError。
        """
        if not isinstance(path, Path):
            raise TypeError("Expected Path")
        self._options["temp_dir_path"] = str(path)
        return self

    def icon_as_template(self, is_template: bool, /) -> Self:
        """
        设置 macOS 模板状态；其他桌面平台无效果。

        :param is_template: 严格 bool，模板状态仅 macOS 有效
        :return: 当前构建器或新建构建器
        仅保存构建选项，不初始化 GUI；参数类型错误抛出 TypeError，异步回调抛出 BindingError。
        """
        self._options["icon_as_template"] = _bool(is_template)
        return self

    def show_menu_on_left_click(self, enable: bool, /) -> Self:
        """
        设置左击菜单开关；默认开启，Linux 无效果。

        :param enable: 严格 bool，控制左击菜单；Linux 无效果
        :return: 当前构建器或新建构建器
        仅保存构建选项，不初始化 GUI；参数类型错误抛出 TypeError，异步回调抛出 BindingError。
        """
        self._options["show_menu_on_left_click"] = _bool(enable)
        return self

    def on_menu_event(self, handler: MenuHandler, /) -> Self:
        """
        保存全应用菜单回调；要求同步 callable，build 后注册。

        :param handler: 同步 callable，异步回调拒绝；异常由 run_return 重抛
        :return: 当前构建器或新建构建器
        仅保存构建选项，不初始化 GUI；参数类型错误抛出 TypeError，异步回调抛出 BindingError。
        """
        _handler(handler)
        self._menu_handler = handler
        return self

    def on_tray_icon_event(self, handler: TrayHandler, /) -> Self:
        """
        保存该托盘鼠标回调；要求同步 callable，build 后注册。

        :param handler: 同步 callable，异步回调拒绝；异常由 run_return 重抛
        :return: 当前构建器或新建构建器
        仅保存构建选项，不初始化 GUI；参数类型错误抛出 TypeError，异步回调抛出 BindingError。
        """
        _handler(handler)
        self._mouse_handler = handler
        return self

    def build(self, manager: ManagerType, /) -> TrayIcon:
        """
        在应用 setup 或运行期创建托盘，后台线程释放 GIL等待 GUI。

        :param manager: 应用、应用句柄或存活窗口
        :return: 应用持有引用的托盘
        :raises BindingError: feature 未启用、重复 ID、资源失效或同步 GUI 回调重入
        """
        if not _native.tray_available:
            raise _native.BindingError("unsupported_capability: Build with the desktop tray-icon feature")
        return _from_native(
            _native.TrayResource.create(
                _handle(manager),
                json.dumps(self._options),
                _menu(self._menu),
                self._icon,
                self._menu_handler,
                None if self._mouse_handler is None else _adapt_tray(self._mouse_handler),
            )
        )


__all__ = [
    "MouseButton",
    "MouseButtonState",
    "TrayIcon",
    "TrayIconBuilder",
    "TrayIconEvent",
    "TrayIconEventType",
    "TrayIconId",
]
