# 功能清单

本文记录当前已绑定的公开能力，按领域组织。状态分级与平台证据见[能力矩阵](capability-matrix.md)，
接口契约与迁移差异见[迁移契约](migration-contract.md)。清单只列已实现的 Python 入口，
不表示上游 API 已完整覆盖。

## 应用与生命周期

- Python 主线程启动真实 Tauri/WebView 窗口，退出后返回 Python。
- 原生应用构建、运行前 `App.handle()`、`setup(AppHandle)`、生命周期事件与退出拦截。
- `RunEvent.ExitRequested.api.prevent_exit()` 仅在同步回调内有效；退出时释放监听器与共享状态。
- 构建期原生插件注册；配置窗口失败的 Python 错误归还。

## 命令与 IPC

- `Commands.command()`、同步/异步命令、Pydantic 参数与响应。
- 来源窗口、`AppHandle`、请求头与 `State[T]` 共享状态注入。
- 原生 IPC Channel、Pydantic 通道模型、JSON/二进制流、显式结束与窗口代次清理。
- 旧 PyTauri `plugin:pytauri|pyfunc` 协议、JSON/原始字节正文与 ArrayBuffer 返回。
- 前端 `window.__TAURI__.pytaruix.pyInvoke` 与兼容入口 `window.__TAURI__.pytauri.pyInvoke`。

## 事件与调度

- 六种事件目标、对象或原始 JSON 发送，应用/窗口作用域与任意目标监听。
- `listen`、`once`、`listen_any`、`once_any`、`unlisten` 与窗口代次隔离。
- 应用与窗口级主线程任务调度。

## 窗口与 WebView

- 运行期动态窗口、配置构建与异步建窗，逻辑/物理尺寸与位置、RGBA 图像与扩展属性。
- 标题、焦点、可见性、缩放、主题、拖放事件与标题变更、下载回调。
- 导航、页面加载、关闭请求与关闭拦截，销毁代次与失效句柄拒绝。
- WebView 新窗口 Allow/Deny、浏览器权限决策、应用资源响应钩子与不可变 HTTP 快照。
- 显式绝对路径 `data_directory`；Windows 焦点查询包含 WebView 子控件。
- 精确标签本地权限与宿主 capabilities，新旧 IPC 均接受上游 ACL 检查。

## 系统集成

- 显示器/工作区/DPI 查询、只读快照与物理矩形；默认 PNG/ICO 原生加载，可显式关闭格式。
- 原生菜单/子菜单、普通/勾选/图像/分隔项与 17 种预定义角色（编辑、窗口、应用、About）、默认应用菜单、NativeIcon、挂载/弹出与同步字符串事件。
- 显式 `tray-icon` feature 的桌面托盘 Builder、图像/菜单/提示、鼠标事件、应用查询与显式关闭。
- dialog 2.8.1 桌面文件/目录/保存与消息框的回调及阻塞接口。
- 路径解析：`BaseDirectory` 变量、`PathResolver.resolve/parse` 与 21 个目录属性。
- 进程查询：当前 PID、当前可执行文件路径与重启入口。

## 宿主与构建

- 宿主 JSON/TOML 配置、平台覆盖、显式开发地址与宿主 capabilities。
- 宿主 PNG/ICO 默认图标与可选开发者工具支持。
- 核心 Cargo features 转发、锁定源码发现清单与独立人工审核 API 账本。
- `get_runtime_info()` 查询绑定版本与当前已实现能力。
