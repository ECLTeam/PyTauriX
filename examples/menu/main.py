# PyTauriX
# 文件作用：真实 Windows 菜单读回、选择事件、线程和资源代次验收。
# 公开接口：无。
from __future__ import annotations

import gc
import json
import os
import sys
import threading
import time
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import cast

from anyio.from_thread import start_blocking_portal
from pytaurix import AppHandle, BindingError, Commands, WebviewUrl, WebviewWindow, builder_factory, context_factory
from pytaurix.dpi import LogicalPosition, PhysicalPosition
from pytaurix.events import WindowEvent, WindowEventType
from pytaurix.ffi.image import Image
from pytaurix.menu import CheckMenuItem, ContextMenu, IconMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu
from pytaurix.webview import WebviewWindowBuilder

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from menu_windows import DesktopMenus


def main() -> int:
    """
    运行真实原生菜单场景；仅操纵本进程窗口，回调失败由 run_return 归还。
    """
    root = Path(__file__).resolve().parent
    mode = os.environ.get("PYTARUIX_FAILURE_MODE", "normal")
    desktop = DesktopMenus()
    commands = Commands()
    checks: dict[str, bool] = {}
    windows: dict[str, WebviewWindow] = {}
    menus: dict[str, Menu] = {}
    entries: dict[str, MenuItem | CheckMenuItem | IconMenuItem | Submenu] = {}
    events: list[tuple[str, str]] = []
    references: list[weakref.ReferenceType[object]] = []
    destroyed = threading.Event()
    close_requested = threading.Event()
    prevent_first_close = True
    selected = threading.Event()
    command_done = threading.Event()
    icon = Image.from_path(root / "icons" / "menu.png")

    def rejected(name: str, operation: Callable[[], object], code: str) -> None:
        try:
            operation()
        except BindingError as error:
            checks[name] = str(error).startswith(code + ":")
        else:
            checks[name] = False

    class Handler:
        def __init__(self, name: str) -> None:
            self.name = name

        def __call__(self, source: AppHandle | WebviewWindow, event: str) -> None:
            print("MENU_EVENT " + self.name + " " + event, flush=True)
            events.append((self.name, event))
            checks["event_string"] = type(event) is str
            checks["event_main_thread"] = threading.current_thread() is threading.main_thread()
            checks["event_owner"] = (
                isinstance(source, AppHandle)
                if self.name.startswith("app")
                else isinstance(source, WebviewWindow)
                and source.label()
                in {
                    "main",
                    "probe",
                }
            )
            rejected("callback_query", menus["main"].items, "blocking_callback")
            rejected("callback_register", lambda: source.on_menu_event(lambda *_: None), "blocking_callback")
            selected.set()
            if mode == "exception":
                raise RuntimeError("menu callback failure")
            if mode == "awaitable":

                async def pending() -> None:
                    raise RuntimeError("Awaitable must be closed without execution")

                return cast(None, pending())

    def register(source: AppHandle | WebviewWindow, name: str) -> weakref.ReferenceType[object]:
        handler = Handler(name)
        reference = weakref.ref(cast(object, handler))
        references.append(reference)
        source.on_menu_event(handler)
        return reference

    def on_event(event: WindowEventType) -> None:
        nonlocal prevent_first_close
        if isinstance(event, WindowEvent.CloseRequested) and prevent_first_close:
            event.api.prevent_close()
            prevent_first_close = False
            close_requested.set()
        if isinstance(event, WindowEvent.Destroyed):
            destroyed.set()

    def setup(handle: AppHandle) -> None:
        window = handle.get_webview_window("main")
        assert window is not None
        windows["main"] = window
        item = MenuItem.with_id(handle, "open", "Open", True, "Ctrl+Shift+O")
        check = CheckMenuItem.with_id(window, "checked", "Checked", True, True)
        image = IconMenuItem.with_id(handle, "icon", "Image", True, icon)
        submenu = Submenu.with_id_and_items(
            handle, "file", "&File", True, [item, check, image, PredefinedMenuItem.separator(handle)]
        )
        menu = Menu.with_id_and_items(handle, "root", [submenu])
        checks["setup_attach"] = window.set_menu(menu) is None
        menus["main"] = menu
        entries.update(open=item, checked=check, icon=image, file=submenu)
        register(handle, "app1")
        if mode == "normal":
            register(handle, "app2")
            replaced = register(window, "replaced")
            register(window, "main")
            checks["replacement_released"] = replaced() is None

    def read(window: WebviewWindow) -> list[dict[str, object]]:
        result: list[list[dict[str, object]]] = []
        done = threading.Event()

        def inspect_native() -> None:
            result.append(desktop.snapshot(desktop.hwnd(window.title())))
            done.set()

        window.run_on_main_thread(inspect_native)
        assert done.wait(5)
        return result[0]

    def wait_event(names: set[str], id: str, start: int) -> bool:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if {(name, event) for name, event in events[start:]} >= {(name, id) for name in names}:
                return True
            time.sleep(0.02)
        return False

    @commands.command()
    def inspect(app_handle: AppHandle, webview_window: WebviewWindow) -> None:
        try:
            window = webview_window
            hwnd = desktop.hwnd("原生菜单验收")
            start = len(events)
            desktop.choose_bar(hwnd, "f")
            if mode != "normal":
                assert selected.wait(5)
                return
            checks["bar_selection"] = wait_event({"app1", "app2", "main"}, "open", start)
            menu, submenu = menus["main"], cast(Submenu, entries["file"])
            raw = read(window)
            children = cast(list[dict[str, object]], raw[0]["items"])
            checks["native_text_order"] = [str(item["text"]).split("\t")[0] for item in children[:3]] == [
                "Open",
                "Checked",
                "Image",
            ] and bool(children[3]["separator"])
            checks["native_initial_flags"] = bool(children[0]["enabled"]) and bool(children[1]["checked"])
            checks["native_icon"] = children[2]["icon"] == (icon.width, icon.height, icon.rgba)
            checks["window_get"] = window.menu() is not None and cast(Menu, window.menu()).id() == "root"
            checks["lookup"] = submenu.get("open") is not None and menu.get("open") is None
            checks["ordered_types"] = [type(item) for item in submenu.items()] == [
                MenuItem,
                CheckMenuItem,
                IconMenuItem,
                PredefinedMenuItem,
            ]
            item = cast(MenuItem, entries["open"])
            item.set_text("Updated")
            item.set_enabled(False)
            check = cast(CheckMenuItem, entries["checked"])
            check.set_checked(False)
            image = cast(IconMenuItem, entries["icon"])
            image.set_icon(None)
            raw = cast(list[dict[str, object]], read(window)[0]["items"])
            checks["native_updates"] = (
                str(raw[0]["text"]).startswith("Updated")
                and not raw[0]["enabled"]
                and not raw[1]["checked"]
                and raw[2]["icon"] is None
            )
            item.set_enabled(True)
            item.set_accelerator(None)
            item.set_accelerator("Ctrl+Shift+O")
            image.set_icon(icon)
            check.set_checked(True)
            checks["native_update_recovery"] = bool(
                cast(list[dict[str, object]], read(window)[0]["items"])[0]["enabled"]
            )
            submenu.set_text("&Tools")
            submenu.set_enabled(False)
            checks["submenu_updates"] = (
                submenu.text() == "&Tools" and not submenu.is_enabled() and not read(window)[0]["enabled"]
            )
            submenu.set_text("&File")
            submenu.set_enabled(True)
            check.set_text("Check updated")
            check.set_enabled(False)
            check.set_accelerator("Ctrl+Shift+C")
            image.set_text("Icon updated")
            image.set_enabled(False)
            image.set_accelerator("Ctrl+Shift+I")
            checks["item_variants"] = (
                check.text() == "Check updated"
                and image.text() == "Icon updated"
                and not check.is_enabled()
                and not image.is_enabled()
            )
            check.set_enabled(True)
            image.set_enabled(True)
            check.set_accelerator(None)
            image.set_accelerator(None)
            separator = cast(PredefinedMenuItem, submenu.items()[3])
            separator.set_text("Divider")
            checks["separator_text"] = separator.text() == "Divider"
            auto_check = CheckMenuItem(app_handle, "Auto check", True, False)
            auto_icon = IconMenuItem(app_handle, "Auto icon", True)
            checks["auto_variants"] = not auto_check.is_checked() and auto_icon.is_enabled()
            root_extra = Submenu(app_handle, "Extra root", True)
            menu.prepend(root_extra)
            menu.insert(root_extra, 2)
            checks["root_container"] = len(menu.items()) == 3 and menu.get(root_extra.id()) is not None
            menu.remove(root_extra)
            menu.append_items([root_extra])
            assert menu.remove_at(1) is not None
            menu.prepend_items([root_extra])
            menu.insert_items([root_extra], 1)
            menu.remove(root_extra)
            checks["root_container"] &= len(menu.items()) == 1 and menu.remove_at(99) is None
            start = len(events)
            desktop.choose_bar(hwnd, "f", 1)
            checks["check_selection"] = (
                wait_event({"app1", "app2", "main"}, "checked", start)
                and not check.is_checked()
                and not cast(list[dict[str, object]], read(window)[0]["items"])[1]["checked"]
            )
            check.set_checked(True)
            for name, operation, code in (
                ("index", lambda: submenu.insert(item, 9999), "invalid_index"),
                ("negative", lambda: submenu.remove_at(-1), "invalid_index"),
                ("bool_index", lambda: submenu.insert(item, True), "invalid_index"),
                ("accelerator", lambda: item.set_accelerator("Invalid+Key+Garbage"), "invalid_accelerator"),
                ("accelerator_create", lambda: MenuItem(app_handle, "bad", True, "not a key"), "invalid_accelerator"),
                ("nul", lambda: item.set_text("bad\0text"), "invalid_menu"),
                ("cycle", lambda: submenu.append(submenu), "menu_failed"),
            ):
                rejected("invalid_" + name, operation, code)
            for name, operation in (
                ("item", lambda: submenu.append(cast(MenuItem, menu))),
                ("enabled", lambda: item.set_enabled(cast(bool, 1))),
                ("id", lambda: Menu.with_id(app_handle, cast(str, 1))),
                ("icon", lambda: image.set_icon(cast(Image, b"image"))),
            ):
                try:
                    operation()
                except TypeError:
                    checks["invalid_type_" + name] = True
            checks["invalid_id_missing"] = submenu.get("missing") is None and submenu.remove_at(9999) is None
            extra = MenuItem(app_handle, "Extra", True)
            submenu.prepend(extra)
            submenu.insert(extra, 2)
            checks["duplicate_insert"] = len(submenu.items()) == 6
            submenu.remove(extra)
            checks["removed_alive"] = len(submenu.items()) == 4 and extra.text() == "Extra"
            duplicate = MenuItem.with_id(app_handle, "duplicate", "first", True)
            another = MenuItem.with_id(app_handle, "duplicate", "second", True)
            submenu.append_items([duplicate, another])
            checks["duplicate_id"] = cast(MenuItem, submenu.get("duplicate")).text() == "first"
            submenu.remove(another)
            checks["duplicate_id_remove"] = submenu.get("duplicate") is None
            nested = Submenu(app_handle, "Nested", True)
            submenu.append(nested)
            rejected("invalid_transitive_cycle", lambda: nested.append(submenu), "menu_failed")
            submenu.remove(nested)
            batch = [MenuItem(app_handle, str(i), True) for i in range(3)]
            submenu.prepend_items(batch[:2])
            submenu.insert_items(batch[2:], 2)
            checks["batch_order"] = [entry.text() for entry in submenu.items()[:3]] == ["0", "1", "2"]
            for _ in range(3):
                assert submenu.remove_at(0) is not None
            probe = WebviewWindowBuilder.build(
                app_handle, "probe", WebviewUrl.App("quiet.html"), title="菜单副窗口", on_window_event=on_event
            )
            windows["probe"] = probe
            # 同一子菜单共享到两个根菜单，构造可接受窗口管理器。
            second = Menu.with_items(probe, [submenu])
            menus["probe"] = second
            checks["window_alias"] = second.set_as_window_menu(probe) is None
            checks["shared_submenu"] = read(probe)[0]["items"] == read(window)[0]["items"]
            old = probe.set_menu(menu)
            checks["replace"] = old is not None and old.id() == second.id()
            checks["remove"] = cast(Menu, probe.remove_menu()).id() == menu.id() and read(probe) == []
            app_menu = Menu.with_id_and_items(
                app_handle, "app-menu", [Submenu.with_items(app_handle, "&App", True, [extra])]
            )
            menus["app"] = app_menu
            checks["app_alias"] = app_menu.set_as_app_menu() is None
            checks["app_get"] = cast(Menu, app_handle.menu()).id() == app_menu.id()
            checks["app_native"] = read(probe)[0]["text"] == "&App"
            checks["app_remove"] = cast(Menu, app_handle.remove_menu()).id() == app_menu.id()
            app_handle.set_menu(app_menu)
            second.set_as_window_menu(probe)
            probe_ref = register(probe, "probe")
            checks["probe_callback_owned"] = probe_ref() is not None
            popup = Menu.with_id_and_items(
                app_handle, "popup", [MenuItem.with_id(app_handle, "popup-item", "Popup", True)]
            )
            menus["popup"] = popup
            for name, operation in (
                ("popup_menu", lambda: ContextMenu.popup(popup, window)),
                ("popup_submenu", lambda: ContextMenu.popup_at(submenu, window, PhysicalPosition(80, 80))),
                ("popup_submenu_default", lambda: ContextMenu.popup(submenu, window)),
                ("popup_logical", lambda: window.popup_menu_at(popup, LogicalPosition(100, 100))),
            ):
                start = len(events)
                errors: list[Exception] = []

                def choose(errors: list[Exception] = errors) -> None:
                    try:
                        desktop.choose_popup(hwnd)
                    except Exception as error:
                        errors.append(error)

                chooser = threading.Thread(target=choose)
                chooser.start()
                operation()
                chooser.join(timeout=6)
                assert not chooser.is_alive() and not errors, errors
                expected_id = "open" if name.startswith("popup_submenu") else "popup-item"
                checks[name] = wait_event({"app1", "app2", "main", "probe"}, expected_id, start)
            worker_done = threading.Event()

            def worker() -> None:
                checks["worker"] = item.text() == "Updated" and check.is_checked() and item.is_enabled()
                worker_done.set()

            thread = threading.Thread(target=worker)
            thread.start()
            checks["worker_done"] = worker_done.wait(3)
            thread.join(timeout=1)
            window.clear_menu_event_handlers()
            app_handle.clear_menu_event_handlers()
            checks["clear_references"] = references[0]() is None and references[1]() is None and references[3]() is None
            register(app_handle, "app-live")
            checks["window_ownership"] = second.app_handle().get_webview_window("main") is not None
            probe.close()
            assert close_requested.wait(3)
            checks["close_prevented_native"] = bool(read(probe)) and not destroyed.is_set()
            desktop.close_window(desktop.hwnd("菜单副窗口"))
            retire(app_handle)
            finish(app_handle)
        except Exception as error:
            print("MENU_INSPECT_ERROR " + repr(error), flush=True)
            app_handle.exit(1)
            raise
        finally:
            command_done.set()

    @commands.command()
    def retire(app_handle: AppHandle) -> None:
        checks["destroyed"] = destroyed.wait(3)
        old = windows["probe"]
        flushed = threading.Event()
        app_handle.run_on_main_thread(flushed.set)
        assert flushed.wait(3)
        checks["closed_callback_released"] = references[4]() is None
        for name, operation in (
            ("get", old.menu),
            ("set", lambda: old.set_menu(menus["main"])),
            ("remove", old.remove_menu),
            ("listen", lambda: old.on_menu_event(lambda *_: None)),
            ("clear", old.clear_menu_event_handlers),
            ("popup", lambda: old.popup_menu(menus["popup"])),
            ("construct", lambda: Menu(old)),
        ):
            rejected("closed_" + name, operation, "window_closed")
        checks["app_resource_survives"] = menus["probe"].items()[0].id() == "file"
        fresh = WebviewWindowBuilder.build(app_handle, "probe", WebviewUrl.App("quiet.html"), title="重建菜单窗口")
        menus["probe"].set_as_window_menu(fresh)
        rejected("generation", old.menu, "window_closed")
        start = len(events)
        fresh.set_focus()
        time.sleep(0.15)
        hwnd = desktop.hwnd("重建菜单窗口")
        desktop.choose_bar(hwnd, "f")
        checks["event_after_rebuild"] = wait_event({"app-live"}, "open", start)
        time.sleep(0.05)
        checks["event_clear_and_generation"] = events[start:] == [("app-live", "open")]
        register(fresh, "probe-fresh")
        checks["fresh_native"] = read(fresh)[0]["text"] == "&File"

    @commands.command()
    def finish(app_handle: AppHandle) -> None:
        print("MENU_RESULT " + json.dumps(checks, sort_keys=True), flush=True)
        app_handle.exit(0 if all(checks.values()) else 1)

    @commands.command()
    def diagnostic(body: str, app_handle: AppHandle) -> None:
        print("MENU_DIAGNOSTIC " + body, flush=True)
        app_handle.exit(1)

    with start_blocking_portal() as portal:
        app = builder_factory().build(
            context=context_factory(root), invoke_handler=commands.generate_handler(portal), setup=setup
        )
        rejected("before_loop", lambda: Menu(app), "app_not_running")
        try:
            code = app.run_return()
        except (RuntimeError, BindingError) as error:
            expected = "menu callback failure" if mode == "exception" else "invalid_callback:"
            if mode == "normal" or expected not in str(error):
                raise
            code = 0
            print("MENU_FAILURE_RECOVERED " + mode, flush=True)
        assert command_done.wait(6)
    for name, operation in (
        ("query", menus["main"].items),
        ("id", menus["main"].id),
        ("attach", lambda: app.handle().set_menu(menus["main"])),
        ("item", lambda: entries["open"].text()),
    ):
        rejected("app_closed_" + name, operation, "app_closed")
        assert checks["app_closed_" + name]
    gc.collect()
    assert all(reference() is None for reference in references)
    print("MENU_RESOURCES_RELEASED", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
