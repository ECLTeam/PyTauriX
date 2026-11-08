# ============================================================
# PyTauriX
# 文件作用：提供显式单位的原生尺寸和位置类型。
# 公开接口：LogicalSize、PhysicalSize、LogicalPosition、PhysicalPosition、PhysicalRect。
# ============================================================
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TypeAlias

from ._native import LogicalPosition, LogicalSize, PhysicalPosition, PhysicalRect, PhysicalSize

SizeType: TypeAlias = LogicalSize | PhysicalSize
PositionType: TypeAlias = LogicalPosition | PhysicalPosition


@dataclass(frozen=True, slots=True)
class PhysicalPositionF64:
    """
    保存原生托盘鼠标位置的浮点物理像素快照。

    :param x: 有限横坐标，允许负值与小数
    :param y: 有限纵坐标，允许负值与小数
    :raises ValueError: 坐标非有限数
    无 GUI、线程或应用存活限制。
    """

    x: float
    y: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.x) or not math.isfinite(self.y):
            raise ValueError("Coordinates must be finite")


@dataclass(frozen=True, slots=True)
class Rect:
    """
    保存带显式单位的位置与尺寸快照，不拥有原生资源。

    :param position: 逻辑或物理位置
    :param size: 逻辑或物理尺寸
    无线程或窗口存活限制，允许原生零尺寸。
    """

    position: PositionType
    size: SizeType


__all__ = [
    "LogicalPosition",
    "LogicalSize",
    "PhysicalPosition",
    "PhysicalPositionF64",
    "PhysicalRect",
    "PhysicalSize",
    "PositionType",
    "Rect",
    "SizeType",
]
