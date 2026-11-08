# ============================================================
# PytaruiX
# 文件作用：公开已实现的原生句柄与底层类型。
# 公开接口：AppHandle、BindingError、Context、WebviewWindow。
# ============================================================
from .._native import AppHandle, BindingError, Context, Webview, WebviewWindow
from ..dpi import Rect
from ..event_target import EventTarget, EventTargetType
from ..webview_requests import (
    NewWindowFeatures,
    NewWindowResponse,
    PermissionKind,
    PermissionResponse,
    WebResourceRequest,
    WebResourceResponse,
)
from .emitter import Emitter

__all__ = [
    "AppHandle",
    "BindingError",
    "Context",
    "Emitter",
    "EventTarget",
    "EventTargetType",
    "NewWindowFeatures",
    "NewWindowResponse",
    "PermissionKind",
    "PermissionResponse",
    "Rect",
    "WebResourceRequest",
    "WebResourceResponse",
    "Webview",
    "WebviewWindow",
]
