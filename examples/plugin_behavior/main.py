# ============================================================
# PytaruiX
# 文件作用：插件行为验收入口，真实调用全局快捷键、系统通知与默认程序。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import ctypes
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from pytaruix import AppHandle, BindingError, Commands, Manager, builder_factory, context_factory
from pytaruix.plugins.dialog import DialogExt, MessageDialogButtons
from pytaruix.plugins.dialog import init as dialog_init
from pytaruix.plugins.global_shortcut import GlobalShortcut
from pytaruix.plugins.global_shortcut import init as global_shortcut_init
from pytaruix.plugins.notification import Notification
from pytaruix.plugins.notification import init as notification_init
from pytaruix.plugins.opener import Opener
from pytaruix.plugins.opener import init as opener_init

ACCELERATOR = "Ctrl+Alt+F9"
NOTIFICATION_ID = 4242
OUTPUT = Path(os.environ.get("PYTARUIX_PLUGIN_BEHAVIOR_OUT", "plugin-behavior.json"))
PROBE_DIR = Path(tempfile.gettempdir()) / "pytaruix-plugin-behavior"
PROBE_FILE = PROBE_DIR / "probe.txt"

report: dict[str, object] = {"accelerator": ACCELERATOR}
_probe_hit = threading.Event()


class _ProbeHandler(BaseHTTPRequestHandler):
    """
    记录一次真实 HTTP 命中，证明默认浏览器确实打开了本地地址。
    """

    def do_GET(self) -> None:
        """
        返回一段自述页并标记命中。
        """
        body = (
            "<!doctype html><meta charset=utf-8><title>PytaruiX opener</title>"
            "<h1>opener 验收已到达本地服务</h1>"
            "<p>这个页面由默认浏览器打开，可以关闭。</p>"
            "<script>setTimeout(() => window.close(), 1200)</script>"
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        _probe_hit.set()

    def log_message(self, format: str, *args: object) -> None:
        """
        关闭默认访问日志，避免驱动脚本输出噪声。
        """


def _window(handle: AppHandle) -> Any:
    """
    取主窗口；缺失时直接失败，避免后续回调空转。

    :param handle: 应用句柄
    :return: 主窗口对象
    """
    window = Manager.get_webview_window(handle, "main")
    if window is None:
        raise RuntimeError("main window is missing")
    return window


def _input_structure() -> type[ctypes.Structure] | None:
    """
    构造与 Win32 INPUT 布局一致的 ctypes 结构，非 Windows 返回 None。

    :return: INPUT 结构类型或 None
    """

    class KeyboardInput(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class MouseInput(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class HardwareInput(ctypes.Structure):
        _fields_ = [
            ("uMsg", ctypes.c_ulong),
            ("wParamL", ctypes.c_ushort),
            ("wParamH", ctypes.c_ushort),
        ]

    class InputUnion(ctypes.Union):
        _fields_ = [("ki", KeyboardInput), ("mi", MouseInput), ("hi", HardwareInput)]

    class Input(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("u", InputUnion)]

    return Input


def _inject_shortcut() -> bool:
    """
    用 SendInput 合成 Ctrl+Alt+F9，验证热键能收到真实键盘事件。

    :return: 是否成功提交合成事件
    """
    if sys.platform != "win32":
        return False
    structure = _input_structure()
    if structure is None:
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    vk_control, vk_menu, vk_f9 = 0x11, 0x12, 0x78
    key_up = 0x0002
    sequence = [
        (vk_control, 0),
        (vk_menu, 0),
        (vk_f9, 0),
        (vk_f9, key_up),
        (vk_menu, key_up),
        (vk_control, key_up),
    ]
    inputs = (structure * len(sequence))()
    for index, (virtual_key, flags) in enumerate(sequence):
        inputs[index].type = 1
        inputs[index].u.ki.wVk = virtual_key
        inputs[index].u.ki.dwFlags = flags
    sent = user32.SendInput(len(sequence), ctypes.byref(inputs), ctypes.sizeof(structure))
    return sent == len(sequence)


def _confirm(window: Any, message: str, title: str) -> bool:
    """
    用原生消息框取得人工确认。

    :param window: 父窗口
    :param message: 询问文本
    :param title: 标题
    :return: 选择「是」为 True
    """
    builder = DialogExt.message(window, message)
    return bool(builder.blocking_show(title=title, buttons=MessageDialogButtons.YesNo()))


def _shortcut_checks(handle: AppHandle, window: Any) -> None:
    """
    覆盖注册、查询、重复注册拒绝、触发、注销与批量注销。

    :param handle: 应用句柄
    :param window: 主窗口，用于在需要人工按键时置顶提示
    """
    shortcuts = GlobalShortcut(handle)
    fired = threading.Event()
    seen: list[str] = []

    def handler(app_handle: AppHandle, accelerator: str) -> None:
        """
        记录按键回调；回调只应在按下时触发。

        :param app_handle: 应用句柄
        :param accelerator: 规范化后的快捷键
        """
        seen.append(accelerator)
        fired.set()

    shortcuts.register(ACCELERATOR, handler)
    report["shortcut_registered"] = shortcuts.is_registered(ACCELERATOR)
    try:
        shortcuts.register(ACCELERATOR, handler)
    except BindingError as error:
        report["shortcut_duplicate_rejected"] = True
        report["shortcut_duplicate_error"] = str(error)
    else:
        report["shortcut_duplicate_rejected"] = False
    report["shortcut_injected"] = _inject_shortcut()
    manual = False
    if not fired.wait(6.0):
        manual = True
        window.set_always_on_top(True)
        window.set_title(f"请按 {ACCELERATOR}")
        _inject_shortcut()
        fired.wait(30.0)
        window.set_title("PytaruiX 插件行为验收")
        window.set_always_on_top(False)
    report["shortcut_manual"] = manual
    report["shortcut_fired"] = fired.is_set()
    report["shortcut_payload"] = seen[0] if seen else ""
    shortcuts.unregister(ACCELERATOR)
    report["shortcut_unregistered"] = not shortcuts.is_registered(ACCELERATOR)
    shortcuts.register(ACCELERATOR, handler)
    shortcuts.unregister_all()
    report["shortcut_unregister_all"] = not shortcuts.is_registered(ACCELERATOR)


def _notification_checks(handle: AppHandle, window: Any) -> None:
    """
    发送系统通知并取得人工可见性确认。

    :param handle: 应用句柄
    :param window: 主窗口，作为消息框父窗口
    """
    notification = Notification(handle)
    report["notification_permission_state"] = notification.permission_state()
    report["notification_request_result"] = notification.request_permission()
    token = time.strftime("%H:%M:%S")
    notification.send(
        "PytaruiX 插件验收",
        f"看到这条通知请点「是」。时间 {token}。",
        id=NOTIFICATION_ID,
    )
    report["notification_marker"] = token
    time.sleep(1.5)
    report["notification_visible"] = _confirm(
        window,
        f"屏幕上是否出现了标题为「PytaruiX 插件验收」、时间 {token} 的系统通知？",
        "系统通知",
    )


def _opener_checks(handle: AppHandle, window: Any) -> None:
    """
    用默认浏览器访问本地服务，并确认默认程序与文件管理器被唤起。

    :param handle: 应用句柄
    :param window: 主窗口，作为消息框父窗口
    """
    opener = Opener(handle)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProbeHandler)
    port = int(server.server_address[1])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        opener.open_url(f"http://127.0.0.1:{port}/probe")
        report["opener_url_hit"] = _probe_hit.wait(25.0)
    finally:
        server.shutdown()
        server.server_close()
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    PROBE_FILE.write_text("PytaruiX opener 验收文件。\n", encoding="utf-8")
    opener.open_path(PROBE_FILE)
    report["opener_path_opened"] = _confirm(
        window,
        f"是否已用默认程序打开 {PROBE_FILE.name}（通常是记事本）？",
        "默认程序打开文件",
    )
    opener.reveal_item_in_dir(PROBE_FILE)
    report["opener_revealed"] = _confirm(
        window,
        f"文件管理器是否已打开并选中 {PROBE_FILE.name}？",
        "在文件管理器中定位",
    )


def _run_checks(handle: AppHandle) -> None:
    """
    在后台线程顺序执行三组检查，随后写出结果并退出。

    :param handle: 应用句柄
    """
    try:
        window = _window(handle)
        for name, check in (
            ("shortcut", _shortcut_checks),
            ("notification", _notification_checks),
            ("opener", _opener_checks),
        ):
            try:
                check(handle, window)
            except Exception as error:
                report[f"{name}_error"] = f"{type(error).__name__}: {error}"
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print("PLUGIN_BEHAVIOR_RESULT " + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    handle.exit(1 if "error" in report else 0)


def _setup(handle: AppHandle) -> None:
    """
    在事件循环 Ready 时启动后台检查，不阻塞 GUI 线程。

    :param handle: 应用句柄
    """
    threading.Thread(target=_run_checks, args=(handle,), daemon=True).start()


def main() -> int:
    """
    构建带三个插件的应用并保持事件循环。

    :return: 应用退出代码
    """
    context = context_factory(Path(__file__).resolve().parent)
    commands = Commands()
    app = builder_factory().build(
        context=context,
        invoke_handler=commands.generate_handler(),
        plugins=[dialog_init(), global_shortcut_init(), notification_init(), opener_init()],
        setup=_setup,
    )
    return app.run_return()


if __name__ == "__main__":
    raise SystemExit(main())
