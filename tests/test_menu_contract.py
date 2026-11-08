from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from typing import cast

import pytest
from pytaurix import get_runtime_info
from pytaurix import menu as public
from pytaurix.ffi import menu as ffi
from pytaurix.manager import ManagerType


def test_menu_import_identity_and_string_event() -> None:
    assert public.__all__ == ffi.__all__
    assert all(getattr(public, name) is getattr(ffi, name) for name in public.__all__)
    assert public.MenuID is str and public.MenuEvent is str
    assert "menu.events" in get_runtime_info().capabilities
    assert hasattr(public.Menu, "default")
    assert hasattr(public.IconMenuItem, "set_native_icon")
    assert hasattr(public.PredefinedMenuItem, "about")
    assert not hasattr(public.PredefinedMenuItem, "with_id")


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


ROLE_KINDS = {
    "separator": "separator",
    "copy": "copy",
    "cut": "cut",
    "paste": "paste",
    "select_all": "select_all",
    "undo": "undo",
    "redo": "redo",
    "minimize": "minimize",
    "maximize": "maximize",
    "fullscreen": "fullscreen",
    "close_window": "close_window",
    "quit": "quit",
    "hide": "hide",
    "hide_others": "hide_others",
    "show_all": "show_all",
    "services": "services",
    "bring_all_to_front": "bring_all_to_front",
}


def test_predefined_roles_map_to_native_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str | None]] = []

    def fake_create(
        kind: str,
        manager: object,
        id: object = None,
        text: str = "",
        enabled: bool = True,
        checked: bool = False,
        accelerator: str | None = None,
        icon: object = None,
        metadata: public.AboutMetadata | None = None,
    ) -> object:
        calls.append((kind, text, None if metadata is None else metadata.to_json()))
        return object()

    monkeypatch.setattr(ffi, "_create", fake_create)
    manager = cast(ManagerType, object())
    for name, kind in ROLE_KINDS.items():
        getattr(public.PredefinedMenuItem, name)(manager)
        assert calls[-1] == (kind, "", None)

    public.PredefinedMenuItem.copy(manager, "Copy")
    assert calls[-1] == ("copy", "Copy", None)


def test_about_metadata_serializes_only_provided_fields() -> None:
    metadata = public.AboutMetadata(name="PyTauriX", version="0.1.0", authors=("ECL", "Contributors"))
    assert json.loads(metadata.to_json()) == {
        "name": "PyTauriX",
        "version": "0.1.0",
        "authors": ["ECL", "Contributors"],
    }
    assert public.AboutMetadata().to_json() == "{}"


def test_native_icon_enum_matches_upstream_variant_names() -> None:
    assert len(public.NativeIcon) == 56
    assert str(public.NativeIcon.FOLDER) == "Folder"
    assert str(public.NativeIcon.I_CHAT_THEATER) == "IChatTheater"
    assert str(public.NativeIcon.STATUS_PARTIALLY_AVAILABLE) == "StatusPartiallyAvailable"
