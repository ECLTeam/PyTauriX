# ============================================================
# PyTauriX
# 文件作用：模拟 ECL 工作线程选择文件，并验收真实 dialog 与资源生命周期。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import gc
import json
import os
import threading
import uuid
import weakref
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import anyio
from anyio.from_thread import start_blocking_portal
from pytaurix import (
    AppHandle,
    BindingError,
    Commands,
    Manager,
    WebviewUrl,
    WebviewWindow,
    builder_factory,
    context_factory,
)
from pytaurix.plugins.dialog import (
    DialogExt,
    FileDialogBuilder,
    FileDialogBuilderArgs,
    MessageDialogBuilder,
    MessageDialogBuilderArgs,
    MessageDialogButtons,
    MessageDialogKind,
    init,
)
from pytaurix.webview import WebviewWindowBuilder


def main() -> int:
    """
    在真实 WebView 中运行文件、消息、回调错误和窗口/应用关闭场景。
    """
    print(f"DIALOG_PID {os.getpid()}", flush=True)
    root = Path(__file__).resolve().parent
    mode = os.getenv("PYTARUIX_FAILURE_MODE", "normal")
    prefix = "pytaurix-dialog-" + uuid.uuid4().hex
    commands = Commands()
    checks: dict[str, bool] = {}
    references: list[weakref.ReferenceType[Receiver]] = []
    windows: dict[str, WebviewWindow] = {}
    boxes: list[FileDialogBuilder] = []
    stop = threading.Event()
    ticks = 0

    def tick() -> None:
        nonlocal ticks
        while not stop.wait(0.005):
            ticks += 1

    ticker = threading.Thread(target=tick, daemon=True)
    ticker.start()

    class Receiver:
        """
        原生登记独占的同步回调，执行或关闭后须释放。
        """

        def __init__(self, event: threading.Event, results: list[object]) -> None:
            self.event = event
            self.results = results

        def __call__(self, value: object) -> object:
            if mode.startswith("callback_"):
                self.event.set()
            if mode == "callback_exception":
                raise LookupError("intentional dialog failure")
            if mode == "callback_awaitable":
                return coroutine()
            if mode.endswith("callback"):
                raise AssertionError("Late callback ran after owner closed")
            self.results.append(value)
            try:
                boxes[0].blocking_pick_file()
            except BindingError as error:
                assert "would_block" in str(error), str(error)
                checks["callback_block_rejected"] = True
            else:
                raise AssertionError("Blocking inside dialog callback accepted")
            self.event.set()
            return None

    async def coroutine() -> None:
        raise AssertionError("Native callback executed awaitable")

    def receiver(event: threading.Event, results: list[object]) -> Receiver:
        value = Receiver(event, results)
        references.append(weakref.ref(value))
        return value

    def request(title: str, **parameters: object) -> None:
        print("DIALOG_REQUEST " + json.dumps({"title": title, **parameters}, ensure_ascii=False), flush=True)

    async def until(predicate: Callable[[], bool]) -> None:
        for _ in range(150):
            if predicate():
                return
            await anyio.sleep(0.02)
        raise AssertionError("Dialog lifecycle timed out")

    async def file_case(
        box: FileDialogBuilder,
        operation: str,
        options: FileDialogBuilderArgs,
        *,
        blocking: bool,
        expected: object,
        title: str,
    ) -> None:
        before = ticks
        if blocking:
            value = await anyio.to_thread.run_sync(lambda: getattr(box, "blocking_" + operation)(**options))
        else:
            event = threading.Event()
            results: list[object] = []
            getattr(box, operation)(receiver(event, results), **options)
            assert await anyio.to_thread.run_sync(lambda: event.wait(20)), "Native callback timed out"
            value = results[0]
            await until(lambda: references[-1]() is None)
        if isinstance(expected, list):
            assert isinstance(value, list) and all(isinstance(path, Path) for path in value), repr(value)
            assert set(value) == set(expected), (value, expected)
        else:
            assert value == expected and (value is None or isinstance(value, Path)), (value, expected)
        checks[title] = True
        checks["gil_released"] = ticks > before

    async def message_case(
        box: MessageDialogBuilder,
        options: MessageDialogBuilderArgs,
        *,
        blocking: bool,
        expected: bool,
        title: str,
    ) -> None:
        if blocking:
            value = await anyio.to_thread.run_sync(lambda: box.blocking_show(**options))
        else:
            event = threading.Event()
            results: list[object] = []
            box.show(receiver(event, results), **options)
            assert await anyio.to_thread.run_sync(lambda: event.wait(20))
            value = results[0]
            await until(lambda: references[-1]() is None)
        assert type(value) is bool and value is expected, (title, value, expected)
        checks[title] = True

    def setup(handle: AppHandle) -> None:
        main_window = Manager.get_webview_window(handle, "main")
        assert main_window is not None
        main_window.set_title(prefix + "-main")
        windows["main"] = main_window
        boxes.append(DialogExt.file(main_window))
        try:
            boxes[0].blocking_pick_file()
        except BindingError as error:
            assert "would_block" in str(error)
            checks["gui_block_rejected"] = True
        else:
            raise AssertionError("GUI dialog blocked")
        try:
            boxes[0].pick_file(cast(Callable[[Path | None], object], None))
        except BindingError as error:
            assert "invalid_callback" in str(error)
            checks["invalid_callback"] = True
        else:
            raise AssertionError("None entered private blocking API")

    @commands.command()
    async def exercise(app_handle: AppHandle) -> dict[str, object]:
        if mode != "normal":
            return await lifecycle(app_handle)
        with TemporaryDirectory(prefix="pytaurix-dialog-中文-") as temporary:
            directory = Path(temporary).resolve()
            files = [directory / "文件一.txt", directory / "文件二.txt"]
            folders = [directory / "目录一", directory / "目录二"]
            for path in files:
                path.write_text("dialog test", encoding="utf-8")
            (directory / "filtered.bin").write_bytes(b"excluded")
            for path in folders:
                path.mkdir()
            save = directory / "保存目标.txt"
            expected_values = [files[0], files, folders[0], folders, save]
            operations = ["pick_file", "pick_files", "pick_folder", "pick_folders", "save_file"]
            for blocking in (False, True):
                for operation, expected in zip(operations, expected_values, strict=True):
                    for cancel in (False, True):
                        title = prefix + f"-{operation}-{blocking}-{cancel}"
                        options: FileDialogBuilderArgs = {
                            "set_title": title,
                            "set_directory": directory,
                            "set_can_create_directories": not blocking,
                        }
                        if "folder" not in operation:
                            options["add_filter"] = ("Dialog Text", ["txt"])
                            options["set_file_name"] = "保存目标.txt" if operation == "save_file" else "文件一.txt"
                        if blocking:
                            options["set_parent"] = windows["main"]
                        value = None if cancel else expected
                        paths = expected if isinstance(expected, list) else [expected]
                        request(
                            title,
                            kind="file",
                            cancel=cancel,
                            paths=[str(path) for path in paths],
                            parent=prefix + "-main" if blocking else None,
                            directory=str(directory),
                            filename=options.get("set_file_name"),
                            filter="Dialog Text" if "folder" not in operation else None,
                        )
                        await file_case(boxes[0], operation, options, blocking=blocking, expected=value, title=title)
                        assert not save.exists(), "Save dialog wrote a file"
            variants = [
                (MessageDialogButtons.Ok(), 1, []),
                (MessageDialogButtons.OkCancel(), 2, []),
                (MessageDialogButtons.YesNo(), 2, []),
                (MessageDialogButtons.YesNoCancel(), 3, []),
                (MessageDialogButtons.OkCustom("肯定中文"), 1, ["肯定中文"]),
                (MessageDialogButtons.OkCancelCustom("肯定中文", "取消中文"), 2, ["肯定中文", "取消中文"]),
                (
                    MessageDialogButtons.YesNoCancelCustom("是中文", "否中文", "取消中文"),
                    3,
                    ["是中文", "否中文", "取消中文"],
                ),
            ]
            for blocking in (False, True):
                for variant_index, (buttons, count, labels) in enumerate(variants):
                    for choice in range(count):
                        title = prefix + f"-message-{blocking}-{variant_index}-{choice}"
                        kind = list(MessageDialogKind)[variant_index % 3]
                        options_message: MessageDialogBuilderArgs = {"title": title, "buttons": buttons, "kind": kind}
                        if blocking:
                            options_message["parent"] = windows["main"]
                        request(
                            title,
                            kind="message",
                            choice=choice,
                            labels=labels,
                            text="消息中文🌟",
                            parent=prefix + "-main" if blocking else None,
                        )
                        await message_case(
                            DialogExt.message(windows["main"], "消息中文🌟"),
                            options_message,
                            blocking=blocking,
                            expected=choice == 0,
                            title=title,
                        )
            checks["callbacks_released"] = all(reference() is None for reference in references)
            checks["save_selects_only"] = not save.exists()
            checks["frontend_roundtrip"] = True
            return {"files": [str(path) for path in files], "checks": len(checks)}

    async def lifecycle(handle: AppHandle) -> dict[str, object]:
        title = prefix + "-lifecycle-" + mode
        if mode.startswith("callback_"):
            request(title, kind="message", choice=0, labels=["触发"], text="消息中文🌟", parent=None)
            delivered = threading.Event()
            DialogExt.message(handle, "消息中文🌟").show(
                receiver(delivered, []),
                title=title,
                buttons=MessageDialogButtons.OkCustom("触发"),
            )
            assert await anyio.to_thread.run_sync(lambda: delivered.wait(20))
            await anyio.sleep(0.1)
            return {"checks": len(checks)}
        is_window = mode.startswith(("window", "parent"))
        if is_window:
            windows["secondary"] = await WebviewWindowBuilder.build_async(
                handle,
                "secondary",
                WebviewUrl.App("index.html"),
                title=prefix + "-secondary",
            )
        owner = windows["secondary"] if mode.startswith("window") else handle
        box = DialogExt.file(owner)
        options: FileDialogBuilderArgs = {"set_title": title}
        if mode.startswith("parent"):
            options["set_parent"] = windows["secondary"]
        waiting = threading.Event()
        errors: list[str] = []
        blocking = mode.endswith("blocking")
        if blocking:

            def wait() -> None:
                waiting.set()
                try:
                    box.blocking_pick_file(**options)
                except BindingError as error:
                    errors.append(str(error))
                else:
                    errors.append("accepted after owner closed")

            worker = threading.Thread(target=wait)
            worker.start()
        else:
            box.pick_file(receiver(threading.Event(), []), **options)
            worker = None
        request(
            title, kind="lifecycle", action=mode, parent=prefix + "-secondary" if mode.startswith("parent") else None
        )
        # 驱动确认真实系统窗口出现后，通过 stdin 放行销毁动作。
        assert await anyio.to_thread.run_sync(lambda: input() == "DIALOG_VISIBLE")
        if is_window:
            old = windows["secondary"]
            old.close()
            await until(lambda: Manager.get_webview_window(handle, "secondary") is None)
            if worker is not None:
                await anyio.to_thread.run_sync(lambda: worker.join(3))
                assert not worker.is_alive() and len(errors) == 1 and "window_closed" in errors[0], errors
            else:
                gc.collect()
                await until(lambda: references[-1]() is None)
            try:
                box.pick_file(lambda _: None, **options)
            except BindingError as error:
                assert "window_closed" in str(error), str(error)
            else:
                if not mode.startswith("parent"):
                    raise AssertionError("Old generation accepted a dialog")
            windows["secondary"] = await WebviewWindowBuilder.build_async(
                handle,
                "secondary",
                WebviewUrl.App("index.html"),
                title=prefix + "-rebuilt",
            )
            checks["generation_isolation"] = mode.startswith("parent") or old is not windows["secondary"]
            print("DIALOG_OWNER_CLEARED", flush=True)
            assert await anyio.to_thread.run_sync(lambda: input() == "DIALOG_DISMISSED")
            await anyio.sleep(0.15)
            checks["late_callback_suppressed"] = all(reference() is None for reference in references)
            checks["blocking_woken"] = worker is None or not worker.is_alive()
            return {"checks": len(checks)}
        handle.exit(0)
        # run_return 清理负责唤醒后台等待；主线程外等待，不阻止原生退出。
        if worker is not None:
            await anyio.to_thread.run_sync(lambda: worker.join(3))
            assert not worker.is_alive() and len(errors) == 1 and "app_closed" in errors[0], errors
            checks["blocking_woken"] = True
        return {"checks": len(checks)}

    @commands.command()
    def finish(body: dict[str, bool], app_handle: AppHandle) -> None:
        assert all(body.values()) and body
        checks.update(body)
        print("DIALOG_RESULT " + json.dumps(checks, sort_keys=True), flush=True)
        app_handle.exit(0)

    @commands.command()
    def diagnostic(message: str, app_handle: AppHandle) -> None:
        print("DIALOG_ERROR " + message, flush=True)
        app_handle.exit(1)

    try:
        with start_blocking_portal("asyncio") as portal:
            app = builder_factory().build(
                context=context_factory(root),
                invoke_handler=commands.generate_handler(portal),
                setup=setup,
                plugins=[init()],
            )
            # App 与 AppHandle 入口在 GUI 主线程创建，无隐式父窗口。
            DialogExt.file(app)
            DialogExt.file(app.handle())
            try:
                result = app.run_return()
            except (LookupError, BindingError) as error:
                expected = "invalid_callback" if mode == "callback_awaitable" else "intentional dialog failure"
                assert mode.startswith("callback_") and expected in str(error), str(error)
                print("DIALOG_FAILURE_RECOVERED " + mode, flush=True)
                result = 0
        gc.collect()
        assert all(reference() is None for reference in references), "Dialog callbacks leaked"
        if mode.startswith("app"):
            assert mode == "app_callback" or checks.get("blocking_woken"), checks
            print("DIALOG_APP_EXIT_OK " + mode, flush=True)
        print("DIALOG_RESOURCES_RELEASED", flush=True)
        return result
    finally:
        stop.set()
        ticker.join(2)


if __name__ == "__main__":
    raise SystemExit(main())
