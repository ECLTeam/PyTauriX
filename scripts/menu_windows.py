# PytaruiX
# 文件作用：独立读回当前测试进程的 Win32 菜单，通过原生菜单循环选择项目。
# 公开接口：DesktopMenus。
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from display_windows import Bitmap, BitmapHeader, DesktopDisplay


class MenuInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.UINT),
        ("mask", wintypes.UINT),
        ("type", wintypes.UINT),
        ("state", wintypes.UINT),
        ("id", wintypes.UINT),
        ("submenu", wintypes.HMENU),
        ("checked", wintypes.HBITMAP),
        ("unchecked", wintypes.HBITMAP),
        ("data", ctypes.c_size_t),
        ("text", wintypes.LPWSTR),
        ("length", wintypes.UINT),
        ("bitmap", wintypes.HBITMAP),
    ]


class DesktopMenus(DesktopDisplay):
    """
    只操作当前 PID 的原生窗口与菜单，不伪造 WM_COMMAND 或 Python 回调。
    """

    def __init__(self) -> None:
        super().__init__()
        signatures = {
            "GetMenu": ([wintypes.HWND], wintypes.HMENU),
            "GetMenuItemCount": ([wintypes.HMENU], ctypes.c_int),
            "GetMenuItemInfoW": (
                [wintypes.HMENU, wintypes.UINT, wintypes.BOOL, ctypes.POINTER(MenuInfo)],
                wintypes.BOOL,
            ),
            "PostMessageW": ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
            "SetForegroundWindow": ([wintypes.HWND], wintypes.BOOL),
            "GetMenuItemRect": (
                [wintypes.HWND, wintypes.HMENU, wintypes.UINT, ctypes.POINTER(wintypes.RECT)],
                wintypes.BOOL,
            ),
            "SetCursorPos": ([ctypes.c_int, ctypes.c_int], wintypes.BOOL),
            "WindowFromPoint": ([wintypes.POINT], wintypes.HWND),
            "GetAncestor": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
            "mouse_event": ([wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t], None),
        }
        for name, (arguments, result) in signatures.items():
            method = getattr(self.api, name)
            method.argtypes, method.restype = arguments, result

    def _bitmap(self, handle: int) -> tuple[int, int, bytes] | None:
        if not handle:
            return None
        bitmap = Bitmap()
        if not self.gdi.GetObjectW(handle, ctypes.sizeof(bitmap), ctypes.byref(bitmap)):
            raise ctypes.WinError(ctypes.get_last_error())
        header = BitmapHeader()
        header.size, header.width, header.height = ctypes.sizeof(header), bitmap.width, -bitmap.height
        header.planes, header.bits = 1, 32
        pixels = ctypes.create_string_buffer(bitmap.width * bitmap.height * 4)
        dc = self.gdi.CreateCompatibleDC(None)
        try:
            if self.gdi.GetDIBits(dc, handle, 0, bitmap.height, pixels, ctypes.byref(header), 0) != bitmap.height:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.gdi.DeleteDC(dc)
        bgra = pixels.raw
        rgba = bytes(
            value for i in range(0, len(bgra), 4) for value in (bgra[i + 2], bgra[i + 1], bgra[i], bgra[i + 3])
        )
        return bitmap.width, bitmap.height, rgba

    def _info(self, menu: int, position: int) -> MenuInfo:
        info = MenuInfo()
        text = ctypes.create_unicode_buffer(1024)
        info.size, info.mask = ctypes.sizeof(info), 0x1C7
        info.text, info.length = ctypes.cast(text, wintypes.LPWSTR), 1023
        if not self.api.GetMenuItemInfoW(menu, position, True, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        # Windows 指针字段不能保有局部缓冲区；结构附加引用保持读取期间有效。
        info._buffer = text
        return info

    def snapshot(self, hwnd: int) -> list[dict[str, object]]:
        """
        读回菜单文字、次序、启用/勾选、嵌套项与实际 HBITMAP 像素。
        """
        self.windows._own(hwnd)

        def read(menu: int) -> list[dict[str, object]]:
            result: list[dict[str, object]] = []
            for position in range(self.api.GetMenuItemCount(menu)):
                info = self._info(menu, position)
                result.append(
                    {
                        "text": info.text,
                        "enabled": not bool(info.state & 3),
                        "checked": bool(info.state & 8),
                        "separator": bool(info.type & 0x800),
                        "icon": self._bitmap(info.bitmap),
                        "items": read(info.submenu) if info.submenu else [],
                    }
                )
            return result

        menu = self.api.GetMenu(hwnd)
        return read(menu) if menu else []

    def _post(self, hwnd: int, message: int, key: int, value: int = 0) -> None:
        self.windows._own(hwnd)
        if not self.api.PostMessageW(hwnd, message, key, value):
            raise ctypes.WinError(ctypes.get_last_error())

    def choose_popup(self, hwnd: int, position: int = 0, *, timeout: float = 5) -> None:
        """
        等待本进程原生弹出菜单，通过菜单输入选择；不直接发送命令 ID。
        """
        self.windows._own(hwnd)
        deadline = time.monotonic() + timeout
        popup = None
        while time.monotonic() < deadline:
            popup = next((item for item in self.windows.windows() if item.kind == "#32768"), None)
            if popup is not None:
                break
            time.sleep(0.02)
        if popup is None:
            raise RuntimeError("Owned native popup menu did not appear")
        handle = ctypes.c_size_t()
        self.windows._own(popup.hwnd)
        if not self.api.SendMessageTimeoutW(popup.hwnd, 0x1E1, 0, 0, 2, 3000, ctypes.byref(handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        text = str(self._info(handle.value, position).text).replace("&", "")
        print("MENU_NATIVE_SELECT " + text, flush=True)
        self._click_item(popup.hwnd, handle.value, position)

    def _click_item(self, hwnd: int, menu: int, position: int) -> None:
        self.windows._own(hwnd)
        rect = wintypes.RECT()
        if not self.api.GetMenuItemRect(hwnd, menu, position, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        point = wintypes.POINT((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
        hit = self.api.WindowFromPoint(point)
        root = self.api.GetAncestor(hit, 2)
        self.windows._own(root)
        if root != hwnd:
            raise RuntimeError("Owned menu item is occluded; refusing system input")
        self.api.SetCursorPos(point.x, point.y)
        time.sleep(0.08)
        self.api.mouse_event(2, 0, 0, 0, 0)
        self.api.mouse_event(4, 0, 0, 0, 0)

    def choose_bar(self, hwnd: int, mnemonic: str, position: int = 0) -> None:
        """
        从原生读回菜单项位置，通过真实鼠标打开菜单栏并选择。
        """
        for attempt in range(3):
            self.windows._own(hwnd)
            self.api.SetForegroundWindow(hwnd)
            time.sleep(0.15)
            menu = self.api.GetMenu(hwnd)
            index = next(
                (
                    index
                    for index in range(self.api.GetMenuItemCount(menu))
                    if str(self._info(menu, index).text).lower().startswith("&" + mnemonic.lower())
                ),
                None,
            )
            if index is None:
                raise RuntimeError("Owned native menu mnemonic unavailable")
            self._click_item(hwnd, menu, index)
            try:
                self.choose_popup(hwnd, position, timeout=1)
                return
            except RuntimeError as error:
                if str(error) != "Owned native popup menu did not appear" or attempt == 2:
                    raise

    def close_window(self, hwnd: int) -> None:
        """
        向本进程窗口发送系统关闭请求，覆盖与点击原生关闭按钮相同的路径。
        """
        self._post(hwnd, 0x112, 0xF060)
