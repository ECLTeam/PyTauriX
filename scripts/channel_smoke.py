# PytaruiX
# 文件作用：在独立进程验收真实双窗口 Channel。
# 公开接口：无。
from __future__ import annotations

from pathlib import Path

from desktop_smoke import _checks, _run


def main() -> None:
    """
    核验双窗口数据、关闭、缓存与代次证据，不使用模拟传输。
    """
    output = _run(Path(__file__).resolve().parents[1], "channel", "normal")
    checks = _checks(output, "CHANNEL_RESULT ")
    expected = {"window_closed", "old_send", "old_view", "old_window", "fresh_view", "generation", "destroyed_cache"}
    for label in ("main", "secondary"):
        expected.update(
            f"{name}_{label}"
            for name in (
                "view",
                "invalid_json",
                "invalid_type",
                "invalid_model",
                "explicit_close",
                "closed_send",
                "closed_invalid",
                "workers",
                "shared_close",
                "shared_send",
            )
        )
        expected.update(
            f"frontend_{label}_{name}"
            for name in (
                "ids",
                "cache_owner",
                "cache_once",
                "invalid_fetch",
                "missing_fetch_header",
                "invalid_id",
                "dialog_acl",
                "serial_json",
                "binary_empty",
                "binary_small",
                "large_json",
                "binary_large",
                "mixed_order",
                "json_thresholds",
                "binary_thresholds",
                "concurrent",
                "producer_order",
                "gc_end",
                "close_end",
                "ffi",
                "retained_active",
                "after_return",
            )
        )
    if set(checks) != expected or not all(checks.values()) or "CHANNEL_RESOURCES_RELEASED" not in output:
        raise RuntimeError(f"Channel evidence incomplete: {checks}")
    print("CHANNEL_SMOKE_PASSED")


if __name__ == "__main__":
    main()
