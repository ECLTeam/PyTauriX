from __future__ import annotations

import inspect
from collections.abc import Callable

import pytest
from pytaruix import get_runtime_info
from pytaruix import menu as public
from pytaruix.ffi import menu as ffi


def test_menu_import_identity_and_string_event() -> None:
    assert public.__all__ == ffi.__all__
    assert all(getattr(public, name) is getattr(ffi, name) for name in public.__all__)
    assert public.MenuID is str and public.MenuEvent is str
    assert "menu.events" in get_runtime_info().capabilities
    assert not hasattr(public.Menu, "default")
    assert not hasattr(public.PredefinedMenuItem, "about")
    assert not hasattr(public.IconMenuItem, "with_native_icon")


@pytest.mark.parametrize(
    ("entry", "names", "defaults"),
    [
        (public.Menu, ["manager"], {}),
        (public.Menu.with_id, ["manager", "id"], {}),
        (public.Menu.with_items, ["manager", "items"], {}),
        (public.Menu.with_id_and_items, ["manager", "id", "items"], {}),
        (public.Submenu, ["manager", "text", "enabled"], {}),
        (public.Submenu.with_id, ["manager", "id", "text", "enabled"], {}),
        (public.Submenu.with_items, ["manager", "text", "enabled", "items"], {}),
        (public.Submenu.with_id_and_items, ["manager", "id", "text", "enabled", "items"], {}),
        (public.MenuItem, ["manager", "text", "enabled", "accelerator"], {"accelerator": None}),
        (public.MenuItem.with_id, ["manager", "id", "text", "enabled", "accelerator"], {"accelerator": None}),
        (public.CheckMenuItem, ["manager", "text", "enabled", "checked", "accelerator"], {"accelerator": None}),
        (
            public.CheckMenuItem.with_id,
            ["manager", "id", "text", "enabled", "checked", "accelerator"],
            {"accelerator": None},
        ),
        (
            public.IconMenuItem,
            ["manager", "text", "enabled", "icon", "accelerator"],
            {"icon": None, "accelerator": None},
        ),
        (
            public.IconMenuItem.with_id,
            ["manager", "id", "text", "enabled", "icon", "accelerator"],
            {"icon": None, "accelerator": None},
        ),
        (public.PredefinedMenuItem.separator, ["manager"], {}),
        (public.ContextMenu.popup, ["slf", "window"], {}),
        (public.ContextMenu.popup_at, ["slf", "window", "position"], {}),
    ],
)
def test_pytauri_positional_construction(
    entry: Callable[..., object], names: list[str], defaults: dict[str, object]
) -> None:
    parameters = inspect.signature(entry).parameters
    assert list(parameters) == names
    assert all(parameter.kind is inspect.Parameter.POSITIONAL_ONLY for parameter in parameters.values())
    assert {
        name: parameter.default
        for name, parameter in parameters.items()
        if parameter.default is not inspect.Parameter.empty
    } == defaults


def test_predefined_factory_and_context_types_without_gui() -> None:
    with pytest.raises(TypeError, match="separator"):
        public.PredefinedMenuItem()
    with pytest.raises(TypeError, match="WebviewWindow"):
        public.ContextMenu.popup(None, None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="WebviewWindow"):
        public.ContextMenu.popup_at(None, None, None)  # type: ignore[arg-type]
