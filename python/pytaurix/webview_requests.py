# PyTauriX
# 文件作用：提供 WebView 策略回调的不可变请求快照及显式返回类型。
# 公开接口：HTTP 请求/响应、新窗口几何及决策、浏览器权限种类与决策。
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .errors import BindingError

__all__ = [
    "NewWindowFeatures",
    "NewWindowResponse",
    "PermissionKind",
    "PermissionResponse",
    "WebResourceRequest",
    "WebResourceResponse",
]


class NewWindowResponse(Enum):
    """
    决定 window.open 是否交给平台默认实现；不授予新窗口宿主 IPC 权限。

    Create 需要平台 WebView 环境共享，当前未绑定；同步回调内禁止阻塞建窗。
    """

    Allow = "allow"
    Deny = "deny"


class PermissionResponse(Enum):
    """
    仅决定本次浏览器权限请求；Default 遵循平台行为，不等同于授权。

    不修改宿主 ACL；浏览器持久化的已有决定可能使本钩子不再触发。
    """

    Allow = "allow"
    Deny = "deny"
    Default = "default"


class PermissionKind(Enum):
    """
    锁定上游的浏览器权限种类，各平台实际支持的子集不同。

    回调在原生线程同步执行；kind 不包含可信请求来源 URL，不能仅凭窗口初始 URL 授权远程页面。
    """

    Microphone = "microphone"
    Camera = "camera"
    Geolocation = "geolocation"
    Notifications = "notifications"
    ClipboardRead = "clipboard-read"
    DisplayCapture = "display-capture"
    Midi = "midi"
    Sensors = "sensors"
    MediaKeySystemAccess = "media-key-system-access"
    LocalFonts = "local-fonts"
    WindowManagement = "window-management"
    PointerLock = "pointer-lock"
    AutomaticDownloads = "automatic-downloads"
    FileSystemAccess = "file-system-access"
    Autoplay = "autoplay"
    Other = "other"


@dataclass(frozen=True, slots=True)
class NewWindowFeatures:
    """
    保存 window.open 建议的逻辑客户区尺寸和工作区位置；缺省为 None。

    快照不持有上游 opener、原生环境或窗口，可在回调后读取。
    """

    size: tuple[float, float] | None
    position: tuple[float, float] | None


@dataclass(frozen=True, slots=True)
class WebResourceRequest:
    """
    保存应用协议的 HTTP 请求快照，正文为字节，头部元组保留重复项和原始值。

    原生构造并持有独立副本；不是所有网络流量的拦截器，不包含可写来源身份。
    """

    url: str
    method: str
    headers: tuple[tuple[str, bytes], ...]
    body: bytes


@dataclass(frozen=True, slots=True)
class WebResourceResponse:
    """
    保存完整 HTTP 响应快照；资源回调返回 None 保持原响应，返回本类型原子替换响应。

    :param status: 100 到 599 的整数状态码
    :param headers: HTTP 头名称与原始字节值，可重复；复制为不可变元组
    :param body: 不可变字节正文，所有权归本快照
    :raises BindingError: 类型、状态码或头字段不合法；原生提交时再次校验 HTTP 语法
    """

    status: int
    headers: tuple[tuple[str, bytes], ...]
    body: bytes

    def __post_init__(self) -> None:
        _validate_response(self)
        object.__setattr__(self, "headers", tuple((name, value) for name, value in self.headers))


def _validate_response(response: WebResourceResponse) -> None:
    if type(response.status) is not int or not 100 <= response.status <= 599:
        raise BindingError("invalid_response: HTTP status must be an integer between 100 and 599")
    if not isinstance(response.body, bytes):
        raise BindingError("invalid_response: HTTP body must be bytes")
    if not isinstance(response.headers, (tuple, list)):
        raise BindingError("invalid_response: HTTP headers must contain name/bytes pairs")
    tokens = "!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for pair in response.headers:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise BindingError("invalid_response: HTTP headers must contain name/bytes pairs")
        name, value = pair
        if not isinstance(name, str) or not name or not isinstance(value, bytes):
            raise BindingError("invalid_response: HTTP header requires a nonempty name and bytes value")
        if any(character not in tokens for character in name):
            raise BindingError("invalid_response: Invalid HTTP header name")
        if any(byte in (0, 10, 13, 127) or (byte < 32 and byte != 9) for byte in value):
            raise BindingError("invalid_response: Invalid HTTP header value")


def _response_parts(value: object) -> tuple[int, tuple[tuple[str, bytes], ...], bytes]:
    if not isinstance(value, WebResourceResponse):
        raise BindingError("invalid_callback: Resource callback must return WebResourceResponse or None")
    _validate_response(value)
    return value.status, value.headers, value.body


def _decision(value: object, kind: str) -> str:
    expected = NewWindowResponse if kind == "new_window" else PermissionResponse
    if not isinstance(value, expected):
        raise BindingError(f"invalid_callback: Callback must return {expected.__name__}")
    return value.value
