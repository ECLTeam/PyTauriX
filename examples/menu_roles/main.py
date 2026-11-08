# PytaruiX
# 文件作用：真实桌面核验全部预定义菜单角色的构造、文本与挂载。
# 公开接口：无。
from __future__ import annotations

import json
from pathlib import Path

from pytaruix import AppHandle, Commands, builder_factory, context_factory
from pytaruix.menu import AboutMetadata, Menu, PredefinedMenuItem

ROLES = (
    "separator",
    "copy",
    "cut",
    "paste",
    "select_all",
    "undo",
    "redo",
    "minimize",
    "maximize",
    "fullscreen",
    "close_window",
    "quit",
    "hide",
    "hide_others",
    "show_all",
    "services",
    "bring_all_to_front",
)


def main() -> int:
    """
    在 setup 中创建全部角色并挂载菜单，完成后立即退出。

    菜单资源操作不允许在同步 GUI 回调内执行，因此不使用 Ready 回调。
    """
    root = Path(__file__).resolve().parent
    commands = Commands()
    checks: dict[str, bool] = {}

    def setup(app_handle: AppHandle) -> None:
        items = [getattr(PredefinedMenuItem, role)(app_handle) for role in ROLES]
        checks["created"] = len(items) == len(ROLES)
        checks["separator_text_empty"] = items[0].text() == ""
        about = PredefinedMenuItem.about(
            app_handle,
            "About PytaruiX",
            AboutMetadata(name="PytaruiX", version="0.1.0", authors=("ECL",)),
        )
        checks["about_text"] = about.text() == "About PytaruiX"
        quit_item = PredefinedMenuItem.quit(app_handle, "Quit")
        checks["quit_text"] = quit_item.text() == "Quit"
        copy_item = PredefinedMenuItem.copy(app_handle, "Copy")
        copy_item.set_text("Copy Text")
        checks["text_override"] = copy_item.text() == "Copy Text"
        menu = Menu.with_items(app_handle, [*items, about, quit_item])
        listed = menu.items()
        checks["menu_size"] = len(listed) == len(ROLES) + 2
        checks["items_are_predefined"] = all(isinstance(item, PredefinedMenuItem) for item in listed)
        app_handle.set_menu(menu)
        checks["menu_attached"] = app_handle.menu() is not None
        print("MENU_ROLES_RESULT " + json.dumps(checks, sort_keys=True), flush=True)
        app_handle.exit(0 if all(checks.values()) else 1)

    context = context_factory(root)
    app = builder_factory().build(
        context=context,
        invoke_handler=commands.generate_handler(),
        setup=setup,
    )
    return app.run_return()


if __name__ == "__main__":
    raise SystemExit(main())
