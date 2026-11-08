# PyTauriX
# 文件作用：串行验收原生 WebView 策略、错误返回及回调释放。
# 公开接口：无。
from __future__ import annotations

from pathlib import Path

from desktop_smoke import _checks, _run


def main() -> None:
    """
    运行真实页面触发三种回调及各自的错误、异常和 awaitable 分支。

    :raises RuntimeError: 任一检查缺失或失败
    """
    root = Path(__file__).resolve().parents[1]
    expected = {
        "original_response",
        "resource_replaced",
        "repeated_headers",
        "popup_denied",
        "permission_denied",
        "request_snapshot",
        "original_snapshot",
        "new_window_callback",
        "new_window_features",
        "permission_callback",
        "dedicated_profile",
        "absolute_config_rejected",
    }
    for mode in ("normal",):
        output = _run(root, "webview_policy", mode)
        checks = _checks(output, "POLICY_RESULT ")
        if set(checks) != expected or not all(value is True for value in checks.values()):
            raise RuntimeError(f"Policy evidence incomplete: {checks}")
        if "POLICY_RESOURCES_RELEASED" not in output:
            raise RuntimeError("Policy callbacks leaked after exit")
    for kind in ("resource", "new-window", "permission"):
        for failure in ("invalid", "exception", "awaitable"):
            mode = f"{kind}-{failure}"
            output = _run(root, "webview_policy", mode)
            if f"POLICY_FAILURE_RECOVERED {mode}" not in output or "POLICY_RESOURCES_RELEASED" not in output:
                raise RuntimeError(f"Policy failure recovery incomplete: {mode}")
    print("WEBVIEW_POLICY_SMOKE_PASSED")


if __name__ == "__main__":
    main()
