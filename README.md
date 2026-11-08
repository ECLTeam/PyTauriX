# PytaruiX

通过 PyO3 为 Python 提供 Tauri 绑定的独立新项目。发行包及 Python 导入名为 `pytaruix`，编码风格参考 ECL，公开 API 布局参考 PyTauri。

当前为第十三阶段系统交互与 WebView 策略回调开发版本；尚未完成全部 Tauri API、插件和发布验收。

后续推进见 [开发路线](docs/zh-CN/development-roadmap.md) 和 [第十一阶段体积与性能基础方案](docs/zh-CN/optimization-foundation-stage-plan.md)。
项目开发、线程/资源边界、构建裁剪、验收与独立发行要求统一见 [项目规范](AGENTS.md)。第十一阶段基线、feature 边界修正、release 参数实验已完成；第十二阶段扩展接口已有 Windows 证据；第十三阶段新增资源/新窗口/权限策略、独立 WebView profile 和系统交互验收，详见 [阶段方案](docs/zh-CN/system-webview-stage-plan.md)。
基线：Tauri 2.12.1、tauri-build 2.7.1、PyO3 0.29.3、Rust 1.90+、Python 3.11+。
release profile 采用 thin LTO、`opt-level = "s"` 与 `codegen-units = 1`；第十一阶段默认 wheel 基线约 3.25 MiB，当前产物以所属阶段记录为准。
首次构建需要 Rust 编译器与当前平台的 Tauri 系统依赖；Windows 需要 MSVC 构建工具和 WebView2。

## 当前能力

- Python 主线程启动真实 Tauri/WebView 窗口，退出后返回 Python。
- `Commands.command()`、同步/异步命令、Pydantic 参数与响应、来源窗口/句柄/请求头/共享状态注入。
- 原生 IPC Channel、Pydantic 通道模型、JSON/二进制流、显式结束与窗口代次清理。
- 原生应用构建、运行前 handle、setup、生命周期事件和退出拦截。
- 构建时原生插件注册；dialog 2.8.1 桌面文件/目录/保存和消息框的回调及阻塞接口。
- 窗口标题/焦点/关闭、应用和窗口主线程任务调度。
- 六种事件目标、对象或原始 JSON 发送，应用/窗口作用域与任意目标监听、一次监听和注销。
- 运行期动态窗口、配置构建与异步建窗，逻辑/物理尺寸与位置、RGBA 图像和扩展窗口属性；缩放/主题/拖放事件、标题变更与下载回调。
- WebView 新窗口 Allow/Deny、浏览器权限决策及应用资源响应钩子；不可变 HTTP 快照和校验后的完整响应替换。
- 显式绝对路径 `data_directory`，宿主拥有 WebView profile；Windows 焦点查询包含 WebView 子控件。
- 显示器/工作区/DPI 查询、只读快照和物理矩形；默认 PNG/ICO 原生加载，可显式关闭格式。
- 原生菜单/子菜单、普通/勾选/图像/分隔项、挂载/弹出与同步字符串事件；显式清理和窗口代次隔离。
- 显式 tray-icon feature 的桌面托盘 Builder、图像/菜单/提示、鼠标事件、应用查询、引用移除与显式关闭。
- 关闭拦截、销毁代次、导航/页面加载/标题变更/下载回调；精确标签本地权限，新旧 IPC 均接受上游 ACL 检查。
- 前端 `window.__TAURI__.pytaruix.pyInvoke` 与兼容入口 `window.__TAURI__.pytauri.pyInvoke`。
- 旧 PyTauri plugin 调用协议、JSON/原始字节正文与 ArrayBuffer 返回。
- 核心 Cargo features 转发、锁定源码发现清单与独立人工审核 API 账本。
- 宿主 JSON/TOML、平台覆盖、显式开发地址和宿主 capabilities；实际插件权限在构建前解析。
- 宿主 PNG/ICO 默认图标、配置窗口失败的 Python 错误归还；可选开发者工具支持。
- `get_runtime_info()` 查询绑定版本和当前已实现能力。

## 开始使用

在仓库根目录执行：

```powershell
uv sync --locked --no-install-project
uv run --no-sync maturin develop --locked --jobs 1
uv run --no-sync python examples/minimal/main.py
```

```python
from pytaruix import AppHandle, Commands, Manager, RunEvent
from pytaruix import builder_factory, context_factory
```

`Builder.build()` 构建原生应用；`App.handle()` 在运行前可用；每个进程支持一个原生应用。
配置窗口和 `setup(AppHandle)` 沿用 Tauri 2.12.1 的 Ready 初始化时机。早到的前端 IPC 等待 setup 完成后执行。
使用 `Manager.manage(app, object)` 注册状态，命令可通过 `Annotated[T, State()]` 取得原对象，或通过 `State[T].value` 访问。
`RunEvent.ExitRequested.api.prevent_exit()` 仅在同步回调内有效；退出释放监听器和状态，失效句柄拒绝资源操作。
配置与资源目录由调用方显式传入，不自动搜索已安装包的 entry point。资源在启动前读取为快照。
宿主定义 capabilities 后，动态窗口遵循宿主策略；仅无宿主策略的原型示例会自动授予本地精确标签权限。
ECL 调试功能需要 `maturin develop --features devtools`，正式发行 wheel 同样显式开启此 feature。
异步命令运行期间必须保持 AnyIO portal 开放。仅 Windows 已在本地验证，其他平台待 CI 验证。

## 结构与验证

`crates/bindings` 为原生边界，`python/pytaruix` 为公共 API，`frontend/bridge.js` 为前端桥，
`examples/minimal` 为真实窗口示例，`tests` 与 `scripts` 提供行为测试和覆盖核验。

```powershell
uv run --no-sync ruff check python tests scripts examples
uv run --no-sync ruff format --check python tests scripts examples
uv run --no-sync pyright
uv run --no-sync pytest
cargo fmt --all --check
cargo clippy --locked --jobs 1 -- -D warnings
uv run --no-sync python scripts/update_coverage.py --check
uv run --no-sync python scripts/desktop_smoke.py
uv run --no-sync python scripts/dynamic_window_smoke.py
uv run --no-sync python scripts/window_attributes_smoke.py
uv run --no-sync python scripts/event_dispatch_smoke.py
uv run --no-sync python scripts/dialog_smoke.py
uv run --no-sync python scripts/channel_smoke.py
uv run --no-sync python scripts/display_image_smoke.py
uv run --no-sync python scripts/menu_smoke.py
uv run --no-sync python scripts/host_config_smoke.py
# 托盘验收需先使用 --features tray-icon,devtools 构建。
uv run --no-sync python scripts/tray_smoke.py
uv run --no-sync python scripts/webview_policy_smoke.py
# 以下系统输入驱动仅在 Windows 实际桌面运行。
uv run --no-sync python scripts/system_interaction_smoke.py
```

详见 [实施方案](docs/zh-CN/implementation-plan.md)、[迁移契约](docs/zh-CN/migration-contract.md)、
[能力矩阵](docs/zh-CN/capability-matrix.md) 和 [验证记录](docs/zh-CN/validation.md)。
动态窗口用法和线程/权限差异见 [窗口指南](docs/zh-CN/windows.md)。
主线程调度、事件目标和监听作用域见 [事件指南](docs/zh-CN/events.md)。
插件注册、文件和消息框、线程及关闭契约见 [对话框指南](docs/zh-CN/plugins-dialog.md)。
原生进度/日志/二进制流、Pydantic 通道字段和结束契约见 [Channel 指南](docs/zh-CN/channels.md)。
屏幕快照、线程限制、格式开关与图像错误见 [显示器和图像指南](docs/zh-CN/displays-images.md)。
原生菜单构造、线程、共享所有权和事件广播契约见 [菜单指南](docs/zh-CN/menus.md)。
ECL 导入、配置、权限和隔离迁移/独立程序验收见 [ECL 接入指南](docs/zh-CN/ecl.md)。
资源请求、新窗口/权限策略与专用数据目录见 [策略回调指南](docs/zh-CN/webview-policies.md)。
系统托盘、事件、平台限制及引用/关闭契约见 [托盘指南](docs/zh-CN/tray.md)。

新项目许可证尚待确定，当前阶段不发布软件包。没有复制 PyTauri 实现代码，参考来源见迁移契约。
