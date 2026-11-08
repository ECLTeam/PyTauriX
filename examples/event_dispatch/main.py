# ============================================================
# PytaruiX
# 文件作用：三窗口目标路由、ECL 调度链路和回调资源生命周期的真实桌面验收。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import gc
import json
import os
import threading
import weakref
from pathlib import Path

from anyio.from_thread import start_blocking_portal
from pytaruix import (
    AppHandle,
    BindingError,
    Commands,
    Emitter,
    Event,
    EventTarget,
    Listener,
    Manager,
    RunEvent,
    RunEventType,
    WebviewUrl,
    WebviewWindow,
    WindowEvent,
    WindowEventType,
    builder_factory,
    context_factory,
)
from pytaruix.ffi import Emitter as FfiEmitter
from pytaruix.webview import WebviewWindowBuilder


def main() -> int:
    """
    验收真实事件路由与主线程任务，失败模式将原始 Python 异常归还。

    :return: 退出代码；本例只测试 Windows WebviewWindow 资源形态
    """
    root = Path(__file__).resolve().parent
    mode = os.getenv("PYTARUIX_FAILURE_MODE", "normal")
    commands = Commands()
    checks: dict[str, bool] = {}
    ready: set[str] = set()
    reports: dict[str, dict[str, object]] = {}
    routes: dict[str, list[str]] = {}
    refs: dict[str, weakref.ReferenceType[Recorder]] = {}
    ids: dict[str, int] = {}
    windows: dict[str, WebviewWindow] = {}
    sent = False
    ticks = 0
    closing_tasks = 0
    closing_submissions = 0
    checks["window_task_before_destroy"] = True
    stop = threading.Event()
    cases = ["Any", "raw", "App", "AnyLabel", "Window", "Webview", "WebviewWindow", "string", "missing"]
    payloads: list[object] = [{"message": "中文🌟"}, 42, "字符串", None, True, [1, "界"], 3.5, {"ecl": "迁移🌟"}]

    def background() -> None:
        nonlocal ticks
        while not stop.wait(0.005):
            ticks += 1

    ticker = threading.Thread(target=background, daemon=True)
    ticker.start()

    class Recorder:
        """
        由原生登记独占拥有的回调；弱引用检查执行、销毁及退出的释放。
        """

        def __init__(self, name: str) -> None:
            self.name = name

        def __call__(self, event: Event | None = None) -> object:
            nonlocal closing_tasks, closing_submissions
            if self.name == "pending_window":
                closing_tasks += 1
                assert closing_tasks < 30, "Native destruction was starved"
                checks["window_task_before_destroy"] = windows["alpha"].title() == "ECL 主线程桥接"
                # CloseRequested 之后仍可能先执行任务；继续排队，销毁必须清掉最后一项。
                submit_from_worker(windows["alpha"], recorder("pending_window"))
                closing_submissions += 1
                return None
            if self.name == "pending_app":
                checks[self.name + "_cancelled"] = False
                return None
            if self.name == "failure":
                if mode.endswith("awaitable"):
                    return coroutine()
                raise LookupError("intentional " + mode + " failure")
            assert event is not None
            routes.setdefault(self.name, []).append(json.loads(event.payload())["case"])
            return None

    async def coroutine() -> None:
        raise AssertionError("Native callbacks must reject this coroutine")

    def recorder(name: str) -> Recorder:
        value = Recorder(name)
        refs[name] = weakref.ref(value)
        return value

    def submit_from_worker(owner: AppHandle | WebviewWindow, callback: Recorder) -> None:
        errors: list[Exception] = []

        def submit() -> None:
            try:
                owner.run_on_main_thread(callback)
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=submit)
        worker.start()
        worker.join(timeout=3)
        assert not worker.is_alive(), "Submission waited for callback completion"
        if errors:
            raise errors[0]

    def window_event(event: WindowEventType) -> None:
        nonlocal closing_submissions
        if isinstance(event, WindowEvent.CloseRequested):
            submit_from_worker(windows["alpha"], recorder("pending_window"))
            closing_submissions += 1

    def setup(handle: AppHandle) -> None:
        for label in ("main", "alpha", "beta"):
            window = (
                Manager.get_webview_window(handle, label)
                if label == "main"
                else WebviewWindowBuilder.build(handle, label, WebviewUrl.App("index.html"), inner_size=(320, 220))
            )
            assert window is not None
            windows[label] = window
            ids[label] = Listener.listen(window, "matrix", recorder(label))
        ids["app"] = Listener.listen(handle, "matrix", recorder("app"))
        ids["any"] = Listener.listen_any(windows["alpha"], "matrix", recorder("any"))
        ids["once"] = Listener.once(windows["alpha"], "matrix", recorder("once"))
        ids["once_any"] = Listener.once_any(windows["beta"], "matrix", recorder("once_any"))
        removed = Listener.listen(windows["beta"], "matrix", recorder("removed"))
        Listener.unlisten(windows["beta"], removed)
        Listener.unlisten(windows["beta"], removed)
        checks["unlisten_released"] = refs["removed"]() is None
        try:
            Listener.unlisten(windows["beta"], ids["alpha"])
        except BindingError as error:
            checks["listener_owner"] = "listener_owner" in str(error)
        windows["alpha"].on_window_event(window_event)

    @commands.command("ready")
    def ready_command(webview_window: WebviewWindow) -> None:
        ready.add(webview_window.label())

    @commands.command()
    def status(app_handle: AppHandle) -> dict[str, object]:
        return {
            "ready": len(ready),
            "sent": sent,
            "reports": len(reports),
            "gone": Manager.get_webview_window(app_handle, "alpha") is None,
        }

    @commands.command()
    def exercise(app_handle: AppHandle) -> None:
        nonlocal sent
        if mode != "normal":
            callback = recorder("failure")
            if mode.startswith("task"):
                submit_from_worker(windows["alpha"], callback)
            else:
                Listener.listen(windows["alpha"], "failure", callback)
                Emitter.emit_to(app_handle, EventTarget.WebviewWindow("alpha"), "failure", None)
            return
        targets = [
            EventTarget.Any(),
            EventTarget.Any(),
            EventTarget.App(),
            EventTarget.AnyLabel("alpha"),
            EventTarget.Window("alpha"),
            EventTarget.Webview("alpha"),
            EventTarget.WebviewWindow("alpha"),
            "alpha",
            EventTarget.WebviewWindow("missing"),
        ]
        for case, target in zip(cases, targets, strict=True):
            if case == "raw":
                FfiEmitter.emit_str(app_handle, "matrix", '{"case":"raw"}')
            else:
                Emitter.emit_to(app_handle, target, "matrix", {"case": case})
        checks["once_released"] = refs["once"]() is None and refs["once_any"]() is None
        for payload in payloads[:-1]:
            FfiEmitter.emit_str_to(
                windows["alpha"], EventTarget.WebviewWindow("alpha"), "payload", json.dumps(payload, ensure_ascii=False)
            )
        try:
            FfiEmitter.emit_str(app_handle, "payload", "{broken")
        except BindingError as error:
            checks["invalid_json"] = "invalid_json" in str(error)
        try:
            windows["alpha"].run_on_main_thread(None)  # type: ignore[arg-type]
        except BindingError as error:
            checks["invalid_callback"] = "invalid_callback" in str(error)
        done = threading.Event()
        before = ticks

        def dispatched() -> None:
            checks["gui_thread"] = threading.current_thread() is threading.main_thread()
            checks["worker_submission"] = threading.current_thread() is not submitting_thread
            windows["alpha"].set_title("ECL 主线程桥接")
            FfiEmitter.emit_str_to(windows["alpha"], EventTarget.WebviewWindow("alpha"), "payload", '{"ecl":"迁移🌟"}')
            try:
                WebviewWindowBuilder.build(app_handle, "forbidden", WebviewUrl.App("quiet.html"))
            except BindingError as error:
                checks["task_callback_context"] = "would_block" in str(error)
            stop.wait(0.02)
            done.set()

        submitting_thread = threading.current_thread()
        windows["alpha"].run_on_main_thread(dispatched)
        assert done.wait(3), "Main-thread task was not executed"
        done.clear()

        def application_task() -> None:
            checks["gui_thread"] &= threading.current_thread() is threading.main_thread()
            done.set()

        app_handle.run_on_main_thread(application_task)
        assert done.wait(3), "Application main-thread task was not executed"
        checks["background_thread"] = ticks > before
        sent = True

    @commands.command()
    def report(body: dict[str, object], webview_window: WebviewWindow) -> None:
        reports[webview_window.label()] = body

    @commands.command()
    def evaluate() -> None:
        native_expected = {
            "app": ["Any", "raw", "App"],
            "main": ["Any", "raw"],
            "beta": ["Any", "raw"],
            "alpha": ["Any", "raw", "AnyLabel", "WebviewWindow", "string"],
            "any": cases,
            "once": ["Any"],
            "once_any": ["Any"],
        }
        checks["native_target_matrix"] = routes == native_expected
        for label, result in reports.items():
            expected = {"Any": cases}
            for kind in ("Window", "Webview", "WebviewWindow"):
                expected[kind] = ["Any", "raw", "AnyLabel", kind, "string"] if label == "alpha" else ["Any", "raw"]
            if label == "main":
                expected["App"] = ["Any", "raw", "App"]
            checks["frontend_targets_" + label] = result["routes"] == expected
            checks["frontend_payloads_" + label] = result["payloads"] == (payloads if label == "alpha" else [])
        if not all(checks.values()):
            print("EVENT_EVIDENCE " + json.dumps({"routes": routes, "reports": reports}), flush=True)

    @commands.command()
    def retire() -> None:
        windows["alpha"].close()

    @commands.command()
    def rebuild(app_handle: AppHandle) -> None:
        gc.collect()
        checks["pending_window_cancelled"] = closing_submissions == closing_tasks + 1
        checks["window_callbacks_released"] = refs["alpha"]() is None and refs["any"]() is None
        checks["window_task_released"] = refs["pending_window"]() is None
        fresh = WebviewWindowBuilder.build(app_handle, "alpha", WebviewUrl.App("quiet.html"), visible=False)
        fired: list[int] = []
        new_id = Listener.listen(fresh, "generation", lambda event: fired.append(event.id()))
        Listener.unlisten(app_handle, ids["alpha"])
        old = windows["alpha"]
        for name, operation in (
            ("old_task_rejected", lambda: old.run_on_main_thread(recorder("rejected"))),
            ("old_listener_rejected", lambda: Listener.unlisten(old, new_id)),
        ):
            try:
                operation()
            except BindingError as error:
                checks[name] = "window_closed" in str(error)
        checks["rejected_callback_released"] = refs["rejected"]() is None
        Emitter.emit_to(app_handle, EventTarget.WebviewWindow("alpha"), "generation", None)
        checks["generation_isolation"] = fired == [new_id]
        fresh.close()

    @commands.command()
    def finish(app_handle: AppHandle) -> None:
        app_handle.exit(0 if checks and all(checks.values()) else 1)

    @commands.command()
    def diagnostic(body: str, app_handle: AppHandle) -> None:
        print("EVENT_JS_ERROR " + body, flush=True)
        app_handle.exit(1)

    def lifecycle(handle: AppHandle, event: RunEventType) -> None:
        if isinstance(event, RunEvent.Exit):
            checks["pending_app_cancelled"] = True
            submit_from_worker(handle, recorder("pending_app"))

    try:
        with start_blocking_portal() as portal:
            app = builder_factory().build(
                context=context_factory(root), invoke_handler=commands.generate_handler(portal), setup=setup
            )
            try:
                code = app.run_return(lifecycle)
            except (LookupError, BindingError) as error:
                if mode == "normal":
                    raise
                expected = "invalid_callback" if mode.endswith("awaitable") else "intentional " + mode + " failure"
                assert expected in str(error), str(error)
                print("EVENT_FAILURE_RECOVERED " + mode, flush=True)
                code = 0
            gc.collect()
            assert all(ref() is None for ref in refs.values()), {name: ref() for name, ref in refs.items()}
            print("EVENT_RESOURCES_RELEASED", flush=True)
            if mode == "normal":
                checks["app_task_released"] = refs["pending_app"]() is None
                print("EVENT_RESULT " + json.dumps(checks, sort_keys=True), flush=True)
                assert all(checks.values()), checks
            return code
    finally:
        stop.set()
        ticker.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
