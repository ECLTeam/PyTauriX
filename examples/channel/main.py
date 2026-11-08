# PytaruiX
# 文件作用：真实双 WebView 的通道数据、终止、缓存与代次验收。
# 公开接口：无。
from __future__ import annotations

import gc
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import cast

import anyio
from anyio.from_thread import start_blocking_portal
from pydantic import BaseModel
from pytaruix import (
    AppHandle,
    BindingError,
    Commands,
    Manager,
    WebviewUrl,
    WebviewWindow,
    builder_factory,
    context_factory,
)
from pytaruix.ffi.ipc import JavaScriptChannelId as FfiId
from pytaruix.ipc import Channel, JavaScriptChannelId
from pytaruix.webview import Webview, WebviewWindowBuilder


class Progress(BaseModel):
    completed: int
    total: int


class Request(BaseModel):
    serial: JavaScriptChannelId[Progress]
    threaded: JavaScriptChannelId[Progress]
    late: JavaScriptChannelId[Progress]
    gc: JavaScriptChannelId[Progress]
    retained: JavaScriptChannelId[Progress]
    raw: JavaScriptChannelId[Progress]


def main() -> int:
    """
    双窗口验收原生 SDK Channel，结束后核验应用失效清理。
    """
    root = Path(__file__).resolve().parent
    commands = Commands()
    checks: dict[str, bool] = {}
    reports: dict[str, dict[str, bool]] = {}
    retained: dict[str, Channel[Progress]] = {}
    old_views: dict[str, Webview] = {}
    windows: dict[str, WebviewWindow] = {}
    releases: dict[str, threading.Event] = {}
    workers: list[threading.Thread] = []
    done = threading.Event()
    abandoned_id: int | None = None

    def rejected(name: str, operation: Callable[[], object], code: str) -> None:
        try:
            operation()
        except BindingError as error:
            checks[name] = str(error).startswith(code + ":")
        else:
            checks[name] = False

    @commands.command()
    async def stream(body: Request, webview_window: WebviewWindow) -> dict[str, int]:
        label = webview_window.label()
        print("CHANNEL_STREAM " + label, flush=True)
        release = threading.Event()
        releases[label] = release
        view = webview_window.as_ref_webview()
        old_views[label] = view
        windows[label] = webview_window
        checks["view_" + label] = view.label() == label and view.app_handle().get_webview_window(label) is not None
        serial = body.serial.channel_on(view)
        rejected("invalid_json_" + label, lambda: serial.send("{bad"), "invalid_json")
        try:
            serial.send(cast(str, bytearray(b"bad")))
        except TypeError:
            checks["invalid_type_" + label] = True
        try:
            serial.send_model(cast(Progress, {"completed": 1}))
        except TypeError:
            checks["invalid_model_" + label] = True
        serial.send_model(Progress(completed=1, total=3))
        for text in (
            '"中文🌟"',
            "null",
            "true",
            "42",
            '[1,"界",{"nested":false}]',
            '{ "log": "原文", "owner": ' + json.dumps(label) + " }",
        ):
            serial.send(text)
        serial.send(b"")
        serial.send(bytes(range(256)))
        serial.send(json.dumps({"large": "界" * 9000, "owner": label}, ensure_ascii=False))
        serial.send(bytes(range(256)) * 512)
        serial.send('"after-large"')
        serial.send("-0.0")
        for length in (8191, 8192, 8193):
            serial.send(json.dumps("x" * (length - 2)))
        for length in (1023, 1024, 1025):
            serial.send(bytes(index % 256 for index in range(length)))
        serial.close()
        serial.close()
        checks["explicit_close_" + label] = serial.closed
        rejected("closed_send_" + label, lambda: serial.send("0"), "channel_closed")
        rejected("closed_invalid_" + label, lambda: serial.send("bad"), "channel_closed")
        threaded = body.threaded.channel_on(view)
        errors: list[Exception] = []

        def produce(producer: int) -> None:
            try:
                for index in range(20):
                    threaded.send(json.dumps({"producer": producer, "index": index, "owner": label}))
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=produce, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        await anyio.to_thread.run_sync(lambda: [thread.join(timeout=5) for thread in threads])
        checks["workers_" + label] = not errors and not any(thread.is_alive() for thread in threads)
        threaded.close()
        gc_channel = body.gc.channel_on(view)
        gc_channel.send('"gc"')
        del gc_channel
        gc.collect()
        retained[label] = body.retained.channel_on(view)
        retained[label].send('"alive"')
        raw = body.raw.root.channel_on(view)
        shared = Channel[Progress](raw)
        raw.send('"ffi"')
        raw.close()
        checks["shared_close_" + label] = shared.closed
        rejected("shared_send_" + label, lambda: shared.send("0"), "channel_closed")
        late = body.late.channel_on(view)

        def delayed() -> None:
            if not release.wait(10):
                return
            late.send_model(Progress(completed=3, total=3))
            late.close()
            done.set()

        worker = threading.Thread(target=delayed, daemon=True)
        workers.append(worker)
        worker.start()
        return {"serial": serial.id(), "threaded": threaded.id(), "late": late.id(), "raw": raw.id()}

    @commands.command()
    def resume(webview_window: WebviewWindow) -> None:
        releases[webview_window.label()].set()

    @commands.command()
    def legacy(body: JavaScriptChannelId[Progress], webview_window: WebviewWindow) -> None:
        channel = body.channel_on(webview_window.as_ref_webview())
        channel.send_model(Progress(completed=2, total=3))
        channel.close()

    @commands.command()
    def report(body: dict[str, bool], webview_window: WebviewWindow) -> None:
        print("CHANNEL_REPORT " + webview_window.label() + " " + json.dumps(body), flush=True)
        reports[webview_window.label()] = body

    @commands.command()
    def status(app_handle: AppHandle) -> dict[str, object]:
        return {
            "reports": len(reports),
            "gone": "secondary" not in Manager.webview_windows(app_handle),
            "abandoned": abandoned_id is not None,
            "cache_checked": "destroyed_cache" in checks,
        }

    @commands.command()
    def abandon(webview_window: WebviewWindow) -> None:
        assert webview_window.label() == "secondary"
        retained["secondary"].send(json.dumps({"abandoned": "x" * 9000}))

    @commands.command()
    def abandoned(body: int, webview_window: WebviewWindow) -> None:
        nonlocal abandoned_id
        assert webview_window.label() == "secondary"
        abandoned_id = body

    @commands.command()
    def cache_id() -> int:
        assert abandoned_id is not None
        return abandoned_id

    @commands.command()
    def cache_report(body: bool, webview_window: WebviewWindow) -> None:
        checks["destroyed_cache"] = body
        webview_window.close()

    @commands.command()
    def retire() -> None:
        windows["secondary"].close()

    @commands.command()
    def rebuild(app_handle: AppHandle) -> None:
        checks["window_closed"] = retained["secondary"].closed
        rejected("old_send", lambda: retained["secondary"].send("0"), "window_closed")
        rejected(
            "old_view", lambda: FfiId.from_str("__CHANNEL__:0").channel_on(old_views["secondary"]), "window_closed"
        )
        rejected("old_window", lambda: windows["secondary"].as_ref_webview(), "window_closed")
        fresh = WebviewWindowBuilder.build(app_handle, "secondary", WebviewUrl.App("quiet.html"), visible=False)
        checks["fresh_view"] = fresh.as_ref_webview().label() == "secondary"
        rejected("generation", lambda: retained["secondary"].send("0"), "window_closed")

    @commands.command()
    def finish(app_handle: AppHandle) -> None:
        for label, report in reports.items():
            checks.update({f"frontend_{label}_{key}": value for key, value in report.items()})
        assert done.wait(2)
        print("CHANNEL_RESULT " + json.dumps(checks, sort_keys=True), flush=True)
        app_handle.exit(0 if len(reports) == 2 and all(checks.values()) else 1)

    @commands.command()
    def diagnostic(body: str, app_handle: AppHandle) -> None:
        print("CHANNEL_JS_ERROR " + body, flush=True)
        app_handle.exit(1)

    with start_blocking_portal() as portal:
        app = builder_factory().build(context=context_factory(root), invoke_handler=commands.generate_handler(portal))
        print("CHANNEL_NATIVE_READY", flush=True)
        code = app.run_return()
    for worker in workers:
        worker.join(timeout=2)
    assert retained["main"].closed
    rejected("app_send", lambda: retained["main"].send("0"), "app_closed")
    rejected("app_view", lambda: FfiId.from_str("__CHANNEL__:0").channel_on(old_views["main"]), "app_closed")
    retained["main"].close()
    assert checks["app_send"] and checks["app_view"]
    print("CHANNEL_RESOURCES_RELEASED", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
