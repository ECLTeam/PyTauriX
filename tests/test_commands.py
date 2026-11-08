from __future__ import annotations

import json
from typing import cast

import anyio
import pytest
from anyio.from_thread import start_blocking_portal
from pydantic import BaseModel
from pytaurix import AppHandle, CommandError, Commands


class Person(BaseModel):
    name: str


class Greeting(BaseModel):
    message: str


def test_model_body_and_result_with_handle_injection() -> None:
    commands = Commands()
    handle = cast(AppHandle, object())

    @commands.command("greet")
    def handler(body: Person, app_handle: AppHandle) -> Greeting:
        assert app_handle is handle
        return Greeting(message=f"Hello {body.name}")

    invoke = commands.generate_handler()
    assert json.loads(invoke("greet", '{"name":"Python"}', handle)) == {"message": "Hello Python"}


def test_named_parameters_defaults_and_unchanged_function() -> None:
    commands = Commands()

    def add(left: int, right: int = 2) -> int:
        return left + right

    assert commands.command()(add) is add
    assert commands.generate_handler()("add", '{"left":3}', cast(AppHandle, object())) == "5"


@pytest.mark.parametrize("payload", ["{}", '"invalid"', '{"name":null}', "{"])
def test_invalid_model_payload_returns_stable_error(payload: str) -> None:
    commands = Commands()

    @commands.command()
    def greet(body: Person) -> str:
        return body.name

    with pytest.raises(CommandError) as failure:
        commands.generate_handler()("greet", payload, cast(AppHandle, object()))
    assert failure.value.code == "invalid_payload"


def test_command_failure_is_safe_and_does_not_break_next_call() -> None:
    commands = Commands()

    @commands.command()
    def fail() -> None:
        raise TypeError("private token must not escape")

    @commands.command()
    def ping() -> str:
        return "pong"

    invoke = commands.generate_handler()
    handle = cast(AppHandle, object())
    with pytest.raises(CommandError) as failure:
        invoke("fail", "null", handle)
    assert failure.value.code == "command_failed"
    assert "private token" not in str(failure.value)
    assert invoke("ping", "null", handle) == '"pong"'


def test_duplicate_registration_and_snapshot() -> None:
    commands = Commands()

    @commands.command()
    def first() -> int:
        return 1

    invoke = commands.generate_handler()
    with pytest.raises(CommandError, match="already registered"):
        commands.command()(first)

    @commands.command()
    def later() -> int:
        return 2

    with pytest.raises(CommandError) as failure:
        invoke("later", "null", cast(AppHandle, object()))
    assert failure.value.code == "unknown_command"


def test_unknown_parameter_cannot_override_injected_handle() -> None:
    commands = Commands()

    @commands.command()
    def greet(name: str, app_handle: AppHandle) -> str:
        return name

    with pytest.raises(CommandError) as failure:
        commands.generate_handler()("greet", '{"name":"x","app_handle":null}', cast(AppHandle, object()))
    assert failure.value.code == "invalid_payload"


def test_async_portal_supports_models() -> None:
    commands = Commands()

    @commands.command()
    async def greet(body: Person) -> Greeting:
        await anyio.sleep(0)
        return Greeting(message=body.name)

    with start_blocking_portal() as portal:
        invoke = commands.generate_handler(portal)
        assert json.loads(invoke("greet", '{"name":"async"}', cast(AppHandle, object()))) == {"message": "async"}


def test_async_without_portal_closes_coroutine() -> None:
    commands = Commands()

    @commands.command()
    async def ping() -> str:
        return "pong"

    with pytest.raises(CommandError) as failure:
        commands.generate_handler()("ping", "null", cast(AppHandle, object()))
    assert failure.value.code == "async_runtime_required"


@pytest.mark.parametrize("result", [object(), float("nan")])
def test_invalid_response_is_reported(result: object) -> None:
    commands = Commands()

    @commands.command()
    def bad() -> object:
        return result

    with pytest.raises(CommandError) as failure:
        commands.generate_handler()("bad", "null", cast(AppHandle, object()))
    assert failure.value.code == "invalid_response"


def test_mixed_body_parameters_rejected_at_registration() -> None:
    commands = Commands()

    def bad(body: Person, other: int) -> None:
        pass

    with pytest.raises(CommandError) as failure:
        commands.command()(bad)
    assert failure.value.code == "invalid_signature"
