# PytaruiX
# 文件作用：启动真实菜单角色桌面验收，核验全部预定义项。
# 公开接口：无。
from __future__ import annotations

from pathlib import Path

from desktop_smoke import _checks, _run


def main() -> None:
    """
    独立进程核验 17 种预定义角色、About 元数据与菜单挂载。
    """
    output = _run(Path(__file__).resolve().parents[1], "menu_roles", "normal")
    checks = _checks(output, "MENU_ROLES_RESULT ")
    expected = {
        "created",
        "items_are_predefined",
        "separator_text_empty",
        "about_text",
        "quit_text",
        "text_override",
        "menu_size",
        "menu_attached",
        "default_menu",
        "native_icon_text",
        "native_icon_cleared",
        "invalid_native_icon",
    }
    if not expected <= set(checks) or not all(checks.values()):
        raise RuntimeError(f"Menu role evidence incomplete: {checks}")
    print("MENU_ROLES_SMOKE_PASSED")


if __name__ == "__main__":
    main()
