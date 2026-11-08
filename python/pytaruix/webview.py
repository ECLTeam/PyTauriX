# ============================================================
# PytaruiX
# 文件作用：创建运行期 WebView 窗口，校验选定构建参数与回调。
# 公开接口：Webview、WebviewWindow、WebviewWindowBuilder、WebviewWindowBuilderArgs。
# ============================================================
from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Literal, TypedDict, Unpack
from urllib.parse import urlsplit

import anyio

from . import _native
from .errors import BindingError
from .events import DownloadEventType, PageLoadPayload, WindowEventType
from .ffi import Webview, WebviewWindow
from .ffi.image import Image
from .manager import ManagerType, _handle
from .url import WebviewUrl, WebviewUrlType
from .webview_requests import (
    NewWindowFeatures,
    NewWindowResponse,
    PermissionKind,
    PermissionResponse,
    WebResourceRequest,
    WebResourceResponse,
)

__all__ = ["Webview", "WebviewWindow", "WebviewWindowBuilder", "WebviewWindowBuilderArgs"]


class WebviewWindowBuilderArgs(TypedDict, total=False):
    """
    描述已绑定构建选项；位置与尺寸元组采用逻辑像素，平台限制沿用上游。
    """

    title: str
    inner_size: tuple[float, float]
    min_inner_size: tuple[float, float]
    max_inner_size: tuple[float, float]
    position: tuple[float, float]
    traffic_light_position: tuple[float, float]
    center: bool
    visible: bool
    focused: bool
    focusable: bool
    resizable: bool
    maximized: bool
    maximizable: bool
    minimizable: bool
    closable: bool
    fullscreen: bool
    decorations: bool
    transparent: bool
    shadow: bool
    always_on_top: bool
    always_on_bottom: bool
    visible_on_all_workspaces: bool
    content_protected: bool
    skip_taskbar: bool
    drag_drop_enabled: bool
    accept_first_mouse: bool
    hidden_title: bool
    zoom_hotkeys_enabled: bool
    use_https_scheme: bool
    devtools: bool | None
    theme: Literal["light", "dark"] | None
    title_bar_style: Literal["visible", "transparent", "overlay"]
    user_agent: str
    window_classname: str
    tabbing_identifier: str
    additional_browser_args: str
    parent: str
    proxy_url: str
    initialization_script: str
    background_color: tuple[int, int, int, int]
    icon: Image
    on_navigation: Callable[[str], bool]
    on_page_load: Callable[[WebviewWindow, PageLoadPayload], object]
    on_window_event: Callable[[WindowEventType], object]
    on_document_title_changed: Callable[[WebviewWindow, str], object]
    on_download: Callable[[Webview, DownloadEventType], bool]
    data_directory: Path
    on_new_window: Callable[[str, NewWindowFeatures], NewWindowResponse]
    on_permission_request: Callable[[Webview, PermissionKind], PermissionResponse]
    on_web_resource_request: Callable[[WebResourceRequest, WebResourceResponse], WebResourceResponse | None]


class WebviewWindowBuilder:
    """
    保持静态 build/from_config 形状；新本地标签取得精确匹配的桌面桥权限。

    同步创建可在 setup 或命令工作线程调用；原生 GUI 回调内同步建窗明确拒绝。
    每个窗口提供一个可替换的窗口事件处理器，销毁清理回调，旧句柄保持失效。
    """

    field_by_option = MappingProxyType(
        {
            "title": "title",
            "center": "center",
            "visible": "visible",
            "focused": "focus",
            "focusable": "focusable",
            "resizable": "resizable",
            "maximized": "maximized",
            "maximizable": "maximizable",
            "minimizable": "minimizable",
            "closable": "closable",
            "fullscreen": "fullscreen",
            "decorations": "decorations",
            "transparent": "transparent",
            "shadow": "shadow",
            "always_on_top": "alwaysOnTop",
            "always_on_bottom": "alwaysOnBottom",
            "visible_on_all_workspaces": "visibleOnAllWorkspaces",
            "content_protected": "contentProtected",
            "skip_taskbar": "skipTaskbar",
            "drag_drop_enabled": "dragDropEnabled",
            "accept_first_mouse": "acceptFirstMouse",
            "hidden_title": "hiddenTitle",
            "zoom_hotkeys_enabled": "zoomHotkeysEnabled",
            "use_https_scheme": "useHttpsScheme",
            "devtools": "devtools",
            "theme": "theme",
            "title_bar_style": "titleBarStyle",
            "user_agent": "userAgent",
            "window_classname": "windowClassname",
            "tabbing_identifier": "tabbingIdentifier",
            "additional_browser_args": "additionalBrowserArgs",
            "parent": "parent",
            "proxy_url": "proxyUrl",
            "background_color": "backgroundColor",
        }
    )
    fields_by_pair = MappingProxyType(
        {
            "inner_size": ("width", "height"),
            "min_inner_size": ("minWidth", "minHeight"),
            "max_inner_size": ("maxWidth", "maxHeight"),
            "position": ("x", "y"),
            "traffic_light_position": ("x", "y"),
        }
    )
    special_options = frozenset(
        {
            "initialization_script",
            "data_directory",
            "icon",
            "on_navigation",
            "on_page_load",
            "on_window_event",
            "on_document_title_changed",
            "on_download",
            "on_new_window",
            "on_permission_request",
            "on_web_resource_request",
        }
    )
    text_options = frozenset(
        {"title", "user_agent", "window_classname", "tabbing_identifier", "additional_browser_args", "parent"}
    )
    optional_flag_options = frozenset({"devtools"})

    @staticmethod
    def build(
        manager: ManagerType, label: str, url: WebviewUrlType, /, **kwargs: Unpack[WebviewWindowBuilderArgs]
    ) -> WebviewWindow:
        """
        同步创建窗口，重复标签和未知参数明确报错，创建失败释放预注册回调。

        :param manager: 活跃应用或窗口句柄
        :param label: 唯一窗口标签
        :param url: 应用或外部 URL 类型
        :param kwargs: 已绑定选项，尺寸/位置元组使用逻辑像素
        :return: 新窗口句柄
        :raises BindingError: 无效配置、调用上下文、动态权限或原生创建失败
        """
        if not isinstance(label, str) or not label:
            raise BindingError("invalid_label: Window label must be a nonempty string")
        if not isinstance(url, (WebviewUrl.App, WebviewUrl.External)):
            raise BindingError("invalid_url: Expected WebviewUrl.App or External")
        value = str(url.path) if isinstance(url, WebviewUrl.App) else url.url
        config: dict[str, object] = {"label": label, "url": value}
        return WebviewWindowBuilder._build(manager, config, kwargs)

    @staticmethod
    def from_config(
        manager: ManagerType, config: Mapping[str, object], /, **kwargs: Unpack[WebviewWindowBuilderArgs]
    ) -> WebviewWindow:
        """
        从单个 WindowConfig 映射创建窗口，显式选项覆盖配置且不修改输入。

        :param manager: 活跃应用或窗口句柄
        :param config: 单个原生窗口配置映射，字段使用上游名称
        :param kwargs: 已绑定覆盖选项与回调
        :return: 新窗口句柄
        :raises BindingError: 配置无效、重复标签或创建失败
        """
        return WebviewWindowBuilder._build(manager, dict(config), kwargs)

    @staticmethod
    async def build_async(
        manager: ManagerType, label: str, url: WebviewUrlType, /, **kwargs: Unpack[WebviewWindowBuilderArgs]
    ) -> WebviewWindow:
        """
        从异步命令创建窗口，在 AnyIO 工作线程执行同一构建逻辑。

        :param manager: 活跃句柄，不能跨线程传递主线程 App 对象
        :param label: 唯一标签
        :param url: 明确 URL 类型
        :param kwargs: 构建选项
        :return: 新窗口；等待完成期间不占用事件循环
        :raises BindingError: 同步回调、无效配置或创建失败
        """
        handle = _handle(manager)
        return await anyio.to_thread.run_sync(lambda: WebviewWindowBuilder.build(handle, label, url, **kwargs))

    @staticmethod
    def _build(manager: ManagerType, config: dict[str, object], options: WebviewWindowBuilderArgs) -> WebviewWindow:
        known = WebviewWindowBuilder.field_by_option.keys() | WebviewWindowBuilder.fields_by_pair.keys()
        if options.keys() - known - WebviewWindowBuilder.special_options:
            raise BindingError("invalid_window_config: Unknown builder option")
        for name, value in options.items():
            if name in WebviewWindowBuilder.fields_by_pair:
                if not isinstance(value, (tuple, list)) or len(value) != 2:
                    raise BindingError("invalid_size: Expected a two-element geometry pair")
                for number in value:
                    if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                        raise BindingError("invalid_size: Geometry must contain finite numbers")
                fields = WebviewWindowBuilder.fields_by_pair[name]
                if name == "traffic_light_position":
                    config["trafficLightPosition"] = {"x": value[0], "y": value[1]}
                else:
                    config[fields[0]], config[fields[1]] = value
            elif name in WebviewWindowBuilder.field_by_option:
                if name in WebviewWindowBuilder.text_options:
                    if not isinstance(value, str) or (name == "parent" and not value):
                        raise BindingError("invalid_window_config: Text option requires a nonempty string")
                elif name == "background_color":
                    if (
                        not isinstance(value, (tuple, list))
                        or len(value) != 4
                        or any(
                            isinstance(channel, bool) or not isinstance(channel, int) or not 0 <= channel <= 255
                            for channel in value
                        )
                    ):
                        raise BindingError("invalid_window_config: background_color requires four RGBA bytes")
                elif name == "proxy_url":
                    if not isinstance(value, str):
                        raise BindingError("invalid_url: proxy_url must be text")
                    parsed = urlsplit(value)
                    if (
                        parsed.scheme not in {"http", "https"}
                        or not parsed.hostname
                        or parsed.username
                        or parsed.password
                        or "\x00" in value
                    ):
                        raise BindingError("invalid_url: proxy_url requires an HTTP(S) URL without credentials")
                elif name == "theme":
                    if value is not None and value not in {"light", "dark"}:
                        raise BindingError("invalid_window_config: theme must be None, 'light' or 'dark'")
                elif name == "title_bar_style":
                    if value not in {"visible", "transparent", "overlay"}:
                        raise BindingError("invalid_window_config: title_bar_style is not supported")
                elif name in WebviewWindowBuilder.optional_flag_options:
                    if value is not None and not isinstance(value, bool):
                        raise BindingError("invalid_window_config: Optional window flags must be bool or None")
                elif not isinstance(value, bool):
                    raise BindingError("invalid_window_config: Window flags must be bool")
                config[WebviewWindowBuilder.field_by_option[name]] = value
        directory = options.get("data_directory")
        if directory is not None and (not isinstance(directory, Path) or not directory.is_absolute()):
            raise BindingError("invalid_window_config: data_directory requires an absolute Path")
        if "data_directory" in options and directory is None:
            raise BindingError("invalid_window_config: data_directory requires an absolute Path")
        if "initialization_script" in options and not isinstance(options["initialization_script"], str):
            raise BindingError("invalid_window_config: initialization_script must be text")
        if "icon" in options and not isinstance(options["icon"], Image):
            raise BindingError("invalid_image: Expected Image")
        for key in (
            "on_navigation",
            "on_page_load",
            "on_window_event",
            "on_document_title_changed",
            "on_download",
            "on_new_window",
            "on_permission_request",
            "on_web_resource_request",
        ):
            if key in options and not callable(options.get(key)):
                raise BindingError("invalid_callback: Callback must be callable")
        # WindowConfig 的 URL 可表示 App 路径或 External URL；先执行相同来源校验。
        url = config.get("url", "index.html")
        if not isinstance(url, str):
            raise BindingError("invalid_url: WindowConfig URL must be text")
        if "://" in url:
            WebviewUrl.External(url)
        else:
            WebviewUrl.App(url)
        try:
            text = json.dumps(config, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise BindingError("invalid_window_config: Configuration must be JSON serializable") from error
        return _native.build_window(
            _handle(manager),
            text,
            initialization_script=options.get("initialization_script"),
            icon=options.get("icon"),
            navigation=options.get("on_navigation"),
            page_load=options.get("on_page_load"),
            window_event=options.get("on_window_event"),
            title_changed=options.get("on_document_title_changed"),
            download=options.get("on_download"),
            new_window=options.get("on_new_window"),
            permission=options.get("on_permission_request"),
            resource=options.get("on_web_resource_request"),
            data_directory=directory,
        )
