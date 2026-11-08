from __future__ import annotations

import json
from typing import cast

import pytest
from pytaurix import AppHandle, CommandError, Commands, Request
from pytaurix._native import Request as NativeRequest


class _Handle:
    """最小请求替身：只提供注入路径与包装类读取的成员。"""

    def __init__(self, cancelled: bool = False) -> None:
        self.id = "session-1"
        self.cancelled = cancelled
        self.cancel_calls = 0

    def cancel(self) -> bool:
        self.cancel_calls += 1
        self.cancelled = True
        return True


def _request(cancelled: bool = False) -> NativeRequest:
    return cast(NativeRequest, _Handle(cancelled))


def test_request_injection_wraps_native_handle() -> None:
    commands = Commands()
    seen: dict[str, Request] = {}

    @commands.command()
    def ping(request: Request) -> str:
        seen["request"] = request
        return request.id

    invoke = commands.generate_handler()
    assert invoke("ping", "null", cast(AppHandle, object()), None, None, _request()) == '"session-1"'
    assert isinstance(seen["request"], Request)
    assert seen["request"].cancelled is False
    assert "session-1" in repr(seen["request"])


def test_cancellable_command_requires_request_identifier() -> None:
    commands = Commands()

    @commands.command()
    def ping(request: Request) -> str:
        return request.id

    with pytest.raises(CommandError) as failure:
        commands.generate_handler()("ping", "null", cast(AppHandle, object()))
    assert failure.value.code == "request_unavailable"


def test_request_cancel_delegates_to_native_handle() -> None:
    commands = Commands()
    handle = _Handle()

    @commands.command()
    def ping(request: Request) -> bool:
        assert request.cancelled is False
        return request.cancel()

    invoke = commands.generate_handler()
    assert invoke("ping", "null", cast(AppHandle, object()), None, None, cast(NativeRequest, handle)) == "true"
    assert handle.cancel_calls == 1


def test_command_observes_cancellation_before_completion() -> None:
    commands = Commands()

    @commands.command()
    def loop(request: Request) -> str:
        if request.cancelled:
            raise CommandError("cancelled", "Request was cancelled")
        return "done"

    with pytest.raises(CommandError) as failure:
        commands.generate_handler()("loop", "null", cast(AppHandle, object()), None, None, _request(True))
    assert failure.value.code == "cancelled"


def test_command_without_request_parameter_ignores_handle() -> None:
    commands = Commands()

    @commands.command()
    def plain(name: str) -> str:
        return name

    handle = _Handle()
    invoke = commands.generate_handler()
    result = invoke("plain", '{"name":"无常"}', cast(AppHandle, object()), None, None, cast(NativeRequest, handle))
    assert json.loads(result) == "无常"
    assert handle.cancel_calls == 0
