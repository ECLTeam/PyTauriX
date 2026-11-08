# PytaruiX
# 文件作用：发送已序列化 JSON，避免重复编码。
# 公开接口：Emitter。
from __future__ import annotations

from typing import TYPE_CHECKING

from ..event_target import EventTargetType, _target_json

if TYPE_CHECKING:
    from ..manager import ManagerType


class Emitter:
    """
    接收 JSON 文本的底层发送接口；资源状态、JSON 和事件名称由原生边界核验。

    对象或 Pydantic 模型应使用根 Emitter，避免在此接口再次序列化。
    """

    @staticmethod
    def emit_str(manager: ManagerType, event: str, payload: str, /) -> None:
        """
        向全部目标发送已序列化 JSON；执行期间释放 GIL。

        :param manager: 应用、应用句柄或活跃窗口
        :param event: 合法事件名称
        :param payload: JSON 文本，包括对象、标量或 null
        :raises BindingError: 资源关闭、JSON 无效或发送失败
        """
        # 运行期再解析 manager，避免公共 ffi 与高层 Manager 导入循环。
        from ..manager import _event_manager

        _event_manager(manager).emit_json(event, payload)

    @staticmethod
    def emit_str_to(manager: ManagerType, target: EventTargetType | str, event: str, payload: str, /) -> None:
        """
        按明确目标发送 JSON 文本，字符串目标保留 AnyLabel 语义。

        :param manager: 应用、应用句柄或活跃窗口
        :param target: 六种目标之一或标签字符串
        :param event: 合法事件名称
        :param payload: 已序列化 JSON，不能再次序列化
        :raises BindingError: 无效目标、JSON、状态或原生发送失败
        """
        from ..manager import _event_manager

        _event_manager(manager).emit_target_json(_target_json(target), event, payload)
