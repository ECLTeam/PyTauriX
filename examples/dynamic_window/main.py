# ============================================================
# PytaruiX
# 文件作用：真实动态窗口、销毁代次、回调及精确来源权限的联合验收。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import gc
import json
import os
import threading
import time
import uuid
import weakref
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from anyio.from_thread import start_blocking_portal
from pytaruix import (
    AppHandle,
    BindingError,
    CloseRequestApi,
    Commands,
    Emitter,
    Manager,
    PageLoadEvent,
    PageLoadPayload,
    WebviewUrl,
    WebviewWindow,
    WindowEvent,
    WindowEventType,
    builder_factory,
    context_factory,
)
from pytaruix.dpi import LogicalPosition, LogicalSize, PhysicalPosition, PhysicalSize
from pytaruix.ffi.image import Image
from pytaruix.webview import WebviewWindowBuilder


def main() -> int:
    """
    运行实际 WebView 场景；失败模式核验原异常归还和回调引用释放。

    :return: 验收退出代码；测试服务器和后台线程随应用退出关闭
    """
    root = Path(__file__).resolve().parent
    mode = os.getenv("PYTARUIX_FAILURE_MODE", "normal")
    label = "child-" + uuid.uuid4().hex
    commands = Commands()
    checks: dict[str, bool] = {}
    reports: dict[str, dict[str, bool]] = {}
    windows: list[WebviewWindow] = []
    callbacks: list[weakref.ReferenceType[Recorder]] = []
    saved_api: CloseRequestApi | None = None
    closes = 0
    destroyed = False
    ready = False
    target_seen = False
    navigated = False
    pages: set[PageLoadEvent] = set()
    denied_navigation = False
    ticks = 0
    stop = threading.Event()
    create_done = threading.Event()

    class ReportServer(BaseHTTPRequestHandler):
        """
        仅监听本机临时端口，接收无 IPC 权限页面的验收证据。
        """

        def do_GET(self) -> None:
            data = (root / "web" / "denied.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            report = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reports[self.path.removeprefix("/")] = report
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), ReportServer)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    server_url = f"http://127.0.0.1:{server.server_port}"

    def background() -> None:
        nonlocal ticks
        while not stop.wait(0.01):
            ticks += 1

    worker = threading.Thread(target=background, daemon=True)
    worker.start()

    class Recorder:
        """
        原生窗口独占持有的回调，弱引用用于验证关闭和失败清理。
        """

        def navigation(self, url: str) -> bool:
            nonlocal denied_navigation
            if mode == "navigation":
                raise ValueError("intentional navigation failure")
            if mode == "navigation_return":
                return "invalid"  # type: ignore[return-value]
            if "blocked.html" in url:
                denied_navigation = True
                return False
            return True

        def page_load(self, window: WebviewWindow, payload: PageLoadPayload) -> None:
            if mode == "page_load":
                raise LookupError("intentional page_load failure")
            assert window.label() == label and payload.url
            pages.add(payload.event)

        def event(self, event: WindowEventType) -> None:
            nonlocal saved_api, closes, destroyed
            if mode == "window_event":
                raise RuntimeError("intentional window_event failure")
            if isinstance(event, WindowEvent.CloseRequested):
                closes += 1
                if closes == 1:
                    event.api.prevent_close()
                    saved_api = event.api
            elif isinstance(event, WindowEvent.Destroyed):
                destroyed = True
                if windows:
                    try:
                        windows[0].title()
                    except BindingError as error:
                        checks["destroyed_callback_invalidates"] = (
                            "window_closed" in str(error)
                            and Manager.get_webview_window(handle, label) is None
                            and label not in Manager.webview_windows(handle)
                        )
                    else:
                        checks["destroyed_callback_invalidates"] = False
            elif isinstance(event, WindowEvent.Resized):
                checks["resize_event"] = isinstance(event.size, PhysicalSize)
            elif isinstance(event, WindowEvent.Moved):
                checks["move_event"] = isinstance(event.position, PhysicalPosition)
            elif isinstance(event, WindowEvent.Focused):
                checks["focus_event"] = isinstance(event.focused, bool)
            try:
                WebviewWindowBuilder.build(handle, "forbidden-in-callback", WebviewUrl.App("child.html"))
            except BindingError as error:
                checks["callback_context"] = "would_block" in str(error)
            else:
                checks["callback_context"] = False

    def setup(app_handle: AppHandle) -> None:
        setup_window = WebviewWindowBuilder.build(
            app_handle, "setup-child", WebviewUrl.App("quiet.html"), visible=False
        )
        assert "setup-child" in Manager.webview_windows(app_handle)
        setup_window.close()
        checks["setup_creation"] = True

    async def async_page_load(window: WebviewWindow, payload: PageLoadPayload) -> None:
        raise AssertionError("Native callbacks must not schedule this coroutine")

    async def create_window(app_handle: AppHandle) -> str:
        if mode == "normal":
            failed_recorder = Recorder()
            failed_ref = weakref.ref(failed_recorder)
            try:
                WebviewWindowBuilder.from_config(
                    app_handle,
                    {"label": "native-failure", "url": "quiet.html", "visible": False, "proxyUrl": "ftp://127.0.0.1:1"},
                    on_navigation=failed_recorder.navigation,
                )
            except BindingError as error:
                checks["native_failure"] = "window_create_failed" in str(error)
            else:
                checks["native_failure"] = False
            del failed_recorder
            gc.collect()
            checks["failed_callback_released"] = failed_ref() is None
            recovered = WebviewWindowBuilder.from_config(
                app_handle,
                {"label": "native-failure", "url": "quiet.html", "visible": False},
                title="失败后重建",
            )
            checks["native_failure_recovery"] = recovered.title() == "失败后重建"
            recovered.close()
        for name, operation, code in (
            (
                "invalid_label",
                lambda: WebviewWindowBuilder.build(app_handle, "bad*", WebviewUrl.App("child.html")),
                "invalid_label",
            ),
            (
                "invalid_size",
                lambda: WebviewWindowBuilder.build(
                    app_handle, "bad-size", WebviewUrl.App("child.html"), inner_size=(-1, 400)
                ),
                "invalid_size",
            ),
        ):
            try:
                operation()
            except BindingError as error:
                checks[name] = code in str(error)
            else:
                checks[name] = False
        recorder = Recorder()
        callbacks.append(weakref.ref(recorder))
        before = ticks
        window = await WebviewWindowBuilder.build_async(
            app_handle,
            label,
            WebviewUrl.App("child.html"),
            title="动态子窗口",
            inner_size=(420, 300),
            min_inner_size=(200, 150),
            max_inner_size=(1000, 900),
            visible=False,
            focused=False,
            initialization_script="window.stage3Init = 'ready';",
            background_color=(240, 242, 245, 255),
            icon=Image(bytes([80, 120, 220, 255]) * 256, 16, 16),
            on_navigation=recorder.navigation,
            on_page_load=async_page_load if mode == "page_load_awaitable" else recorder.page_load,
            on_window_event=recorder.event,
        )
        windows.append(window)
        alias = Manager.get_webview_window(app_handle, label)
        assert alias is not None
        windows.extend([alias, Manager.webview_windows(app_handle)[label]])
        checks["window_manager"] = Manager.get_webview_window(window, "main") is not None
        checks["background_thread"] = ticks > before
        checks["hidden_creation"] = not window.is_visible()
        checks["title"] = window.title() == "动态子窗口"
        try:
            WebviewWindowBuilder.build(app_handle, label, WebviewUrl.App("child.html"))
        except BindingError as error:
            checks["duplicate"] = "duplicate_window" in str(error)
        window.show()
        window.set_size(PhysicalSize(440, 320))
        window.set_position(PhysicalPosition(180, 160))
        window.set_icon(Image(bytes([30, 80, 140, 255]) * 256, 16, 16))
        WebviewWindowBuilder.build(app_handle, "external", WebviewUrl.External(server_url + "/?kind=external"))
        return label

    @commands.command()
    async def create(app_handle: AppHandle) -> str:
        try:
            return await create_window(app_handle)
        finally:
            create_done.set()

    @commands.command()
    def child_ready(body: dict[str, bool], webview_window: WebviewWindow) -> str:
        nonlocal ready
        assert webview_window.label() == label
        ready = True
        checks.update(body)
        checks["origin"] = webview_window.label() == label
        return label

    @commands.command()
    def child_event() -> None:
        nonlocal target_seen
        target_seen = True

    @commands.command()
    def nav_report() -> None:
        nonlocal navigated
        navigated = True

    @commands.command()
    def forbidden() -> bool:
        checks["unauthorized_command_executed"] = False
        return True

    @commands.command()
    def status(app_handle: AppHandle) -> dict[str, object]:
        return {
            "ready": ready,
            "target_seen": target_seen,
            "navigated": navigated,
            "closes": closes,
            "destroyed": destroyed,
            "gone": label not in Manager.webview_windows(app_handle),
            "reports": len(reports),
        }

    @commands.command()
    def control(body: str, app_handle: AppHandle) -> bool:
        window = windows[0]
        if body == "geometry":
            size, position = window.inner_size(), window.outer_position()
            checks["physical_geometry"] = (size.width, size.height, position.x, position.y) == (440, 320, 180, 160)
            checks["visible"] = window.is_visible()
            window.hide()
        elif body == "hidden":
            checks["hide"] = not window.is_visible()
            window.show()
            window.set_focus()
            window.set_min_size(None)
            window.set_max_size(None)
            window.set_size(LogicalSize(450, 330))
            window.set_position(LogicalPosition(200, 180))
        elif body == "logical":
            scale = window.scale_factor()
            size, position = window.inner_size(), window.outer_position()
            checks["logical_geometry"] = (size.width, size.height, position.x, position.y) == (
                round(450 * scale),
                round(330 * scale),
                round(200 * scale),
                round(180 * scale),
            )
            # 外部测试窗可能异步完成创建并抢到焦点；有限重试后仍须读回真实状态。
            deadline = time.monotonic() + 2
            while not window.is_focused() and time.monotonic() < deadline:
                window.set_focus()
                time.sleep(0.05)
            checks["focus"] = window.is_focused()
            window.maximize()
        elif body == "maximized":
            checks["maximize"] = window.is_maximized()
            window.unmaximize()
        elif body == "restored":
            checks["restore"] = not window.is_maximized()
            window.minimize()
        elif body == "minimized":
            checks["minimize"] = window.is_minimized()
            window.unminimize()
        elif body == "unminimized":
            checks["unminimize"] = not window.is_minimized()
            window.center()
            window.set_fullscreen(True)
        elif body == "fullscreen":
            checks["fullscreen"] = window.is_fullscreen()
            window.set_fullscreen(False)
        elif body == "flags":
            checks["fullscreen_restore"] = not window.is_fullscreen()
            window.set_decorations(False)
            window.set_shadow(False)
            window.set_always_on_top(True)
            window.set_resizable(False)
            window.set_maximizable(False)
            window.set_minimizable(False)
            window.set_closable(False)
            window.set_focusable(False)
            window.set_skip_taskbar(True)
        elif body == "flags_check":
            checks["flags"] = (
                not window.is_decorated()
                and window.is_always_on_top()
                and not window.is_resizable()
                and not window.is_maximizable()
                and not window.is_minimizable()
                and not window.is_closable()
            )
            window.set_decorations(True)
            window.set_shadow(True)
            window.set_always_on_top(False)
            window.set_resizable(True)
            window.set_maximizable(True)
            window.set_minimizable(True)
            window.set_closable(True)
            window.set_focusable(True)
            window.set_skip_taskbar(False)
            Emitter.emit_to(app_handle, label, "dynamic-target", True)
        elif body == "close":
            window.close()
        elif body == "expired_close":
            assert saved_api is not None
            try:
                saved_api.prevent_close()
            except BindingError as error:
                checks["close_expired"] = "request_expired" in str(error)
            checks["close_prevented"] = window.is_visible() and not destroyed
            window.close()
        return True

    @commands.command()
    def retire(app_handle: AppHandle) -> bool:
        gc.collect()
        checks["callbacks_released"] = callbacks[0]() is None
        old_errors = []
        for old in windows:
            try:
                old.set_title("should fail")
            except BindingError as error:
                old_errors.append("window_closed" in str(error))
        checks["old_handle"] = len(old_errors) == 3 and all(old_errors)
        config: dict[str, object] = {"label": label, "url": "quiet.html", "title": "配置窗口", "visible": False}
        original = dict(config)
        fresh = WebviewWindowBuilder.from_config(app_handle, config, title="重建窗口")
        checks["config_unchanged"] = config == original
        checks["same_label_rebuild"] = fresh.title() == "重建窗口" and fresh.label() == label
        recorder = Recorder()
        callbacks.append(weakref.ref(recorder))
        fresh.on_window_event(recorder.event)
        old_errors = []
        for old in windows:
            try:
                old.show()
            except BindingError as error:
                old_errors.append("window_closed" in str(error))
        checks["old_handle_after_rebuild"] = len(old_errors) == 3 and all(old_errors)
        fresh.close()
        return True

    @commands.command()
    def finish(body: bool, app_handle: AppHandle) -> None:
        gc.collect()
        checks["replaced_callback_released"] = all(callback() is None for callback in callbacks)
        checks["target_isolation"] = body and target_seen
        checks["navigation"] = denied_navigation and navigated
        checks["page_load"] = pages == {PageLoadEvent.Started, PageLoadEvent.Finished}
        checks["external_denied"] = reports.get("external") == {"json": True, "legacy": True}
        checks["label_denied"] = reports.get("local") == {"json": True, "legacy": True}
        print("DYNAMIC_RESULT " + json.dumps(checks, sort_keys=True), flush=True)
        app_handle.exit(0 if checks and all(checks.values()) else 1)

    @commands.command()
    def diagnostic(body: str, app_handle: AppHandle) -> None:
        print("JS_ERROR " + body, flush=True)
        app_handle.exit(1)

    config = {
        "app": {
            "windows": [
                {"label": "main", "title": "动态窗口验收", "width": 540, "height": 360},
                {"label": "untrusted", "url": f"denied.html?kind=local&server={server_url}", "visible": False},
            ]
        }
    }
    try:
        with start_blocking_portal() as portal:
            app = builder_factory().build(
                context=context_factory(root, tauri_config=config),
                invoke_handler=commands.generate_handler(portal),
                setup=setup,
            )
            handle = app.handle()
            try:
                WebviewWindowBuilder.build(handle, "too-early", WebviewUrl.App("quiet.html"))
            except BindingError as error:
                checks["before_running"] = "app_not_running" in str(error)
            try:
                code = app.run_return()
            except (ValueError, LookupError, RuntimeError, BindingError) as error:
                if mode == "normal":
                    raise
                expected = (
                    "invalid_callback"
                    if mode in {"navigation_return", "page_load_awaitable"}
                    else f"intentional {mode} failure"
                )
                assert expected in str(error), repr(error)
                print("DYNAMIC_FAILURE_RECOVERED " + mode, flush=True)
                code = 0
            # GUI 回调失败可先结束主循环；建窗命令帧在恢复后才释放自己的回调参数。
            if callbacks:
                assert create_done.wait(3), "In-flight window creation did not finish"
        # 关闭 portal 后再检查最终引用，排除已完成 AnyIO 任务/异常帧的临时持有。
        gc.collect()
        assert all(callback() is None for callback in callbacks)
        print("DYNAMIC_RESOURCES_RELEASED", flush=True)
        return code
    finally:
        stop.set()
        worker.join(timeout=2)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
