# ============================================================
# PyTauriX
# 文件作用：真实桌面验证协议媒体流：file_range_response 的 200/206、
#          Accept-Ranges/ETag/If-Range 协商与 Range 步进消费。
#          真实编解码的 <video> 播放依赖环境有媒体样本，留人工验收；
#          本场景用确定性模式文件按播放器方式逐块 Range 步进。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from anyio.from_thread import start_blocking_portal
from pytaurix import (
    AppHandle,
    Commands,
    ProtocolRequest,
    ProtocolResponse,
    builder_factory,
    context_factory,
    create_protocol,
    file_range_response,
)

commands = Commands()
report: dict[str, Any] = {}

MEDIA_SIZE = 4 * 1024 * 1024
MEDIA_NAME = "pattern.bin"


def media_runtime_file() -> Path:
    """
    在运行时目录生成确定性模式文件：字节值为下标对 256 取模。

    文件不能放进 web/ 快照目录：与前端资源同路径的协议 URL 会被快照
    优先接管，自定义处理器收不到响应权（见 protocols.md 边界说明）。

    :return: 运行时媒体文件路径
    """
    directory = Path(tempfile.gettempdir()) / "pytaurix-media-range"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / MEDIA_NAME
    if not target.exists() or target.stat().st_size != MEDIA_SIZE:
        target.write_bytes(bytes(index % 256 for index in range(MEDIA_SIZE)))
    return target


def serve(request: ProtocolRequest) -> ProtocolResponse:
    """
    按文件区间响应：无 Range 返回 200 全量，带 Range 返回 206 切片。

    WebView 页面源与自定义 scheme 跨源：补 CORS 头允许 fetch 与 <video> 访问，
    并经 Access-Control-Expose-Headers 放行媒体协商头供前端断言读取。

    :param request: 原生快照的协议请求
    :return: file_range_response 构建的响应
    """
    media = media_runtime_file()
    headers = dict(request.headers)
    if request.method == "OPTIONS":
        requested = headers.get("access-control-request-headers") or "range, if-range"
        return ProtocolResponse(
            status=204,
            headers=(
                ("access-control-allow-origin", "*"),
                ("access-control-allow-headers", requested),
                ("access-control-allow-methods", "GET, HEAD, OPTIONS"),
                ("access-control-max-age", "600"),
            ),
        )
    if_range = headers.get("if-range")
    response = file_range_response(
        media,
        "application/octet-stream",
        range=request.range,
        if_range=if_range,
    )
    return replace(
        response,
        headers=(
            *response.headers,
            ("access-control-allow-origin", "*"),
            ("access-control-expose-headers", "etag, accept-ranges, content-range"),
        ),
    )


@commands.command()
def progress(body: dict[str, object]) -> None:
    """
    记录前端单项检查结果并输出，供驱动脚本诊断。

    :param body: 单项检查名与结果
    """
    print("PROGRESS " + json.dumps(body, sort_keys=True), flush=True)


@commands.command()
def finish(body: dict[str, object], app_handle: AppHandle) -> None:
    """
    汇总前端检查并退出进程。

    :param body: 前端收集的布尔检查
    :param app_handle: 注入的应用句柄
    """
    report["frontend"] = body
    print("MEDIA_RANGE_RESULT " + json.dumps(report, sort_keys=True), flush=True)
    failed = [name for name, value in body.items() if value is not True]
    app_handle.exit(1 if failed else 0)


def main() -> int:
    """
    构建应用并保持事件循环，直到前端完成检查。

    :return: 应用退出代码
    """
    media_runtime_file()
    with start_blocking_portal("asyncio") as portal:
        context = context_factory(Path(__file__).resolve().parent)
        app = builder_factory().build(
            context=context,
            invoke_handler=commands.generate_handler(portal),
            protocols=[create_protocol("mediarange", serve)],
        )
        return app.run_return()


if __name__ == "__main__":
    raise SystemExit(main())
