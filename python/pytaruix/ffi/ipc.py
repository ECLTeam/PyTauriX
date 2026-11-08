# PytaruiX
# 文件作用：公开原生 IPC 通道标识及发送句柄。
# 公开接口：Channel、JavaScriptChannelId。
from __future__ import annotations

from .._native import Channel, JavaScriptChannelId

__all__ = ["Channel", "JavaScriptChannelId"]
