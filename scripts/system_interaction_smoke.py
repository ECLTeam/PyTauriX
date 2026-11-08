# PytaruiX
# 文件作用：验收自有桌面窗口上的真实系统焦点与文件拖放。
# 公开接口：无。
from __future__ import annotations

from pathlib import Path

from desktop_smoke import _checks, _run


def main() -> None:
    """
    运行独立进程并要求实际 OLE 四种事件、焦点和源文件保护检查全部通过。
    """
    output = _run(Path(__file__).resolve().parents[1], "system_interaction", "normal")
    checks = _checks(output, "SYSTEM_INTERACTION_RESULT ")
    expected = {
        "system_focus",
        "drag_enter",
        "drag_over",
        "drag_leave",
        "drag_drop",
        "file_unchanged",
        "focus_loss",
        "focus_restore",
        "theme_events",
    }
    if set(checks) != expected or not all(value is True for value in checks.values()):
        raise RuntimeError(f"System interaction evidence incomplete: {checks}")
    print("SYSTEM_INTERACTION_SMOKE_PASSED")


if __name__ == "__main__":
    main()
