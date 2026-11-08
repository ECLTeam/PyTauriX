# PytaruiX
# 文件作用：启动真实路径与进程桌面验收，核验完整证据集合。
# 公开接口：无。
from __future__ import annotations

from pathlib import Path

from desktop_smoke import _checks, _run


def main() -> None:
    """
    独立进程核验宿主目录解析、进程查询与非法名称拒绝。
    """
    output = _run(Path(__file__).resolve().parents[1], "path", "normal")
    checks = _checks(output, "PATH_RESULT ")
    expected = {
        "app_data_present",
        "resolve_under_app_data",
        "parse_variable",
        "string_base_name",
        "temp_matches_environment",
        "resource_dir_present",
        "home_present",
        "directories_well_formed",
        "app_directories_present",
        "invalid_base_rejected",
        "current_pid_matches",
        "current_binary_matches",
    }
    if not expected <= set(checks) or not all(checks.values()):
        raise RuntimeError(f"Path/process evidence incomplete: {checks}")
    print("PATH_SMOKE_PASSED")


if __name__ == "__main__":
    main()
