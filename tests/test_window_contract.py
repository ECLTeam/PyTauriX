# ============================================================
# PyTauriX
# 文件作用：验证 URL、RGBA 数据、单位类型与回调载荷的边界契约。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from pytaurix import BindingError, PageLoadEvent, WebviewUrl, WindowEvent
from pytaurix.dpi import LogicalPosition, LogicalSize, PhysicalPosition, PhysicalSize
from pytaurix.events import _page_load, _window_event
from pytaurix.ffi.image import Image
from pytaurix.manager import ManagerType
from pytaurix.webview import WebviewWindowBuilder, WebviewWindowBuilderArgs


@pytest.mark.parametrize(
    "path", ["../secret", "/root", r"C:\root", "https://example.com", "%2e%2e/secret", "a/../../b"]
)
def test_app_url_cannot_escape_assets(path: str) -> None:
    with pytest.raises(BindingError, match="invalid_url"):
        WebviewUrl.App(path)


def test_url_variants_and_paths() -> None:
    assert WebviewUrl.App(Path("views") / "settings.html").path == "views/settings.html"
    assert WebviewUrl.App("index.html?view=settings#top").path == "index.html?view=settings#top"
    assert WebviewUrl.External("https://example.com/page").url == "https://example.com/page"


@pytest.mark.parametrize("url", ["file:///private", "javascript:alert(1)", "https:///missing", "relative.html"])
def test_external_url_requires_http_origin(url: str) -> None:
    with pytest.raises(BindingError, match="invalid_url"):
        WebviewUrl.External(url)


@pytest.mark.parametrize("rgba,width,height", [(b"", 0, 1), (b"", 1, 0), (b"abc", 1, 1), (b"", 2**32 - 1, 2**32 - 1)])
def test_image_rejects_inconsistent_or_overflowing_data(rgba: bytes, width: int, height: int) -> None:
    with pytest.raises(BindingError, match="invalid_image"):
        Image(rgba, width, height)


def test_image_owns_rgba_and_has_readonly_dimensions() -> None:
    image = Image(bytes([10, 20, 30, 255]), 1, 1)
    assert (image.width, image.height, image.rgba) == (1, 1, bytes([10, 20, 30, 255]))
    with pytest.raises(AttributeError):
        object.__setattr__(image, "width", 3)


@pytest.mark.parametrize("width,height", [(0, 1), (-1, 2), (float("nan"), 2), (2, float("inf"))])
def test_logical_dimensions_are_positive_and_finite(width: float, height: float) -> None:
    with pytest.raises(BindingError, match="invalid_size"):
        LogicalSize(width, height)


def test_geometry_preserves_units_and_signed_coordinates() -> None:
    assert (LogicalSize(12.5, 8).width, PhysicalSize(20, 10).width) == (12.5, 20)
    assert (LogicalPosition(-1.5, 8).x, PhysicalPosition(-20, 10).x) == (-1.5, -20)
    with pytest.raises(BindingError, match="invalid_size"):
        PhysicalSize(0, 2)
    with pytest.raises(BindingError, match="invalid_position"):
        LogicalPosition(float("inf"), 0)


def test_minimized_resize_event_can_contain_zero_dimensions() -> None:
    event = _window_event("resized", "[0,0]", None)
    assert isinstance(event, WindowEvent.Resized)
    assert (event.size.width, event.size.height) == (0, 0)
    moved = _window_event("moved", "[-20,10]", None)
    assert isinstance(moved, WindowEvent.Moved) and moved.position.x == -20
    assert _page_load("https://example.com/", "finished").event is PageLoadEvent.Finished


def test_scale_theme_and_drag_drop_events_parse() -> None:
    scale = _window_event("scale_factor_changed", "[1.5,1600,900]", None)
    assert isinstance(scale, WindowEvent.ScaleFactorChanged)
    assert scale.scale_factor == 1.5 and scale.new_inner_size.width == 1600
    theme = _window_event("theme_changed", '"dark"', None)
    assert isinstance(theme, WindowEvent.ThemeChanged) and theme.theme == "dark"
    enter = _window_event("drag_drop_enter", json.dumps({"paths": ["C:/a.txt"], "position": [1.5, 2.5]}), None)
    assert isinstance(enter, WindowEvent.DragDropEnter)
    assert enter.paths == ("C:/a.txt",) and enter.position == (1.5, 2.5)
    over = _window_event("drag_drop_over", json.dumps({"position": [-1.0, 2.0]}), None)
    assert isinstance(over, WindowEvent.DragDropOver) and over.position == (-1.0, 2.0)
    drop = _window_event(
        "drag_drop_drop", json.dumps({"paths": ["C:/a.txt", "C:/b.txt"], "position": [3.0, 4.0]}), None
    )
    assert isinstance(drop, WindowEvent.DragDropDrop) and drop.paths == ("C:/a.txt", "C:/b.txt")
    assert isinstance(_window_event("drag_drop_leave", "null", None), WindowEvent.DragDropLeave)


def test_builder_maps_new_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_build(handle: object, config_json: str, **kwargs: object) -> object:
        captured["config"] = json.loads(config_json)
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("pytaurix.webview._handle", lambda manager: manager)
    monkeypatch.setattr("pytaurix.webview._native.build_window", fake_build)
    WebviewWindowBuilder.build(
        cast(ManagerType, object()),
        "main",
        WebviewUrl.App("index.html"),
        user_agent="PyTauriX/1",
        drag_drop_enabled=False,
        always_on_bottom=True,
        visible_on_all_workspaces=True,
        content_protected=True,
        window_classname="PyTauriXWindow",
        theme="dark",
        title_bar_style="overlay",
        traffic_light_position=(4.0, 8.0),
        hidden_title=True,
        accept_first_mouse=True,
        tabbing_identifier="pytaurix",
        additional_browser_args="--disable-features=Test",
        parent="host",
        proxy_url="http://127.0.0.1:8080",
        zoom_hotkeys_enabled=False,
        use_https_scheme=False,
        devtools=None,
        on_document_title_changed=lambda window, title: None,
        on_download=lambda webview, event: True,
    )
    config = captured.get("config")
    assert isinstance(config, dict)
    assert config["theme"] == "dark" and config["titleBarStyle"] == "overlay"
    assert config["trafficLightPosition"] == {"x": 4.0, "y": 8.0}
    assert config["windowClassname"] == "PyTauriXWindow"
    assert config["proxyUrl"] == "http://127.0.0.1:8080"
    assert config["devtools"] is None and config["parent"] == "host"
    kwargs = captured.get("kwargs")
    assert isinstance(kwargs, dict)
    assert kwargs["title_changed"] is not None
    assert callable(kwargs["download"])


@pytest.mark.parametrize(
    "option,value",
    [
        ("theme", "system"),
        ("title_bar_style", "hidden"),
        ("proxy_url", "http://user:secret@127.0.0.1:8080"),
        ("parent", ""),
        ("devtools", "yes"),
    ],
)
def test_builder_rejects_invalid_new_options(option: str, value: object) -> None:
    options = cast(WebviewWindowBuilderArgs, {option: value})
    with pytest.raises(BindingError):
        WebviewWindowBuilder._build(cast(ManagerType, object()), {"label": "main", "url": "index.html"}, options)
