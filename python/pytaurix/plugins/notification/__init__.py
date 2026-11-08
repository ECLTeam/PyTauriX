# ============================================================
# PyTauriX
# 文件作用：重导出通知插件契约。
# 公开接口：Notification、init。
# ============================================================
from .ffi import Notification, init

__all__ = ["Notification", "init"]
