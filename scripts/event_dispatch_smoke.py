# ============================================================
# PytaruiX
# 文件作用：独立进程验收事件路由、主线程任务与回调失败的资源清理。
# 公开接口：无。
# ============================================================
from __future__ import annotations

from pathlib import Path

from desktop_smoke import _checks, _run

event_checks = frozenset(
    {
        "app_task_released",
        "background_thread",
        "frontend_payloads_alpha",
        "frontend_payloads_beta",
        "frontend_payloads_main",
        "frontend_targets_alpha",
        "frontend_targets_beta",
        "frontend_targets_main",
        "generation_isolation",
        "gui_thread",
        "invalid_callback",
        "invalid_json",
        "listener_owner",
        "native_target_matrix",
        "old_listener_rejected",
        "old_task_rejected",
        "once_released",
        "pending_app_cancelled",
        "pending_window_cancelled",
        "rejected_callback_released",
        "task_callback_context",
        "unlisten_released",
        "window_callbacks_released",
        "window_task_before_destroy",
        "window_task_released",
        "worker_submission",
    }
)


def main() -> None:
    """
    运行三窗口联合场景和四个失败场景，所有进程均由本脚本创建并限制超时。
    """
    root = Path(__file__).resolve().parents[1]
    output = _run(root, "event_dispatch", "normal")
    checks = _checks(output, "EVENT_RESULT ")
    if set(checks) != event_checks or not all(checks.values()) or "EVENT_RESOURCES_RELEASED" not in output:
        raise RuntimeError(f"Event and dispatch checks incomplete: {checks}")
    for mode in ("task_exception", "task_awaitable", "listener_exception", "listener_awaitable"):
        output = _run(root, "event_dispatch", mode)
        if f"EVENT_FAILURE_RECOVERED {mode}" not in output or "EVENT_RESOURCES_RELEASED" not in output:
            raise RuntimeError(f"Callback exception or cleanup incomplete: {mode}")
    print("EVENT_DISPATCH_SMOKE_PASSED")


if __name__ == "__main__":
    main()
