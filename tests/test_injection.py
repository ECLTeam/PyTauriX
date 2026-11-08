from __future__ import annotations

import json
from typing import Annotated, cast

import pytest
from pytaruix import AppHandle, CommandError, Commands, Headers, State, WebviewWindow


class Shared:
    def __init__(self) -> None:
        self.calls = 0


class Handle:
    def __init__(self, shared: Shared | None) -> None:
        self.shared = shared

    def try_state(self, state_type: type[object]) -> object | None:
        assert state_type is Shared
        return self.shared


def test_state_markers_and_authoritative_context() -> None:
    commands = Commands()
    shared = Shared()
    handle = cast(AppHandle, Handle(shared))
    window = cast(WebviewWindow, object())
    headers: Headers = [(b"x-test", b"first"), (b"x-test", b"second")]

    @commands.command()
    def probe(
        name: str,
        app: AppHandle,
        source: WebviewWindow,
        request: Headers,
        direct: Annotated[Shared, State()],
        wrapped: State[Shared],
    ) -> int:
        assert direct is wrapped.value is shared
        assert app is handle and source is window
        assert request == headers
        request.append((b"new", b"value"))
        direct.calls += 1
        return direct.calls

    invoke = commands.generate_handler()
    assert invoke("probe", '{"name":"a"}', handle, window, headers) == "1"
    assert invoke("probe", b'{"name":"b"}', handle, window, headers) == "2"
    assert len(headers) == 2
    for field in ("app", "source", "request", "direct", "wrapped"):
        with pytest.raises(CommandError) as error:
            invoke("probe", json.dumps({"name": "a", field: None}), handle, window, headers)
        assert error.value.code == "invalid_payload"


def test_missing_state_cannot_fall_back_to_untrusted_payload() -> None:
    commands = Commands()

    @commands.command()
    def probe(shared: State[Shared]) -> int:
        return shared.value.calls

    with pytest.raises(CommandError) as error:
        commands.generate_handler()("probe", '{"shared":{}}', cast(AppHandle, Handle(None)))
    assert error.value.code == "state_missing"


def test_origin_is_required_for_window_injection() -> None:
    commands = Commands()

    @commands.command()
    def probe(window: WebviewWindow) -> str:
        return window.label()

    with pytest.raises(CommandError) as error:
        commands.generate_handler()("probe", "null", cast(AppHandle, object()))
    assert error.value.code == "invalid_window"


def test_raw_bytes_and_json_scalars() -> None:
    commands = Commands()

    @commands.command()
    def raw(body: bytes) -> bytes:
        return body[::-1]

    @commands.command()
    def scalar(body: int) -> int:
        return body + 1

    @commands.command()
    def empty() -> str:
        return "ok"

    invoke = commands.generate_handler()
    handle = cast(AppHandle, object())
    assert invoke("raw", b"\xff\x00\x01", handle) == b"\x01\x00\xff"
    assert invoke("scalar", b"5", handle) == "6"
    assert invoke("empty", b"", handle) == '"ok"'
    with pytest.raises(CommandError) as error:
        invoke("scalar", b"\xff", handle)
    assert error.value.code == "invalid_payload"


def test_managed_state_requires_a_concrete_type() -> None:
    commands = Commands()

    def bad(state: State[list[str]]) -> None:
        pass

    with pytest.raises(CommandError) as error:
        commands.command()(bad)
    assert error.value.code == "invalid_signature"
