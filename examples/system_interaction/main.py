# PytaruiX
# 文件作用：使用真实系统文件源验证 WebView 拖入、移动、离开、释放与焦点。
# 公开接口：无。
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

from anyio.from_thread import start_blocking_portal
from pytaruix import AppHandle, Commands, WebviewUrl, WindowEvent, WindowEventType, builder_factory, context_factory
from pytaruix.webview import WebviewWindowBuilder

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from interaction_windows import DesktopInteraction
from smoke_resources import run_profiled_example


def _run_application(profile: Path) -> int:
    """
    使用自有临时文件与独立源进程产生真实 OLE 事件，不模拟 Python 回调或窗口消息。

    :return: 原生应用退出代码
    """
    records: list[WindowEventType] = []
    lock = threading.Lock()
    checks: dict[str, bool] = {}
    failures: list[str] = []
    worker: threading.Thread | None = None
    title = f"PytaruiX OLE target {os.getpid()}"

    def event(value: WindowEventType) -> None:
        with lock:
            records.append(value)

    def setup(handle: AppHandle) -> None:
        nonlocal worker
        window = WebviewWindowBuilder.build(
            handle,
            "interaction",
            WebviewUrl.App("index.html"),
            title=title,
            data_directory=profile,
            inner_size=(500, 350),
            position=(420, 180),
            always_on_top=True,
            on_window_event=event,
        )

        probe_title = f"PytaruiX focus probe {os.getpid()}"
        probe = WebviewWindowBuilder.build(
            handle,
            "focus-probe",
            WebviewUrl.App("index.html"),
            title=probe_title,
            data_directory=profile / "probe",
            visible=False,
            inner_size=(240, 150),
            position=(1000, 180),
        )

        def drive() -> None:
            try:
                desktop = DesktopInteraction()
                system_focus = desktop.focus(title)
                native_focus = window.is_focused()
                print("SYSTEM_FOCUS_DEBUG " + json.dumps({"system": system_focus, "native": native_focus}), flush=True)
                checks["system_focus"] = system_focus and native_focus
                probe.show()
                checks["focus_loss"] = desktop.focus(probe_title) and probe.is_focused() and not window.is_focused()
                probe.hide()
                checks["focus_restore"] = desktop.focus(title) and window.is_focused()
                window.set_theme("dark")
                time.sleep(0.15)
                window.set_theme("light")
                deadline = time.monotonic() + 2
                themes: set[str] = set()
                while time.monotonic() < deadline:
                    with lock:
                        themes = {item.theme for item in records if isinstance(item, WindowEvent.ThemeChanged)}
                    if themes == {"dark", "light"}:
                        break
                    time.sleep(0.05)
                checks["theme_events"] = themes == {"dark", "light"} and window.theme() == "light"

                with tempfile.TemporaryDirectory(prefix="pytaruix-drop-") as temporary:
                    path = Path(temporary) / "拖放验收.txt"
                    path.write_text("owned drag payload", encoding="utf-8")
                    desktop.drag_file(title, path, leave=True)
                    desktop.drag_file(title, path)
                    with lock:
                        events = tuple(records)
                    checks["drag_enter"] = any(
                        isinstance(item, WindowEvent.DragDropEnter)
                        and tuple(Path(value).resolve() for value in item.paths) == (path.resolve(),)
                        for item in events
                    )
                    checks["drag_over"] = any(isinstance(item, WindowEvent.DragDropOver) for item in events)
                    checks["drag_leave"] = any(isinstance(item, WindowEvent.DragDropLeave) for item in events)
                    checks["drag_drop"] = any(
                        isinstance(item, WindowEvent.DragDropDrop)
                        and tuple(Path(value).resolve() for value in item.paths) == (path.resolve(),)
                        for item in events
                    )
                    checks["file_unchanged"] = path.read_text(encoding="utf-8") == "owned drag payload"
                    print(
                        "SYSTEM_INTERACTION_PATH "
                        + json.dumps(
                            {
                                "expected": str(path),
                                "received": [
                                    item.paths for item in events if isinstance(item, WindowEvent.DragDropDrop)
                                ],
                            }
                        ),
                        flush=True,
                    )
                    print("SYSTEM_INTERACTION_EVENTS " + repr(events), flush=True)
                print("SYSTEM_INTERACTION_RESULT " + json.dumps(checks, sort_keys=True), flush=True)
                handle.exit(0 if all(checks.values()) else 1)
            except Exception:
                failures.append(traceback.format_exc())
                handle.exit(1)

        worker = threading.Thread(target=drive, name="owned-interaction")
        worker.start()

    with start_blocking_portal() as portal:
        app = builder_factory().build(
            context=context_factory(Path(__file__).resolve().parent, tauri_config={"app": {"windows": []}}),
            invoke_handler=Commands().generate_handler(portal),
            setup=setup,
        )
        code = app.run_return()
    if worker is not None:
        worker.join(timeout=5)
        assert not worker.is_alive()
    if failures:
        raise RuntimeError(failures[0])
    return code


def main() -> int:
    """由父进程拥有 WebView profile，在原生进程退出后清理。"""
    return run_profiled_example(Path(__file__).resolve(), "pytaruix-interaction-", _run_application)


if __name__ == "__main__":
    raise SystemExit(main())
