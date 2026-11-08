# PytaruiX
# 文件作用：真实 WebView 显示器/DPI、图像及窗口代次验收。
# 公开接口：无。
from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import cast

from anyio.from_thread import start_blocking_portal
from pytaruix import AppHandle, BindingError, Commands, WebviewUrl, WebviewWindow, builder_factory, context_factory
from pytaruix.dpi import LogicalPosition, LogicalSize, PhysicalPosition, PhysicalSize
from pytaruix.events import WindowEvent, WindowEventType
from pytaruix.ffi.image import Image
from pytaruix.ffi.window import Monitor
from pytaruix.webview import WebviewWindowBuilder

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from display_windows import DesktopDisplay


def describe(monitor: Monitor) -> dict[str, object]:
    """
    读取五项属性和物理矩形，转换成便于独立对照的值。
    """
    work = monitor.work_area
    return {
        "name": monitor.name,
        "size": (monitor.size.width, monitor.size.height),
        "position": (monitor.position.x, monitor.position.y),
        "work_position": (work.position.x, work.position.y),
        "work_size": (work.size.width, work.size.height),
        "scale_factor": monitor.scale_factor,
    }


def main() -> int:
    """
    Windows 上独立核对系统查询与实际图标像素，不改变系统显示配置。
    """
    root = Path(__file__).resolve().parent
    desktop = DesktopDisplay()
    commands = Commands()
    checks: dict[str, bool] = {}
    windows: dict[str, WebviewWindow] = {}
    snapshots: list[Monitor] = []
    destroyed = threading.Event()
    first = Image.from_path(root / "icons" / "builder.png")
    second = Image.from_bytes((root / "icons" / "updated.ico").read_bytes())

    def rejected(name: str, operation: Callable[[], object], code: str) -> None:
        try:
            operation()
        except BindingError as error:
            checks[name] = str(error).startswith(code + ":")
        else:
            checks[name] = False

    def on_event(event: WindowEventType) -> None:
        if isinstance(event, WindowEvent.Destroyed):
            destroyed.set()

    @commands.command()
    def inspect(app_handle: AppHandle, webview_window: WebviewWindow) -> None:
        windows["main"] = webview_window
        native = desktop.monitors()
        monitors = webview_window.available_monitors()
        snapshots.extend(monitors)
        try:
            monitors[0].name = "changed"  # type: ignore[misc]
        except AttributeError:
            checks["monitor_readonly"] = True
        expected = [{key: item[key] for key in describe(monitors[0])} for item in native]
        actual = [describe(monitor) for monitor in monitors]
        checks["enumeration"] = len(actual) == len(expected) and all(item in expected for item in actual)
        primary = webview_window.primary_monitor()
        checks["primary"] = primary is not None and describe(primary) == next(
            item for item, raw in zip(expected, native, strict=True) if raw["primary"]
        )
        hwnd = desktop.hwnd("显示器与图像验收")
        current = webview_window.current_monitor()
        checks["current"] = current is not None and describe(current) == next(
            item for item, raw in zip(expected, native, strict=True) if raw["handle"] == desktop.current_handle(hwnd)
        )
        checks["dpi"] = current is not None and current.scale_factor == desktop.dpi(hwnd) / 96
        for i, monitor in enumerate(monitors):
            work = monitor.work_area
            point = webview_window.monitor_from_point(
                work.position.x + work.size.width / 2, work.position.y + work.size.height / 2
            )
            checks[f"point_{i}"] = point is not None and describe(point) == describe(monitor)
        outside_x = max(m.position.x + m.size.width for m in monitors) + 10000
        outside_y = max(m.position.y + m.size.height for m in monitors) + 10000
        checks["outside_none"] = webview_window.monitor_from_point(outside_x, outside_y) is None
        for i, pair in enumerate(((float("nan"), 0.0), (0.0, float("inf")), (float("-inf"), 0.0))):
            rejected(
                f"invalid_point_{i}", lambda pair=pair: webview_window.monitor_from_point(*pair), "invalid_position"
            )
        try:
            webview_window.monitor_from_point(cast(float, "coordinate"), 0)
        except TypeError:
            checks["point_type"] = True
        callback_done = threading.Event()

        def callback() -> None:
            rejected("callback_guard", webview_window.available_monitors, "blocking_callback")
            callback_done.set()

        app_handle.run_on_main_thread(callback)
        checks["callback_done"] = callback_done.wait(3)
        worker_done = threading.Event()

        def worker() -> None:
            try:
                checks["worker"] = (
                    [describe(m) for m in webview_window.available_monitors()] == actual
                    and webview_window.primary_monitor() is not None
                    and webview_window.current_monitor() is not None
                    and webview_window.monitor_from_point(0, 0) is not None
                )
            finally:
                worker_done.set()

        thread = threading.Thread(target=worker)
        thread.start()
        checks["worker_done"] = worker_done.wait(3)
        thread.join(timeout=1)
        probe = WebviewWindowBuilder.build(
            app_handle,
            "probe",
            WebviewUrl.App("quiet.html"),
            title="图像原生像素验收",
            icon=first,
            on_window_event=on_event,
        )
        windows["probe"] = probe
        icon_done = threading.Event()

        def check_icon(image: Image, name: str) -> None:
            # 本进程的 GetWindowText/WM_GETICON 在 GUI 线程执行，避免跨线程重入窗口回调。
            probe_hwnd = desktop.hwnd("图像原生像素验收")
            checks[name] = desktop.icon(probe_hwnd) == (32, 32, image.rgba)
            icon_done.set()

        app_handle.run_on_main_thread(lambda: check_icon(first, "builder_icon"))
        assert icon_done.wait(3)
        probe.set_icon(second)
        icon_done.clear()
        app_handle.run_on_main_thread(lambda: check_icon(second, "updated_icon"))
        assert icon_done.wait(3)
        probe.set_size(LogicalSize(320, 240))
        physical = probe.inner_size()
        scale = probe.scale_factor()
        checks["logical_size"] = (physical.width, physical.height) == (round(320 * scale), round(240 * scale))
        probe.set_size(PhysicalSize(400, 300))
        checks["physical_size"] = (probe.inner_size().width, probe.inner_size().height) == (400, 300)
        probe.set_position(LogicalPosition(100, 100))
        position = probe.outer_position()
        checks["logical_position"] = (position.x, position.y) == (round(100 * scale), round(100 * scale))
        probe.set_position(PhysicalPosition(140, 160))
        position = probe.outer_position()
        checks["physical_position"] = (position.x, position.y) == (140, 160)
        checks["probe_monitor"] = probe.current_monitor() is not None
        print("DISPLAY_HARDWARE " + json.dumps(native, ensure_ascii=False), flush=True)
        probe.close()

    @commands.command()
    def retire(app_handle: AppHandle) -> None:
        checks["destroyed"] = destroyed.wait(3)
        old = windows["probe"]
        for name, operation in (
            ("current", old.current_monitor),
            ("primary", old.primary_monitor),
            ("available", old.available_monitors),
            ("point", lambda: old.monitor_from_point(0, 0)),
        ):
            rejected("closed_" + name, operation, "window_closed")
        before = [describe(monitor) for monitor in snapshots]
        fresh = WebviewWindowBuilder.build(
            app_handle, "probe", WebviewUrl.App("quiet.html"), title="重建显示器验收", icon=second
        )
        checks["fresh"] = fresh.current_monitor() is not None
        rejected("generation", old.available_monitors, "window_closed")
        checks["snapshot_after_close"] = [describe(monitor) for monitor in snapshots] == before

    @commands.command()
    def finish(app_handle: AppHandle) -> None:
        print("DISPLAY_IMAGE_RESULT " + json.dumps(checks, sort_keys=True), flush=True)
        app_handle.exit(0 if all(checks.values()) else 1)

    @commands.command()
    def diagnostic(body: str, app_handle: AppHandle) -> None:
        app_handle.exit(1)

    with start_blocking_portal() as portal:
        app = builder_factory().build(context=context_factory(root), invoke_handler=commands.generate_handler(portal))
        code = app.run_return()
    for name, operation in (
        ("current", windows["main"].current_monitor),
        ("primary", windows["main"].primary_monitor),
        ("available", windows["main"].available_monitors),
        ("point", lambda: windows["main"].monitor_from_point(0, 0)),
    ):
        rejected("app_" + name, operation, "app_closed")
        assert checks["app_" + name]
    assert snapshots and all(describe(monitor)["size"] != (0, 0) for monitor in snapshots)
    print("DISPLAY_IMAGE_RESOURCES_RELEASED", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
