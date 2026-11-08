# ============================================================
# PytaruiX
# 文件作用：Windows 桌面验收工具，只操作调用方创建的 PID 与唯一对话框标题。
# 公开接口：DesktopDialogs。
# ============================================================
from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Control:
    """
    保存指定测试进程窗口的控件快照。
    """

    hwnd: int
    id: int
    kind: str
    text: str


class DesktopDialogs:
    """
    按 PID 和精确标题定位测试窗口，所有输入前重新核验归属。
    """

    def __init__(self, pid: int) -> None:
        if os.name != "nt":
            raise RuntimeError("This acceptance driver requires Windows")
        self.pid = pid
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        signatures = {
            "EnumWindows": ([self.callback_type, wintypes.LPARAM], wintypes.BOOL),
            "EnumChildWindows": ([wintypes.HWND, self.callback_type, wintypes.LPARAM], wintypes.BOOL),
            "GetWindowThreadProcessId": ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            "GetWindowTextW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            "GetClassNameW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            "GetDlgCtrlID": ([wintypes.HWND], ctypes.c_int),
            "IsWindow": ([wintypes.HWND], wintypes.BOOL),
            "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
            "SendMessageTimeoutW": (
                [
                    wintypes.HWND,
                    wintypes.UINT,
                    wintypes.WPARAM,
                    wintypes.LPARAM,
                    wintypes.UINT,
                    wintypes.UINT,
                    ctypes.POINTER(ctypes.c_size_t),
                ],
                wintypes.LPARAM,
            ),
            "GetWindow": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
        }
        for name, (arguments, result) in signatures.items():
            method = getattr(self.api, name)
            method.argtypes = arguments
            method.restype = result

    @classmethod
    def from_spawned(cls, launcher_pid: int, application_pid: int) -> DesktopDialogs:
        """
        核验 venv 重定向进程的后代关系，避免把进程报告当作操作任意 PID 的授权。
        """
        if os.name != "nt":
            raise RuntimeError("This acceptance driver requires Windows")

        class ProcessEntry(ctypes.Structure):
            _fields_ = [
                ("size", wintypes.DWORD),
                ("usage", wintypes.DWORD),
                ("pid", wintypes.DWORD),
                ("heap", ctypes.c_size_t),
                ("module", wintypes.DWORD),
                ("threads", wintypes.DWORD),
                ("parent", wintypes.DWORD),
                ("priority", wintypes.LONG),
                ("flags", wintypes.DWORD),
                ("exe", wintypes.WCHAR * 260),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        for name in ("Process32FirstW", "Process32NextW"):
            method = getattr(kernel, name)
            method.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
            method.restype = wintypes.BOOL
        snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = ProcessEntry()
            entry.size = ctypes.sizeof(entry)
            parents: dict[int, int] = {}
            found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while found:
                parents[entry.pid] = entry.parent
                found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)
        cursor = application_pid
        visited: set[int] = set()
        while cursor != launcher_pid:
            if cursor in visited or cursor not in parents:
                raise RuntimeError("Reported application is not a descendant of our spawned process")
            visited.add(cursor)
            cursor = parents[cursor]
        return cls(application_pid)

    def _own(self, hwnd: int) -> None:
        process = wintypes.DWORD()
        self.api.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
        if process.value != self.pid or not self.api.IsWindow(hwnd):
            raise RuntimeError("Window no longer belongs to the spawned test process")

    def _text(self, hwnd: int, kind: bool = False) -> str:
        buffer = ctypes.create_unicode_buffer(8192)
        method = self.api.GetClassNameW if kind else self.api.GetWindowTextW
        method(hwnd, buffer, len(buffer))
        return buffer.value

    def windows(self) -> list[Control]:
        result: list[Control] = []

        def collect(hwnd: int, _: int) -> bool:
            process = wintypes.DWORD()
            self.api.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
            if process.value == self.pid and self.api.IsWindowVisible(hwnd):
                result.append(Control(hwnd, 0, self._text(hwnd, True), self._text(hwnd)))
            return True

        self.api.EnumWindows(self.callback_type(collect), 0)
        return result

    def wait(self, title: str, timeout: float = 15) -> int:
        """
        等待测试标题对应的真实系统对话框，超时不触碰其他窗口。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for window in self.windows():
                if window.text == title and window.kind == "#32770":
                    return window.hwnd
            time.sleep(0.03)
        raise RuntimeError(f"Owned dialog did not appear: {title}; {self.windows()}")

    def controls(self, hwnd: int) -> list[Control]:
        """
        枚举指定测试对话框的子控件。
        """
        self._own(hwnd)
        result: list[Control] = []

        def collect(child: int, _: int) -> bool:
            self._own(child)
            result.append(Control(child, self.api.GetDlgCtrlID(child), self._text(child, True), self._text(child)))
            return True

        self.api.EnumChildWindows(hwnd, self.callback_type(collect), 0)
        return result

    def _send(self, hwnd: int, message: int, wparam: int = 0, lparam: int = 0) -> None:
        self._own(hwnd)
        result = ctypes.c_size_t()
        if not self.api.SendMessageTimeoutW(hwnd, message, wparam, lparam, 2, 3000, ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())

    def enter(self, hwnd: int, value: str) -> None:
        """
        设置本对话框的文件名编辑框，不发送全局键盘事件。
        """
        edit = next(
            (control for control in self.controls(hwnd) if control.id in (1001, 1148, 1152) and control.kind == "Edit"),
            None,
        )
        if edit is None:
            edit = next(
                (control for control in self.controls(hwnd) if control.id == 1148 and control.kind == "Edit"), None
            )
        if edit is None:
            raise RuntimeError(f"File input not found: {self.controls(hwnd)}")
        buffer = ctypes.create_unicode_buffer(value)
        self._send(edit.hwnd, 0x000C, 0, ctypes.addressof(buffer))

    def content(self, control: Control) -> str:
        """
        跨进程读取已核验控件内容；GetWindowText 不读取其他进程的编辑框。
        """
        buffer = ctypes.create_unicode_buffer(8192)
        self._send(control.hwnd, 0x000D, len(buffer), ctypes.addressof(buffer))
        return buffer.value

    def click(self, hwnd: int, id: int) -> None:
        """
        单击本对话框中的明确按钮 ID。
        """
        control = next(
            (control for control in self.controls(hwnd) if control.id == id and control.kind == "Button"), None
        )
        if control is None:
            raise RuntimeError(f"Button not found: {id}; {self.controls(hwnd)}")
        self._send(control.hwnd, 0x00F5)

    def owner(self, hwnd: int) -> int | None:
        """
        返回测试对话框的原生 owner，供显式父窗口断言使用。
        """
        self._own(hwnd)
        return self.api.GetWindow(hwnd, 4) or None

    def message_button(self, hwnd: int, index: int, labels: list[str]) -> None:
        """
        点击 TaskDialog 内部按钮；自定义标签逐项核验，不依赖本地化标准文本。
        """
        buttons = [control for control in self.controls(hwnd) if control.kind == "Button"]
        if labels and [control.text for control in buttons] != labels:
            raise RuntimeError(f"Custom button labels differ: {buttons}")
        if index >= len(buttons):
            raise RuntimeError(f"Message button not found: {buttons}")
        self._send(buttons[index].hwnd, 0x00F5)
