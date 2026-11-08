# ============================================================
# PyTauriX
# 文件作用：重导出单实例插件契约。
# 公开接口：init。
# ============================================================
from .ffi import SingleInstanceHandler, init

__all__ = ["SingleInstanceHandler", "init"]
