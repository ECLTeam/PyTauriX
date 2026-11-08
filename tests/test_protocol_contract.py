from __future__ import annotations

import pytest
from pytaurix import Protocol, ProtocolRequest, ProtocolResponse, create_protocol
from pytaurix.protocol import _serve, _validate_scheme


@pytest.mark.parametrize("name", ["appdata", "app-data", "app+data", "app.data", "app2"])
def test_valid_scheme_names(name: str) -> None:
    assert _validate_scheme(name) == name


@pytest.mark.parametrize(
    "name",
    ["", "AppData", "app data", "2app", "app/data", "app_data", "tauri", "asset", "http", "https", "ipc", "channel"],
)
def test_invalid_scheme_names_are_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="scheme must be lowercase ASCII"):
        _validate_scheme(name)


def test_scheme_length_limit() -> None:
    assert _validate_scheme("a" * 32) == "a" * 32
    with pytest.raises(ValueError):
        _validate_scheme("a" * 33)


def test_serve_builds_request_snapshot_and_tuple() -> None:
    seen: list[ProtocolRequest] = []

    def handler(request: ProtocolRequest) -> ProtocolResponse:
        seen.append(request)
        return ProtocolResponse(
            status=201,
            headers=(("content-type", "text/plain"), ("x-demo", "1")),
            body=b"ok",
        )

    serve = _serve(handler)
    status, headers, body = serve("appdata://localhost/a.txt", "GET", [("accept", "*/*")], b"payload", "main")

    assert (status, headers, body) == (201, [("content-type", "text/plain"), ("x-demo", "1")], b"ok")
    assert seen[0].uri == "appdata://localhost/a.txt"
    assert seen[0].method == "GET"
    assert seen[0].headers == (("accept", "*/*"),)
    assert seen[0].body == b"payload"
    assert seen[0].webview_label == "main"


def test_serve_rejects_non_response_values() -> None:
    serve = _serve(lambda request: "plain string")  # type: ignore[arg-type,return-value]
    with pytest.raises(TypeError, match="must return ProtocolResponse"):
        serve("appdata://localhost/", "GET", [], b"", "main")


def test_response_defaults_are_empty_ok() -> None:
    response = ProtocolResponse()
    assert (response.status, response.headers, response.body) == (200, (), b"")


def test_create_protocol_rejects_async_and_non_callable_handlers() -> None:
    async def handler(request: ProtocolRequest) -> ProtocolResponse:
        return ProtocolResponse()

    with pytest.raises(ValueError, match="must be synchronous"):
        create_protocol("appdata", handler)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be callable"):
        create_protocol("appdata", object())  # type: ignore[arg-type]


def test_create_protocol_returns_unconsumed_descriptor() -> None:
    protocol = create_protocol("appdata", lambda request: ProtocolResponse(body=b"ok"))
    assert isinstance(protocol, Protocol)
    assert protocol.name == "appdata"
    assert protocol.consumed is False
