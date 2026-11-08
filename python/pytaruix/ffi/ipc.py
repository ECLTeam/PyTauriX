# PytaruiX
# 文件作用：公开原生 IPC 通道标识、发送句柄与请求取消句柄。
# 公开接口：Channel、JavaScriptChannelId、Request。
from __future__ import annotations

from .._native import Channel, JavaScriptChannelId, Request

__all__ = ["Channel", "JavaScriptChannelId", "Request"]
