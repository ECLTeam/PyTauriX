# ============================================================
# PytaruiX
# 文件作用：重导出全局快捷键插件契约。
# 公开接口：GlobalShortcut、ShortcutHandler、init。
# ============================================================
from .ffi import GlobalShortcut, ShortcutHandler, init

__all__ = ["GlobalShortcut", "ShortcutHandler", "init"]
