# 第九阶段方案：ECL 接入与交付验收

状态：用户于 2026-10-02 明确“开始，并且项目更名为PytaruiX”，方案 1 已授权，接入实现、Windows 源码及独立程序桌面验收完成；原生拖放由用户暂缓验收，外部业务与其他平台单列。
项目统一为 PytaruiX，发行包及导入名为 pytaruix，Rust crate 为 pytaruix-*；历史包名仅保留在阶段快照和迁移说明中。
长期完整绑定 Tauri 的目标继续保留；本阶段以当前 ECL 实际依赖和运行结果为验收基准。

## 调研基线

框架路径：E:/Projects/EuoraCraft-Launcher/Tarui-PyO3，第八阶段原型，pytaruix 0.1.0a1。
ECL 路径：E:/Projects/EuoraCraft-Launcher/EuoraCraft-Launcher，HEAD eaa6973a1d2cfd6501ae35b92f4d0d7d387800e6。
调查对象包括当前工作区；ECL/utils/config.py、Tauri.toml 和 frontend 有既有未提交变更，实施须保留，不能仅按 HEAD 内容替换。
参考 PyTauri 位于 C:/Users/Wuchang325/.codex/worktrees/c9ec/pytauri，本阶段不修改该参考仓库。

已核对：ECL/adapters/tauri.py、api/{registry,bridge,windows,files,accounts,system}.py、plugins/host_dependencies.py，
frontend/src/api/transport/tauri.ts、app/runtime/desktopWindow.ts、App.vue，Tauri.toml、capabilities/default.toml，
pyproject.toml、packaging/build-nuitka.ps1、EuoraCraft-Launcher.spec 和 .github/workflows/build.yml。

## 阶段开始时的接入差距

| ECL 调用或配置 | 框架现状 | 本阶段工作 |
| --- | --- | --- |
| Commands、AnyIO portal、来源窗口/应用句柄、dict 正文 | 已绑定，示例验证；尚未用当前 ECL 全部正式处理器验收 | 核验实际命令注册、类型身份和异常边界，保留命令名与响应形状 |
| pytauri/pytauri_plugins/pytauri_wheel 导入 | 新包使用 pytaruix 命名空间 | 在隔离的 ECL 接入环境调整直接导入、依赖和注入注解，不使用 sys.modules 全局替换 |
| Tauri.toml 与配置递归覆盖 | Python context_factory 仅读取 tauri.conf.json | 补 TOML 配置发现、优先级和覆盖，保持明确资源根目录 |
| capabilities/default.toml | 当前读取不到宿主文件，编译示例能力只匹配 main/secondary | 补宿主能力载入和权限解析，核验 main/theme-studio/plugin.* 实际标签 |
| 原生标题栏 API：minimize/close/startDragging/isDecorated | Tauri 原生前端接口存在，但示例 ACL 缺少部分调用权限 | 按 ECL 显式权限授权，真实 JS 调用验收；不能靠新增 Python 同名接口代替 ACL |
| frontendDist 相对目录和 HTTP 开发地址 | 支持目录快照；拒绝 URL 和 devUrl | 保持生产资源快照，补明确开发来源和按来源匹配的权限，未知远程页面仍无自动授权 |
| run_on_main_thread → emit_str_to → WebviewWindow 目标 | 已有原生证据 | 用实际 ECL 事件桥验收就绪前缓存、多窗口定向和销毁清理 |
| 动态子窗口、初始化脚本、RGBA 图标、几何、焦点、关闭回调 | 选定接口已绑定 | 验收主题编辑窗口、插件/终端窗口、单例复用、边界保存和随主窗口关闭 |
| DialogExt.file 的 blocking_pick/save 接口 | 已有桌面子集 | 核对实际过滤器、目录/默认文件名和取消结果，验收 ECL 保存背景与皮肤链路 |
| debug_devtools_open → open_devtools | 未绑定 | 补开发者工具的打开/关闭/状态，说明构建 feature 和平台限制 |
| 主窗口图标和 native/custom/system_shadow 模式 | 现使用框架占位默认图标；选定窗口属性存在 | 从宿主配置加载真实默认图标，验收三种主窗口模式和子窗口约定 |
| 原生文件拖放事件 | 上游提供，当前未在 ECL 验收 | 验收 tauri://drag-* 监听、文件路径及退出注销，不只测 DOM 兜底 |
| Nuitka 包含原生扩展、发行元数据和资源 | ECL 清单固定旧包名；当前只有本地 wheel | 更新隔离接入环境的模块/元数据/资源清单，验证脱离源码目录的独立程序 |
| 插件宿主依赖声明与保留导入名称 | ECL 保护旧框架命名空间 | 同步新发行包和 pytaruix 宿主声明，保持现有 ECL 插件依赖管理行为 |

ECL 当前直接注册的 Tauri 插件只有 dialog；系统单实例、更新、文件/进程处理有自身业务实现。
本阶段不以“缺少其他 Tauri 插件”推断这些 ECL 功能缺失，实际链路须分别验证。
convertFileSrc 目前在传输适配器中提供，但检索未发现业务调用；不能因此自行开放任意本地文件访问。

## 接入方案与选择

1. **显式接入新包（推荐）**：修改 ECL 六处 Python 直接导入文件及依赖/打包清单，继续使用现有前端 pytauri.pyInvoke 协议。
   业务命令、数据目录和插件 SDK 保持现有契约；新框架身份明确，便于删除旧运行时依赖和定位问题。
2. **另发兼容包**：保留旧导入路径，以独立兼容发行包转发选定 API。
   需要处理与真实 PyTauri 包冲突、发行元数据、插件注入类型和入口发现，范围更大；不能用运行时 monkey patch 冒充兼容。
3. **补齐完整 PyTauri 后再接入**：扩大 API 覆盖后集中迁移。
   对近期 ECL 目标投入较大，不能提前发现实际配置和打包问题；继续作为长期目标。

建议选择方案 1。这里的“六处”指 adapters/tauri.py 和 api/{registry,bridge,windows,files,accounts}.py；
system.py 会受新增开发者工具影响，host_dependencies.py、项目依赖、测试替身与打包文件另外审核。

## 实施顺序

1. 固化当前调用与配置样本：记录来源提交、工作区相关文件摘要、正式命令签名、前端调用和原始数据/事件形状。
2. 在框架补配置/TOML、能力载入、开发来源、默认图标与开发者工具；同步公共文档、类型和覆盖账本。
   不扩大默认示例权限代替宿主配置；无效能力或不可用插件权限明确失败，不静默丢弃。
3. 加入 ECL 接入验收环境：隔离 checkout/工作树与专用数据目录，保存当前相关未提交变更的副本，调整直接导入和安装依赖。
   不覆盖用户正在使用的启动器或真实账户/实例数据；不得忽略带未提交内容的 frontend。
4. 启动实际 ECL 前后端，验证下述功能；按检查结果修复授权接入范围内的类型、线程、窗口回调和资源语义。
5. 更新隔离接入环境的 Nuitka 清单并产出独立程序；前端构建资源、Tauri 配置、capabilities、原生 DLL/扩展和发行元数据一起验收。
6. 框架回归、双版本 wheel/源包验收及跨平台构建 CI；汇总已通过与无法执行的平台检查。

本阶段实施已明确授权；实现、提交、推送、发布分别遵循本会话授权。
迁移验证完成后提供可审核的 ECL 改动，不将“在隔离副本通过”表述为原 ECL 已切换。
同一阶段若整合 CI，需要可用 Git 远程/分支；本地只有工作流文件或构建日志不能宣称云端 CI 通过。

## 验收标准

- 当前 ECL 正式命令全部成功注册；真实前端调用 frontend_ready、系统/设置和实例读取，窗口/应用注入不能由正文覆盖。
- 主窗口三种模式分别启动；真实标题栏最小化、拖动与关闭，启动焦点及后续单实例置前不回归。
- 原生后端事件到前端的完整转发、就绪前缓存、定向隔离、错误后恢复和日志/任务状态更新。
- 主题编辑窗口、实际注册插件窗口和终端窗口的创建、复用、关闭、尺寸保存和主窗口退出联动。
- 原生文件/目录选择、取消、过滤器、默认文件名、背景/皮肤保存，以及实际文件拖放。
- 插件窗口命令授权、插件启动/停用及窗口资源清理；既有 ECL 插件 SDK 行为保持。
- 开发服务器可加载并调用受授权 IPC；生产运行从打包资源启动，不依赖开发服务或源码工作目录。
- 游戏启动/进程日志/终止使用隔离测试实例验证；账户与网络业务依赖外部条件时单列结果，不把假响应计为完整验收。
- 独立 Nuitka 程序能脱离源码树启动、使用对话框/子窗口并正常退出；更新交接和重启以测试包/测试目录验收。
- ECL 相关后端测试、Ruff，涉及前端改动时执行 pnpm check 和生产构建；框架 Ruff/Pyright/pytest、Rustfmt/Clippy 与既有七组真实桌面脚本回归。
- Python 3.11/3.14 独立 wheel 和实际源包重建；Windows 优先完成真实桌面/打包证据，Linux/macOS 构建与 GUI 各自记录，未执行不标为通过。

达到本阶段标准后，才能称为“可用于 ECL 的接入版本”；完整 Tauri/PyTauri 覆盖、正式发行许可和移动平台另行推进。

## 当前实施结果与验收修正

统一命名、TOML/平台覆盖、宿主能力与实际插件权限、显式开发来源、默认图标和开发者工具已经实现。
配置窗口失败改为有序返回 Python 错误；Windows 开发者工具关闭/状态明确报告上游平台不可用。
隔离副本记录当前 ECL 与前端工作区，正式注册 216 个命令，三种主窗口模式均有真实 IPC/设置/事件/插件窗口/退出证据。
文件对话框、背景与皮肤字节、实际子进程日志/输入/终止已验证，当前来源提供 16 个文件的可审核迁移补丁。
插件 descriptorId 保持点号，原生窗口 label 改为冒号，capabilities 使用 plugin:*；不靠放宽宿主权限获得通过。

进一步核对发现当前 ECL 的内置窗口描述符为空，主题编辑器与终端没有已注册的内置窗口。
本阶段使用实际插件贡献窗口，并在框架通用宿主用例验证 theme-studio 标签，不能宣称当前 ECL 内置主题/终端窗口验收完成。
Minecraft、账户、完整更新替换/重启、Linux/macOS GUI 与云端 CI 仍有外部条件和未执行项。
独立 Nuitka standalone 已脱离源码目录通过三种窗口模式及离线插件/原生依赖用例。
原生文件拖放因模拟器覆盖输入位置，由用户明确保留为待验收；不将其他成功项目替代其结果，详见 [验证记录](validation.md)。

## 官方依据

- [Capabilities](https://v2.tauri.app/security/capabilities/)：窗口/WebView 与权限关联、JSON/TOML 文件及远程来源。
- [配置参考](https://v2.tauri.app/reference/config/)：frontendDist、devUrl、窗口和宿主配置。
- 当前代码中的 Cargo feature 转发不等于运行期 Python 配置加载，也不能代替真实前端权限验收。
