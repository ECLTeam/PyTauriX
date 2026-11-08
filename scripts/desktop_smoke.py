# ============================================================
# PyTauriX
# 文件作用：在独立进程验收真实 WebView、双窗口与回调失败恢复。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

single_checks = frozenset(
    {
        "async_model",
        "background_thread",
        "event",
        "error",
        "validation",
        "unknown",
        "recovered",
        "window_title",
    }
)
dual_checks = frozenset(
    {
        "origin",
        "setup",
        "headers",
        "native_listeners",
        "raw_bytes",
        "scalar",
        "empty",
        "fail_error",
        "validation",
        "unknown",
        "injected_spoof",
        "recovered",
        "shared_state",
        "target_isolation",
        "unlisten",
        "unlisten_active",
    }
)


def _run(root: Path, example: str, mode: str) -> str:
    environment = dict(os.environ, PYTARUIX_SMOKE="1", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    environment.pop("PYTARUIX_CALLBACK_FAILURE", None)
    environment.pop("PYTARUIX_FAILURE_MODE", None)
    if mode == "lifecycle":
        environment["PYTARUIX_CALLBACK_FAILURE"] = "1"
    else:
        environment["PYTARUIX_FAILURE_MODE"] = mode
    try:
        result = subprocess.run(
            [sys.executable, str(root / "examples" / example / "main.py")],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        captured = error.stdout or b""
        print(captured.decode("utf-8", errors="replace") if isinstance(captured, bytes) else captured, flush=True)
        captured = error.stderr or b""
        print(captured.decode("utf-8", errors="replace") if isinstance(captured, bytes) else captured, flush=True)
        raise RuntimeError("Desktop process timed out before completion") from error
    print(result.stdout, end="")
    if result.returncode:
        raise RuntimeError(f"Desktop smoke failed ({result.returncode}): {result.stderr}")
    return result.stdout


def _checks(output: str, prefix: str) -> dict[str, object]:
    line = next((line for line in output.splitlines() if line.startswith(prefix)), None)
    return json.loads(line.removeprefix(prefix)) if line else {}


def main() -> None:
    """
    启动五次独立桌面进程，核验双方窗口证据、清理和异常归还 Python。

    超时仅终止本脚本创建的进程；macOS/Linux 需在相应平台另外运行。
    """
    root = Path(__file__).resolve().parents[1]
    output = _run(root, "minimal", "normal")
    checks = _checks(output, "SMOKE_RESULT ")
    if set(checks) != single_checks or not all(checks.values()):
        raise RuntimeError(f"Single window checks incomplete: {checks}")
    if any(marker not in output for marker in ("NATIVE_READY", "APP_CONSUMED_OK", "RUNTIME_CONSUMED_OK")):
        raise RuntimeError("Application ownership checks incomplete")
    if "CALLBACK_RECOVERED" not in _run(root, "minimal", "lifecycle"):
        raise RuntimeError("Lifecycle exception did not return to Python")
    output = _run(root, "dual_window", "normal")
    reports = _checks(output, "DUAL_RESULT ")
    if set(reports) != {"main", "secondary"}:
        raise RuntimeError("Both native windows must report")
    for label, report in reports.items():
        if not isinstance(report, dict) or set(report) != dual_checks or not all(report.values()):
            raise RuntimeError(f"Dual window checks incomplete for {label}: {report}")
    if any(
        marker not in output
        for marker in (
            "BUILD_HANDLE_OK",
            "SETUP_OK",
            "NATIVE_READY",
            "EXIT_PREVENTED",
            "EXIT_API_EXPIRED_OK",
            "EXIT_ALLOWED",
            "RESOURCES_RELEASED_OK",
        )
    ):
        raise RuntimeError("Lifecycle or resource cleanup checks incomplete")
    for mode in ("setup", "listener"):
        output = _run(root, "dual_window", mode)
        if f"FAILURE_RECOVERED {mode}" not in output or "RESOURCES_RELEASED_OK" not in output:
            raise RuntimeError(f"Callback recovery or cleanup incomplete: {mode}")
    print("DESKTOP_SMOKE_PASSED")


if __name__ == "__main__":
    main()
