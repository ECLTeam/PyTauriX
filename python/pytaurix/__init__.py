# ============================================================
# PyTauriX
# 文件作用：提供框架公共入口与顶层导出。
# 公开接口：应用、命令、共享状态、生命周期、管理器与事件。
# ============================================================
from __future__ import annotations

from . import process
from .application import App, Builder, builder_factory, context_factory
from .dpi import LogicalPosition, LogicalSize, PhysicalPosition, PhysicalSize, Rect
from .errors import BindingError, CommandError
from .event_target import EventTarget, EventTargetType
from .events import (
    CloseRequestApi,
    Event,
    ExitRequestApi,
    PageLoadEvent,
    PageLoadPayload,
    RunEvent,
    RunEventType,
    WindowEvent,
    WindowEventType,
)
from .ffi import AppHandle, Context, Webview, WebviewWindow
from .ipc import Commands, Headers, Request, State
from .manager import Emitter, Listener, Manager
from .path import BaseDirectory, PathResolver
from .protocol import Protocol, ProtocolRequest, ProtocolResponse, create_protocol
from .runtime import RuntimeInfo, get_runtime_info
from .url import WebviewUrl, WebviewUrlType
from .webview_requests import (
    NewWindowFeatures,
    NewWindowResponse,
    PermissionKind,
    PermissionResponse,
    WebResourceRequest,
    WebResourceResponse,
)

__all__ = [
    "App",
    "AppHandle",
    "BaseDirectory",
    "BindingError",
    "Builder",
    "CloseRequestApi",
    "CommandError",
    "Commands",
    "Context",
    "Emitter",
    "Event",
    "EventTarget",
    "EventTargetType",
    "ExitRequestApi",
    "Headers",
    "Listener",
    "LogicalPosition",
    "LogicalSize",
    "Manager",
    "NewWindowFeatures",
    "NewWindowResponse",
    "PageLoadEvent",
    "PageLoadPayload",
    "PathResolver",
    "PermissionKind",
    "PermissionResponse",
    "PhysicalPosition",
    "PhysicalSize",
    "Protocol",
    "ProtocolRequest",
    "ProtocolResponse",
    "Rect",
    "Request",
    "RunEvent",
    "RunEventType",
    "RuntimeInfo",
    "State",
    "WebResourceRequest",
    "WebResourceResponse",
    "Webview",
    "WebviewUrl",
    "WebviewUrlType",
    "WebviewWindow",
    "WindowEvent",
    "WindowEventType",
    "builder_factory",
    "context_factory",
    "create_protocol",
    "get_runtime_info",
    "process",
]
