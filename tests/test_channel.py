from __future__ import annotations

import json
from typing import cast

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError
from pytaurix import AppHandle, BindingError, CommandError, Commands
from pytaurix.ffi.ipc import Channel as FfiChannel
from pytaurix.ffi.ipc import JavaScriptChannelId as FfiId
from pytaurix.ipc import Channel, JavaScriptChannelId


class Progress(BaseModel):
    completed: int


class Request(BaseModel):
    channel: JavaScriptChannelId[Progress]


@pytest.mark.parametrize("text", ["__CHANNEL__:0", "__CHANNEL__:4294967295", "__CHANNEL__:0007", "__CHANNEL__:+7"])
def test_native_and_model_channel_ids_round_trip(text: str) -> None:
    native = FfiId.from_str(text)
    model = Request.model_validate({"channel": text})
    assert isinstance(model.channel.root, FfiId)
    assert str(native) == text
    assert Request(channel=JavaScriptChannelId[Progress](native)).channel.root is native
    assert model.model_dump() == {"channel": text}
    assert json.loads(model.model_dump_json()) == {"channel": text}
    assert JavaScriptChannelId[Progress].model_validate_json(json.dumps(text)).model_dump() == text


@pytest.mark.parametrize(
    "value", [None, 1, True, {}, [], "", "7", "__CHANNEL__:-1", "__CHANNEL__:4294967296", "__CHANNEL__: 7"]
)
def test_invalid_id_becomes_model_validation_error(value: object) -> None:
    with pytest.raises(ValidationError):
        Request.model_validate({"channel": value})
    if isinstance(value, str):
        with pytest.raises(BindingError, match="invalid_channel_id"):
            JavaScriptChannelId[Progress].from_str(value)


def test_id_schema_is_json_string_and_native_instances_are_supported() -> None:
    schema = Request.model_json_schema()
    assert schema["$defs"]["JavaScriptChannelId_Progress_"]["type"] == "string"
    native = FfiId.from_str("__CHANNEL__:9")
    assert TypeAdapter(JavaScriptChannelId[Progress]).validate_python(native).root is native
    assert (
        TypeAdapter(JavaScriptChannelId[Progress]).dump_json(JavaScriptChannelId[Progress](native))
        == b'"__CHANNEL__:9"'
    )


def test_channel_id_command_supports_root_and_nested_models() -> None:
    commands = Commands()

    @commands.command()
    def nested(body: Request) -> str:
        return str(body.channel.root)

    @commands.command()
    def root(body: JavaScriptChannelId[Progress]) -> str:
        return str(body.root)

    handler = commands.generate_handler()
    handle = cast(AppHandle, object())
    assert handler("nested", '{"channel":"__CHANNEL__:13"}', handle) == '"__CHANNEL__:13"'
    assert handler("root", '"__CHANNEL__:13"', handle) == '"__CHANNEL__:13"'
    with pytest.raises(CommandError) as error:
        handler("nested", '{"channel":"bad"}', handle)
    assert error.value.code == "invalid_payload"


def test_public_handles_have_no_arbitrary_callback_constructor() -> None:
    for factory in (FfiId, FfiChannel):
        with pytest.raises(TypeError):
            factory()
    with pytest.raises(TypeError, match="native Channel"):
        Channel(cast(FfiChannel, object()))
