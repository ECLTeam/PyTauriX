from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest
from pytaurix import BindingError, _native, get_runtime_info
from pytaurix import tray as public
from pytaurix.dpi import PhysicalPositionF64
from pytaurix.ffi import tray as ffi


def test_import_and_feature_contract() -> None:
    assert public.__all__ == ffi.__all__
    assert all(getattr(public, name) is getattr(ffi, name) for name in public.__all__)
    assert ("tray.icon" in get_runtime_info().capabilities) is _native.tray_available
    builder = public.TrayIconBuilder.new()
    assert builder.id() == builder.id()
    assert public.TrayIconBuilder.with_id("test").id() == "test"
    if not _native.tray_available:
        with pytest.raises(BindingError, match="unsupported_capability"):
            builder.build(None)  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", ["Click", "DoubleClick", "Enter", "Move", "Leave"])
def test_native_event_snapshots_keep_float_precision_and_zero_size(kind: str) -> None:
    event = ffi._event(
        json.dumps(
            {
                "type": kind,
                "id": "sample",
                "position": {"x": -10.75, "y": 5.125},
                "rect": {
                    "position": {"Physical": {"x": -20, "y": 5}},
                    "size": {"Physical": {"width": 0, "height": 24}},
                },
                "button": "Right",
                "buttonState": "Up",
            }
        )
    )
    assert isinstance(event, getattr(public.TrayIconEvent, kind))
    assert event.position == PhysicalPositionF64(-10.75, 5.125)
    assert event.rect.position.x == -20 and event.rect.size.width == 0
    if isinstance(event, public.TrayIconEvent.Click):
        assert event.button is public.MouseButton.Right
        assert event.button_state is public.MouseButtonState.Up
    with pytest.raises(FrozenInstanceError):
        event.id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("coordinate", [float("nan"), float("inf"), -float("inf")])
def test_mouse_snapshot_rejects_nonfinite_coordinate(coordinate: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        PhysicalPositionF64(coordinate, 0)


def test_async_callbacks_rejected_before_gui_initialization() -> None:
    async def async_handler(*_: object) -> None:
        pass

    class AsyncHandler:
        async def __call__(self, *_: object) -> None:
            pass

    for handler in (async_handler, AsyncHandler(), None):
        with pytest.raises(BindingError, match="invalid_callback"):
            public.TrayIconBuilder().on_tray_icon_event(handler)  # type: ignore[arg-type]


def test_builder_rejects_wrong_types_before_native_calls() -> None:
    builder = public.TrayIconBuilder()
    with pytest.raises(TypeError):
        builder.show_menu_on_left_click(1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        builder.icon(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        builder.menu(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        builder.temp_dir_path("temp")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        public.TrayIconBuilder.with_id(1)  # type: ignore[arg-type]
