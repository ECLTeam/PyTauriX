# ============================================================
# PytaruiX
# 文件作用：双窗口验证注入、旧字节协议、监听器与受控退出。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import json
import os
import threading
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from anyio.from_thread import start_blocking_portal
from pytaruix import (
    AppHandle,
    BindingError,
    Commands,
    Emitter,
    Event,
    ExitRequestApi,
    Headers,
    Listener,
    Manager,
    RunEvent,
    RunEventType,
    State,
    WebviewWindow,
    builder_factory,
    context_factory,
)


@dataclass
class Shared:
    """
    保存跨窗口共享状态，显式同步命令线程与主线程。
    """

    lock: threading.Lock = field(default_factory=threading.Lock)
    seen: set[str] = field(default_factory=set)
    report_by_window: dict[str, dict[str, bool]] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)
    setup_done: bool = False
    exiting: bool = False


class EventRecorder:
    """
    记录事件，便于通过弱引用确认退出释放回调对象。
    """

    def __init__(self, shared: Shared, name: str) -> None:
        self.shared = shared
        self.name = name

    def __call__(self, event: Event) -> None:
        self.shared.events.append(self.name)
        assert json.loads(event.payload()) == {"check": True}
        assert isinstance(event.id(), int)


def main() -> int:
    """
    运行双窗口验收，输出由真实前端和 Python 联合核验的证据。

    :return: 原生退出代码
    """
    mode = os.getenv("PYTARUIX_FAILURE_MODE", "normal")
    commands = Commands()
    state_ref: weakref.ReferenceType[Shared] | None = None
    recorder_ref: weakref.ReferenceType[EventRecorder] | None = None
    saved_api: ExitRequestApi | None = None
    exit_requests = 0
    removed_listener: int | None = None

    def setup(handle: AppHandle) -> None:
        nonlocal recorder_ref, removed_listener
        if mode == "setup":
            raise ValueError("intentional setup failure")
        shared = Manager.state(handle, Shared)
        shared.setup_done = True
        assert Manager.get_webview_window(handle, "main") is not None
        assert Manager.get_webview_window(handle, "secondary") is not None
        recorder = EventRecorder(shared, "live")
        recorder_ref = weakref.ref(recorder)
        Listener.listen(handle, "native-check", recorder)
        Listener.once(handle, "native-check", EventRecorder(shared, "once"))
        removed_listener = Listener.listen(handle, "native-check", EventRecorder(shared, "removed"))
        Listener.unlisten(handle, removed_listener)
        Listener.unlisten(handle, removed_listener)
        Listener.listen(handle, "failure-check", fail_listener)
        print("SETUP_OK", flush=True)

    def fail_listener(event: Event) -> None:
        raise LookupError("intentional listener failure")

    def on_event(handle: AppHandle, event: RunEventType) -> None:
        nonlocal saved_api, exit_requests
        if isinstance(event, RunEvent.Ready):
            print("NATIVE_READY", flush=True)
            if mode == "listener":
                Emitter.emit(handle, "failure-check", None)
        elif isinstance(event, RunEvent.ExitRequested):
            exit_requests += 1
            if mode == "normal" and exit_requests == 1 and event.code == 0:
                event.api.prevent_exit()
                saved_api = event.api
                print("EXIT_PREVENTED", flush=True)
                # 同步回调结束后，请求在下一轮事件分发中执行。
                handle.exit(0)
            elif mode == "normal" and saved_api is not None:
                assert saved_api is not None
                try:
                    saved_api.prevent_exit()
                except BindingError as error:
                    assert "request_expired" in str(error)
                    print("EXIT_API_EXPIRED_OK", flush=True)
                else:
                    raise AssertionError("Expired exit API remained active")
        elif isinstance(event, RunEvent.Exit):
            print("EXIT_ALLOWED", flush=True)

    @commands.command()
    def probe(
        claimed_label: str,
        webview_window: WebviewWindow,
        headers: Headers,
        shared: Annotated[Shared, State()],
        wrapped: State[Shared],
        app_handle: AppHandle,
    ) -> dict[str, object]:
        assert shared is wrapped.value
        assert shared is Manager.state(app_handle, Shared)
        label = webview_window.label()
        assert claimed_label != label
        assert any(name == b"x-migration" and value == b"legacy-client" for name, value in headers)
        assert shared.setup_done
        with shared.lock:
            shared.seen.add(label)
            count = len(shared.seen)
        return {"label": label, "shared_count": count, "setup": True, "headers": True}

    @commands.command()
    def empty() -> str:
        return "empty-ok"

    @commands.command()
    def raw(body: bytes) -> bytes:
        return body[::-1]

    @commands.command()
    def scalar(body: int) -> int:
        return body + 1

    @commands.command()
    def fail() -> None:
        raise RuntimeError("private payload must not escape")

    @commands.command()
    def events(app_handle: AppHandle, shared: State[Shared]) -> bool:
        with shared.value.lock:
            if not shared.value.events:
                Emitter.emit(app_handle, "native-check", {"check": True})
                Emitter.emit(app_handle, "native-check", {"check": True})
            return shared.value.events.count("once") == 1 and shared.value.events.count("live") == 2

    @commands.command()
    def ready(shared: State[Shared], app_handle: AppHandle) -> bool:
        with shared.value.lock:
            both = shared.value.seen == {"main", "secondary"}
        if both:
            Emitter.emit_to(app_handle, "secondary", "target-check", {"target": "secondary"})
        return both

    @commands.command()
    def report(
        body: dict[str, bool], webview_window: WebviewWindow, shared: State[Shared], app_handle: AppHandle
    ) -> None:
        with shared.value.lock:
            shared.value.report_by_window[webview_window.label()] = body
            if len(shared.value.report_by_window) == 2 and not shared.value.exiting:
                shared.value.exiting = True
                success = all(all(checks.values()) for checks in shared.value.report_by_window.values())
                print("DUAL_RESULT " + json.dumps(shared.value.report_by_window, sort_keys=True), flush=True)
                app_handle.exit(0 if success else 1)

    @commands.command()
    def diagnostic(body: str, app_handle: AppHandle) -> None:
        print("JS_ERROR " + body, flush=True)
        app_handle.exit(1)

    with start_blocking_portal() as portal:
        app = builder_factory().build(
            context=context_factory(Path(__file__).resolve().parent),
            invoke_handler=commands.generate_handler(portal),
            setup=setup,
        )
        handle = app.handle()
        shared = Shared()
        state_ref = weakref.ref(shared)
        assert Manager.manage(app, shared)
        assert not Manager.manage(handle, Shared())
        assert Manager.state(handle, Shared) is shared
        del shared
        print("BUILD_HANDLE_OK", flush=True)
        try:
            code = app.run_return(on_event)
        except (ValueError, LookupError) as error:
            expected = f"intentional {'setup' if mode == 'setup' else 'listener'} failure"
            if str(error) != expected:
                raise
            print("FAILURE_RECOVERED " + mode, flush=True)
            code = 0
        assert state_ref() is None
        assert recorder_ref is None or recorder_ref() is None
        for operation in (lambda: handle.exit(0), lambda: Manager.try_state(handle, Shared), lambda: app.handle()):
            try:
                operation()
            except BindingError as error:
                assert "app_closed" in str(error)
            else:
                raise AssertionError("Closed handle operation succeeded")
        print("RESOURCES_RELEASED_OK", flush=True)
        if mode == "normal":
            assert exit_requests == 2
        return code


if __name__ == "__main__":
    raise SystemExit(main())
