# ============================================================
# PyTauriX
# 文件作用：真实桌面验证协议异步处理器：协程处理器经 portal 调度，
#          WebView fetch 往返拿到正确状态码与正文。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import asyncio
import functools
import json
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
)

commands = Commands()
report: dict[str, Any] = {}


def sync_serve(request: ProtocolRequest) -> ProtocolResponse:
    """
    同步对照处理器：路径 /sync 返回 200，验证同步形态未受扩展影响。

    :param request: 原生快照的协议请求
    :return: 200 JSON 响应
    """
    return ProtocolResponse(
        status=200,
        headers=(("content-type", "application/json"), ("access-control-allow-origin", "*")),
        body=json.dumps({"ok": True, "path": "sync", "uri": request.uri}).encode("utf-8"),
    )


async def async_serve(request: ProtocolRequest, portal: Any) -> ProtocolResponse:
    """
    异步处理器：在事件循环内挂起后返回，验证 portal 调度与阻塞线程等待。

    :param request: 原生快照的协议请求
    :param portal: 阻塞 portal，处理器经其提交回事件循环
    :return: 200 JSON 响应
    """
    await asyncio.sleep(0.05)
    return ProtocolResponse(
        status=200,
        headers=(("content-type", "application/json"), ("access-control-allow-origin", "*")),
        body=json.dumps({"ok": True, "path": "async", "uri": request.uri}).encode("utf-8"),
    )


@commands.command()
def finish(body: dict[str, object], app_handle: AppHandle) -> None:
    """
    汇总前端检查并退出进程。

    :param body: 前端收集的布尔检查
    :param app_handle: 注入的应用句柄
    """
    report["frontend"] = body
    print("ASYNC_PROTOCOL_RESULT " + json.dumps(report, sort_keys=True), flush=True)
    failed = [name for name, value in body.items() if value is not True]
    app_handle.exit(1 if failed else 0)


def main() -> int:
    """
    构建应用并保持事件循环，直到前端完成检查。

    :return: 应用退出代码
    """
    with start_blocking_portal("asyncio") as portal:
        context = context_factory(Path(__file__).resolve().parent)
        app = builder_factory().build(
            context=context,
            invoke_handler=commands.generate_handler(portal),
            protocols=[
                create_protocol(
                    "asyncproto",
                    functools.partial(async_serve, portal=portal),
                    portal=portal,
                ),
                create_protocol("syncproto", sync_serve),
            ],
        )
        return app.run_return()


if __name__ == "__main__":
    raise SystemExit(main())
