# PytaruiX
# 文件作用：独立 Windows 显示器查询及本进程窗口图标像素读取。
# 公开接口：DesktopDisplay。
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from dialog_windows import DesktopDialogs


class MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("monitor", wintypes.RECT),
        ("work", wintypes.RECT),
        ("flags", wintypes.DWORD),
        ("device", wintypes.WCHAR * 32),
    ]


class IconInfo(ctypes.Structure):
    _fields_ = [
        ("icon", wintypes.BOOL),
        ("x", wintypes.DWORD),
        ("y", wintypes.DWORD),
        ("mask", wintypes.HBITMAP),
        ("color", wintypes.HBITMAP),
    ]


class Bitmap(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.LONG),
        ("width", wintypes.LONG),
        ("height", wintypes.LONG),
        ("stride", wintypes.LONG),
        ("planes", wintypes.WORD),
        ("bits", wintypes.WORD),
        ("pixels", ctypes.c_void_p),
    ]


class BitmapHeader(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("width", wintypes.LONG),
        ("height", wintypes.LONG),
        ("planes", wintypes.WORD),
        ("bits", wintypes.WORD),
        ("compression", wintypes.DWORD),
        ("image_size", wintypes.DWORD),
        ("x_ppm", wintypes.LONG),
        ("y_ppm", wintypes.LONG),
        ("used", wintypes.DWORD),
        ("important", wintypes.DWORD),
    ]


class DesktopDisplay:
    """
    独立对照 Win32 数据，仅访问当前测试进程窗口；不修改系统显示设置。
    """

    def __init__(self) -> None:
        self.windows = DesktopDialogs(os.getpid())
        self.api = self.windows.api
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        self.shcore = ctypes.WinDLL("shcore", use_last_error=True)
        self.monitor_callback = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HANDLE, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
        )
        signatures = {
            "EnumDisplayMonitors": (
                [wintypes.HDC, ctypes.c_void_p, self.monitor_callback, wintypes.LPARAM],
                wintypes.BOOL,
            ),
            "GetMonitorInfoW": ([wintypes.HANDLE, ctypes.POINTER(MonitorInfo)], wintypes.BOOL),
            "MonitorFromWindow": ([wintypes.HWND, wintypes.DWORD], wintypes.HANDLE),
            "GetDpiForWindow": ([wintypes.HWND], wintypes.UINT),
            "GetIconInfo": ([wintypes.HANDLE, ctypes.POINTER(IconInfo)], wintypes.BOOL),
            "GetClassLongPtrW": ([wintypes.HWND, ctypes.c_int], ctypes.c_size_t),
        }
        for name, (arguments, result) in signatures.items():
            method = getattr(self.api, name)
            method.argtypes = arguments
            method.restype = result
        self.shcore.GetDpiForMonitor.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.POINTER(wintypes.UINT),
            ctypes.POINTER(wintypes.UINT),
        ]
        self.shcore.GetDpiForMonitor.restype = wintypes.LONG
        gdi_signatures = {
            "GetObjectW": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p], ctypes.c_int),
            "CreateCompatibleDC": ([wintypes.HDC], wintypes.HDC),
            "DeleteDC": ([wintypes.HDC], wintypes.BOOL),
            "DeleteObject": ([wintypes.HANDLE], wintypes.BOOL),
            "GetDIBits": (
                [
                    wintypes.HDC,
                    wintypes.HBITMAP,
                    wintypes.UINT,
                    wintypes.UINT,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    wintypes.UINT,
                ],
                ctypes.c_int,
            ),
        }
        for name, (arguments, result) in gdi_signatures.items():
            method = getattr(self.gdi, name)
            method.argtypes = arguments
            method.restype = result

    def hwnd(self, title: str) -> int:
        """
        按精确标题获取当前进程的可见窗口，找不到则失败。
        """
        result = next(window.hwnd for window in self.windows.windows() if window.text == title)
        self.windows._own(result)
        return result

    def monitors(self) -> list[dict[str, object]]:
        """
        返回 Win32 的设备、几何、工作区、主屏标记及有效 DPI 快照。
        """
        result: list[dict[str, object]] = []
        errors: list[Exception] = []

        def collect(handle: int, _dc: int, _rect: object, _data: int) -> bool:
            try:
                info = MonitorInfo()
                info.size = ctypes.sizeof(info)
                if not self.api.GetMonitorInfoW(handle, ctypes.byref(info)):
                    raise ctypes.WinError(ctypes.get_last_error())
                x, y = wintypes.UINT(), wintypes.UINT()
                if self.shcore.GetDpiForMonitor(handle, 0, ctypes.byref(x), ctypes.byref(y)) != 0:
                    raise RuntimeError("GetDpiForMonitor failed")
                result.append(
                    {
                        "handle": handle,
                        "name": info.device,
                        "position": (info.monitor.left, info.monitor.top),
                        "size": (info.monitor.right - info.monitor.left, info.monitor.bottom - info.monitor.top),
                        "work_position": (info.work.left, info.work.top),
                        "work_size": (info.work.right - info.work.left, info.work.bottom - info.work.top),
                        "scale_factor": x.value / 96,
                        "primary": bool(info.flags & 1),
                    }
                )
            except Exception as error:
                errors.append(error)
                return False
            return True

        success = self.api.EnumDisplayMonitors(None, None, self.monitor_callback(collect), 0)
        if errors:
            raise errors[0]
        if not success:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    def current_handle(self, hwnd: int) -> int:
        """
        独立查询指定测试窗口所在显示器。
        """
        self.windows._own(hwnd)
        return self.api.MonitorFromWindow(hwnd, 0)

    def dpi(self, hwnd: int) -> int:
        """
        读取当前测试窗口的有效 DPI。
        """
        self.windows._own(hwnd)
        return self.api.GetDpiForWindow(hwnd)

    def icon(self, hwnd: int) -> tuple[int, int, bytes]:
        """
        读取 Tao 设置的窗口小图标，返回原始位图尺寸与 RGBA；用于不透明像素样本。

        释放 GetIconInfo 分配的位图和 GDI DC，不释放窗口拥有的 HICON。
        """
        self.windows._own(hwnd)
        handle = ctypes.c_size_t()
        if not self.api.SendMessageTimeoutW(hwnd, 0x7F, 0, 0, 2, 3000, ctypes.byref(handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        icon = handle.value or self.api.GetClassLongPtrW(hwnd, -34)
        info = IconInfo()
        if not icon or not self.api.GetIconInfo(icon, ctypes.byref(info)):
            raise RuntimeError("The owned window has no readable native icon")
        dc = None
        try:
            bitmap = Bitmap()
            if not self.gdi.GetObjectW(info.color, ctypes.sizeof(bitmap), ctypes.byref(bitmap)):
                raise ctypes.WinError(ctypes.get_last_error())
            header = BitmapHeader()
            header.size = ctypes.sizeof(header)
            header.width = bitmap.width
            header.height = -bitmap.height
            header.planes, header.bits = 1, 32
            pixels = ctypes.create_string_buffer(bitmap.width * bitmap.height * 4)
            dc = self.gdi.CreateCompatibleDC(None)
            if (
                not dc
                or self.gdi.GetDIBits(dc, info.color, 0, bitmap.height, pixels, ctypes.byref(header), 0)
                != bitmap.height
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            bgra = pixels.raw
            rgba = bytes(
                value for i in range(0, len(bgra), 4) for value in (bgra[i + 2], bgra[i + 1], bgra[i], bgra[i + 3])
            )
            return bitmap.width, bitmap.height, rgba
        finally:
            if dc:
                self.gdi.DeleteDC(dc)
            for bitmap_handle in (info.color, info.mask):
                if bitmap_handle:
                    self.gdi.DeleteObject(bitmap_handle)
