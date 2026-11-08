# PytaruiX
# 文件作用：菜单公开契约、种类边界及 PyTauri 兼容构造。
# 公开接口：Menu、Submenu、MenuItem、CheckMenuItem、IconMenuItem、PredefinedMenuItem、ContextMenu。
from __future__ import annotations

from collections.abc import Sequence
from typing import TypeAlias, TypeVar

from .. import _native
from ..dpi import PositionType
from ..manager import ManagerType, _handle
from ..webview import WebviewWindow
from .image import Image

MenuID: TypeAlias = str
MenuEvent: TypeAlias = MenuID
_T = TypeVar("_T", bound="_MenuObject")


def _bool(value: bool) -> bool:
    if type(value) is not bool:
        raise TypeError("Expected bool")
    return value


def _text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("Expected str")
    return value


def _index(value: int) -> int:
    if type(value) is not int or value < 0:
        raise _native.BindingError("invalid_index: Expected a non-negative integer")
    return value


def _create(
    kind: str,
    manager: ManagerType,
    id: MenuID | None = None,
    text: str = "",
    enabled: bool = True,
    checked: bool = False,
    accelerator: str | None = None,
    icon: Image | None = None,
) -> _native.MenuResource:
    if not _native.menu_available:
        raise _native.BindingError("platform_unavailable: Native menus require a desktop platform")
    if accelerator is not None:
        _text(accelerator)
    if icon is not None and not isinstance(icon, Image):
        raise TypeError("Expected Image or None")
    return _native.MenuResource.create(
        _handle(manager),
        kind,
        None if id is None else _text(id),
        _text(text),
        _bool(enabled),
        _bool(checked),
        accelerator,
        icon,
    )


class _MenuObject:
    __slots__ = ("_native_menu",)
    _native_menu: _native.MenuResource

    @classmethod
    def _from_resource(cls: type[_T], resource: _native.MenuResource) -> _T:
        instance = cls.__new__(cls)
        instance._native_menu = resource
        return instance

    def app_handle(self) -> _native.AppHandle:
        """
        返回菜单资源所属应用，不延长构造时窗口寿命。

        可跨线程和回调读取；应用退出后抛出 app_closed。
        """
        return self._native_menu.app_handle()

    def id(self) -> MenuID:
        """
        返回原生字符串 ID，允许与其他项目使用相同 ID。

        可跨线程和回调读取；退出后报错，不自动保证 ID 唯一。
        """
        return self._native_menu.id()


class _TextItem(_MenuObject):
    __slots__ = ()

    def text(self) -> str:
        """
        返回原生项目文字，助记符沿用平台规则。

        桌面运行期间释放 GIL；同步 GUI 回调内抛出 blocking_callback。
        """
        return self._native_menu.text()

    def set_text(self, text: str, /) -> None:
        """
        设置文字并更新所有共享父菜单；拒绝包含 NUL 的字符串。

        工作线程释放 GIL，退出或同步 GUI 回调内报错。
        """
        self._native_menu.set_text(_text(text))


class _Enabled(_TextItem):
    __slots__ = ()

    def is_enabled(self) -> bool:
        """
        查询项目原生启用状态。

        桌面运行期间释放 GIL，退出或同步 GUI 回调内报错。
        """
        return self._native_menu.flag(False)

    def set_enabled(self, enabled: bool, /) -> None:
        """
        设置项目启用状态，参数必须为 bool。

        更新共享项目；工作线程释放 GIL，禁止同步 GUI 回调重入。
        """
        self._native_menu.set_flag(False, _bool(enabled))


class _Accelerated(_Enabled):
    __slots__ = ()

    def set_accelerator(self, accelerator: str | None, /) -> None:
        """
        设置原生快捷键，None 清除；沿用 muda 的快捷键语法。

        无效字符串抛出 invalid_accelerator 且不修改；释放 GIL，禁止回调重入。
        """
        if accelerator is not None:
            _text(accelerator)
        self._native_menu.set_accelerator(accelerator)


class _Container(_MenuObject):
    __slots__ = ()

    def append(self, item: MenuItemKind, /) -> None:
        """
        追加同应用项目，允许原生共享与重复插入。

        子菜单循环由原生拒绝，macOS 顶层限制沿用上游；释放 GIL，禁止回调重入。
        """
        self._native_menu.insert(_item(item)._native_menu)

    def append_items(self, items: Sequence[MenuItemKind], /) -> None:
        """
        按顺序追加项目序列，与上游一样逐项执行。

        参数预先校验种类；原生中途失败可保留之前的修改，释放 GIL，禁止回调重入。
        """
        checked = [_item(item) for item in items]
        for item in checked:
            self.append(item)

    def prepend(self, item: MenuItemKind, /) -> None:
        """
        将同应用项目插入首位。

        沿用原生共享规则；释放 GIL，退出或同步 GUI 回调内报错。
        """
        self.insert(item, 0)

    def prepend_items(self, items: Sequence[MenuItemKind], /) -> None:
        """
        保持序列顺序，将项目插入菜单起始位置。

        与上游一样逐项修改；释放 GIL，禁止同步 GUI 回调重入。
        """
        self.insert_items(items, 0)

    def insert(self, item: MenuItemKind, position: int, /) -> None:
        """
        在非负位置插入项目，位置不能超过当前项目数。

        越界抛出 invalid_index，校验与修改在同一 GUI 任务内；释放 GIL。
        """
        self._native_menu.insert(_item(item)._native_menu, _index(position))

    def insert_items(self, items: Sequence[MenuItemKind], position: int, /) -> None:
        """
        在位置依序插入项目，与上游一样逐项修改。

        种类和非负索引预先校验，失败可保留之前修改；释放 GIL，禁止回调重入。
        """
        position = _index(position)
        checked = [_item(item) for item in items]
        for offset, item in enumerate(checked):
            self.insert(item, position + offset)

    def remove(self, item: MenuItemKind, /) -> None:
        """
        移除全部原生 ID 匹配项；已有项目句柄仍可独立使用。

        无匹配项抛出 menu_failed；释放 GIL，退出或同步 GUI 回调内报错。
        """
        self._native_menu.remove(_item(item)._native_menu)

    def remove_at(self, position: int, /) -> MenuItemKind | None:
        """
        移除非负位置项目并返回句柄，超出项目数返回 None。

        负数或 bool 抛出 invalid_index；释放 GIL，禁止同步 GUI 回调重入。
        """
        result = self._native_menu.remove_at(_index(position))
        return None if result is None else _from_item(result)

    def get(self, id: MenuID, /) -> MenuItemKind | None:
        """
        查找直接子项中首个匹配 ID，不递归查找嵌套菜单。

        无匹配项返回 None，原生读取失败保留异常；释放 GIL，禁止回调重入。
        """
        id = _text(id)
        return next((item for item in self.items() if item.id() == id), None)

    def items(self) -> list[MenuItemKind]:
        """
        返回有序直接子项句柄，保持原生共享身份。

        桌面运行期间释放 GIL；退出或同步 GUI 回调内报错。
        """
        return [_from_item(item) for item in self._native_menu.items()]


class Menu(_Container):
    """
    可挂载到应用或窗口、也可弹出的桌面根菜单。

    macOS 顶层只接受 Submenu；资源属于应用，构造在 setup 或运行期间进行。
    """

    __slots__ = ()

    def __init__(self, manager: ManagerType, /) -> None:
        """
        创建自动 ID 的空菜单；manager 接受 App、AppHandle 或 WebviewWindow。

        桌面 setup 或运行期间释放 GIL，禁止同步 GUI 回调重入。
        """
        self._native_menu = _create("menu", manager)

    @classmethod
    def with_id(cls, manager: ManagerType, id: MenuID, /) -> Menu:
        """
        创建显式字符串 ID 的空菜单。

        桌面 setup 或运行期间释放 GIL，退出或同步 GUI 回调内报错。
        """
        return cls._from_resource(_create("menu", manager, _text(id)))

    @classmethod
    def with_items(cls, manager: ManagerType, items: Sequence[MenuItemKind], /) -> Menu:
        """
        创建自动 ID 菜单并逐项追加初始项目。

        沿用原生共享与平台限制；释放 GIL，禁止同步 GUI 回调重入。
        """
        menu = cls(manager)
        menu.append_items(items)
        return menu

    @classmethod
    def with_id_and_items(cls, manager: ManagerType, id: MenuID, items: Sequence[MenuItemKind], /) -> Menu:
        """
        创建显式 ID 菜单并依序追加项目。

        桌面 setup 或运行期间执行，失败保留原生异常；释放 GIL。
        """
        menu = cls.with_id(manager, id)
        menu.append_items(items)
        return menu

    def set_as_app_menu(self) -> None:
        """
        将菜单挂载到所属应用，保持 PyTauri 的 None 返回契约。

        需要旧菜单时使用 AppHandle.set_menu；释放 GIL，禁止回调重入。
        """
        self.app_handle().set_menu(self)

    def set_as_window_menu(self, window: WebviewWindow, /) -> None:
        """
        挂载到同应用 WebviewWindow，保持 PyTauri 的 None 返回契约。

        接受 WebviewWindow 是本项目扩展；原窗口关闭后报错，释放 GIL。
        """
        if not isinstance(window, WebviewWindow):
            raise TypeError("Expected WebviewWindow")
        window.set_menu(self)


class Submenu(_Container, _Enabled):
    """
    带文字与启用状态的嵌套菜单，也支持上下文弹出。

    可共享到多个父菜单；循环依赖由原生拒绝，资源属于应用。
    """

    __slots__ = ()

    def __init__(self, manager: ManagerType, text: str, enabled: bool, /) -> None:
        """
        创建自动 ID 子菜单，enabled 必须为 bool。

        桌面 setup 或运行期间释放 GIL，禁止同步 GUI 回调重入。
        """
        self._native_menu = _create("submenu", manager, text=text, enabled=enabled)

    @classmethod
    def with_id(cls, manager: ManagerType, id: MenuID, text: str, enabled: bool, /) -> Submenu:
        """
        创建指定 ID、文字和启用状态的子菜单。

        桌面 setup 或运行期间释放 GIL，退出或同步回调内报错。
        """
        return cls._from_resource(_create("submenu", manager, _text(id), text, enabled))

    @classmethod
    def with_items(
        cls,
        manager: ManagerType,
        text: str,
        enabled: bool,
        items: Sequence[MenuItemKind],
        /,
    ) -> Submenu:
        """
        创建自动 ID 子菜单并按顺序追加项目。

        原生共享与循环限制适用；释放 GIL，禁止同步回调重入。
        """
        menu = cls(manager, text, enabled)
        menu.append_items(items)
        return menu

    @classmethod
    def with_id_and_items(
        cls,
        manager: ManagerType,
        id: MenuID,
        text: str,
        enabled: bool,
        items: Sequence[MenuItemKind],
        /,
    ) -> Submenu:
        """
        创建显式 ID 子菜单并按顺序追加初始项目。

        桌面 setup 或运行期间执行，原生失败保留异常；释放 GIL。
        """
        menu = cls.with_id(manager, id, text, enabled)
        menu.append_items(items)
        return menu


class MenuItem(_Accelerated):
    """
    普通原生菜单项，支持文字、启用状态和可选快捷键。

    项目共享时修改作用于所有父菜单；移除后句柄仍可使用。
    """

    __slots__ = ()

    def __init__(self, manager: ManagerType, text: str, enabled: bool, accelerator: str | None = None, /) -> None:
        """
        创建自动 ID 普通项，省略快捷键时为 None。

        无效快捷键抛出 invalid_accelerator；桌面 setup 或运行期间释放 GIL。
        """
        self._native_menu = _create("item", manager, text=text, enabled=enabled, accelerator=accelerator)

    @classmethod
    def with_id(
        cls,
        manager: ManagerType,
        id: MenuID,
        text: str,
        enabled: bool,
        accelerator: str | None = None,
        /,
    ) -> MenuItem:
        """
        创建指定 ID 的普通项目，参数形状沿用 PyTauri。

        无效快捷键在构造前拒绝；释放 GIL，禁止同步 GUI 回调重入。
        """
        return cls._from_resource(_create("item", manager, _text(id), text, enabled, accelerator=accelerator))


class CheckMenuItem(_Accelerated):
    """
    带原生勾选状态的菜单项，选择行为沿用平台原生规则。

    checked 必须为 bool；同步 GUI 回调中读取状态须转到工作线程。
    """

    __slots__ = ()

    def __init__(
        self,
        manager: ManagerType,
        text: str,
        enabled: bool,
        checked: bool,
        accelerator: str | None = None,
        /,
    ) -> None:
        """
        创建自动 ID 勾选项，checked 指定初始状态。

        桌面 setup 或运行期间释放 GIL，禁止同步 GUI 回调重入。
        """
        self._native_menu = _create(
            "check", manager, text=text, enabled=enabled, checked=checked, accelerator=accelerator
        )

    @classmethod
    def with_id(
        cls,
        manager: ManagerType,
        id: MenuID,
        text: str,
        enabled: bool,
        checked: bool,
        accelerator: str | None = None,
        /,
    ) -> CheckMenuItem:
        """
        创建指定 ID 的勾选项目，可省略快捷键。

        参数顺序沿用 PyTauri；释放 GIL，退出或同步 GUI 回调内报错。
        """
        return cls._from_resource(_create("check", manager, _text(id), text, enabled, checked, accelerator))

    def is_checked(self) -> bool:
        """
        查询原生勾选状态，包括用户选择产生的更新。

        桌面运行期间释放 GIL；退出或同步 GUI 回调内报错。
        """
        return self._native_menu.flag(True)

    def set_checked(self, checked: bool, /) -> None:
        """
        设置共享项目的勾选状态，参数必须为 bool。

        工作线程释放 GIL；退出或同步 GUI 回调内报错。
        """
        self._native_menu.set_flag(True, _bool(checked))


class IconMenuItem(_Accelerated):
    """
    使用自有 RGBA 图像的原生菜单项。

    icon 为 Image 或 None，NativeIcon 角色未绑定；显示外观沿用平台。
    """

    __slots__ = ()

    def __init__(
        self,
        manager: ManagerType,
        text: str,
        enabled: bool,
        icon: Image | None = None,
        accelerator: str | None = None,
        /,
    ) -> None:
        """
        创建自动 ID 图像项目，icon 与快捷键默认均为 None。

        桌面 setup 或运行期间释放 GIL，禁止同步 GUI 回调重入。
        """
        self._native_menu = _create("icon", manager, text=text, enabled=enabled, accelerator=accelerator, icon=icon)

    @classmethod
    def with_id(
        cls,
        manager: ManagerType,
        id: MenuID,
        text: str,
        enabled: bool,
        icon: Image | None = None,
        accelerator: str | None = None,
        /,
    ) -> IconMenuItem:
        """
        创建指定 ID 的图像项目，参数形状沿用 PyTauri。

        图像数据由原生拥有；释放 GIL，退出或同步回调内报错。
        """
        return cls._from_resource(
            _create("icon", manager, _text(id), text, enabled, accelerator=accelerator, icon=icon)
        )

    def set_icon(self, icon: Image | None, /) -> None:
        """
        设置图像，None 清除；接受已解码 PNG/ICO 或 RGBA Image。

        原生拥有图像数据；释放 GIL，禁止同步 GUI 回调重入。
        """
        if icon is not None and not isinstance(icon, Image):
            raise TypeError("Expected Image or None")
        self._native_menu.set_icon(icon)


class PredefinedMenuItem(_TextItem):
    """
    当前仅提供原生 separator，其他预定义角色未实现。

    通过 separator 工厂创建；文本显示行为沿用平台。
    """

    __slots__ = ()

    def __init__(self) -> None:
        """
        拒绝直接构造；使用 separator(manager)。

        本类型不在导入或构造错误时初始化 GUI。
        """
        raise TypeError("Use PredefinedMenuItem.separator(manager)")

    @classmethod
    def separator(cls, manager: ManagerType, /) -> PredefinedMenuItem:
        """
        创建属于应用的原生分隔项。

        桌面 setup 或运行期间释放 GIL，退出或同步回调内报错。
        """
        return cls._from_resource(_create("separator", manager))


MenuItemKind: TypeAlias = MenuItem | Submenu | PredefinedMenuItem | CheckMenuItem | IconMenuItem
ImplContextMenu: TypeAlias = Menu | Submenu


class ContextMenu:
    """
    Menu 与 Submenu 的上下文弹出辅助入口。

    当前接受 WebviewWindow 是本项目扩展，未提供 PyTauri 独立 Window。
    """

    @staticmethod
    def popup(slf: ImplContextMenu, window: WebviewWindow, /) -> None:
        """
        在同应用窗口弹出菜单，位置沿用平台默认。

        可能等待用户选择；工作线程释放 GIL，禁止同步 GUI 回调重入。
        """
        if not isinstance(slf, (Menu, Submenu)) or not isinstance(window, WebviewWindow):
            raise TypeError("Expected Menu or Submenu and WebviewWindow")
        window.popup_menu(slf)

    @staticmethod
    def popup_at(slf: ImplContextMenu, window: WebviewWindow, position: PositionType, /) -> None:
        """
        在窗口相对逻辑或物理位置弹出菜单。

        位置使用 DPI 类型，可能等待用户选择；释放 GIL，禁止同步回调重入。
        """
        if not isinstance(slf, (Menu, Submenu)) or not isinstance(window, WebviewWindow):
            raise TypeError("Expected Menu or Submenu and WebviewWindow")
        window.popup_menu_at(slf, position)


def _item(value: MenuItemKind) -> MenuItemKind:
    if not isinstance(value, (MenuItem, Submenu, PredefinedMenuItem, CheckMenuItem, IconMenuItem)):
        raise TypeError("Expected a native menu item")
    return value


def _from_item(resource: _native.MenuResource) -> MenuItemKind:
    kind = resource.kind()
    classes = {
        "item": MenuItem,
        "submenu": Submenu,
        "separator": PredefinedMenuItem,
        "check": CheckMenuItem,
        "icon": IconMenuItem,
    }
    return classes[kind]._from_resource(resource)


def _from_native(resource: _native.MenuResource) -> Menu:
    if resource.kind() != "menu":
        raise _native.BindingError("invalid_menu: Expected Menu")
    return Menu._from_resource(resource)


__all__ = [
    "CheckMenuItem",
    "ContextMenu",
    "IconMenuItem",
    "ImplContextMenu",
    "Menu",
    "MenuEvent",
    "MenuID",
    "MenuItem",
    "MenuItemKind",
    "PredefinedMenuItem",
    "Submenu",
]
