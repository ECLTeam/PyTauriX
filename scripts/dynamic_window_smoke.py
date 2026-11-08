# ============================================================
# PytaruiX
# 文件作用：以独立真实桌面进程验证动态窗口及回调失败模式。
# 公开接口：无。
# ============================================================
from __future__ import annotations

from pathlib import Path

from desktop_smoke import _checks, _run

dynamic_checks = frozenset(
    {
        "background_thread",
        "before_running",
        "callback_context",
        "callbacks_released",
        "close_expired",
        "close_prevented",
        "config_unchanged",
        "destroyed_callback_invalidates",
        "duplicate",
        "external_denied",
        "flags",
        "focus",
        "focus_event",
        "fullscreen",
        "fullscreen_restore",
        "hidden_creation",
        "hide",
        "initialization",
        "invalid_label",
        "invalid_size",
        "label_denied",
        "legacy_ipc",
        "logical_geometry",
        "maximize",
        "minimize",
        "move_event",
        "navigation",
        "old_handle",
        "old_handle_after_rebuild",
        "origin",
        "page_load",
        "physical_geometry",
        "replaced_callback_released",
        "resize_event",
        "restore",
        "same_label_rebuild",
        "setup_creation",
        "target_isolation",
        "title",
        "unminimize",
        "visible",
        "window_manager",
        "native_failure",
        "failed_callback_released",
        "native_failure_recovery",
    }
)


def main() -> None:
    """
    验收动态窗口和五类回调失败；超时只清理自身创建的子进程。
    """
    root = Path(__file__).resolve().parents[1]
    output = _run(root, "dynamic_window", "normal")
    checks = _checks(output, "DYNAMIC_RESULT ")
    if set(checks) != dynamic_checks or not all(checks.values()) or "DYNAMIC_RESOURCES_RELEASED" not in output:
        raise RuntimeError(f"Dynamic window checks incomplete: {checks}")
    for mode in ("navigation", "navigation_return", "page_load", "page_load_awaitable", "window_event"):
        output = _run(root, "dynamic_window", mode)
        if f"DYNAMIC_FAILURE_RECOVERED {mode}" not in output or "DYNAMIC_RESOURCES_RELEASED" not in output:
            raise RuntimeError(f"Callback recovery incomplete: {mode}")
    print("DYNAMIC_WINDOW_SMOKE_PASSED")


if __name__ == "__main__":
    main()
