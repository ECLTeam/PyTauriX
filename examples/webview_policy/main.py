# PyTauriX
# 文件作用：通过真实 WebView 验证资源、新窗口和权限策略及失败清理。
# 公开接口：无。
from __future__ import annotations

import gc
import json
import os
import sys
import threading
import weakref
from pathlib import Path
from typing import cast

from anyio.from_thread import start_blocking_portal
from pytaurix import (
    AppHandle,
    BindingError,
    Commands,
    NewWindowFeatures,
    NewWindowResponse,
    PermissionKind,
    PermissionResponse,
    WebResourceRequest,
    WebResourceResponse,
    Webview,
    WebviewWindow,
    builder_factory,
    context_factory,
)
from pytaurix.webview import WebviewWindowBuilder

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from smoke_resources import run_profiled_example


async def unexpected_async() -> None:
    """生成用于确认原生同步回调拒绝 awaitable 并主动关闭的协程。"""


class Policy:
    """持有本场景结果，不持有窗口；回调释放通过弱引用独立确认。"""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.lock = threading.Lock()
        self.seen: dict[str, bool] = {}

    def failure(self, kind: str) -> object:
        """仅在选定模式产生错误返回或异常，不调用原生回调替身。"""
        if self.mode == f"{kind}-exception":
            raise ValueError(f"policy {kind} failure")
        if self.mode == f"{kind}-awaitable":
            return unexpected_async()
        return True

    def resource(self, request: WebResourceRequest, original: WebResourceResponse) -> WebResourceResponse | None:
        """只替换已知自有资源，其他响应保持上游内容。"""
        if not request.url.endswith("/replaced.html"):
            return None
        if self.mode.startswith("resource-"):
            return cast(WebResourceResponse, self.failure("resource"))
        with self.lock:
            self.seen["request_snapshot"] = request.method == "GET" and isinstance(request.body, bytes)
            self.seen["original_snapshot"] = original.status == 200 and b"original replacement" in original.body
        return WebResourceResponse(
            201,
            (("content-type", b"text/plain"), ("x-pytaurix", b"one"), ("x-pytaurix", b"two")),
            b"native replacement",
        )

    def new_window(self, url: str, features: NewWindowFeatures) -> NewWindowResponse:
        """默认拒绝页面弹窗，仅 allow 场景接受自有 popup 页面。"""
        if self.mode.startswith("new-window-"):
            return cast(NewWindowResponse, self.failure("new-window"))
        with self.lock:
            self.seen["new_window_callback"] = "popup.html" in url
            self.seen["new_window_features"] = features.size == (310, 230)
        return NewWindowResponse.Deny

    def permission(self, view: Webview, kind: PermissionKind) -> PermissionResponse:
        """拒绝所有浏览器权限，本场景只请求通知能力。"""
        if self.mode.startswith("permission-"):
            return cast(PermissionResponse, self.failure("permission"))
        with self.lock:
            self.seen["permission_callback"] = kind is PermissionKind.Geolocation and view.label() == "policy"
        return PermissionResponse.Deny


def _run_application(data: Path) -> int:
    """
    使用独立 WebView 数据目录启动策略窗口，并验证退出后句柄及回调清理。

    :return: 原生进程退出代码
    """
    mode = os.environ.get("PYTARUIX_FAILURE_MODE", "normal")
    commands = Commands()
    references: list[weakref.ReferenceType[Policy]] = []
    windows: list[WebviewWindow] = []
    timer: threading.Timer | None = None

    @commands.command()
    def debug(body: dict[str, object]) -> None:
        print("POLICY_DEBUG " + json.dumps(body), flush=True)

    @commands.command()
    def report(body: dict[str, bool | str], app_handle: AppHandle) -> None:
        policy = references[0]()
        assert policy is not None
        with policy.lock:
            evidence = body | policy.seen
        evidence["dedicated_profile"] = data.is_dir() and any(data.iterdir())
        if mode != "normal":
            evidence["expected_failure_missing"] = False
        print("POLICY_RESULT " + json.dumps(evidence, sort_keys=True), flush=True)
        app_handle.exit(0 if all(value is True for value in evidence.values()) else 1)

    def setup(handle: AppHandle) -> None:
        nonlocal timer
        policy = Policy(mode)
        references.append(weakref.ref(policy))
        try:
            WebviewWindowBuilder.from_config(
                handle, {"label": "bad-profile", "url": "controller.html", "dataDirectory": str(data)}
            )
        except BindingError as error:
            policy.seen["absolute_config_rejected"] = str(error).startswith("invalid_window_config:")
        else:
            raise AssertionError("Absolute config dataDirectory was silently ignored")
        windows.append(
            WebviewWindowBuilder.from_config(
                handle,
                {"label": "policy", "url": f"index.html?mode={mode}"},
                data_directory=data,
                title=f"PyTauriX policy {os.getpid()}",
                inner_size=(440, 300),
                on_new_window=policy.new_window,
                on_permission_request=policy.permission,
                on_web_resource_request=policy.resource,
            )
        )
        timer = threading.Timer(18, lambda: handle.exit(2))
        timer.daemon = True
        timer.start()

    with start_blocking_portal() as portal:
        app = builder_factory().build(
            context=context_factory(
                Path(__file__).resolve().parent,
                tauri_config={"app": {"windows": []}},
            ),
            invoke_handler=commands.generate_handler(portal),
            setup=setup,
        )
        try:
            code = app.run_return()
        except (BindingError, ValueError) as error:
            expected = "policy " if mode.endswith("-exception") else "invalid_callback:"
            if mode == "normal" or expected not in str(error):
                raise
            print("POLICY_FAILURE_RECOVERED " + mode, flush=True)
            code = 0
        finally:
            if timer is not None:
                timer.cancel()
                timer.join(timeout=2)
    gc.collect()
    assert references and all(reference() is None for reference in references)
    for index in range(len(windows)):
        try:
            windows[index].title()
        except BindingError as error:
            assert "app_closed:" in str(error)
        else:
            raise AssertionError("Exited policy window remained usable")
    windows.clear()
    timer = None
    del app
    gc.collect()
    print("POLICY_RESOURCES_RELEASED", flush=True)
    return code


def main() -> int:
    """由父进程拥有 profile，待真实 WebView 进程结束后清理，不终止未知浏览器进程。"""
    return run_profiled_example(Path(__file__).resolve(), "pytaurix-policy-", _run_application)


if __name__ == "__main__":
    raise SystemExit(main())
