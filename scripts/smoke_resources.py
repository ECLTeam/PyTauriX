# PytaruiX
# 文件作用：由验收父进程拥有并清理独立 WebView profile，避免浏览器退出与文件删除竞争。
# 公开接口：run_profiled_example。
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path


def run_profiled_example(entry: Path, prefix: str, run: Callable[[Path], int]) -> int:
    """
    在独立自有子进程运行原生场景，进程结束后有界重试清理自有 profile。

    :param entry: 本示例的绝对脚本路径
    :param prefix: 本场景唯一临时目录前缀
    :param run: 在子进程接收专用目录并运行应用的函数
    :return: 场景退出代码
    :raises OSError: 浏览器退出后仍无法清理；不忽略失败或终止未知进程
    """
    inherited = os.environ.get("PYTARUIX_SMOKE_PROFILE")
    base = Path(tempfile.gettempdir()).resolve()
    if inherited:
        path = Path(inherited).resolve()
        if path.parent != base or not path.name.startswith(prefix):
            raise RuntimeError("Unexpected inherited smoke profile")
        return run(path)
    directory = tempfile.TemporaryDirectory(prefix=prefix)
    path = Path(directory.name).resolve()
    if path.parent != base or not path.name.startswith(prefix):
        raise RuntimeError("Unexpected profile cleanup target")
    try:
        environment = dict(os.environ, PYTARUIX_SMOKE_PROFILE=str(path), PYTHONUNBUFFERED="1")
        return subprocess.run([sys.executable, str(entry)], env=environment, timeout=35, check=False).returncode
    finally:
        for attempt in range(30):
            try:
                directory.cleanup()
                break
            except OSError as error:
                if getattr(error, "winerror", None) not in {5, 32, 145} or attempt == 29:
                    raise
                time.sleep(0.1)
