# ============================================================
# PyTauriX
# 文件作用：定义框架与 IPC 边界的稳定异常。
# 公开接口：BindingError、CommandError。
# ============================================================
from __future__ import annotations

from ._native import BindingError

__all__ = ["BindingError", "CommandError"]


class CommandError(Exception):
    """
    保存可安全返回前端的命令失败代码与说明。

    :param code: 稳定错误码
    :param message: 不包含凭据或隐私输入的用户可读说明
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
