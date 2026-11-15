# ============================================================
# PyTauriX
# 文件作用：驱动协议扩展桌面场景：异步处理器与媒体区间消费。
#          各场景独立进程跑真实 WebView，超时即判定失败。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCENARIOS: dict[str, frozenset[str]] = {
    "async_protocol": frozenset({"async_status", "async_body", "async_scheduled", "sync_regression"}),
    "media_range": frozenset({"full_200", "slice_206", "stepped_playback", "fallback_200", "if_range_negotiation"}),
}


def _run(root: Path, example: str) -> str:
    environment = dict(os.environ, PYTARUIX_SMOKE="1", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    try:
        result = subprocess.run(
            [sys.executable, str(root / "examples" / example / "main.py")],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        for captured in (error.stdout, error.stderr):
            print(captured.decode("utf-8", errors="replace") if isinstance(captured, bytes) else captured, flush=True)
        raise RuntimeError("Desktop scenario timed out before completion") from error
    print(result.stdout, end="")
    if result.returncode:
        raise RuntimeError(f"{example} failed ({result.returncode}): {result.stderr}")
    return result.stdout


def _checks(output: str, prefix: str) -> dict[str, object]:
    line = next((line for line in output.splitlines() if line.startswith(prefix)), None)
    return json.loads(line.removeprefix(prefix)) if line else {}


def main() -> None:
    """
    依次运行两个协议扩展场景，核验前端上报的检查全集为真。

    Windows 真实 WebView 之外的平台需在相应平台另行运行。
    """
    root = Path(__file__).resolve().parents[1]
    for example, expected in SCENARIOS.items():
        prefix = "ASYNC_PROTOCOL_RESULT " if example == "async_protocol" else "MEDIA_RANGE_RESULT "
        result = _checks(_run(root, example), prefix)
        checks = result.get("frontend")
        if not isinstance(checks, dict):
            raise RuntimeError(f"{example} did not report frontend checks: {result}")
        missing = set(expected) - set(checks)
        failed = [name for name in expected if checks.get(name) is not True]
        extra = {name: value for name, value in checks.items() if name not in expected}
        if missing or failed:
            raise RuntimeError(f"{example} checks incomplete: missing={missing} failed={failed} extra={extra}")
    print("PROTOCOL_SCENARIOS_PASSED")


if __name__ == "__main__":
    main()
