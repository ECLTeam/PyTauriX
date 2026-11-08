# ============================================================
# PytaruiX
# 文件作用：提供可匹配的生命周期、窗口事件及页面加载载荷。
# 公开接口：RunEvent、WindowEvent、PageLoadPayload、PageLoadEvent 与请求控制 API。
# ============================================================
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from ._native import CloseRequestApi, Event, ExitRequestApi
from .dpi import PhysicalPosition, PhysicalSize

__all__ = [
    "CloseRequestApi",
    "DownloadEventType",
    "DownloadFinished",
    "DownloadRequested",
    "Event",
    "ExitRequestApi",
    "PageLoadEvent",
    "PageLoadPayload",
    "RunEvent",
    "RunEventType",
    "WindowEvent",
    "WindowEventType",
]


class RunEvent:
    """
    提供 Ready、Exit 与 ExitRequested；退出控制只在同步回调期间有效。
    """

    @dataclass(frozen=True, slots=True)
    class Ready:
        """
        应用及配置窗口已就绪。
        """

    @dataclass(frozen=True, slots=True)
    class Exit:
        """
        应用事件循环正在退出。
        """

    @dataclass(frozen=True, slots=True)
    class ExitRequested:
        """
        收到退出请求；用户交互的 code 为 None，api.prevent_exit 在本次回调内有效。
        """

        code: int | None
        api: ExitRequestApi


RunEventType: TypeAlias = RunEvent.Ready | RunEvent.Exit | RunEvent.ExitRequested


class WindowEvent:
    """
    表示已绑定窗口事件；尺寸和位置载荷为物理像素，控制 API 仅在本次回调内有效。
    """

    @dataclass(frozen=True, slots=True)
    class CloseRequested:
        """
        窗口请求关闭，api.prevent_close 阻止本次请求。
        """

        api: CloseRequestApi

    @dataclass(frozen=True, slots=True)
    class Destroyed:
        """
        原生窗口已销毁，本代句柄立即失效；回调后释放窗口回调槽。
        """

    @dataclass(frozen=True, slots=True)
    class Focused:
        """
        原生窗口焦点发生变化。
        """

        focused: bool

    @dataclass(frozen=True, slots=True)
    class Resized:
        """
        客户区尺寸变化，采用物理像素。
        """

        size: PhysicalSize

    @dataclass(frozen=True, slots=True)
    class Moved:
        """
        窗口位置变化，采用物理像素。
        """

        position: PhysicalPosition

    @dataclass(frozen=True, slots=True)
    class ScaleFactorChanged:
        """
        窗口缩放因子变化，包含新的客户区物理尺寸。
        """

        scale_factor: float
        new_inner_size: PhysicalSize

    @dataclass(frozen=True, slots=True)
    class ThemeChanged:
        """
        系统窗口主题变化；theme 为 light 或 dark。
        """

        theme: str

    @dataclass(frozen=True, slots=True)
    class DragDropEnter:
        """
        拖入窗口，路径与光标物理位置为不可变快照。
        """

        paths: tuple[str, ...]
        position: tuple[float, float]

    @dataclass(frozen=True, slots=True)
    class DragDropOver:
        """
        拖拽在窗口内移动。
        """

        position: tuple[float, float]

    @dataclass(frozen=True, slots=True)
    class DragDropDrop:
        """
        文件在窗口内释放。
        """

        paths: tuple[str, ...]
        position: tuple[float, float]

    @dataclass(frozen=True, slots=True)
    class DragDropLeave:
        """
        拖拽离开窗口或取消。
        """


WindowEventType: TypeAlias = (
    WindowEvent.CloseRequested
    | WindowEvent.Destroyed
    | WindowEvent.Focused
    | WindowEvent.Resized
    | WindowEvent.Moved
    | WindowEvent.ScaleFactorChanged
    | WindowEvent.ThemeChanged
    | WindowEvent.DragDropEnter
    | WindowEvent.DragDropOver
    | WindowEvent.DragDropDrop
    | WindowEvent.DragDropLeave
)


class PageLoadEvent(Enum):
    """
    区分原生页面加载开始与完成。
    """

    Started = "started"
    Finished = "finished"


@dataclass(frozen=True, slots=True)
class PageLoadPayload:
    """
    保存本次加载 URL 和阶段，不持有窗口或原生请求资源。
    """

    url: str
    event: PageLoadEvent


def _page_load(url: str, event: str) -> PageLoadPayload:
    return PageLoadPayload(url, PageLoadEvent(event))


@dataclass(frozen=True, slots=True)
class DownloadRequested:
    """
    下载请求；destination 为原生建议路径，回调返回 False 可取消下载。
    """

    url: str
    destination: str


@dataclass(frozen=True, slots=True)
class DownloadFinished:
    """
    下载结束；path 可能缺失，success 表示原生报告的结果。
    """

    url: str
    path: str | None
    success: bool


DownloadEventType: TypeAlias = DownloadRequested | DownloadFinished


def _window_event(name: str, payload_json: str, api: CloseRequestApi | None) -> WindowEventType:
    if name == "close_requested":
        if api is None:
            raise RuntimeError("Close request API is missing")
        return WindowEvent.CloseRequested(api)
    if name == "destroyed":
        return WindowEvent.Destroyed()
    if name == "drag_drop_leave":
        return WindowEvent.DragDropLeave()
    value = json.loads(payload_json)
    if name == "focused":
        return WindowEvent.Focused(value)
    if name == "resized":
        # 最小化原生载荷允许零；公共正尺寸构造器不允许零。
        return WindowEvent.Resized(_physical_size(value[0], value[1]))
    if name == "scale_factor_changed":
        return WindowEvent.ScaleFactorChanged(value[0], _physical_size(value[1], value[2]))
    if name == "theme_changed":
        return WindowEvent.ThemeChanged(value)
    if name == "drag_drop_over":
        return WindowEvent.DragDropOver(tuple(value["position"]))
    if name in {"drag_drop_enter", "drag_drop_drop"}:
        paths = tuple(value["paths"])
        position = tuple(value["position"])
        if name == "drag_drop_enter":
            return WindowEvent.DragDropEnter(paths, position)
        return WindowEvent.DragDropDrop(paths, position)
    return WindowEvent.Moved(PhysicalPosition(value[0], value[1]))


def _physical_size(width: int, height: int) -> PhysicalSize:
    # 原生事件已由 Rust 构造 PhysicalSize；直接调用专门载荷工厂保留零尺寸。
    from . import _native

    return _native.physical_size_payload(width, height)
