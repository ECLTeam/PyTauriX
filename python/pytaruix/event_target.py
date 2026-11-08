# PytaruiX
# 文件作用：保留上游事件目标的类型与标签，避免将所有目标降为字符串。
# 公开接口：EventTarget、EventTargetType。
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TypeAlias

from .errors import BindingError


@dataclass(frozen=True, slots=True)
class _LabeledTarget:
    label: str

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or "\x00" in self.label:
            raise BindingError("invalid_target: Event target label must be text without NUL")


class EventTarget:
    """
    提供六种事件路由目标；相同标签的不同原生对象仍保留目标类型。

    该类型不授予 IPC 权限。字符串发送目标等价于 AnyLabel，命名沿用 PyTauri。
    """

    @dataclass(frozen=True, slots=True)
    class Any:
        """
        匹配全部事件目标。
        """

    @dataclass(frozen=True, slots=True)
    class App:
        """
        匹配应用及应用句柄监听器。
        """

    @dataclass(frozen=True, slots=True)
    class AnyLabel(_LabeledTarget):
        """
        匹配给定标签的 Window、Webview 和 WebviewWindow。
        """

    @dataclass(frozen=True, slots=True)
    class Window(_LabeledTarget):
        """
        匹配给定标签的原生窗口目标。
        """

    @dataclass(frozen=True, slots=True)
    class Webview(_LabeledTarget):
        """
        匹配给定标签的原生 WebView 目标。
        """

    @dataclass(frozen=True, slots=True)
    class WebviewWindow(_LabeledTarget):
        """
        匹配给定标签的 WebView 窗口目标。
        """


EventTargetType: TypeAlias = (
    EventTarget.Any
    | EventTarget.App
    | EventTarget.AnyLabel
    | EventTarget.Window
    | EventTarget.Webview
    | EventTarget.WebviewWindow
)


def _target_json(target: EventTargetType | str) -> str:
    if isinstance(target, str):
        target = EventTarget.AnyLabel(target)
    if not isinstance(
        target,
        (
            EventTarget.Any,
            EventTarget.App,
            EventTarget.AnyLabel,
            EventTarget.Window,
            EventTarget.Webview,
            EventTarget.WebviewWindow,
        ),
    ):
        raise BindingError("invalid_target: Expected EventTarget or a string label")
    value = {"kind": type(target).__name__}
    if isinstance(target, _LabeledTarget):
        value["label"] = target.label
    return json.dumps(value, ensure_ascii=False)
