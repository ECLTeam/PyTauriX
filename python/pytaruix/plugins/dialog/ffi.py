# ============================================================
# PytaruiX
# 文件作用：提供可迁移的桌面对话框契约、参数校验及原生桥接。
# 公开接口：DialogExt、文件/消息构建器、选项、按钮、init。
# ============================================================
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TypeAlias, TypedDict, Unpack, cast

from ... import _native
from ...errors import BindingError
from ...ffi import WebviewWindow
from ...manager import ManagerType, _handle
from ...plugin import Plugin

if not _native.plugin_dialog_available:
    raise ImportError("Dialog requires a desktop build with the plugin-dialog Cargo feature")

FilePath: TypeAlias = Path
ImplDialogExt: TypeAlias = ManagerType


class MessageDialogKind(Enum):
    """
    选择原生消息图标；具体图标由操作系统决定。
    """

    Info = "Info"
    Warning = "Warning"
    Error = "Error"


class MessageDialogButtons:
    """
    对齐常见标准按钮及自定义标签；bool 结果仅表达肯定选择。
    """

    @dataclass(frozen=True, slots=True)
    class Ok:
        """
        显示确认按钮。
        """

    @dataclass(frozen=True, slots=True)
    class OkCancel:
        """
        显示确认和取消按钮。
        """

    @dataclass(frozen=True, slots=True)
    class YesNo:
        """
        显示是和否按钮。
        """

    @dataclass(frozen=True, slots=True)
    class YesNoCancel:
        """
        显示是、否和取消按钮。
        """

    class OkCustom(tuple[str]):
        """
        保存自定义肯定按钮标签，并保留 tuple 和 _0 契约。
        """

        __match_args__ = ("_0",)

        def __new__(cls, label: str, /) -> MessageDialogButtons.OkCustom:
            return tuple.__new__(cls, (_text(label),))

        @property
        def _0(self) -> str:
            return self[0]

    class OkCancelCustom(tuple[str, str]):
        """
        保存肯定及取消按钮标签。
        """

        __match_args__ = ("_0", "_1")

        def __new__(cls, positive: str, negative: str, /) -> MessageDialogButtons.OkCancelCustom:
            return tuple.__new__(cls, (_text(positive), _text(negative)))

        @property
        def _0(self) -> str:
            return self[0]

        @property
        def _1(self) -> str:
            return self[1]

    class YesNoCancelCustom(tuple[str, str, str]):
        """
        保存肯定、否定及取消按钮标签。
        """

        __match_args__ = ("_0", "_1", "_2")

        def __new__(cls, yes: str, no: str, cancel: str, /) -> MessageDialogButtons.YesNoCancelCustom:
            return tuple.__new__(cls, (_text(yes), _text(no), _text(cancel)))

        @property
        def _0(self) -> str:
            return self[0]

        @property
        def _1(self) -> str:
            return self[1]

        @property
        def _2(self) -> str:
            return self[2]


MessageDialogButtonsType: TypeAlias = (
    MessageDialogButtons.Ok
    | MessageDialogButtons.OkCancel
    | MessageDialogButtons.YesNo
    | MessageDialogButtons.YesNoCancel
    | MessageDialogButtons.OkCustom
    | MessageDialogButtons.OkCancelCustom
    | MessageDialogButtons.YesNoCancelCustom
)


class FileDialogBuilderArgs(TypedDict, total=False):
    """
    文件操作选项；父窗口仅在显式指定时设置。
    """

    add_filter: tuple[str, Sequence[str]]
    set_directory: Path | str
    set_file_name: str
    set_parent: WebviewWindow
    set_title: str
    set_can_create_directories: bool


class MessageDialogBuilderArgs(TypedDict, total=False):
    """
    消息选项；默认图标、标题及按钮由上游决定。
    """

    title: str
    parent: WebviewWindow
    kind: MessageDialogKind
    buttons: MessageDialogButtonsType


def _text(value: object) -> str:
    if not isinstance(value, str) or "\0" in value:
        raise BindingError("invalid_dialog_option: Expected text without NUL")
    return value


def _options(options: dict[str, object], *, message: bool = False) -> tuple[str, WebviewWindow | None]:
    allowed = MessageDialogBuilderArgs.__annotations__ if message else FileDialogBuilderArgs.__annotations__
    if options.keys() - allowed.keys():
        raise BindingError("invalid_dialog_option: Unsupported dialog option")
    prepared = dict(options)
    parent = prepared.pop("parent" if message else "set_parent", None)
    if parent is not None and not isinstance(parent, WebviewWindow):
        raise BindingError("invalid_parent: Expected WebviewWindow")
    for name, value in list(prepared.items()):
        if name == "set_directory":
            if not isinstance(value, (str, Path)):
                raise BindingError("invalid_dialog_option: Expected Path or str")
            prepared[name] = _text(str(value))
        elif name == "add_filter":
            if not isinstance(value, tuple) or len(value) != 2:
                raise BindingError("invalid_dialog_option: Expected filter name and extensions")
            name_value, extensions = value
            if not isinstance(extensions, Sequence) or isinstance(extensions, (str, bytes)):
                raise BindingError("invalid_dialog_option: Expected a sequence of extensions")
            prepared[name] = [_text(name_value), [_text(extension) for extension in extensions]]
        elif name == "set_can_create_directories":
            if not isinstance(value, bool):
                raise BindingError("invalid_dialog_option: Expected bool")
        elif name == "kind":
            if not isinstance(value, MessageDialogKind):
                raise BindingError("invalid_dialog_option: Expected MessageDialogKind")
            prepared[name] = value.value
        elif name == "buttons":
            variants = (
                MessageDialogButtons.Ok,
                MessageDialogButtons.OkCancel,
                MessageDialogButtons.YesNo,
                MessageDialogButtons.YesNoCancel,
                MessageDialogButtons.OkCustom,
                MessageDialogButtons.OkCancelCustom,
                MessageDialogButtons.YesNoCancelCustom,
            )
            if type(value) not in variants:
                raise BindingError("invalid_dialog_option: Expected MessageDialogButtons variant")
            variant = type(value).__name__
            if isinstance(value, tuple):
                labels = [_text(label) for label in value]
                prepared[name] = {variant: labels[0] if len(labels) == 1 else labels}
            else:
                prepared[name] = variant
        else:
            prepared[name] = _text(value)
    return json.dumps(prepared, allow_nan=False), cast(WebviewWindow | None, parent)


def _callback(handler: object) -> None:
    if not callable(handler):
        raise BindingError("invalid_callback: Dialog callback must be callable")


def init() -> Plugin:
    """
    创建一次性 dialog 插件描述符，不初始化 GUI。

    :return: 传给 Builder.build(plugins=...) 的原生插件
    """
    return _native.dialog_init()


class FileDialogBuilder:
    """
    选择桌面路径；取消返回 None，保存操作只选择路径，不写文件。

    阻塞操作限运行中的工作线程；回调须同步，不保证 GUI 线程。
    构建器保留创建时的窗口代次，所属窗口关闭后失效。
    """

    def __init__(self, native: _native.Dialog) -> None:
        self._native = native

    def _blocking(self, mode: str, options: dict[str, object]) -> object:
        encoded, parent = _options(options)
        return self._native.file(mode, encoded, parent)

    def _submit(self, mode: str, handler: Callable[..., object], options: dict[str, object]) -> None:
        _callback(handler)
        encoded, parent = _options(options)
        self._native.file(mode, encoded, parent, handler)

    def pick_file(
        self, handler: Callable[[FilePath | None], object], /, **kwargs: Unpack[FileDialogBuilderArgs]
    ) -> None:
        """
        异步提交原生选择器；同步回调收到路径或取消的 None。
        """
        self._submit("pick_file", handler, dict(kwargs))

    def blocking_pick_file(self, /, **kwargs: Unpack[FileDialogBuilderArgs]) -> FilePath | None:
        """
        在工作线程等待路径；期间释放 GIL，所有者关闭时返回稳定错误。
        """
        return cast(FilePath | None, self._blocking("pick_file", dict(kwargs)))

    def pick_files(
        self, handler: Callable[[list[FilePath] | None], object], /, **kwargs: Unpack[FileDialogBuilderArgs]
    ) -> None:
        """
        异步提交原生选择器；同步回调收到路径或取消的 None。
        """
        self._submit("pick_files", handler, dict(kwargs))

    def blocking_pick_files(self, /, **kwargs: Unpack[FileDialogBuilderArgs]) -> list[FilePath] | None:
        """
        在工作线程等待路径；期间释放 GIL，所有者关闭时返回稳定错误。
        """
        return cast(list[FilePath] | None, self._blocking("pick_files", dict(kwargs)))

    def pick_folder(
        self, handler: Callable[[FilePath | None], object], /, **kwargs: Unpack[FileDialogBuilderArgs]
    ) -> None:
        """
        异步提交原生选择器；同步回调收到路径或取消的 None。
        """
        self._submit("pick_folder", handler, dict(kwargs))

    def blocking_pick_folder(self, /, **kwargs: Unpack[FileDialogBuilderArgs]) -> FilePath | None:
        """
        在工作线程等待路径；期间释放 GIL，所有者关闭时返回稳定错误。
        """
        return cast(FilePath | None, self._blocking("pick_folder", dict(kwargs)))

    def pick_folders(
        self, handler: Callable[[list[FilePath] | None], object], /, **kwargs: Unpack[FileDialogBuilderArgs]
    ) -> None:
        """
        异步提交原生选择器；同步回调收到路径或取消的 None。
        """
        self._submit("pick_folders", handler, dict(kwargs))

    def blocking_pick_folders(self, /, **kwargs: Unpack[FileDialogBuilderArgs]) -> list[FilePath] | None:
        """
        在工作线程等待路径；期间释放 GIL，所有者关闭时返回稳定错误。
        """
        return cast(list[FilePath] | None, self._blocking("pick_folders", dict(kwargs)))

    def save_file(
        self, handler: Callable[[FilePath | None], object], /, **kwargs: Unpack[FileDialogBuilderArgs]
    ) -> None:
        """
        异步提交原生选择器；同步回调收到路径或取消的 None。
        """
        self._submit("save_file", handler, dict(kwargs))

    def blocking_save_file(self, /, **kwargs: Unpack[FileDialogBuilderArgs]) -> FilePath | None:
        """
        在工作线程等待路径；期间释放 GIL，所有者关闭时返回稳定错误。
        """
        return cast(FilePath | None, self._blocking("save_file", dict(kwargs)))


class MessageDialogBuilder:
    """
    显示原生消息框；肯定选择返回 True，其余按钮返回 False。
    """

    def __init__(self, native: _native.Dialog) -> None:
        self._native = native

    def show(self, handler: Callable[[bool], object], /, **kwargs: Unpack[MessageDialogBuilderArgs]) -> None:
        """
        异步提交消息框，同步回调接收 bool，异常由 run_return 归还。
        """
        _callback(handler)
        encoded, parent = _options(dict(kwargs), message=True)
        self._native.show(encoded, parent, handler)

    def blocking_show(self, /, **kwargs: Unpack[MessageDialogBuilderArgs]) -> bool:
        """
        在应用运行中的工作线程等待 bool；GUI 及原生回调中拒绝阻塞。
        """
        encoded, parent = _options(dict(kwargs), message=True)
        return cast(bool, self._native.show(encoded, parent))


class DialogExt:
    """
    通过 App、AppHandle 或 WebviewWindow 创建对话框构建器。
    """

    @staticmethod
    def file(manager: ImplDialogExt, /) -> FileDialogBuilder:
        """
        创建文件构建器，不显示窗口，也不隐式设置父窗口。
        """
        return FileDialogBuilder(
            _native.dialog_factory(_handle(manager), manager if isinstance(manager, WebviewWindow) else None)
        )

    @staticmethod
    def message(manager: ImplDialogExt, message: str, /) -> MessageDialogBuilder:
        """
        创建消息构建器，要求应用已注册 dialog 插件。
        """
        return MessageDialogBuilder(
            _native.dialog_factory(
                _handle(manager), manager if isinstance(manager, WebviewWindow) else None, _text(message)
            )
        )
