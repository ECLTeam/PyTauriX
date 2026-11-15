from __future__ import annotations

from types import SimpleNamespace

import pytest
from anyio.from_thread import start_blocking_portal
from pytaurix import (
    Protocol,
    ProtocolRequest,
    ProtocolResponse,
    RangeRequest,
    create_protocol,
    file_range_response,
    parse_range,
)
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


def test_create_protocol_rejects_non_callable_handlers() -> None:
    with pytest.raises(ValueError, match="must be callable"):
        create_protocol("appdata", object())  # type: ignore[arg-type]


def test_create_protocol_requires_portal_for_async_handlers() -> None:
    async def handler(request: ProtocolRequest) -> ProtocolResponse:
        return ProtocolResponse()

    with pytest.raises(ValueError, match="require a blocking portal"):
        create_protocol("appdata", handler)
    with pytest.raises(ValueError, match=r"BlockingPortal\.call"):
        create_protocol("appdata", handler, portal=object())  # type: ignore[arg-type]


def test_create_protocol_accepts_async_handler_with_portal() -> None:
    async def handler(request: ProtocolRequest) -> ProtocolResponse:
        return ProtocolResponse(body=b"async")

    with start_blocking_portal("asyncio") as portal:
        protocol = create_protocol("appdata", handler, portal=portal)
    assert isinstance(protocol, Protocol)
    assert protocol.name == "appdata"


def test_serve_dispatches_async_handler_through_portal() -> None:
    seen: list[ProtocolRequest] = []

    async def handler(request: ProtocolRequest) -> ProtocolResponse:
        seen.append(request)
        return ProtocolResponse(status=200, body=b"from-async")

    with start_blocking_portal("asyncio") as portal:
        serve = _serve(handler, portal)
        status, headers, body = serve("appdata://localhost/a.txt", "GET", [], b"", "main")

    assert (status, headers, body) == (200, [], b"from-async")
    assert seen[0].uri == "appdata://localhost/a.txt"


def test_serve_portal_failure_becomes_exception() -> None:
    async def handler(request: ProtocolRequest) -> ProtocolResponse:
        return ProtocolResponse()

    portal = SimpleNamespace(call=lambda *args: (_ for _ in ()).throw(RuntimeError("portal stopped")))
    serve = _serve(handler, portal)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="portal stopped"):
        serve("appdata://localhost/", "GET", [], b"", "main")


def test_create_protocol_returns_unconsumed_descriptor() -> None:
    protocol = create_protocol("appdata", lambda request: ProtocolResponse(body=b"ok"))
    assert isinstance(protocol, Protocol)
    assert protocol.name == "appdata"
    assert protocol.consumed is False


def test_parse_range_supports_single_range_forms() -> None:
    assert parse_range("bytes=0-99") == RangeRequest(start=0, end=99, suffix=None)
    assert parse_range("bytes=100-") == RangeRequest(start=100, end=None, suffix=None)
    assert parse_range("bytes=-500") == RangeRequest(start=None, end=None, suffix=500)
    assert parse_range("BYTES=10-20") == RangeRequest(start=10, end=20, suffix=None)
    assert parse_range(None) is None


@pytest.mark.parametrize(
    "value",
    ["bytes=0-99,200-300", "items=0-99", "bytes=", "bytes=-", "bytes=a-b", "bytes=99-10", "bytes=1e3-", ""],
)
def test_parse_range_rejects_malformed_and_multi_range(value: str) -> None:
    assert parse_range(value) is None


def test_range_resolve_computes_bounded_intervals() -> None:
    assert RangeRequest(start=0, end=99).resolve(1000) == (0, 100)
    assert RangeRequest(start=990).resolve(1000) == (990, 10)
    assert RangeRequest(suffix=200).resolve(1000) == (800, 200)
    assert RangeRequest(suffix=5000).resolve(1000) == (0, 1000)
    assert RangeRequest(start=990, end=2000).resolve(1000) == (990, 10)


@pytest.mark.parametrize(
    "range_request",
    [RangeRequest(start=1000), RangeRequest(suffix=0), RangeRequest(start=999, end=5)],
)
def test_range_resolve_returns_none_for_unsatisfiable(range_request: RangeRequest) -> None:
    assert range_request.resolve(1000) is None
    assert range_request.resolve(0) is None


def test_request_range_reads_range_header() -> None:
    request = ProtocolRequest(
        uri="appdata://localhost/video.mp4",
        method="GET",
        headers=(("range", "bytes=100-199"),),
    )
    assert request.range == RangeRequest(start=100, end=199, suffix=None)
    assert ProtocolRequest(uri="appdata://localhost/", method="GET").range is None


def test_file_range_response_returns_full_body_without_range(tmp_path) -> None:
    target = tmp_path / "media.mp4"
    target.write_bytes(b"0123456789")

    response = file_range_response(target, "video/mp4")

    assert response.status == 200
    assert response.body == b"0123456789"
    assert ("content-type", "video/mp4") in response.headers
    assert ("accept-ranges", "bytes") in response.headers
    assert response.headers[-1][0] == "etag"


def test_file_range_response_returns_206_with_content_range(tmp_path) -> None:
    target = tmp_path / "media.mp4"
    target.write_bytes(b"0123456789")
    etag = file_range_response(target, "video/mp4").headers[-1][1]

    response = file_range_response(target, "video/mp4", range=RangeRequest(start=2, end=5))

    assert response.status == 206
    assert response.body == b"2345"
    assert ("content-range", "bytes 2-5/10") in response.headers
    assert ("etag", etag) in response.headers
    suffix_response = file_range_response(target, "video/mp4", range=RangeRequest(suffix=4))
    assert suffix_response.body == b"6789"
    assert ("content-range", "bytes 6-9/10") in suffix_response.headers


def test_file_range_response_falls_back_to_full_on_if_range_mismatch(tmp_path) -> None:
    target = tmp_path / "media.mp4"
    target.write_bytes(b"0123456789")
    etag = file_range_response(target, "video/mp4").headers[-1][1]

    stale = file_range_response(target, "video/mp4", range=RangeRequest(start=2), if_range='"file-stale"')
    assert stale.status == 200 and stale.body == b"0123456789"
    weak = file_range_response(target, "video/mp4", range=RangeRequest(start=2), if_range=f"W/{etag}")
    assert weak.status == 200
    matched = file_range_response(target, "video/mp4", range=RangeRequest(start=2), if_range=etag)
    assert matched.status == 206


def test_file_range_response_falls_back_to_full_when_unsatisfiable(tmp_path) -> None:
    target = tmp_path / "media.mp4"
    target.write_bytes(b"0123456789")

    response = file_range_response(target, "video/mp4", range=RangeRequest(start=100))

    assert response.status == 200
    assert response.body == b"0123456789"
