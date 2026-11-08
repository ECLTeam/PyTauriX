# ============================================================
# PyTauriX
# 文件作用：真实桌面验收入口，一次运行覆盖取消、协议、fs 与窗口状态。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

import anyio
from anyio.from_thread import start_blocking_portal
from pytaurix import (
    AppHandle,
    BindingError,
    Commands,
    LogicalSize,
    Manager,
    ProtocolResponse,
    Request,
    builder_factory,
    context_factory,
    create_protocol,
)
from pytaurix.plugins.fs import Fs
from pytaurix.plugins.fs import init as fs_init
from pytaurix.plugins.single_instance import init as single_instance_init
from pytaurix.plugins.window_state import WindowState
from pytaurix.plugins.window_state import init as window_state_init

TARGET_WIDTH = 820
TARGET_HEIGHT = 560
ROUND = os.getenv("PYTARUIX_ACCEPTANCE_ROUND", "1")

commands = Commands()
second_instance = threading.Event()
report: dict[str, object] = {"round": ROUND}


def serve(request: object) -> ProtocolResponse:
    """
    回一个最小 JSON，用于验证自定义 scheme 的真实往返。

    :return: 200 响应，正文固定
    """
    return ProtocolResponse(
        status=200,
        headers=(
            ("content-type", "application/json"),
            ("access-control-allow-origin", "*"),
        ),
        body=json.dumps({"ok": True, "uri": getattr(request, "uri", "")}).encode("utf-8"),
    )


@commands.command()
async def slow(request: Request) -> str:
    """
    可协作取消的长任务：每个检查点读取 cancelled 标志。

    :return: 观察到取消返回 cancelled，跑完返回 completed
    """
    report["slow_started"] = True
    print("SLOW_START " + request.id, flush=True)
    for _ in range(500):
        if request.cancelled:
            report["python_saw_cancel"] = True
            print("SLOW_CANCEL", flush=True)
            return "cancelled"
        await anyio.sleep(0.01)
    print("SLOW_DONE", flush=True)
    return "completed"


@commands.command()
def fs_roundtrip(app_handle: AppHandle) -> dict[str, object]:
    """
    通过 fs 插件写读一个临时文件，比对内容。

    :param app_handle: 注入的应用句柄
    :return: 是否一致、字节数与文件路径
    """
    payload = json.dumps({"round": ROUND, "marker": "pytaurix"}, sort_keys=True).encode("utf-8")
    directory = Path(tempfile.gettempdir()) / "pytaurix-acceptance"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "fs-probe.json"
    files = Fs(app_handle)
    files.write_bytes(target, payload)
    restored = files.read_bytes(target)
    return {"matched": restored == payload, "bytes": len(restored), "path": str(target)}


@commands.command()
def apply_geometry(app_handle: AppHandle) -> dict[str, int]:
    """
    把窗口固定到验收尺寸，供第二轮比对恢复结果。

    :param app_handle: 注入的应用句柄
    :return: 设置后的物理尺寸
    """
    window = Manager.get_webview_window(app_handle, "main")
    if window is None:
        raise RuntimeError("main window is missing")
    window.set_size(LogicalSize(TARGET_WIDTH, TARGET_HEIGHT))
    size = window.inner_size()
    return {"width": size.width, "height": size.height}


@commands.command()
def geometry(app_handle: AppHandle) -> dict[str, int]:
    """
    读取当前窗口的物理尺寸。

    :param app_handle: 注入的应用句柄
    :return: 宽高
    """
    window = Manager.get_webview_window(app_handle, "main")
    if window is None:
        raise RuntimeError("main window is missing")
    size = window.inner_size()
    return {"width": size.width, "height": size.height}


@commands.command()
def acceptance_round() -> str:
    """
    返回当前轮次，供前端选择检查集合。

    :return: 轮次标识
    """
    return ROUND


@commands.command()
def checks_done(body: dict[str, object]) -> None:
    """
    记录前端阶段的检查结果并输出一行，供驱动脚本判断时机。

    :param body: 前端收集的布尔检查
    """
    report["frontend"] = body
    print("CHECKS_DONE " + json.dumps(body, sort_keys=True), flush=True)


@commands.command()
def wait_second_instance() -> bool:
    """
    等待第二实例回调，最多六秒。

    :return: 是否在时限内收到
    """
    seen = second_instance.wait(6.0)
    report["second_instance"] = seen
    return seen


@commands.command()
def finish(body: dict[str, object], app_handle: AppHandle) -> None:
    """
    汇总本轮结果、按需保存窗口状态，然后退出进程。

    :param body: 前端补充数据（几何）
    :param app_handle: 注入的应用句柄
    """
    window = Manager.get_webview_window(app_handle, "main")
    if window is not None and ROUND == "1":
        WindowState(app_handle).save()
    if isinstance(body, dict):
        report["geometry"] = body
    print("ACCEPTANCE_RESULT " + json.dumps(report, sort_keys=True), flush=True)
    frontend = report.get("frontend")
    failed = [
        name
        for name, value in (frontend.items() if isinstance(frontend, dict) else ())
        if isinstance(value, bool) and not value
    ]
    app_handle.exit(1 if failed else 0)


def _second_instance(handle: AppHandle, argv: tuple[str, ...], cwd: str) -> None:
    """
    第二实例被拉起时回调，记录参数并放行等待中的命令。

    :param handle: 第一实例的应用句柄
    :param argv: 第二实例命令行
    :param cwd: 第二实例工作目录
    """
    report["second_argv"] = list(argv)
    report["second_cwd"] = cwd
    second_instance.set()
    print("SECOND_INSTANCE " + json.dumps({"argv": argv, "cwd": cwd}), flush=True)


def main() -> int:
    """
    构建应用并保持事件循环，直到前端完成检查。

    :return: 应用退出代码
    """
    with start_blocking_portal("asyncio") as portal:
        context = context_factory(Path(__file__).resolve().parent)
        plugins = [fs_init(), window_state_init(flags=("size", "position"))]
        try:
            plugins.insert(0, single_instance_init(_second_instance))
        except BindingError as error:
            # 未启用单实例插件时仍可验证其余项，结果里明确说明原因。
            report["second_instance_reason"] = str(error)
        app = builder_factory().build(
            context=context,
            invoke_handler=commands.generate_handler(portal),
            plugins=plugins,
            protocols=[create_protocol("acceptance", serve)],
        )
        return app.run_return()


if __name__ == "__main__":
    raise SystemExit(main())
