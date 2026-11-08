# ============================================================
# PyTauriX
# 文件作用：真实桌面验收扩展窗口属性、主题设置、标题变更与下载回调。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from anyio.from_thread import start_blocking_portal
from pytaurix import AppHandle, Commands, WebviewUrl, builder_factory, context_factory
from pytaurix.webview import WebviewWindowBuilder

CHECKS = (
    "attrs_created",
    "theme_dark",
    "theme_light",
    "setters_applied",
    "title_changed",
    "download_requested",
    "download_finished",
)


def main() -> int:
    """
    创建带扩展属性的窗口，等待页面改标题与 blob 下载事件。

    :return: 应用退出代码
    """
    commands = Commands()
    checks = dict.fromkeys(CHECKS, False)
    titles: list[str] = []
    downloads: list[str] = []

    def on_title(window: object, title: str) -> None:
        titles.append(title)

    def on_download(webview: object, event: object) -> bool:
        downloads.append(f"{type(event).__name__}:{getattr(event, 'url', '')}")
        return True

    def setup(handle: AppHandle) -> None:
        attributes = WebviewWindowBuilder.build(
            handle,
            "attrs",
            WebviewUrl.App("index.html"),
            parent="main",
            title="PyTauriX Attributes",
            inner_size=(360, 240),
            visible=False,
            theme="dark",
            always_on_bottom=True,
            visible_on_all_workspaces=True,
            content_protected=True,
            drag_drop_enabled=True,
            window_classname="PyTauriXAttributes",
            title_bar_style="visible",
            hidden_title=True,
            accept_first_mouse=True,
            tabbing_identifier="pytaurix",
            user_agent="PyTauriXAttributes/1",
            use_https_scheme=False,
            zoom_hotkeys_enabled=False,
            devtools=None,
        )
        checks["attrs_created"] = True
        checks["theme_dark"] = attributes.theme() == "dark"
        attributes.set_theme("light")
        checks["theme_light"] = attributes.theme() == "light"
        attributes.set_always_on_bottom(True)
        attributes.set_content_protected(True)
        attributes.set_visible_on_all_workspaces(True)
        checks["setters_applied"] = True
        WebviewWindowBuilder.build(
            handle,
            "events",
            WebviewUrl.App("index.html?events=1"),
            visible=False,
            on_document_title_changed=on_title,
            on_download=on_download,
        )

        def finish() -> None:
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline and not (
                titles
                and any("Requested:" in item for item in downloads)
                and any("Finished:" in item for item in downloads)
            ):
                time.sleep(0.1)
            print("WINDOW_ATTR_DEBUG " + json.dumps({"titles": titles, "downloads": downloads}), flush=True)
            checks["title_changed"] = any(title == "PyTauriX Title Changed" for title in titles)
            checks["download_requested"] = any("Requested:" in item for item in downloads)
            checks["download_finished"] = any("Finished:" in item for item in downloads)
            print("WINDOW_ATTR_RESULT " + json.dumps(checks, sort_keys=True), flush=True)
            handle.exit(0 if all(checks.values()) else 1)

        threading.Thread(target=finish, name="window-attributes-finish", daemon=True).start()

    with start_blocking_portal("asyncio") as portal:
        app = builder_factory().build(
            context=context_factory(Path(__file__).resolve().parent),
            invoke_handler=commands.generate_handler(portal),
            setup=setup,
        )
        return app.run_return()


if __name__ == "__main__":
    raise SystemExit(main())
