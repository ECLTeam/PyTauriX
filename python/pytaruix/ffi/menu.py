# PytaruiX
# 文件作用：菜单公开契约、种类边界及 PyTauri 兼容构造。
# 公开接口：Menu、Submenu、MenuItem、CheckMenuItem、IconMenuItem、PredefinedMenuItem、ContextMenu。
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, fields
from typing import TypeAlias, TypeVar

from .. import _native
from ..dpi import PositionType
from ..manager import ManagerType, _handle
from ..webview import WebviewWindow
from .image import Image

MenuID: TypeAlias = str
MenuEvent: TypeAlias = MenuID
_T = TypeVar("_T", bound="_MenuObject")


@dataclass(frozen=True, slots=True)
class AboutMetadata:
    """
    描述 About 预定义项的静态信息，只保留调用方提供且非空的字段。

    图标不在本结构内，需通过 Image 单独提供；各字段的平台效果沿用上游。
    """

    name: str | None = None
    version: str | None = None
    short_version: str | None = None
    authors: tuple[str, ...] | None = None
    comments: str | None = None
    copyright: str | None = None
    license: str | None = None
    website: str | None = None
    website_label: str | None = None
    credits: str | None = None

    def to_json(self) -> str:
        """
        序列化为原生入口接收的 JSON 对象。

        :return: 省略空字段的 JSON 文本
        """
        payload: dict[str, object] = {}
        for field in fields(self):
            value = getattr(self, field.name)
            if value is not None:
                payload[field.name] = list(value) if isinstance(value, tuple) else value
        return json.dumps(payload, ensure_ascii=False)


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
    metadata: AboutMetadata | None = None,
) -> _native.MenuResource:
    if not _native.menu_available:
        raise _native.BindingError("platform_unavailable: Native menus require a desktop platform")
    if accelerator is not None:
        _text(accelerator)
    if icon is not None and not isinstance(icon, Image):
        raise TypeError("Expected Image or None")
    if metadata is not None and not isinstance(metadata, AboutMetadata):
        raise TypeError("Expected AboutMetadata or None")
    return _native.MenuResource.create(
        _handle(manager),
        kind,
        None if id is None else _text(id),
        _text(text),
        _bool(enabled),
        _bool(checked),
        accelerator,
        icon,
        None if metadata is None else metadata.to_json(),
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
    平台预定义菜单项：编辑、窗口、应用与 About 等固定角色。

    角色行为、默认文案和快捷键由平台提供；传入 text 只覆盖显示文案，
    不改变角色行为。部分角色仅在 macOS 生效，Windows/Linux 上不显示或无效。
    """

    __slots__ = ()

    def __init__(self) -> None:
        """
        拒绝直接构造；使用对应角色的类方法。

        本类型不在导入或构造错误时初始化 GUI。
        """
        raise TypeError("Use PredefinedMenuItem.separator(manager) or another role factory")

    @classmethod
    def separator(cls, manager: ManagerType, /) -> PredefinedMenuItem:
        """
        创建分隔项，显示行为沿用平台。
        """
        return cls._from_resource(_create("separator", manager))

    @classmethod
    def copy(cls, manager: ManagerType, text: str | None = None, /) -> PredefinedMenuItem:
        """
        创建复制项；text 覆盖平台默认文案，所有桌面平台。
        """
        return cls._from_resource(_create("copy", manager, text=text or ""))

    @classmethod
    def cut(cls, manager: ManagerType, text: str | None = None, /) -> PredefinedMenuItem:
        """
        创建剪切项；text 覆盖平台默认文案，所有桌面平台。
        """
        return cls._from_resource(_create("cut", manager, text=text or ""))

    @classmethod
    def paste(cls, manager: ManagerType, text: str | None = None, /) -> PredefinedMenuItem:
        """
        创建粘贴项；text 覆盖平台默认文案，所有桌面平台。
        """
        return cls._from_resource(_create("paste", manager, text=text or ""))

    @classmethod
    def select_all(cls, manager: ManagerType, text: str | None = None, /) -> PredefinedMenuItem:
        """
        创建全选项；text 覆盖平台默认文案，所有桌面平台。
        """
        return cls._from_resource(_create("select_all", manager, text=text or ""))

    @classmethod
    def undo(cls, manager: ManagerType, text: str | None = None, /) -> PredefinedMenuItem:
        """
        创建撤销项；text 覆盖平台默认文案，所有桌面平台。
        """
        return cls._from_resource(_create("undo", manager, text=text or ""))

    @classmethod
    def redo(cls, manager: ManagerType, text: str | None = None, /) -> PredefinedMenuItem:
        """
        创建重做项；text 覆盖平台默认文案，所有桌面平台。
        """
        return cls._from_resource(_create("redo", manager, text=text or ""))

    @classmethod
    def minimize(cls, manager: ManagerType, text: str | None = None, /) -> PredefinedMenuItem:
        """
        创建最小化窗口项；text 覆盖平台默认文案，所有桌面平台。
        """
        return cls._from_resource(_create("minimize", manager, text=text or ""))

    @classmethod
    def maximize(cls, manager: ManagerType, text: str | None = None, /) -> PredefinedMenuItem:
        """
        创建最大化窗口项；text 覆盖平台默认文案，所有桌面平台。
        """
        return cls._from_resource(_create("maximize", manager, text=text or ""))

    @classmethod
    def fullscreen(cls, manager: ManagerType, text: str | None = None, /) -> PredefinedMenuItem:
        """
        创建切换全屏项；text 覆盖平台默认文案，所有桌面平台。
        """
        return cls._from_resource(_create("fullscreen", manager, text=text or ""))

    @classmethod
    def close_window(cls, manager: ManagerType, text: str | None = None, /) -> PredefinedMenuItem:
        """
        创建关闭窗口项；text 覆盖平台默认文案，所有桌面平台。
        """
        return cls._from_resource(_create("close_window", manager, text=text or ""))

    @classmethod
    def quit(cls, manager: ManagerType, text: str | None = None, /) -> PredefinedMenuItem:
        """
        创建退出应用项；text 覆盖平台默认文案，所有桌面平台。
        """
        return cls._from_resource(_create("quit", manager, text=text or ""))

    @classmethod
    def hide(cls, manager: ManagerType, text: str | None = None, /) -> PredefinedMenuItem:
        """
        创建隐藏应用项；text 覆盖平台默认文案，仅 macOS 生效。
        """
        return cls._from_resource(_create("hide", manager, text=text or ""))

    @classmethod
    def hide_others(cls, manager: ManagerType, text: str | None = None, /) -> PredefinedMenuItem:
        """
        创建隐藏其他应用项；text 覆盖平台默认文案，仅 macOS 生效。
        """
        return cls._from_resource(_create("hide_others", manager, text=text or ""))

    @classmethod
    def show_all(cls, manager: ManagerType, text: str | None = None, /) -> PredefinedMenuItem:
        """
        创建显示全部应用项；text 覆盖平台默认文案，仅 macOS 生效。
        """
        return cls._from_resource(_create("show_all", manager, text=text or ""))

    @classmethod
    def services(cls, manager: ManagerType, text: str | None = None, /) -> PredefinedMenuItem:
        """
        创建系统服务子菜单项；text 覆盖平台默认文案，仅 macOS 生效，Windows/Linux 不显示。
        """
        return cls._from_resource(_create("services", manager, text=text or ""))

    @classmethod
    def bring_all_to_front(cls, manager: ManagerType, text: str | None = None, /) -> PredefinedMenuItem:
        """
        创建前置全部窗口项；text 覆盖平台默认文案，仅 macOS 生效。
        """
        return cls._from_resource(_create("bring_all_to_front", manager, text=text or ""))

    @classmethod
    def about(
        cls,
        manager: ManagerType,
        text: str | None = None,
        metadata: AboutMetadata | None = None,
        /,
    ) -> PredefinedMenuItem:
        """
        创建 About 项；metadata 提供名称、版本、版权等信息。

        :param manager: 应用、应用句柄或窗口
        :param text: 覆盖平台默认文案
        :param metadata: 静态元数据，图标暂不支持
        :return: 预定义菜单项
        :raises BindingError: 应用已关闭、元数据非法或平台不支持
        """
        return cls._from_resource(_create("about", manager, text=text or "", metadata=metadata))


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
        "predefined": PredefinedMenuItem,
        "check": CheckMenuItem,
        "icon": IconMenuItem,
    }
    return classes[kind]._from_resource(resource)


def _from_native(resource: _native.MenuResource) -> Menu:
    if resource.kind() != "menu":
        raise _native.BindingError("invalid_menu: Expected Menu")
    return Menu._from_resource(resource)


__all__ = [
    "AboutMetadata",
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
