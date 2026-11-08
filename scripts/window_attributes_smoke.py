# ============================================================
# PyTauriX
# 文件作用：串行启动扩展窗口属性场景并核验原生结果。
# 公开接口：无。
# ============================================================
from __future__ import annotations

from pathlib import Path

from desktop_smoke import _checks, _run


def main() -> None:
    """
    在独立进程核验扩展属性、主题、标题变更与下载回调。

    :raises RuntimeError: 场景缺失检查项或任一项失败
    """
    root = Path(__file__).resolve().parents[1]
    output = _run(root, "window_attributes", "normal")
    checks = _checks(output, "WINDOW_ATTR_RESULT ")
    expected = {
        "attrs_created",
        "theme_dark",
        "theme_light",
        "setters_applied",
        "title_changed",
        "download_requested",
        "download_finished",
    }
    if set(checks) != expected or not all(checks.values()):
        raise RuntimeError(f"Window attribute evidence incomplete: {checks}")
    print("WINDOW_ATTRIBUTES_SMOKE_PASSED")


if __name__ == "__main__":
    main()
