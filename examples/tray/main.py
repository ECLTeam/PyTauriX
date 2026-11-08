# PytaruiX
# 文件作用：真实通知区域双托盘、鼠标与菜单事件、窗口恢复和资源清理验收。
# 公开接口：无。
from __future__ import annotations

import gc
import json
import os
import sys
import threading
import time
import traceback
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from anyio.from_thread import start_blocking_portal
from pytaruix import AppHandle, BindingError, Commands, WebviewWindow, builder_factory, context_factory
from pytaruix.ffi.image import Image
from pytaruix.menu import Menu, MenuItem, Submenu
from pytaruix.tray import MouseButton, MouseButtonState, TrayIcon, TrayIconBuilder, TrayIconEvent, TrayIconEventType

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from tray_windows import DesktopTray


def main() -> int:
    """
    验收本进程的真实系统托盘，异常回调必须有序归还 Python。

    所有输入先定位当前 PID 的唯一 tooltip；不操作其他应用托盘或未知进程。
    """
    root = Path(__file__).resolve().parent
    mode = os.environ.get("PYTARUIX_FAILURE_MODE", "normal")
    print(f"TRAY_PROCESS {os.getpid()} {mode}", flush=True)
    desktop = DesktopTray()
    commands = Commands()
    checks: dict[str, bool] = {}
    ready: set[str] = set()
    ready_lock = threading.Lock()
    done = threading.Event()
    restored = threading.Event()
    restore_requested = threading.Event()
    selected = threading.Event()
    mouse_events: list[tuple[str, str, str]] = []
    mouse_states: set[MouseButtonState] = set()
    menu_events: list[tuple[str, str]] = []
    trays: dict[str, TrayIcon] = {}
    windows: dict[str, WebviewWindow] = {}
    references: list[weakref.ReferenceType[Any]] = []
    tooltip = desktop.prefix + "main"
    probe_tooltip = desktop.prefix + "probe"
    icon = Image(bytes((25, 130, 210, 255)) * (16 * 16), 16, 16)
    replacement = Image(bytes((210, 85, 35, 255)) * (16 * 16), 16, 16)
    worker_errors: list[str] = []

    def rejected(name: str, operation: Callable[[], object], code: str) -> None:
        try:
            operation()
        except BindingError as error:
            checks[name] = str(error).startswith(code + ":")
        else:
            checks[name] = False

    def wait(predicate: Callable[[], bool], timeout: float = 5) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.03)
        return False

    class MouseHandler:
        def __init__(self, name: str) -> None:
            self.name = name

        def __call__(self, source: TrayIcon | AppHandle, event: TrayIconEventType) -> None:
            mouse_events.append((self.name, event.id, type(event).__name__))
            print(f"TRAY_EVENT {self.name} {event.id} {type(event).__name__}", flush=True)
            checks["mouse_main_thread"] = threading.current_thread() is threading.main_thread()
            checks["mouse_position"] = isinstance(event.position.x, (float, int)) and event.rect.size.width > 0
            if self.name == "global":
                checks["global_source"] = isinstance(source, AppHandle)
                return
            checks["tray_source"] = isinstance(source, TrayIcon) and source.id() == event.id
            if not isinstance(event, TrayIconEvent.Click):
                return
            mouse_states.add(event.button_state)
            rejected("callback_query", trays["main"].rect, "blocking_callback")
            rejected("callback_close", trays["main"].close, "blocking_callback")
            rejected("callback_register", lambda: trays["main"].on_tray_icon_event(self), "blocking_callback")
            if mode == "exception":
                raise RuntimeError("tray callback failure")
            if mode == "awaitable":

                async def pending() -> None:
                    raise RuntimeError("Must not execute an asynchronous GUI callback")

                return cast(None, pending())
            if event.button is MouseButton.Left and not restore_requested.is_set():
                restore_requested.set()

                def restore() -> None:
                    windows["main"].show()
                    windows["main"].set_focus()
                    restored.set()

                threading.Thread(target=restore, daemon=True).start()

    class MenuHandler:
        def __init__(self, name: str) -> None:
            self.name = name

        def __call__(self, source: AppHandle, event: str) -> None:
            checks["menu_main_thread"] = threading.current_thread() is threading.main_thread()
            checks["menu_source"] = isinstance(source, AppHandle) and type(event) is str
            menu_events.append((self.name, event))
            selected.set()

    @commands.command("ready")
    def ready_command(webview_window: WebviewWindow) -> None:
        with ready_lock:
            ready.add(webview_window.label())

    def run_checks(handle: AppHandle) -> None:
        try:
            checks["two_webviews"] = wait(lambda: len(ready) == 2)
            print("TRAY_STAGE native_input", flush=True)
            main_tray = trays["main"]
            probe = trays["probe"]
            checks["app_handle"] = isinstance(main_tray.app_handle(), AppHandle)
            bounds = desktop.locate(tooltip)
            checks["native_tooltip"] = bounds["name"] == tooltip
            checks["native_icon"] = desktop.has_color(bounds, (25, 130, 210))
            rect = main_tray.rect()
            checks["native_rect"] = rect is not None and abs(rect.position.x - bounds["x"]) < bounds["width"]
            windows["main"].hide()
            checks["window_hidden"] = not windows["main"].is_visible()
            desktop.click(bounds)
            if mode != "normal":
                done.set()
                return
            checks["window_restore"] = restored.wait(5) and windows["main"].is_visible()
            desktop.move_away()
            checks["mouse_click"] = wait(
                lambda: any(name == "main" and kind == "Click" for name, _, kind in mouse_events)
            )
            checks["button_states"] = {MouseButtonState.Up, MouseButtonState.Down} <= mouse_states
            checks["global_event"] = any(name == "global" and id == "main-tray" for name, id, _ in mouse_events)
            checks["no_probe_cross_delivery"] = not any(
                name == "probe" and id == "main-tray" for name, id, _ in mouse_events
            )
            bounds = desktop.locate(tooltip)
            # 双击期间保持通知区域激活；恢复窗口已在第一次单击完成。
            checks["double_target_visible"] = desktop.has_color(bounds, (25, 130, 210))
            desktop.click(bounds, double=True)
            checks["double_click"] = wait(
                lambda: any(name == "main" and kind == "DoubleClick" for name, _, kind in mouse_events)
            )
            bounds = desktop.locate(tooltip)
            desktop.hover(bounds)
            desktop.move_away()
            checks["enter_move_leave"] = wait(
                lambda: {"Enter", "Move", "Leave"} <= {kind for name, _, kind in mouse_events if name == "main"}
            )
            time.sleep(0.2)
            checks["left_menu_disabled"] = not desktop.popup_visible()
            bounds = desktop.locate(tooltip)
            desktop.click(bounds, right=True)
            checks["right_menu"] = wait(desktop.popup_visible)
            selected.clear()
            desktop.choose_first()
            checks["native_menu_selection"] = selected.wait(4) and wait(
                lambda: {"main", "probe", "app"} <= {name for name, event in menu_events if event == "show"}
            )
            checks["menu_broadcast"] = {name for name, event in menu_events if event == "show"} == {
                "main",
                "probe",
                "app",
            }
            checks["lookup_alias"] = handle.tray_by_id("main-tray").id() == main_tray.id()  # type: ignore[union-attr]
            checks["missing_id"] = handle.tray_by_id("missing") is None and handle.remove_tray_by_id("missing") is None
            rejected("duplicate_id", lambda: TrayIcon.with_id(handle, "main-tray"), "duplicate_tray")
            rejected("invalid_nul", lambda: main_tray.set_tooltip("bad\0name"), "invalid_tray")
            main_tray.set_icon(replacement)
            bounds = desktop.locate(tooltip)
            checks["native_icon_replaced"] = desktop.has_color(bounds, (210, 85, 35))
            main_tray.set_icon_with_as_template(icon, False)
            bounds = desktop.locate(tooltip)
            checks["native_atomic_icon"] = desktop.has_color(bounds, (25, 130, 210))
            main_tray.set_title("Windows unsupported effect")
            main_tray.set_temp_dir_path(None)
            main_tray.set_icon_as_template(False)
            checks["selected_setters"] = True
            print("TRAY_STAGE update", flush=True)
            updated = tooltip + " updated"
            main_tray.set_tooltip(updated)
            time.sleep(0.3)
            bounds = desktop.locate(updated)
            checks["tooltip_update"] = bounds["name"].endswith(updated)
            main_tray.set_visible(False)
            checks["native_hidden"] = wait(lambda: desktop.absent(updated))
            main_tray.set_visible(True)
            checks["native_restored"] = desktop.locate(updated)["name"].endswith(updated)
            main_tray.set_show_menu_on_left_click(True)
            bounds = desktop.locate(updated)
            desktop.click(bounds)
            checks["left_menu_enabled"] = wait(desktop.popup_visible)
            desktop.choose_first()
            main_tray.set_show_menu_on_left_click(False)
            menu = Menu.with_items(handle, (MenuItem.with_id(handle, "updated", "&Updated", True),))
            main_tray.set_menu(menu)
            bounds = desktop.locate(updated)
            desktop.click(bounds, right=True)
            selected.clear()
            desktop.choose_first()
            checks["menu_replaced"] = selected.wait(4) and wait(
                lambda: any(event == "updated" for _, event in menu_events)
            )
            main_tray.set_menu(None)
            bounds = desktop.locate(updated)
            desktop.click(bounds, right=True)
            time.sleep(0.2)
            checks["menu_removed"] = not desktop.popup_visible()
            submenu = Submenu.with_items(handle, "Nested", True, (MenuItem(handle, "Nested item", True),))
            main_tray.set_menu(submenu)
            checks["submenu_accepted"] = True
            main_tray.set_menu(menu)
            print("TRAY_STAGE lifecycle", flush=True)
            windows["probe"].close()
            checks["window_owner_survives"] = (
                wait(lambda: handle.get_webview_window("probe") is None) and probe.rect() is not None
            )
            probe_bounds = desktop.locate(probe_tooltip)
            desktop.click(probe_bounds)
            checks["probe_listener"] = wait(
                lambda: any(name == "probe" and kind == "Click" for name, _, kind in mouse_events)
            )
            alias = handle.remove_tray_by_id("probe-tray")
            assert alias is not None
            checks["remove_not_close"] = (
                handle.tray_by_id("probe-tray") is None and not probe.closed and alias.id() == probe.id()
            )
            rejected("detached_duplicate_id", lambda: TrayIcon.with_id(handle, "probe-tray"), "duplicate_tray")
            probe.close()
            probe.close()
            checks["close_aliases"] = probe.closed and alias.closed
            rejected("closed_access", alias.rect, "tray_closed")
            old_events = len(mouse_events)
            fresh = TrayIconBuilder.with_id("probe-tray").icon(icon).tooltip(probe_tooltip).build(handle)
            checks["same_id_rebuilt"] = not fresh.closed and alias.closed
            print("TRAY_REBUILT_RECT " + repr(fresh.rect()), flush=True)
            bounds = desktop.locate(probe_tooltip)
            desktop.click(bounds)
            time.sleep(0.2)
            checks["old_generation_silent"] = not any(name == "probe" for name, _, _ in mouse_events[old_events:])
            fresh.close()
            checks["native_closed"] = wait(lambda: desktop.absent(probe_tooltip))
            gc_tray = TrayIconBuilder.with_id("gc-tray").icon(icon).tooltip(desktop.prefix + "gc").build(handle)
            ref = weakref.ref(gc_tray)
            del gc_tray
            gc.collect()
            owned = handle.tray_by_id("gc-tray")
            checks["gc_app_owned"] = ref() is None and owned is not None and not owned.closed
            detached = handle.remove_tray_by_id("gc-tray")
            assert detached is not None
            del owned, detached
            gc.collect()
            recreated = TrayIcon.with_id(handle, "gc-tray")
            checks["gc_detached_released"] = not recreated.closed
            recreated.close()
            main_tray.clear_event_handlers()
            handle.clear_tray_icon_event_handlers()
            handle.clear_menu_event_handlers()
            gc.collect()
            checks["callbacks_released"] = all(reference() is None for reference in references)
            main_tray.close()
            checks["main_closed"] = main_tray.closed and handle.tray_by_id("main-tray") is None
            print("TRAY_MOUSE_EVENTS " + json.dumps(mouse_events), flush=True)
            print("TRAY_RESULT " + json.dumps(checks, sort_keys=True), flush=True)
            handle.exit(0 if all(checks.values()) else 1)
        except Exception:
            worker_errors.append(traceback.format_exc())
            print("TRAY_WORKER_ERROR " + worker_errors[-1], flush=True)
            handle.exit(1)
        finally:
            done.set()

    def setup(handle: AppHandle) -> None:
        for label in ("main", "probe"):
            window = handle.get_webview_window(label)
            assert window is not None
            windows[label] = window
        menu = Menu.with_items(handle, (MenuItem.with_id(handle, "show", "&Show window", True),))
        main_mouse = MouseHandler("main")
        main_menu = MenuHandler("main")
        references.extend((weakref.ref(main_mouse), weakref.ref(main_menu)))
        trays["main"] = (
            TrayIconBuilder.with_id("main-tray")
            .icon(icon)
            .menu(menu)
            .tooltip(tooltip)
            .show_menu_on_left_click(False)
            .on_tray_icon_event(main_mouse)
            .on_menu_event(main_menu)
            .build(handle)
        )
        trays["probe"] = TrayIcon.with_id(windows["probe"], "probe-tray")
        trays["probe"].set_icon(icon)
        trays["probe"].set_tooltip(probe_tooltip)
        trays["probe"].set_menu(menu)
        trays["probe"].set_show_menu_on_left_click(False)
        probe_mouse = MouseHandler("probe")
        probe_menu = MenuHandler("probe")
        references.extend((weakref.ref(probe_mouse), weakref.ref(probe_menu)))
        retired = MouseHandler("retired")
        retired_reference = weakref.ref(retired)
        references.append(retired_reference)
        trays["probe"].on_tray_icon_event(retired)
        trays["probe"].on_tray_icon_event(probe_mouse)
        del retired
        checks["callback_replaced"] = retired_reference() is None
        trays["probe"].on_menu_event(probe_menu)
        app_menu = MenuHandler("app")
        references.append(weakref.ref(app_menu))
        handle.on_menu_event(app_menu)
        checks["builder_stable_id"] = TrayIconBuilder.with_id("stable").id() == "stable"
        threading.Thread(target=run_checks, args=(handle,), daemon=True).start()

    global_handler = MouseHandler("global")
    references.append(weakref.ref(global_handler))
    with start_blocking_portal() as portal:
        app = builder_factory().build(
            context=context_factory(root),
            invoke_handler=commands.generate_handler(portal),
            setup=setup,
            on_tray_icon_event=global_handler,
        )
        del global_handler
        rejected("before_loop", lambda: TrayIcon(app), "app_not_running")
        try:
            code = app.run_return()
        except (RuntimeError, BindingError) as error:
            expected = "tray callback failure" if mode == "exception" else "invalid_callback:"
            if mode == "normal" or expected not in str(error):
                raise
            print("TRAY_FAILURE_RECOVERED " + mode, flush=True)
            code = 0
        assert done.wait(8)
    if worker_errors:
        raise RuntimeError(worker_errors[-1])
    rejected("app_closed", trays["main"].rect, "app_closed")
    assert checks["app_closed"] and all(tray.closed for tray in trays.values())
    for tray in trays.values():
        tray.close()
    gc.collect()
    assert all(reference() is None for reference in references)
    print("TRAY_RESOURCES_RELEASED", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
