# PytaruiX
# 文件作用：独立进程验收生产、显式开发来源及空宿主权限。
# 公开接口：无。
from __future__ import annotations

from pathlib import Path

from desktop_smoke import _checks, _run


def main() -> None:
    """
    三次真实桌面进程，必须同时取得正常、拒绝及回调/退出保护证据。
    """
    for mode in ("production", "development", "deny"):
        output = _run(Path(__file__).resolve().parents[1], "host_config", mode)
        checks = _checks(output, "HOST_RESULT ")
        if not checks or not all(checks.values()):
            raise RuntimeError(f"Host checks incomplete: {checks}")
    print("HOST_CONFIG_SMOKE_PASSED")


if __name__ == "__main__":
    main()
