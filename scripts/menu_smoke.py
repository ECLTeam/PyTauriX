# PyTauriX
# 文件作用：启动三个独立进程核验真实菜单与失败清理证据。
# 公开接口：无。
from __future__ import annotations

from pathlib import Path

from desktop_smoke import _checks, _run

expected = {
    "check_selection",
    "popup_submenu_default",
    "submenu_updates",
    "item_variants",
    "separator_text",
    "auto_variants",
    "root_container",
    "close_prevented_native",
    "setup_attach",
    "replacement_released",
    "before_loop",
    "bar_selection",
    "event_string",
    "event_main_thread",
    "event_owner",
    "callback_query",
    "callback_register",
    "native_text_order",
    "native_initial_flags",
    "native_icon",
    "window_get",
    "lookup",
    "ordered_types",
    "native_updates",
    "native_update_recovery",
    "invalid_index",
    "invalid_negative",
    "invalid_bool_index",
    "invalid_accelerator",
    "invalid_accelerator_create",
    "invalid_nul",
    "invalid_cycle",
    "invalid_type_item",
    "invalid_type_enabled",
    "invalid_type_id",
    "invalid_type_icon",
    "invalid_id_missing",
    "duplicate_insert",
    "removed_alive",
    "duplicate_id",
    "duplicate_id_remove",
    "invalid_transitive_cycle",
    "batch_order",
    "window_alias",
    "shared_submenu",
    "replace",
    "remove",
    "app_alias",
    "app_get",
    "app_native",
    "app_remove",
    "probe_callback_owned",
    "popup_menu",
    "popup_submenu",
    "popup_logical",
    "worker",
    "worker_done",
    "clear_references",
    "window_ownership",
    "destroyed",
    "closed_callback_released",
    "closed_get",
    "closed_set",
    "closed_remove",
    "closed_listen",
    "closed_clear",
    "closed_popup",
    "closed_construct",
    "app_resource_survives",
    "generation",
    "event_after_rebuild",
    "event_clear_and_generation",
    "fresh_native",
}


def main() -> None:
    """
    验收菜单读回、真实选择、两类回调失败及资源释放；进程均由本脚本创建。
    """
    root = Path(__file__).resolve().parents[1]
    output = _run(root, "menu", "normal")
    checks = _checks(output, "MENU_RESULT ")
    if set(checks) != expected or not all(checks.values()) or "MENU_RESOURCES_RELEASED" not in output:
        raise RuntimeError(f"Native menu evidence incomplete: {checks}")
    for mode in ("exception", "awaitable"):
        output = _run(root, "menu", mode)
        if "MENU_FAILURE_RECOVERED " + mode not in output or "MENU_RESOURCES_RELEASED" not in output:
            raise RuntimeError(f"Menu callback recovery incomplete: {mode}")
    print("MENU_SMOKE_PASSED")


if __name__ == "__main__":
    main()
