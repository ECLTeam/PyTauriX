# 动态窗口指南

第三阶段保持 PyTauri 常见模块和静态工厂形状；第十二阶段补齐常用构建属性、窗口事件与 WebView 回调。嵌入、多 WebView 与请求/权限回调仍待后续阶段。

## 创建与线程

```python
from pytaruix import WebviewUrl
from pytaruix.dpi import LogicalSize, PhysicalPosition
from pytaruix.ffi.image import Image
from pytaruix.webview import WebviewWindowBuilder

window = WebviewWindowBuilder.build(
    app_handle,
    "settings",
    WebviewUrl.App("index.html?view=settings"),
    title="设置",
    inner_size=(800, 600),
    min_inner_size=(480, 320),
    visible=False,
    icon=Image(bytes([38, 105, 150, 255]) * 256, 16, 16),
)
window.set_size(LogicalSize(900, 680))
window.set_position(PhysicalPosition(200, 120))
window.show()
```

同步创建可以在 setup 或正在运行的应用命令工作线程执行。原生 GUI/导航/窗口事件回调内同步建窗返回 would_block，尚未运行且不在 setup 中返回 app_not_running。
异步命令用 `await WebviewWindowBuilder.build_async(app_handle, label, url, **kwargs)`，内部由 AnyIO 工作线程执行；App 对象仍归 Python 主线程拥有。
`from_config(manager, config, /, **kwargs)` 复制单个 WindowConfig 映射，配置字段采用上游 camelCase，覆盖参数采用 Python snake_case。
未知构建参数、重复标签与无效几何明确拒绝。尺寸/位置构建元组是逻辑像素；运行期通过 Logical/Physical 类型显式选择单位。
尺寸构造器要求正值；最小化时原生 Resized 或尺寸查询可能返回零值。图像支持自有 RGBA 数据和只读属性，PNG/ICO 加载由对应 feature 控制。

## 构建属性

除标题、尺寸、位置、可见性、装饰、透明、置顶等基础项外，当前还接受：

- 行为：`drag_drop_enabled`、`always_on_bottom`、`visible_on_all_workspaces`、`content_protected`、`accept_first_mouse`、`hidden_title`、`zoom_hotkeys_enabled`、`use_https_scheme`、`devtools`。
- 外观：`theme`（`None`/`light`/`dark`）、`title_bar_style`（`visible`/`transparent`/`overlay`）、`traffic_light_position`、`background_color`。
- WebView：`user_agent`、`additional_browser_args`、`window_classname`、`tabbing_identifier`、`proxy_url`。
- 窗口关系：`parent` 使用现有窗口标签。

`theme`、`title_bar_style`、`proxy_url` 与 `parent` 在 Python 边界严格校验；不接受上游的静默回退。`proxy_url` 必须为无凭据 HTTP(S) 来源。
平台专属项照常接受但不代表效果已验证：`traffic_light_position`、`hidden_title`、`accept_first_mouse`、`tabbing_identifier` 主要面向 macOS；`additional_browser_args` 主要面向 Windows WebView2。

运行期提供 `set_theme`/`theme`、`set_always_on_bottom`、`set_content_protected`、`set_visible_on_all_workspaces`；没有原生读取接口的属性不伪造 getter。

## 生命周期与回调

```python
from pytaruix import WindowEvent, WindowEventType


def on_event(event: WindowEventType) -> None:
    if isinstance(event, WindowEvent.CloseRequested):
        event.api.prevent_close()


window.on_window_event(on_event)
```

提供 CloseRequested、Destroyed、Focused、Resized、Moved、ScaleFactorChanged、ThemeChanged 与拖放 Enter/Over/Drop/Leave。每窗一个可替换处理器，构建时 on_window_event 与运行期注册共用此槽，区别于上游的累加监听。
拖放路径为不可变字符串元组，位置为物理浮点坐标；`on_download` 只在 Requested 阶段用返回值决定是否继续，Finished 提供 url、path 与 success。
`on_document_title_changed` 接收窗口与标题；`on_download` 接收 Webview 与下载事件。两者均为同步回调，awaitable 返回 invalid_callback。
导航回调接受 URL 字符串且必须返回 bool；页面加载接受窗口和 PageLoadPayload，载荷的 url/event 属性区分 Started/Finished。
回调必须同步，coroutine 会被关闭并返回 invalid_callback；异常有序退出，App.run_return 重抛原 Python 异常。
prevent_close 只在本次关闭回调内有效，保存后再调用返回 request_expired。Destroyed 回调开始前使本代全部句柄失效，资源操作返回 window_closed；label 仍可读取。
关闭、创建失败和应用退出释放 Python 回调。相同标签重建获得独立代次，旧句柄不能操作新窗口。Manager.webview_windows 返回原生窗口映射。

## 权限与平台

无宿主策略的原型中，默认 main/secondary 和动态本地窗口按精确标签取得 core:default、旧 pyfunc 与新 python_command 权限。
新旧入口都接受 Tauri 原生 ACL 检查；未授权标签与外部页面拒绝 Python 调用。WebviewUrl.External 只接受 HTTP(S)，不自动授权远程来源。
宿主定义 capabilities 目录或 security.capabilities 后，动态窗口由其窗口模式及来源控制，不自动扩大权限。
默认 feature 包含 dynamic-acl；原型自动授权未开启时，本地动态创建返回 unsupported_capability。CSP 与构建后任意 ACL 修改尚未实现。
上游能力增补不能撤销：关闭窗口不等于删除该标签权限，同标签重建沿用标签策略。
窗口行为目前实测 Windows/WebView2，其他平台待验收。原生图标、阴影、任务栏和焦点设置遵循平台限制；完成设置调用不代表每种外观状态都已独立测量。

运行 `python scripts/dynamic_window_smoke.py` 可在独立进程执行正常场景和五种回调失败场景；验收包含 45 项联合检查。
新增属性、主题读写、三项窗口设置、标题变更与 blob 下载由 `python scripts/window_attributes_smoke.py` 在真实 Windows 桌面独立验收（7 项全通过）。
拖放事件与缩放/主题变化事件目前由契约测试覆盖解析；真实系统拖放与显示器 DPI 变化专项证据待补。
当前桌面会话中 `focus` 一项可能因测试进程不在前台而失败，其余 44 项通过；该结果不记为焦点行为已验证。

窗口和 AppHandle 现在均提供 run_on_main_thread(callback)，适合从后台线程提交 GUI 工作。
同步调度回调内建窗仍返回 would_block；窗口任务与监听关联具体代次，关闭后不会恢复为同标签新窗口的任务。
完整用法与关闭期间的执行顺序见 [事件与主线程指南](events.md)。
