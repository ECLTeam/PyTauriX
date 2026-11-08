# PyTauriX
# 文件作用：独立定位通知区域自有测试图标并发送真实鼠标/键盘输入。
# 公开接口：DesktopTray。
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import time
from ctypes import wintypes
from pathlib import Path
from typing import TypedDict, cast

from dialog_windows import DesktopDialogs


class IconBounds(TypedDict):
    name: str
    x: float
    y: float
    width: float
    height: float
    expanded: bool


class DesktopTray:
    """
    通过 Explorer 的 UI Automation 提示定位自有测试图标，再以真实输入操作。

    只允许当前 PID 的唯一提示前缀；不伪造托盘窗口消息或调用 Python 事件。
    """

    def __init__(self) -> None:
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.api.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.api.SetCursorPos.restype = wintypes.BOOL
        self.api.GetSystemMetrics.argtypes = [ctypes.c_int]
        self.api.GetSystemMetrics.restype = ctypes.c_int
        self.api.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        self.api.FindWindowW.restype = wintypes.HWND
        self.api.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.api.GetWindowRect.restype = wintypes.BOOL
        self.api.mouse_event.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_size_t,
        ]
        self.api.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
        self.prefix = f"PyTauriX tray {os.getpid()} "
        self.windows = DesktopDialogs(os.getpid())
        self.api.GetDC.argtypes = [wintypes.HWND]
        self.api.GetDC.restype = wintypes.HDC
        self.api.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        self.gdi.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        self.gdi.GetPixel.restype = wintypes.DWORD

    def has_color(self, bounds: IconBounds, color: tuple[int, int, int]) -> bool:
        """读取经独立定位的自有图标区域像素，验证不透明测试色实际显示。"""
        expected = color[0] | color[1] << 8 | color[2] << 16
        dc = self.api.GetDC(None)
        if not dc:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            center_x = int(bounds["x"] + bounds["width"] / 2)
            center_y = int(bounds["y"] + bounds["height"] / 2)
            return (
                sum(
                    self.gdi.GetPixel(dc, center_x + x, center_y + y) == expected
                    for x in range(-3, 4)
                    for y in range(-3, 4)
                )
                >= 25
            )
        finally:
            self.api.ReleaseDC(None, dc)

    def popup_visible(self) -> bool:
        """独立读取本 PID 的原生菜单窗口，避免对其他应用发送菜单输入。"""
        return any(control.kind == "#32768" for control in self.windows.windows())

    def _query(self, tooltip: str, *, chevron: bool = False) -> IconBounds | None:
        arguments = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(Path(__file__).with_suffix(".ps1")),
        ]
        arguments.extend(["-Chevron"] if chevron else ["-Tooltip", tooltip])
        result = subprocess.run(arguments, capture_output=True, encoding="utf-8", timeout=8, check=False)
        if result.returncode:
            raise RuntimeError("Tray UI Automation query failed: " + result.stderr)
        return cast(IconBounds | None, json.loads(result.stdout))

    def key(self, key: int) -> None:
        """按下并释放一个虚拟键，仅用于已打开的自有菜单导航。"""
        self.api.keybd_event(key, 0, 0, 0)
        self.api.keybd_event(key, 0, 2, 0)

    def taskbar(self) -> None:
        """通过系统 Win+B 快捷键显示通知区域，不修改任务栏设置。"""
        taskbar = self.api.FindWindowW("Shell_TrayWnd", None)
        rect = wintypes.RECT()
        if not taskbar or not self.api.GetWindowRect(taskbar, ctypes.byref(rect)):
            raise RuntimeError("Windows taskbar unavailable")
        # 自动隐藏的任务栏在多次 UIA 查询期间会收回；先以真实指针停留显示区域，
        # 不点击任何应用按钮，也不修改用户任务栏设置。
        left, top = self.api.GetSystemMetrics(76), self.api.GetSystemMetrics(77)
        right = left + self.api.GetSystemMetrics(78) - 1
        bottom = top + self.api.GetSystemMetrics(79) - 1
        horizontal = rect.right - rect.left > rect.bottom - rect.top
        x = round(rect.left + (rect.right - rect.left) * (0.9 if horizontal else 0.5))
        y = round(rect.top + (rect.bottom - rect.top) * (0.5 if horizontal else 0.9))
        self._move(max(left, min(right, x)), max(top, min(bottom, y)))
        self.api.keybd_event(0x5B, 0, 0, 0)
        self.key(0x42)
        self.api.keybd_event(0x5B, 0, 2, 0)
        time.sleep(0.3)

    def _move(self, x: int, y: int) -> None:
        left, top = self.api.GetSystemMetrics(76), self.api.GetSystemMetrics(77)
        width, height = self.api.GetSystemMetrics(78), self.api.GetSystemMetrics(79)
        self.api.mouse_event(
            0xC001, round((x - left) * 65535 / (width - 1)), round((y - top) * 65535 / (height - 1)), 0, 0
        )

    def click(self, bounds: IconBounds, *, right: bool = False, double: bool = False) -> None:
        """在经 UI Automation 核对的图标中心发送真实鼠标输入。"""
        self._move(int(bounds["x"] + bounds["width"] / 2), int(bounds["y"] + bounds["height"] / 2))
        time.sleep(0.1)
        for _ in range(2 if double else 1):
            if double:
                self._move(int(bounds["x"] + bounds["width"] / 2), int(bounds["y"] + bounds["height"] / 2))
            self.api.mouse_event(0x0008 if right else 0x0002, 0, 0, 0, 0)
            self.api.mouse_event(0x0010 if right else 0x0004, 0, 0, 0, 0)
            time.sleep(0.07)

    def hover(self, bounds: IconBounds) -> None:
        """先进入再在图标内移动，确保原生移动事件及离开计时器实际触发。"""
        self.move_away()
        time.sleep(0.1)
        center_x = int(bounds["x"] + bounds["width"] / 2)
        center_y = int(bounds["y"] + bounds["height"] / 2)
        self._move(center_x - 2, center_y)
        time.sleep(0.08)
        self._move(center_x + 2, center_y)
        time.sleep(0.08)
        self._move(center_x, center_y)
        # 锁定 tray-icon 的离开计时器在首次 tick 消费位置；在 15ms 内离开才能独立验收其事件。
        time.sleep(0.003)

    def locate(self, tooltip: str) -> IconBounds:
        """显示通知区域并独立核对完整提示；必要时展开隐藏图标。"""
        if not tooltip.startswith(self.prefix):
            raise ValueError("Only this test process's uniquely named tray icons may be operated")
        self.taskbar()
        found = self._query(tooltip)
        if found is not None and self._test_icon_visible(found):
            return found
        chevron = self._query(tooltip, chevron=True)
        if chevron is not None:
            if chevron["expanded"]:
                self.click(chevron)
                time.sleep(0.15)
            self.click(chevron)
            time.sleep(0.3)
        for _ in range(8):
            found = self._query(tooltip)
            if found is not None and self._test_icon_visible(found):
                return found
            time.sleep(0.2)
        diagnostic = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(Path(__file__).with_suffix(".ps1")),
                "-Tooltip",
                self.prefix,
                "-Inspect",
            ],
            capture_output=True,
            encoding="utf-8",
            timeout=8,
            check=True,
        )
        raise RuntimeError(f"Native tray icon not found: {tooltip}; {diagnostic.stdout}")

    def _test_icon_visible(self, bounds: IconBounds) -> bool:
        # 本场景只使用两种不透明纯色；UIA 布局更新滞后时，不能在旧坐标发送真实输入。
        return self.has_color(bounds, (25, 130, 210)) or self.has_color(bounds, (210, 85, 35))

    def absent(self, tooltip: str) -> bool:
        """读取已打开的通知区域，判断指定自有图标是否不可见。"""
        if not tooltip.startswith(self.prefix):
            raise ValueError("Expected this process's tray tooltip")
        return self._query(tooltip) is None

    def move_away(self) -> None:
        """将指针移出通知区域以验证离开事件，不点击其他应用。"""
        self._move(self.api.GetSystemMetrics(0) // 2, self.api.GetSystemMetrics(1) // 2)

    def choose_first(self) -> None:
        """通过真实方向键与回车选择已打开的自有托盘菜单第一项。"""
        time.sleep(0.2)
        if not self.popup_visible():
            raise RuntimeError("Owned tray menu is not open")
        self.key(0x28)
        self.key(0x0D)
