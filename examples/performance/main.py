# ============================================================
# PytaruiX
# 文件作用：真实 WebView IPC 基准宿主，采集小 JSON、Pydantic 与并发调用耗时。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel
from pytaruix import AppHandle, Commands, builder_factory, context_factory


class BenchBody(BaseModel):
    """
    保存 Pydantic 基准载荷。
    """

    value: int
    text: str


def main() -> int:
    """
    启动基准窗口，前端通过 finish 命令回报 JSON 结果。

    :return: 应用退出代码
    """
    commands = Commands()

    @commands.command()
    def bench_small(name: str, value: int) -> dict[str, int | str]:
        return {"name": name, "value": value}

    @commands.command()
    def bench_model(body: BenchBody) -> BenchBody:
        return body

    @commands.command()
    def bench_fail() -> None:
        raise RuntimeError("intentional benchmark failure")

    @commands.command()
    def finish(result: dict[str, object], app_handle: AppHandle) -> None:
        print("IPC_BENCH_RESULT " + json.dumps(result, sort_keys=True), flush=True)
        app_handle.exit(0 if "unexpected" not in result else 1)

    app = builder_factory().build(
        context=context_factory(Path(__file__).resolve().parent),
        invoke_handler=commands.generate_handler(),
    )
    return app.run_return()


if __name__ == "__main__":
    raise SystemExit(main())
