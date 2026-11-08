# ============================================================
# PytaruiX
# 文件作用：系统通知插件，发送桌面通知并查询权限状态。
# 公开接口：Notification、init。
# ============================================================
from __future__ import annotations

from ... import _native
from ...errors import BindingError
from ...ffi import AppHandle
from ...plugin import Plugin

__all__ = ["Notification", "init"]


def init() -> Plugin:
    """
    创建一次性通知插件描述符，不初始化 GUI。

    :return: 传给 Builder.build(plugins=...) 的原生插件
    :raises BindingError: 当前构建未包含该插件
    """
    if not _native.plugin_notification_available:
        raise BindingError("unsupported_capability: Build with the plugin-notification feature")
    return _native.notification_init()


def _text(value: object, name: str) -> str:
    """
    校验必填文本参数。

    :raises TypeError: 不是 str
    """
    if not isinstance(value, str):
        raise TypeError(f"{name} must be str")
    return value


class Notification:
    """
    发送系统通知；必须在构建时注册 notification 插件后使用。

    桌面端权限状态通常恒为 granted；Windows 未打包应用缺少应用标识时，
    通知可能不显示，`send()` 只反映上游提交结果。
    """

    def __init__(self, handle: AppHandle) -> None:
        if not isinstance(handle, AppHandle):
            raise TypeError("Notification requires an AppHandle")
        if not _native.plugin_notification_available:
            raise BindingError("unsupported_capability: Build with the plugin-notification feature")
        self._inner = _native.NotificationApi(handle)

    def permission_state(self) -> str:
        """
        查询权限状态名称（如 granted、denied、prompt）。
        """
        return self._inner.permission_state()

    def request_permission(self) -> str:
        """
        请求权限并返回请求后的状态；桌面端通常直接返回 granted。
        """
        return self._inner.request_permission()

    def send(
        self,
        title: str,
        body: str,
        /,
        *,
        silent: bool = False,
        id: int | None = None,
    ) -> None:
        """
        发送通知；同名 id 用于替换同一条通知。

        :raises BindingError: notification_failed 或 plugin_missing
        :raises TypeError: title/body 不是 str 或 id 不是 int
        """
        if id is not None and not isinstance(id, int):
            raise TypeError("id must be int or None")
        self._inner.send(
            _text(title, "title"),
            _text(body, "body"),
            silent=bool(silent),
            id=id,
        )
