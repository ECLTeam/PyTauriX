# PyTauriX
# 文件作用：启动真实显示器与图像桌面验收，核验完整证据集合。
# 公开接口：无。
from __future__ import annotations

from pathlib import Path

from desktop_smoke import _checks, _run


def main() -> None:
    """
    独立进程验收 Windows 系统对照、图标像素、线程与窗口生命周期。
    """
    output = _run(Path(__file__).resolve().parents[1], "display_image", "normal")
    checks = _checks(output, "DISPLAY_IMAGE_RESULT ")
    expected = {
        "enumeration",
        "primary",
        "current",
        "dpi",
        "outside_none",
        "point_type",
        "callback_guard",
        "callback_done",
        "worker",
        "worker_done",
        "builder_icon",
        "updated_icon",
        "logical_size",
        "physical_size",
        "logical_position",
        "physical_position",
        "monitor_readonly",
        "probe_monitor",
        "destroyed",
        "fresh",
        "generation",
        "snapshot_after_close",
    }
    expected.update(f"invalid_point_{i}" for i in range(3))
    expected.update("closed_" + name for name in ("current", "primary", "available", "point"))
    if not expected <= set(checks) or not all(checks.values()) or "DISPLAY_IMAGE_RESOURCES_RELEASED" not in output:
        raise RuntimeError(f"Display/image evidence incomplete: {checks}")
    print("DISPLAY_IMAGE_SMOKE_PASSED")


if __name__ == "__main__":
    main()
