# PytaruiX
# 文件作用：在真实 WebView 验收 TOML、宿主 ACL、开发来源、图标与 ECL 注入形状。
# 公开接口：无。
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from anyio.from_thread import start_blocking_portal
from pytaruix import (
    AppHandle,
    BindingError,
    Commands,
    Manager,
    RunEvent,
    RunEventType,
    WebviewUrl,
    WebviewWindow,
    WindowEvent,
    builder_factory,
    context_factory,
)
from pytaruix.ffi.image import Image
from pytaruix.webview import WebviewWindowBuilder

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from display_windows import DesktopDisplay


def main() -> int:
    """
    两个独立 HTTP 来源与生产资源分别验证；仅操作本进程窗口与服务。
    """
    root = Path(__file__).resolve().parent
    mode = os.getenv("PYTARUIX_FAILURE_MODE", "production")
    reports: dict[str, object] = {}
    checks: dict[str, bool] = {}
    commands = Commands()
    handles: list[AppHandle] = []
    windows: list[WebviewWindow] = []
    closed = threading.Event()
    expected = {"main-denied"} if mode == "deny" else {"main", "theme-studio", "plugin:smoke", "rogue", "external"}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            data = (root / "web" / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            report = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reports[report["label"]] = report["checks"]
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            if set(reports) == expected:
                handles[0].exit(0)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    external = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    for service in (server, external):
        threading.Thread(target=service.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    external_origin = f"http://127.0.0.1:{external.server_port}"
    source = origin if mode == "development" else "http://tauri.localhost"
    config: dict[str, object] = {"build": {"devUrl": origin}}
    if mode == "deny":
        config["app"] = {"security": {"capabilities": [{"identifier": "deny-all", "permissions": []}]}}

    def script(label: str) -> str:
        return (
            "window.__HOST_ACCEPTANCE__="
            + json.dumps(
                {
                    "label": label,
                    "reportUrl": origin + "/report",
                    "expectedOrigin": source,
                }
            )
            + ";"
        )

    @commands.command()
    def identify(body: dict[str, object], app_handle: AppHandle, webview_window: WebviewWindow) -> dict[str, object]:
        assert isinstance(app_handle, AppHandle) and isinstance(webview_window, WebviewWindow)
        if webview_window.label() == "main" and os.name == "nt":
            desktop = DesktopDisplay()
            image = Image.from_path(root / "../display_image/icons/builder.png")
            width, height, pixels = desktop.icon(desktop.hwnd("ECL Host Acceptance"))
            checks["native_host_icon"] = (width, height, pixels) == (image.width, image.height, image.rgba)
        return {"body": body, "label": webview_window.label()}

    @commands.command()
    def restore(webview_window: WebviewWindow) -> bool:
        deadline = time.monotonic() + 3
        while not webview_window.is_minimized() and time.monotonic() < deadline:
            time.sleep(0.02)
        minimized = webview_window.is_minimized()
        webview_window.unminimize()
        return minimized

    @commands.command()
    def close_observed() -> bool:
        return closed.wait(3)

    @commands.command()
    def devtools(webview_window: WebviewWindow) -> bool:
        webview_window.open_devtools()
        if os.name == "nt":
            for operation in (webview_window.close_devtools, webview_window.is_devtools_open):
                try:
                    operation()
                except BindingError as error:
                    assert "platform_unavailable" in str(error)
                else:
                    return False
        return True

    def setup(app_handle: AppHandle) -> None:
        handles.append(app_handle)
        # 禁用配置中自动窗口，以可验证的初始化脚本创建主/子窗口。
        for label in expected:
            window = WebviewWindowBuilder.build(
                app_handle,
                "main" if label == "main-denied" else label,
                WebviewUrl.External(external_origin) if label == "external" else WebviewUrl.App("index.html"),
                title="ECL Host Acceptance" if label.startswith("main") else label,
                inner_size=(500, 320),
                initialization_script=script(label),
            )
            windows.append(window)
            if label == "theme-studio":

                def prevent(event: object) -> None:
                    if isinstance(event, WindowEvent.CloseRequested):
                        event.api.prevent_close()
                        closed.set()

                window.on_window_event(prevent)

    def run_event(app_handle: AppHandle, event: RunEventType) -> None:
        if isinstance(event, RunEvent.Ready):
            window = Manager.get_webview_window(app_handle, "main")
            assert window is not None
            try:
                window.open_devtools()
            except BindingError as error:
                checks["devtools_callback_guard"] = "blocking_callback" in str(error)

    config.setdefault("app", {})["windows"] = []  # type: ignore[index]
    context = context_factory(root, tauri_config=config, dev=mode == "development")
    with start_blocking_portal() as portal:
        app = builder_factory().build(context=context, invoke_handler=commands.generate_handler(portal), setup=setup)
        handle = app.handle()
        timer = threading.Timer(30, lambda: handle.exit(2))
        timer.daemon = True
        timer.start()
        result = app.run_return(run_event)
        timer.cancel()
    for service in (server, external):
        service.shutdown()
        service.server_close()
    checks["reports"] = set(reports) == expected
    checks["host_results"] = all(
        isinstance(report, dict) and report and all(value is True for value in report.values())
        for report in reports.values()
    )
    print("HOST_REPORTS " + json.dumps(reports, ensure_ascii=False))
    print("HOST_RESULT " + json.dumps(checks))
    assert result == 0 and all(checks.values()), checks
    for window in windows:
        try:
            window.open_devtools()
        except BindingError as error:
            assert "app_closed" in str(error)
        else:
            raise AssertionError("Closed app accepted devtools")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
