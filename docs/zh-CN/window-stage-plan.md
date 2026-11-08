# 第三阶段：动态窗口与生命周期

状态：授权范围已实施并完成 Windows 验收。Python 3.11/3.14 独立安装包、45 项动态窗口检查和五种回调失败场景均通过，详见验证记录。

## 本阶段交付

让 Python 能在应用运行期间创建和管理窗口，覆盖 ECL 当前的子窗口调用形状。
保留 `pytaruix.webview`、根 `WebviewUrl` 与 `pytaruix.ffi.image.Image` 的布局。
采用 ECL 的类型、文件头、中文公共文档和领域模块规范。
当前锁定 Tauri 2.12.1 / PyO3 0.29.3；实现前再次核验稳定版本，升级差异单独审核并更新账本。

## 调研证据

- 当前 `webview.py` 仅导出窗口句柄，原生句柄仅提供 label/app_handle/标题/焦点/关闭，没有动态构建器。
- 当前编译期权限仅匹配 main/secondary；新增标签需要权限登记，不能仅创建窗口就宣称 IPC 可用。
- 当前失效检查只覆盖整个应用，需要补充单窗口销毁状态与重建代次。
- ECL 的 `ECL/api/windows.py` 使用 WebviewWindowBuilder.build、WebviewUrl.App、RGBA Image，以及尺寸、位置、隐藏创建、装饰、初始化脚本与背景色。
- PyTauri 的构建入口是静态 build(manager, label, url, /, **kwargs) 与 from_config(manager, config, /, **kwargs)。
- [上游构建器文档](https://docs.rs/tauri/2.12.1/tauri/webview/struct.WebviewWindowBuilder.html)：Windows 的同步原生命令及事件回调内直接建窗存在死锁限制，setup、异步命令或独立线程具有不同调用条件。
- [上游 Manager](https://docs.rs/tauri/2.12.1/tauri/trait.Manager.html#method.add_capability)：运行期增加能力集依赖 dynamic-acl；锁定版本的 default 包含该 feature。

## 接口契约

### 创建、类型与图像

保留以下调用形状：

```python
from pytaruix import WebviewUrl
from pytaruix.ffi.image import Image
from pytaruix.webview import WebviewWindowBuilder

window = WebviewWindowBuilder.build(
    app_handle,
    "settings",
    WebviewUrl.App("index.html"),
    title="设置",
    inner_size=(800, 600),
    min_inner_size=(480, 320),
    visible=False,
)
window.show()
```

- WebviewUrl 包含 App 与 External 的明确类型；本地资源与外部 URL 分别校验，外部页面不自动取得本地 Python IPC 权限。
- build 与 from_config 共用配置转换和校验，from_config 接受单个 WindowConfig 映射；不修改调用方输入。重复标签明确报错，不返回已有窗口。
- 选定构建参数：title、inner_size、min_inner_size、max_inner_size、position、center、visible、focused、focusable、resizable、maximized、maximizable、minimizable、closable、fullscreen、decorations、transparent、shadow、always_on_top、skip_taskbar、initialization_script、background_color、icon，以及本阶段回调。
- 参数使用 TypedDict/领域对象与完整注解；未知参数拒绝，不用任意 kwargs 绕过校验。
- Image(rgba, width, height, /) 持有自有 RGBA 数据；检查维度、字节长度及乘法溢出。提供 rgba/width/height 只读属性；图像文件解码后续单独绑定，不隐式启用 PNG/ICO feature。
- 构建尺寸/位置元组沿用上游逻辑像素语义；运行期显式提供逻辑/物理尺寸与位置类型，避免将两种单位混用。

### 运行期窗口控制

- show/hide、is_visible、title/set_title、set_focus/is_focused。
- inner_size、outer_position、scale_factor、set_size/set_position、center、最小/最大尺寸。
- minimize/unminimize、maximize/unmaximize、is_minimized/is_maximized、fullscreen 查询/设置。
- decorations、shadow、always_on_top、resizable 等本阶段选定属性的设置与可用查询。
- Manager.webview_windows 返回现存窗口映射，保留 get_webview_window。
- close 发出可拦截的关闭请求；Destroyed 后窗口资源操作返回 window_closed。
- 平台不可用或上游具有无操作语义的能力，按实际平台记录并说明；绑定成功不等于行为验收通过。

### 回调与错误

- 窗口事件：CloseRequested(code 无关，含 api.prevent_close)、Destroyed、Focused、Resized、Moved；沿用可匹配类型。
- WebView 回调：on_navigation 和 on_page_load；导航需返回 bool，页面加载提供 URL 与 Started/Finished。
- 需要即时返回结果的回调保持同步，拒绝 coroutine 或错误结果类型，不阻塞等待 AnyIO portal。
- prevent_close 仅在本次关闭回调内有效；保存后再调用返回 request_expired，避免上游失效通道 panic。
- 异常进入现有 RuntimeState 错误通道，导航异常拒绝本次导航并触发有序退出，run_return 重抛原异常。
- 窗口关闭、建窗失败和应用退出均清理该窗口持有的 Python 回调；清理时不持注册表锁调用 Python。

## 原生实现约束

### 线程与 GIL

- 使用 AppHandle 调度原生窗口任务；创建主应用仍严格限定 Python 主线程。
- 同步 build 支持已有 Python IPC 工作线程；setup 中沿用上游允许的构建路径。
- 在 GUI 事件/导航回调中同步建窗时，提前返回明确的 would_block 错误；不在 GUI 线程等待工作线程创建完成。
- 提供异步创建入口，由 AnyIO 工作线程运行同一构建实现，供异步命令使用；不新增隐式全局事件循环。
- 原生建窗与资源调用释放 GIL，回调访问 Python 时 attach；不使用 unsafe 伪装 Send。
- 用真实窗口测试确认上述上下文与早到的页面回调，不能只依据构建器签名判断线程安全。

### 窗口所有权与回调清理

- 注册表维护具体原生窗口的代次和存活状态。所有获取该窗口的句柄共享状态，而不是每次查询重新创建存活标记。
- Destroyed 使本代全部句柄失效。相同标签重新建窗获得新代次，旧句柄无法操作新窗口。
- 建窗期间先准备回调状态，再进入 native build；失败回滚登记并释放引用。
- 原生闭包通过可清空回调槽访问 Python 对象，避免回调被原生管理器一直持有到进程结束。
- 页面回调可能早于 build 返回，注册流程需允许这种顺序，不依赖 Python 已拿到窗口对象。

### 动态窗口权限

- 保留当前 main/secondary 权限范围，新增本地窗口按精确标签登记等价的 core/旧 Python 桥权限，不扩大成任意窗口通配符。
- 使用上游 dynamic-acl 能力集增补路径；feature 未启用时明确返回 unsupported_capability。
- 外部 URL 不自动获得本地能力；外部页面授权与完整 ACL 配置继续作为后续阶段。
- 上游增补能力不等于可撤销权限；对同标签重建保留一致权限策略，不宣称关窗即撤销该标签能力。
- 测试动态窗口的新旧 IPC 和事件；针对未授权标签/外部来源确认拒绝，不仅验证 Python 侧原生发送。

## 文件与执行顺序

1. 更新实施方案、迁移契约与 API 账本；先固定签名、单位、回调及错误码。
2. 原生按 image、窗口状态、窗口构建、窗口事件分职责模块，扩展 runtime/application 的统一资源登记与事件转换。
3. Python 增加 URL/尺寸/位置类型、ffi.image 和 WebviewWindowBuilder；同步维护 _native.pyi 与公共导出。
4. 加入类型/参数/回调失败与资源生命周期测试；新增 examples/dynamic_window 和独立进程验收脚本。
5. 更新 runtime 能力报告、文档、源包包含项和审核账本；运行既有全部验收，避免改变第二阶段契约。

## 验收标准

1. 主窗口通过 Python 命令创建随机标签子窗口，新旧客户端均能完成 IPC 与来源注入。
2. 子窗口收到目标事件，其他窗口不收到；初始化脚本与 RGBA 图标参数经过真实构建。
3. 尺寸/位置经查询核对，隐藏后再显示，焦点与最大化/恢复记录可观测状态；平台拒绝焦点时单独记录结果。
4. 第一次关闭被阻止，过期 prevent_close 被拒绝，第二次关闭销毁窗口并从 Manager 映射移除。
5. 弱引用证明窗口回调释放；旧句柄报 window_closed，同标签重建生成可用新句柄。
6. from_config 不修改输入；无效标签/尺寸/图像数据/重复创建有稳定错误；失败后可继续创建其他窗口。
7. 导航允许/拒绝和页面加载事件通过真实 WebView 验证；回调异常退出后归还 Python，创建错误不使主进程崩溃。
8. GUI 回调内同步建窗及时拒绝，IPC 工作线程与异步入口建窗成功，后台 Python 线程继续运行。
9. Python 3.11/3.14 的独立 wheel、源包重建、pytest、Ruff/Pyright、cargo fmt/全 feature Clippy、覆盖核验及既有桌面验收全部执行。

## 后续批次

on_new_window、下载、资源请求修改、完整 WebView/窗口 API、窗口作用域事件监听与全部 EventTarget 继续逐项引出。
channel、菜单/托盘、官方插件、完整 ACL/CSP/隔离和移动平台仍按各自阶段实施。
本阶段选定参数与回调属于部分绑定，只有人工审核并验证的条目才更新状态。
