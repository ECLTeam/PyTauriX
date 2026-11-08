# ============================================================
# PytaruiX
# 文件作用：注册自定义 URI scheme 协议，并把请求/响应快照转换为原生形状。
# 公开接口：Protocol、ProtocolRequest、ProtocolResponse、create_protocol。
# ============================================================
from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass

from . import _native

__all__ = ["Protocol", "ProtocolRequest", "ProtocolResponse", "create_protocol"]

# 上游已占用或与传输语义冲突的 scheme，注册即拒绝。
_RESERVED = frozenset({"tauri", "asset", "http", "https", "ipc", "channel"})
_SCHEME_LIMIT = 32

Protocol = _native.Protocol


@dataclass(frozen=True, slots=True)
class ProtocolRequest:
    """
    一次自定义协议请求的不可变快照。

    头字段为原始名称/值字符串，正文为原始字节；不包含 Tauri 内部请求对象。
    """

    uri: str
    method: str
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes = b""
    webview_label: str = ""


@dataclass(frozen=True, slots=True)
class ProtocolResponse:
    """
    协议响应；状态码或头字段非法时原生归还空 500。

    头字段按顺序追加，允许同名多次出现；正文按字节返回，不做编码转换。
    """

    status: int = 200
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes = b""


def _validate_scheme(name: str) -> str:
    """
    校验 scheme 名称；非法或保留名称抛 ValueError。

    规则与原生边界一致：ASCII 小写字母开头，只含小写字母、数字与 ``-+.``。
    """
    invalid = (
        not name
        or len(name) > _SCHEME_LIMIT
        or name in _RESERVED
        or not name.isascii()
        or not name[0].islower()
        or any(not (char.islower() or char.isdigit() or char in "-+.") for char in name)
    )
    if invalid:
        raise ValueError("scheme must be lowercase ASCII letters, digits, '-', '+' or '.', and not reserved")
    return name


def _serve(
    handler: Callable[[ProtocolRequest], ProtocolResponse],
) -> Callable[..., tuple[int, list[tuple[str, str]], bytes]]:
    """
    把处理函数包装为原生调用形状；返回值类型错误抛 TypeError。
    """

    def serve(
        uri: str,
        method: str,
        headers: list[tuple[str, str]],
        body: bytes,
        webview_label: str,
    ) -> tuple[int, list[tuple[str, str]], bytes]:
        request = ProtocolRequest(
            uri=uri,
            method=method,
            headers=tuple(headers),
            body=bytes(body),
            webview_label=webview_label,
        )
        response = handler(request)
        if not isinstance(response, ProtocolResponse):
            raise TypeError("protocol handler must return ProtocolResponse")
        return response.status, list(response.headers), bytes(response.body)

    return serve


def create_protocol(
    name: str,
    handler: Callable[[ProtocolRequest], ProtocolResponse],
) -> Protocol:
    """
    创建一次性协议描述符，交给 ``Builder.build(protocols=[...])`` 登记。

    处理器在阻塞工作线程执行，不占用 GUI 线程，因此必须是同步函数；
    异步函数返回协程会被原生判为非法响应，这里提前拒绝。
    任何处理异常由原生转换为空 500，不向前端泄露堆栈。

    :param name: ASCII 小写 scheme，例如 ``appdata``
    :param handler: 接收 ProtocolRequest 并返回 ProtocolResponse 的同步函数
    :return: 构建时消费的协议描述符
    :raises ValueError: scheme 非法、保留或处理器为异步函数
    """
    _validate_scheme(name)
    if not callable(handler):
        raise ValueError("protocol handler must be callable")
    if inspect.iscoroutinefunction(handler):
        raise ValueError("protocol handlers must be synchronous")
    return _native.protocol_create(name, _serve(handler))
