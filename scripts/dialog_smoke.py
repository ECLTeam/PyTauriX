# ============================================================
# PytaruiX
# 文件作用：通过已创建进程的真实 Windows 控件验收文件/消息、生命周期及 ACL。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from dialog_windows import DesktopDialogs


def _exercise(root: Path, mode: str) -> None:
    output: list[str] = []
    lines: queue.Queue[str | None] = queue.Queue()
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTARUIX_FAILURE_MODE=mode)
    log = root / "artifacts" / f"dialog-{sys.version_info.minor}-{mode}-stderr.log"
    log.parent.mkdir(exist_ok=True)
    with log.open("w", encoding="utf-8") as error_log:
        process = subprocess.Popen(
            [sys.executable, str(root / "examples/dialog/main.py")],
            cwd=root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=error_log,
            text=True,
            encoding="utf-8",
        )

        def receive() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        reader = threading.Thread(target=receive, daemon=True)
        reader.start()
        driver: DesktopDialogs | None = None
        current: int | None = None
        requests = 0
        observed: dict[str, int] = {
            "titles": 0,
            "parents": 0,
            "directories": 0,
            "filenames": 0,
            "filters": 0,
            "buttons": 0,
        }
        deadline = time.monotonic() + 180
        try:
            while time.monotonic() < deadline:
                try:
                    line = lines.get(timeout=0.3)
                except queue.Empty:
                    continue
                if line is None:
                    break
                output.append(line)
                if line.startswith("DIALOG_PID "):
                    driver = DesktopDialogs.from_spawned(process.pid, int(line.split()[1]))
                elif line.startswith("DIALOG_REQUEST "):
                    assert driver is not None
                    request = json.loads(line.removeprefix("DIALOG_REQUEST "))
                    title = request["title"]
                    current = driver.wait(title)
                    requests += 1
                    observed["titles"] += 1
                    expected_parent = request["parent"]
                    actual_parent = driver.owner(current)
                    if expected_parent:
                        parent = next(window.hwnd for window in driver.windows() if window.text == expected_parent)
                        assert actual_parent == parent, (actual_parent, parent, title)
                    else:
                        assert actual_parent is None, (actual_parent, title)
                    observed["parents"] += 1
                    kind = request["kind"]
                    if kind == "file":
                        controls = driver.controls(current)
                        address = next(
                            control.text
                            for control in controls
                            if control.id == 1001 and control.kind == "ToolbarWindow32"
                        )
                        assert request["directory"].casefold() in address.casefold(), (address, request["directory"])
                        observed["directories"] += 1
                        if request["filename"]:
                            edit = next(
                                control
                                for control in controls
                                if control.kind == "Edit" and control.id in (1001, 1148, 1152)
                            )
                            assert driver.content(edit) == request["filename"], driver.content(edit)
                            observed["filenames"] += 1
                        if request["filter"]:
                            filter_control = next(
                                control
                                for control in controls
                                if control.kind == "ComboBox" and request["filter"] in driver.content(control)
                            )
                            # 下拉框的当前文本确认为设置的过滤器；目录实际展示结果另作人工验收。
                            assert request["filter"] in driver.content(filter_control), driver.content(filter_control)
                            observed["filters"] += 1
                        if request["cancel"]:
                            driver.click(current, 2)
                        else:
                            paths = request["paths"]
                            driver.enter(
                                current, " ".join('"' + path + '"' for path in paths) if len(paths) > 1 else paths[0]
                            )
                            driver.click(current, 1)
                    elif kind == "message":
                        driver.message_button(current, request["choice"], request["labels"])
                        observed["buttons"] += 1
                    else:
                        assert process.stdin is not None
                        process.stdin.write("DIALOG_VISIBLE\n")
                        process.stdin.flush()
                elif line.startswith("DIALOG_OWNER_CLEARED"):
                    assert driver is not None and current is not None
                    if driver.api.IsWindow(current):
                        driver.click(current, 2)
                    assert process.stdin is not None
                    process.stdin.write("DIALOG_DISMISSED\n")
                    process.stdin.flush()
                elif line.startswith("DIALOG_ERROR "):
                    raise RuntimeError(line)
            else:
                raise RuntimeError("Dialog acceptance process timed out")
            process.wait(timeout=10)
            if process.returncode:
                raise RuntimeError(
                    f"Dialog acceptance failed: {mode}, {process.returncode}; {''.join(output)}; "
                    + log.read_text(encoding="utf-8")
                )
            joined = "".join(output)
            assert "DIALOG_RESOURCES_RELEASED" in joined, joined
            if mode == "normal":
                result = next(
                    json.loads(line.removeprefix("DIALOG_RESULT "))
                    for line in output
                    if line.startswith("DIALOG_RESULT ")
                )
                assert requests == 48 and all(result.values()), (requests, result)
                expected = {
                    "titles": 48,
                    "parents": 48,
                    "directories": 20,
                    "filenames": 12,
                    "filters": 12,
                    "buttons": 28,
                }
                assert observed == expected, observed
                print(
                    "DIALOG_NORMAL_RESULT " + json.dumps({"checks": len(result), "observations": observed}), flush=True
                )
            elif mode.startswith("callback_"):
                assert "DIALOG_FAILURE_RECOVERED " + mode in joined, joined
            elif mode.startswith("app"):
                assert "DIALOG_APP_EXIT_OK " + mode in joined, joined
            else:
                assert "DIALOG_OWNER_CLEARED" in joined and "DIALOG_RESULT " in joined, joined
            print("DIALOG_MODE_PASSED " + mode, flush=True)
        except Exception:
            print("".join(output), flush=True)
            if driver is not None and current is not None and driver.api.IsWindow(current):
                print(driver.controls(current), flush=True)
            raise
        finally:
            if process.poll() is None:
                # 仅终止本脚本创建且尚未结束的启动进程和其后代；包含 venv 重定向层。
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
                process.wait(timeout=10)
            if process.stdin:
                process.stdin.close()
            if process.stdout:
                process.stdout.close()
            reader.join(timeout=2)


def main() -> None:
    """
    运行 48 个真实选择场景及七种失败/关闭场景，不以 mock 替代。
    """
    root = Path(__file__).resolve().parents[1]
    selected = sys.argv[1:] or [
        "normal",
        "callback_exception",
        "callback_awaitable",
        "window_callback",
        "parent_callback",
        "window_blocking",
        "app_callback",
        "app_blocking",
    ]
    for mode in selected:
        _exercise(root, mode)
    print("DIALOG_SMOKE_PASSED", flush=True)


if __name__ == "__main__":
    main()
