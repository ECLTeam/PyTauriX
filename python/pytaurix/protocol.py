# ============================================================
# PyTauriX
# 文件作用：注册自定义 URI scheme 协议，并把请求/响应快照转换为原生形状。
# 公开接口：Protocol、ProtocolRequest、ProtocolResponse、RangeRequest、
#           parse_range、file_range_response、create_protocol。
# ============================================================
from __future__ import annotations

import inspect
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import _native

if TYPE_CHECKING:
    from anyio.from_thread import BlockingPortal

__all__ = [
    "Protocol",
    "ProtocolRequest",
    "ProtocolResponse",
    "RangeRequest",
    "create_protocol",
    "file_range_response",
    "parse_range",
]

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

    @property
    def range(self) -> RangeRequest | None:
        """
        解析请求头中的单个 ``Range`` 范围，供大文件与媒体流响应使用。

        :return: 单范围解析结果；缺失、多范围或畸形头归一为 ``None``
        """
        for name, value in self.headers:
            if name.lower() == "range":
                return parse_range(value)
        return None


@dataclass(frozen=True, slots=True)
class ProtocolResponse:
    """
    协议响应；状态码或头字段非法时原生归还空 500。

    头字段按顺序追加，允许同名多次出现；正文按字节返回，不做编码转换。
    上游 Tauri 2.12.1 的自定义协议响应体只支持一次性字节，不提供流式交付；
    大文件按 ``Range`` 逐块请求、每次返回一块，见 ``file_range_response``。
    """

    status: int = 200
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes = b""


# 处理器返回同步响应，或（提供 portal 的协程处理器）经调度返回响应。
ProtocolHandlerResult = ProtocolResponse | Coroutine[Any, Any, ProtocolResponse]
ProtocolHandler = Callable[[ProtocolRequest], ProtocolHandlerResult]


@dataclass(frozen=True, slots=True)
class RangeRequest:
    """
    单范围 ``Range`` 请求的解析结果。

    ``start``/``end`` 描述 ``bytes=A-B`` 或 ``bytes=A-``（``end`` 为包含值），
    ``suffix`` 描述 ``bytes=-N``；三者互斥，其余字段为 ``None``。
    """

    start: int | None = None
    end: int | None = None
    suffix: int | None = None

    def resolve(self, total_size: int) -> tuple[int, int] | None:
        """
        计算可交付的字节区间。

        :param total_size: 资源总字节数；非正数视为空资源
        :return: ``(start, length)``；空资源、``suffix`` 非正或 ``start``
            越界时返回 ``None``，调用方应回退全量 200 响应
        """
        if total_size <= 0:
            return None
        if self.suffix is not None:
            if self.suffix <= 0:
                return None
            length = min(self.suffix, total_size)
            return (total_size - length, length)
        start = self.start or 0
        if start >= total_size:
            return None
        if self.end is None:
            return (start, total_size - start)
        end = min(self.end, total_size - 1)
        if end < start:
            return None
        return (start, end - start + 1)


def parse_range(header_value: str | None) -> RangeRequest | None:
    """
    解析 ``Range`` 请求头为单范围结构。

    仅支持字节单位下的 ``bytes=A-B``、``bytes=A-`` 与 ``bytes=-N`` 三种形态；
    多范围请求按 RFC 7233 属于可选能力，明确拒绝并归一为 ``None``，
    由调用方回退全量响应，不做部分降级。

    :param header_value: 请求头原始值；缺失时为 ``None``
    :return: 解析结果；无法解析为合法单范围时返回 ``None``
    """
    if header_value is None:
        return None
    unit, separator, spec = header_value.strip().partition("=")
    if not separator or unit.strip().lower() != "bytes" or "," in spec:
        return None
    spec = spec.strip()
    if not spec:
        return None
    dash = spec.find("-")
    if dash < 0:
        return None
    left, right = spec[:dash].strip(), spec[dash + 1 :].strip()
    if not right:
        if not left.isdigit():
            return None
        return RangeRequest(start=int(left), end=None, suffix=None)
    if not left:
        if not right.isdigit():
            return None
        return RangeRequest(start=None, end=None, suffix=int(right))
    if not (left.isdigit() and right.isdigit()):
        return None
    start, end = int(left), int(right)
    if start > end:
        return None
    return RangeRequest(start=start, end=end, suffix=None)


def _file_etag(stat_result: object) -> str:
    # 由文件修改时间与大小生成强校验 ETag；文件被替换后缓存自然失效。
    return f'"file-{stat_result.st_mtime_ns:x}-{stat_result.st_size:x}"'  # type: ignore[attr-defined]


def _if_range_satisfied(if_range: str | None, etag: str) -> bool:
    # If-Range 只支持 ETag 强比较：弱 ETag 与日期形态均按不匹配处理并回退全量。
    return if_range is None or if_range.strip() == etag


def file_range_response(
    path: Path,
    mime: str,
    *,
    range: RangeRequest | None = None,
    if_range: str | None = None,
) -> ProtocolResponse:
    """
    从文件构建媒体流协议响应，支持 ``Range``/``If-Range`` 协商。

    ``range`` 缺失、``If-Range`` 不匹配或区间不可满足时回退全量 200 响应；
    可满足时返回 206 与 ``Content-Range``。全量回退会读取整个文件，调用方
    应把该助手用于能被 WebView 按 Range 逐块请求的场景。文件缺失等
    ``OSError`` 向上传播，由原生按协议约定归还空 500。

    :param path: 只读文件路径
    :param mime: 响应 ``Content-Type``
    :param range: 已解析的范围；缺失时为 ``None``
    :param if_range: 请求头 ``If-Range`` 原始值；缺失时为 ``None``
    :return: 200 全量或 206 分块的响应快照
    """
    stat_result = path.stat()
    etag = _file_etag(stat_result)
    headers = [("content-type", mime), ("accept-ranges", "bytes"), ("etag", etag)]
    resolved = range.resolve(stat_result.st_size) if range is not None else None
    if range is None or not _if_range_satisfied(if_range, etag) or resolved is None:
        return ProtocolResponse(status=200, headers=tuple(headers), body=path.read_bytes())
    start, length = resolved
    with path.open("rb") as handle:
        handle.seek(start)
        body = handle.read(length)
    headers.append(("content-range", f"bytes {start}-{start + length - 1}/{stat_result.st_size}"))
    return ProtocolResponse(status=206, headers=tuple(headers), body=body)


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
    handler: ProtocolHandler,
    portal: BlockingPortal | None = None,
) -> Callable[..., tuple[int, list[tuple[str, str]], bytes]]:
    """
    把处理函数包装为原生调用形状；返回值类型错误抛 TypeError。

    提供 portal 时处理器可为协程函数，经 portal 在其事件循环上调度并阻塞
    等待完成；阻塞等待发生在 Rust 提供的阻塞工作线程，不占用 GUI 线程。
    portal 关闭后到达的请求以异常结束，由原生归还空 500。
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
        if portal is None:
            response = handler(request)
        else:
            response = portal.call(handler, request)
        if not isinstance(response, ProtocolResponse):
            raise TypeError("protocol handler must return ProtocolResponse")
        return response.status, list(response.headers), bytes(response.body)

    return serve


def create_protocol(
    name: str,
    handler: ProtocolHandler,
    *,
    portal: BlockingPortal | None = None,
) -> Protocol:
    """
    创建一次性协议描述符，交给 ``Builder.build(protocols=...)`` 登记。

    处理器接收 ``ProtocolRequest`` 并返回 ``ProtocolResponse``。同步处理器
    在阻塞工作线程执行，GUI 线程不等待；协程函数必须显式提供由
    ``start_blocking_portal`` 创建的 portal，经其事件循环调度并阻塞等待，
    与命令桥的 portal 设施一致。请求不可取消：连接提前断开时协程仍执行
    完毕，最终响应由原生丢弃。处理异常由原生转换为空 500，不向前端泄露
    堆栈。

    :param name: ASCII 小写 scheme，例如 ``appdata``
    :param handler: 同步处理器，或提供 portal 时的协程处理器
    :param portal: 协程处理器依赖的阻塞 portal；同步处理器可省略
    :return: 构建时消费的协议描述符
    :raises ValueError: scheme 非法或保留、处理器不可调用、协程处理器
        缺少 portal、portal 形状不符时抛出
    """
    _validate_scheme(name)
    if not callable(handler):
        raise ValueError("protocol handler must be callable")
    is_async = inspect.iscoroutinefunction(handler)
    if is_async and portal is None:
        raise ValueError("asynchronous protocol handlers require a blocking portal")
    if portal is not None and not callable(getattr(portal, "call", None)):
        raise ValueError("portal must provide a BlockingPortal.call method")
    active_portal = portal if is_async else None
    return _native.protocol_create(name, _serve(handler, active_portal))
