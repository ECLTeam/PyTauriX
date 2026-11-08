# ============================================================
# PytaruiX
# 文件作用：真实桌面示例，同时提供 WebView 自动验收入口。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import anyio
from anyio.from_thread import start_blocking_portal
from pydantic import BaseModel
from pytaruix import AppHandle, Commands, Emitter, Manager, RunEvent, RunEventType, builder_factory, context_factory


class GreetingRequest(BaseModel):
    """
    保存前端提交的姓名。
    """

    name: str


class GreetingResponse(BaseModel):
    """
    返回 Python 问候与运行诊断。
    """

    message: str
    ticks: int


def main() -> int:
    """
    保持异步 portal 和后台线程存活，直到原生窗口退出。

    :return: 应用退出代码
    """
    commands = Commands()
    is_smoke = os.getenv("PYTARUIX_SMOKE") == "1"
    should_fail_callback = os.getenv("PYTARUIX_CALLBACK_FAILURE") == "1"
    stop = threading.Event()
    tick_lock = threading.Lock()
    ticks = 0

    def count_ticks() -> None:
        nonlocal ticks
        while not stop.wait(0.02):
            with tick_lock:
                ticks += 1

    def on_event(app_handle: AppHandle, event: RunEventType) -> None:
        if isinstance(event, RunEvent.Ready):
            print("NATIVE_READY", flush=True)
            if should_fail_callback:
                raise RuntimeError("intentional lifecycle failure")
            window = Manager.get_webview_window(app_handle, "main")
            if window is not None:
                window.set_title("PytaruiX — Python Ready")

    @commands.command()
    def status() -> dict[str, bool]:
        if is_smoke:
            print("JS_CONNECTED", flush=True)
        return {"is_smoke": is_smoke}

    @commands.command()
    def diagnostic(message: str, app_handle: AppHandle) -> None:
        if is_smoke:
            print("JS_ERROR " + message, flush=True)
            app_handle.exit(1)

    @commands.command()
    async def greet(body: GreetingRequest, app_handle: AppHandle) -> GreetingResponse:
        await anyio.sleep(0.05)
        window = Manager.get_webview_window(app_handle, "main")
        if window is not None:
            window.set_title(f"Hello, {body.name}")
        Emitter.emit(app_handle, "python-greeting", {"name": body.name})
        with tick_lock:
            current_ticks = ticks
        return GreetingResponse(message=f"Hello, {body.name}! From Python.", ticks=current_ticks)

    @commands.command()
    def fail() -> None:
        raise RuntimeError("intentional command failure")

    @commands.command()
    def finish(body: dict[str, bool], app_handle: AppHandle) -> None:
        if not is_smoke:
            raise RuntimeError("automatic exit is only available in smoke mode")
        is_success = bool(body) and all(body.values())
        print("SMOKE_RESULT " + json.dumps(body, sort_keys=True), flush=True)
        app_handle.exit(0 if is_success else 1)

    worker = threading.Thread(target=count_ticks, name="example-counter", daemon=True)
    worker.start()
    try:
        with start_blocking_portal("asyncio") as portal:
            context = context_factory(Path(__file__).resolve().parent)
            app = builder_factory().build(context=context, invoke_handler=commands.generate_handler(portal))
            result = app.run_return(on_event)
            if is_smoke:
                try:
                    app.run_return()
                except RuntimeError as error:
                    if "app_consumed" not in str(error):
                        raise
                    print("APP_CONSUMED_OK", flush=True)
                try:
                    builder_factory().build(context=context, invoke_handler=commands.generate_handler(portal))
                except RuntimeError as error:
                    if "runtime_consumed" not in str(error):
                        raise
                    print("RUNTIME_CONSUMED_OK", flush=True)
            return result
    except RuntimeError as error:
        if should_fail_callback and str(error) == "intentional lifecycle failure":
            print("CALLBACK_RECOVERED", flush=True)
            return 0
        raise
    finally:
        stop.set()
        worker.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
