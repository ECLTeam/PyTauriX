# PytaruiX
# 文件作用：串行启动自有托盘测试进程并核验原生行为和两类异常恢复。
# 公开接口：无。
from __future__ import annotations

from pathlib import Path

from desktop_smoke import _checks, _run

expected = frozenset(
    """
    app_handle before_loop builder_stable_id button_states callback_close callback_query callback_register
    callback_replaced callbacks_released close_aliases closed_access detached_duplicate_id double_click
    double_target_visible
    duplicate_id enter_move_leave gc_app_owned gc_detached_released global_event global_source invalid_nul
    left_menu_disabled left_menu_enabled lookup_alias main_closed menu_broadcast menu_main_thread menu_removed
    menu_replaced menu_source missing_id mouse_click mouse_main_thread mouse_position native_closed native_hidden
    native_atomic_icon native_icon native_icon_replaced native_menu_selection native_rect native_restored native_tooltip
    no_probe_cross_delivery old_generation_silent probe_listener remove_not_close right_menu same_id_rebuilt
    selected_setters submenu_accepted tooltip_update tray_source two_webviews window_hidden window_owner_survives
    window_restore
    """.split()
)


def main() -> None:
    """
    验收真实系统托盘、窗口恢复、资源引用及异常后返回 Python。

    三个测试进程由本脚本启动；超时仅终止自有进程，不使用未知 PID。
    """
    root = Path(__file__).resolve().parents[1]
    output = _run(root, "tray", "normal")
    checks = _checks(output, "TRAY_RESULT ")
    if set(checks) != expected or not all(checks.values()) or "TRAY_RESOURCES_RELEASED" not in output:
        raise RuntimeError(f"Native tray evidence incomplete: {checks}")
    for mode in ("exception", "awaitable"):
        output = _run(root, "tray", mode)
        if f"TRAY_FAILURE_RECOVERED {mode}" not in output or "TRAY_RESOURCES_RELEASED" not in output:
            raise RuntimeError(f"Tray callback recovery incomplete: {mode}")
    print("TRAY_SMOKE_PASSED")


if __name__ == "__main__":
    main()
