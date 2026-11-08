from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import cast

import pytest
from pytaruix import BindingError, NewWindowResponse, PermissionResponse, WebResourceResponse
from pytaruix.manager import ManagerType
from pytaruix.webview import WebviewWindowBuilder, WebviewWindowBuilderArgs
from pytaruix.webview_requests import _decision, _response_parts


def test_response_copies_headers_and_preserves_duplicate_binary_values() -> None:
    fields = [["x-test", b"one"], ["x-test", b"\xff"]]
    response = WebResourceResponse(201, cast(tuple[tuple[str, bytes], ...], fields), b"\x00payload")
    fields[0][1] = b"changed"
    assert response.headers == (("x-test", b"one"), ("x-test", b"\xff"))
    assert _response_parts(response) == (201, response.headers, b"\x00payload")
    with pytest.raises(FrozenInstanceError):
        response.status = 500  # type: ignore[misc]


@pytest.mark.parametrize(
    "status,headers,body",
    [
        (True, (), b""),
        (99, (), b""),
        (600, (), b""),
        (200, (), "text"),
        (200, (("x-test", "text"),), b""),
        (200, (("bad name", b"ok"),), b""),
        (200, (("x-test", b"ok\r\ninjected: yes"),), b""),
        (200, (("x-test", b"\x00"),), b""),
        (200, (("x-test", b"\x7f"),), b""),
        (200, (("x-test",),), b""),
    ],
)
def test_response_rejects_invalid_http_boundaries(status: object, headers: object, body: object) -> None:
    with pytest.raises(BindingError, match="invalid_response"):
        WebResourceResponse(cast(int, status), cast(tuple[tuple[str, bytes], ...], headers), cast(bytes, body))


def test_response_revalidates_before_native_submission() -> None:
    response = WebResourceResponse(200, (), b"ok")
    object.__setattr__(response, "headers", (("x-test", b"bad\n"),))
    with pytest.raises(BindingError, match="invalid_response"):
        _response_parts(response)


@pytest.mark.parametrize("value", [True, "allow", None, PermissionResponse.Allow])
def test_new_window_does_not_accept_truthy_or_wrong_decision_types(value: object) -> None:
    with pytest.raises(BindingError, match="invalid_callback"):
        _decision(value, "new_window")


def test_decisions_keep_default_distinct_from_allow() -> None:
    assert _decision(NewWindowResponse.Deny, "new_window") == "deny"
    assert _decision(PermissionResponse.Default, "permission") == "default"
    with pytest.raises(BindingError, match="invalid_callback"):
        _decision(NewWindowResponse.Allow, "permission")


@pytest.mark.parametrize("key", ["on_new_window", "on_permission_request", "on_web_resource_request"])
def test_builder_validates_policy_before_native_creation(key: str) -> None:
    with pytest.raises(BindingError, match="invalid_callback"):
        WebviewWindowBuilder._build(
            cast(ManagerType, object()),
            {"label": "policy", "url": "index.html"},
            cast(WebviewWindowBuilderArgs, {key: True}),
        )


@pytest.mark.parametrize("directory", [None, "relative", Path("relative")])
def test_data_directory_requires_explicit_absolute_path(directory: object) -> None:
    with pytest.raises(BindingError, match="invalid_window_config"):
        WebviewWindowBuilder._build(
            cast(ManagerType, object()),
            {"label": "policy", "url": "index.html"},
            cast(WebviewWindowBuilderArgs, {"data_directory": directory}),
        )
