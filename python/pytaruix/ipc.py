# ============================================================
# PytaruiX
# 文件作用：注册命令、注入受信上下文并提供 JSON/字节协议及原生通道。
# 公开接口：Commands、State、Headers、Request、WebviewWindow、JsonValue、JavaScriptChannelId、Channel。
# ============================================================
from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Generic, Self, TypeAlias, TypeVar, get_args, get_origin, get_type_hints

from anyio.from_thread import BlockingPortal
from pydantic import (
    BaseModel,
    BeforeValidator,
    InstanceOf,
    PlainSerializer,
    RootModel,
    TypeAdapter,
    ValidationError,
    WithJsonSchema,
)
from pydantic_core import to_jsonable_python

from .application import InvokeHandler
from .errors import BindingError, CommandError
from .ffi import AppHandle, Webview, WebviewWindow
from .ffi.ipc import Channel as FfiChannel
from .ffi.ipc import JavaScriptChannelId as FfiJavaScriptChannelId
from .ffi.ipc import Request as FfiRequest

__all__ = ["Channel", "Commands", "Headers", "JavaScriptChannelId", "JsonValue", "Request", "State", "WebviewWindow"]

ModelType = TypeVar("ModelType", bound=BaseModel)


def _channel_id(value: object) -> FfiJavaScriptChannelId:
    if isinstance(value, FfiJavaScriptChannelId):
        return value
    if not isinstance(value, str):
        raise ValueError("Channel ID must be a string or native JavaScriptChannelId")
    try:
        return FfiJavaScriptChannelId.from_str(value)
    except BindingError as error:
        raise ValueError("Invalid JavaScript channel ID") from error


ChannelIdValue = Annotated[
    InstanceOf[FfiJavaScriptChannelId],
    BeforeValidator(_channel_id),
    PlainSerializer(str, return_type=str),
    WithJsonSchema({"type": "string", "pattern": "^__CHANNEL__:[+]?[0-9]+$"}),
]


class JavaScriptChannelId(RootModel[ChannelIdValue], Generic[ModelType]):
    """
    在 Pydantic 模型字段或根模型中接收原生前端 Channel 标识。

    校验前缀和 u32 编号；标识不证明 JS 回调存在，也不是授权凭证。
    """

    @classmethod
    def from_str(cls, value: str, /) -> Self:
        """
        解析 Channel 标识；无效文本返回原生 invalid_channel_id 错误。
        """
        return cls(FfiJavaScriptChannelId.from_str(value))

    def channel_on(self, webview: Webview, /, *, capacity: int = 0) -> Channel[ModelType]:
        """
        绑定指定活跃 Webview 代次，可在工作线程调用，销毁后返回 window_closed。

        :param webview: 现有窗口引用
        :param capacity: 流控容量；0 表示不限制，大于 0 时要求前端用
            ``pytaruix.createChannel`` 归还配额
        :raises ValueError: capacity 为负数
        """
        if capacity < 0:
            raise ValueError("capacity must not be negative")
        return Channel(self.root.channel_on(webview, capacity=capacity))


class Request:
    """
    命令可注入的请求句柄，用于协作式取消。

    取消只拒绝前端 Promise 并把 ``cancelled`` 置为真；同步 Python 代码无法被中断，
    命令需自行检查标志并在安全点返回。句柄不证明调用方已获授权。
    """

    def __init__(self, ffi_request: FfiRequest, /) -> None:
        self._ffi_request = ffi_request

    @property
    def id(self) -> str:
        """
        取得前端提交的请求编号；取消后仍可读取。
        """
        return self._ffi_request.id

    @property
    def cancelled(self) -> bool:
        """
        查询是否已取消；可在工作线程读取。
        """
        return self._ffi_request.cancelled

    def cancel(self) -> bool:
        """
        主动取消并立即拒绝前端 Promise；已应答时返回 False。

        可在工作线程调用；不中断正在执行的同步命令。
        """
        return self._ffi_request.cancel()

    def __repr__(self) -> str:
        return f"Request(id={self.id!r}, cancelled={self.cancelled!r})"


class Channel(Generic[ModelType]):
    """
    原生发送句柄的类型化包装，支持工作线程、显式关闭和最后引用释放。

    发送成功只表示原生接受提交，不确认前端处理。``capacity > 0`` 的通道按配额发送，
    配额由前端 ``pytaruix.createChannel`` 归还；直接构造 ``Channel`` 的前端不得启用配额。
    """

    def __init__(self, ffi_channel: FfiChannel, /) -> None:
        if not isinstance(ffi_channel, FfiChannel):
            raise TypeError("Channel requires a native Channel")
        self._ffi_channel = ffi_channel

    def id(self, /) -> int:
        """
        取得前端回调编号；关闭后仍可读取编号。
        """
        return self._ffi_channel.id()

    def send(self, data: str | bytes, /, *, timeout: float | None = None) -> None:
        """
        发送有效原始 JSON 文本或 ArrayBuffer 字节；原生发送释放 GIL。

        :param data: JSON 文本或二进制载荷
        :param timeout: 启用流控时的等待秒数；省略表示等到配额或通道关闭
        :raises BindingError: invalid_json、channel_closed、window_closed、app_closed、
            channel_backpressure 或 channel_failed
        :raises TypeError: 载荷不是 str/bytes
        :raises ValueError: timeout 为负数或非有限值
        """
        self._ffi_channel.send(data, timeout=timeout)

    def send_model(self, model: ModelType, /) -> None:
        """
        将 Pydantic 模型编码一次后发送；非模型拒绝，编码错误由 Pydantic 归还。
        """
        if not isinstance(model, BaseModel):
            raise TypeError("send_model requires a Pydantic BaseModel")
        self.send(model.model_dump_json())

    def close(self) -> None:
        """
        幂等结束通道，释放原生句柄并提交终止帧；不等待前端确认。
        """
        self._ffi_channel.close()

    @property
    def closed(self) -> bool:
        """
        查询显式关闭或所属窗口/应用失效状态。
        """
        return self._ffi_channel.closed

    @property
    def pending(self) -> int:
        """
        查询尚未归还的流控配额；未启用流控时恒为 0。
        """
        return self._ffi_channel.pending


JsonValue: TypeAlias = bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"] | None
Handler = Callable[..., object]
HandlerType = TypeVar("HandlerType", bound=Handler)
StateType = TypeVar("StateType")


class State(Generic[StateType]):
    """
    标记受管理的状态，兼容 Annotated[T, State()]，也支持 State[T].value。

    状态按具体 Python 类型注册，注入共享原对象，不复制、不由请求载荷覆盖。
    调用方负责对象内部的并发控制；标记对象本身没有状态值。
    """

    def __init__(self, value: StateType | None = None) -> None:
        self._value = value

    @property
    def value(self) -> StateType:
        """
        取得 State[T] 注入的原始共享对象。

        :return: 共享对象
        :raises CommandError: 对声明标记访问状态值
        """
        if self._value is None:
            raise CommandError("state_missing", "State marker has no managed value")
        return self._value


@dataclass(frozen=True, slots=True)
class _HeadersMarker:
    pass


Headers: TypeAlias = Annotated[list[tuple[bytes, bytes]], _HeadersMarker()]


@dataclass(frozen=True, slots=True)
class _Command:
    handler: Handler
    signature: inspect.Signature
    adapter_by_parameter: dict[str, TypeAdapter[object]]
    injection_by_parameter: dict[str, str]
    state_by_parameter: dict[str, tuple[type[object], bool]]
    raw_body: bool


async def _await_result(result: Awaitable[object]) -> object:
    return await result


def _state_annotation(annotation: object) -> tuple[type[object], bool] | None:
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is State:
        if len(arguments) != 1 or not isinstance(arguments[0], type):
            raise CommandError("invalid_signature", "State requires a concrete Python type")
        return arguments[0], True
    if origin is Annotated and any(isinstance(marker, State) for marker in arguments[1:]):
        if not isinstance(arguments[0], type):
            raise CommandError("invalid_signature", "Managed state requires a concrete Python type")
        return arguments[0], False
    return None


class Commands:
    """
    保存命令注册表，生成处理器时固定快照。

    支持模型/命名参数、原始 bytes body、受信窗口/句柄/请求头/共享状态注入和 AnyIO portal。
    """

    def __init__(self) -> None:
        self._command_by_name: dict[str, _Command] = {}

    def command(self, name: str | None = None) -> Callable[[HandlerType], HandlerType]:
        """
        注册有明确参数类型的命令，拒绝重复命令和无法注入的签名。

        :param name: 名称，省略时使用函数名称
        :return: 保留原函数的装饰器
        :raises CommandError: 名称或签名不支持
        """

        def register(handler: HandlerType) -> HandlerType:
            command_name = name if name is not None else handler.__name__
            if not command_name or command_name in self._command_by_name:
                raise CommandError("invalid_command", "Command name is empty or already registered")
            signature = inspect.signature(handler)
            hints = get_type_hints(handler, include_extras=True)
            adapters: dict[str, TypeAdapter[object]] = {}
            injections: dict[str, str] = {}
            states: dict[str, tuple[type[object], bool]] = {}
            raw_body = False
            for parameter_name, parameter in signature.parameters.items():
                if parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD, parameter.POSITIONAL_ONLY}:
                    raise CommandError("invalid_signature", "Command parameters must accept keyword arguments")
                annotation = hints.get(parameter_name)
                state = _state_annotation(annotation)
                if state is not None:
                    states[parameter_name] = state
                elif annotation is AppHandle:
                    injections[parameter_name] = "app_handle"
                elif annotation is WebviewWindow:
                    injections[parameter_name] = "webview_window"
                elif annotation is Request:
                    injections[parameter_name] = "request"
                elif get_origin(annotation) is Annotated and any(
                    isinstance(marker, _HeadersMarker) for marker in get_args(annotation)[1:]
                ):
                    injections[parameter_name] = "headers"
                elif annotation is None:
                    raise CommandError("invalid_signature", "Command parameters require type annotations")
                else:
                    adapters[parameter_name] = TypeAdapter(annotation)
                    raw_body = raw_body or (parameter_name == "body" and annotation is bytes)
            if "body" in adapters and len(adapters) != 1:
                raise CommandError("invalid_signature", "body cannot be combined with other payload parameters")
            self._command_by_name[command_name] = _Command(handler, signature, adapters, injections, states, raw_body)
            return handler

        return register

    def generate_handler(self, portal: BlockingPortal | None = None) -> InvokeHandler:
        """
        创建供原生工作线程调用的 JSON/字节处理器。

        参数来源和注入值由原生 Tauri 提供；portal 需在应用运行期间保持开放。
        bytes body 保留请求原文，bytes 返回值形成 ArrayBuffer；其他结果进行 JSON 序列化。
        声明 ``Request`` 参数的命令拿到请求句柄，没有前端编号时返回 request_unavailable。

        :param portal: 异步命令后台入口
        :return: 固定注册快照的处理器
        """
        commands = dict(self._command_by_name)

        def invoke(
            command_name: str,
            payload_json: str | bytes,
            app_handle: AppHandle,
            webview_window: WebviewWindow | None = None,
            headers: Headers | None = None,
            legacy: bool = False,
            request: FfiRequest | None = None,
        ) -> str | bytes:
            command = commands.get(command_name)
            if command is None:
                raise CommandError("unknown_command", "Command is not registered")
            arguments: dict[str, object] = {}
            for name, injection in command.injection_by_parameter.items():
                if injection == "app_handle":
                    arguments[name] = app_handle
                elif injection == "headers":
                    arguments[name] = list(headers or [])
                elif injection == "request":
                    if request is None:
                        raise CommandError(
                            "request_unavailable",
                            "Cancellable commands require a request identifier",
                        )
                    arguments[name] = Request(request)
                else:
                    if webview_window is None:
                        raise CommandError("invalid_window", "Originating WebviewWindow is unavailable")
                    arguments[name] = webview_window
            for name, (state_type, wrapped) in command.state_by_parameter.items():
                state = app_handle.try_state(state_type)
                if state is None:
                    raise CommandError("state_missing", "Required managed state is not registered")
                arguments[name] = State(state) if wrapped else state
            try:
                if command.raw_body:
                    arguments["body"] = payload_json.encode("utf-8") if isinstance(payload_json, str) else payload_json
                else:
                    # 旧客户端省略正文时发送空请求；没有模型正文时等价 null。
                    payload: JsonValue = json.loads(payload_json) if payload_json else None
                    if "body" in command.adapter_by_parameter:
                        arguments["body"] = command.adapter_by_parameter["body"].validate_python(payload)
                    else:
                        if payload is None:
                            payload = {}
                        if not isinstance(payload, dict):
                            raise CommandError("invalid_payload", "Named command parameters require an object")
                        if payload.keys() - command.adapter_by_parameter.keys():
                            raise CommandError("invalid_payload", "Payload contains unknown parameters")
                        for name, adapter in command.adapter_by_parameter.items():
                            if name in payload:
                                arguments[name] = adapter.validate_python(payload[name])
                bound = command.signature.bind(**arguments)
                bound.apply_defaults()
            except CommandError:
                raise
            except (ValidationError, ValueError, TypeError) as error:
                raise CommandError("invalid_payload", "Command parameters are invalid") from error
            try:
                result = command.handler(*bound.args, **bound.kwargs)
                if inspect.isawaitable(result):
                    if portal is None:
                        if inspect.iscoroutine(result):
                            result.close()
                        raise CommandError("async_runtime_required", "Async commands require an open AnyIO portal")
                    result = portal.call(_await_result, result)
            except CommandError:
                raise
            except Exception as error:
                raise CommandError("command_failed", "Python command failed") from error
            if isinstance(result, bytes):
                return result
            try:
                return json.dumps(to_jsonable_python(result), allow_nan=False)
            except (ValueError, TypeError) as error:
                raise CommandError("invalid_response", "Command result is not JSON serializable") from error

        return invoke
