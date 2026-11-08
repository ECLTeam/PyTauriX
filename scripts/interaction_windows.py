# PyTauriX
# 文件作用：仅在自有窗口区域发送真实鼠标输入，验证系统 OLE 拖放和焦点。
# 公开接口：DesktopInteraction。
from __future__ import annotations

import ctypes
import os
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from dialog_windows import DesktopDialogs


class DesktopInteraction:
    """
    核验本 PID 与自行启动的源进程窗口；每次输入前检查原生窗口归属与遮挡。
    """

    def __init__(self) -> None:
        self.windows = DesktopDialogs(os.getpid())
        self.api = self.windows.api
        signatures = {
            "GetClientRect": ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            "ClientToScreen": ([wintypes.HWND, ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
            "SetCursorPos": ([ctypes.c_int, ctypes.c_int], wintypes.BOOL),
            "WindowFromPoint": ([wintypes.POINT], wintypes.HWND),
            "GetAncestor": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
            "SetForegroundWindow": ([wintypes.HWND], wintypes.BOOL),
            "GetForegroundWindow": ([], wintypes.HWND),
            "mouse_event": ([wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t], None),
        }
        for name, (arguments, result) in signatures.items():
            method = getattr(self.api, name)
            method.argtypes, method.restype = arguments, result

    @staticmethod
    def find(windows: DesktopDialogs, title: str, timeout: float = 8) -> int:
        """
        等待所属 PID 下精确标题的可见顶层窗口，不接受未知进程。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for window in windows.windows():
                if window.text == title:
                    return window.hwnd
            time.sleep(0.05)
        raise RuntimeError(f"Owned interaction window unavailable: {title}")

    def center(self, windows: DesktopDialogs, hwnd: int) -> tuple[int, int]:
        """
        计算已核验窗口的客户区中心，并要求该位置未被其他窗口遮挡。
        """
        windows._own(hwnd)
        rect = wintypes.RECT()
        if not self.api.GetClientRect(hwnd, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        point = wintypes.POINT(rect.right // 2, rect.bottom // 2)
        if not self.api.ClientToScreen(hwnd, ctypes.byref(point)):
            raise ctypes.WinError(ctypes.get_last_error())
        hit = self.api.WindowFromPoint(point)
        if self.api.GetAncestor(hit, 2) != hwnd:
            raise RuntimeError("Owned input location is occluded; refusing system input")
        return point.x, point.y

    def focus(self, title: str) -> bool:
        """
        真实单击本进程窗口客户区并独立读取前台窗口。
        """
        hwnd = self.find(self.windows, title)
        self.api.SetForegroundWindow(hwnd)
        time.sleep(0.1)
        x, y = self.center(self.windows, hwnd)
        self.api.SetCursorPos(x, y)
        self.api.mouse_event(2, 0, 0, 0, 0)
        self.api.mouse_event(4, 0, 0, 0, 0)
        time.sleep(0.1)
        return self.api.GetForegroundWindow() == hwnd

    def drag_file(self, title: str, path: Path, *, leave: bool = False) -> None:
        """
        从自行创建的文件源窗口拖入本进程 WebView；可先离开再回到源窗口释放。

        :param title: 目标窗口唯一标题
        :param path: 测试临时目录内自有文件
        :param leave: True 时拖入再移出，验证 Leave；False 时真实释放文件
        :raises RuntimeError: 源/目标归属不明、遮挡或进程失败
        """
        target = self.find(self.windows, title)
        self.api.SetForegroundWindow(target)
        source_title = f"PyTauriX OLE source {os.getpid()}"
        process = subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-STA",
                "-File",
                str(Path(__file__).with_name("drag_source_windows.ps1")),
                "-Path",
                str(path.resolve()),
                "-Title",
                source_title,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        pressed = False
        try:
            source_windows = DesktopDialogs(process.pid)
            source = self.find(source_windows, source_title)
            start = self.center(source_windows, source)
            end = self.center(self.windows, target)
            self.api.SetForegroundWindow(source)
            self.api.SetCursorPos(*start)
            self.api.mouse_event(2, 0, 0, 0, 0)
            self.api.mouse_event(4, 0, 0, 0, 0)
            time.sleep(0.25)
            self.api.mouse_event(2, 0, 0, 0, 0)
            pressed = True
            time.sleep(0.2)
            for step in range(1, 31):
                x = round(start[0] + (end[0] - start[0]) * step / 30)
                y = round(start[1] + (end[1] - start[1]) * step / 30)
                self.api.SetCursorPos(x, y)
                time.sleep(0.025)
            time.sleep(0.2)
            if leave:
                self.api.SetCursorPos(*start)
                time.sleep(0.2)
            else:
                self.center(self.windows, target)
            self.api.mouse_event(4, 0, 0, 0, 0)
            pressed = False
            time.sleep(0.2)
        finally:
            if pressed:
                self.api.mouse_event(4, 0, 0, 0, 0)
            # Popen 记录的自有源进程；不结束 Explorer 或未知进程。
            process.terminate()
            stdout, stderr = process.communicate(timeout=5)
            print("OLE_SOURCE_DIAGNOSTIC " + stdout + stderr, flush=True)
