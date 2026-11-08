# 阶段实施记录与规划入口

当前路线见 [开发路线](development-roadmap.md)，通用工程规则见 [项目规范](../../AGENTS.md)。
本文保留第一至第十阶段的授权、当时范围与验收摘要；各阶段绝对路径、命令数量、产物和结果按当时快照理解。
2026-11-07 已完成下一步文档规划，第十一阶段实施方案见 [体积与性能基础](optimization-foundation-stage-plan.md)；基线已执行并记录在 [基线结果](performance-baseline.md)，裁剪与参数实验待确认。

## 已确认目标

独立项目；ECL 编码风格；降低 PyTauri 迁移成本；最新稳定 Tauri；最终完整引出其可用能力。
当前项目位置为 `D:/Projects/EuoraCraft-Launcher/PyTaruiX`，项目名为 PytaruiX，发行包和导入名为 `pytaruix`。
早期阶段使用过其他目录与项目名称，保留在对应历史记录中。许可证仍待确定，独立发行前需完成许可决策。

## 第一阶段范围与文件

1. `AGENTS.md`、`pyproject.toml`：编码规则、格式、类型检查、依赖和校验命令。
2. 本目录的迁移契约、能力矩阵、验证记录：可核验的实施范围。
3. `docs/upstream/tauri-2.12.1.json`：Cargo feature 和源码公开声明发现清单。
4. `scripts/update_coverage.py`：从 Cargo 锁定源码重新生成清单，检查 feature 映射与版本漂移。
5. `crates/bindings/src/{application,assets,ipc,window}.rs`：启动、资源、命令与窗口边界。
   `crates/bridge`：通过官方全局脚本构建集成保证桥接入口在 Tauri API 初始化后注册。
6. `python/pytaruix/{application,events,ipc,errors,runtime}.py`、`ffi`、`webview`：公共 API 与兼容形状。
7. `frontend/bridge.js`、`examples/minimal`：真实前端到 Python 闭环。
8. `tests`、`scripts/desktop_smoke.py`：参数、错误、线程、真实 WebView 与退出验证。

本阶段不复制 PyTauri 整仓，不修改 ECL 或参考仓库，不提交/推送，不发布。
第一阶段原生应用仅在 run_return 中构建；第二阶段将改为 build 即构建原生应用。
直接从 Python 主线程启动，运行时释放 GIL，不用 unsafe 穿透 PyO3 的 Send 限制。
前端命令使用原生工作线程调用 Python；异步函数交由用户提供的 AnyIO portal。
生命周期回调失败有序退出，run_return 返回前重新抛出原异常；命令失败只拒绝本次调用。
第二阶段每个进程仅允许构建一个原生应用，失败同样消费运行时。使用者重试应开启新进程。
资源预先读取为不可变快照，校验链接与路径；首轮拒绝运行时 CSP、自定义 ACL 和隔离配置，避免忽略配置。

## 验收

干净虚拟环境安装扩展；真实窗口启动；同步与异步/Pydantic 命令返回成功；错误命令返回稳定错误码；
错误之后下一条调用成功；前端收到 Python 发出的事件；窗口标题可修改；Python 后台线程继续运行；
窗口退出且 Python 进程结束；生命周期回调异常恢复到 Python；重复运行与错误线程调用有明确错误。
同时执行 Ruff、Pyright、pytest、cargo fmt/Clippy、覆盖清单核验、独立 wheel 安装与示例验证。

## 第二阶段（已授权实施）

1. `Builder.build` 立即构建原生应用；`App.handle` 可在运行前取得句柄。原生非 Send 应用保存在主线程线程局部存储，释放 GIL 的闭包只传递可跨线程句柄，不使用 unsafe。窗口与 setup 沿用锁定上游版本，在事件循环 Ready 时创建/调用。
2. `setup(AppHandle)` 和退出请求的 code/api；退出控制只在同步生命周期回调期间有效，过期调用明确报错。Python 回调失败有序退出并重抛原异常。
3. 同一命令处理链注入真实来源 WebviewWindow、原生请求头及按 Python 类型管理的共享状态；支持 `State[T]` 与兼容的 `Annotated[T, State()]`。共享对象的内部并发控制由调用方负责。
4. 支持旧客户端 `plugin:pytauri|pyfunc` / `pyfunc` 请求头 / 字节正文与字节响应；新协议保留结构化错误，旧协议保留字符串拒绝。编译期权限显式登记旧插件与示例的两个窗口。
5. 提供 `emit_to`、`listen`、`once`、`unlisten`；退出释放 Python 监听器与共享状态，失效句柄拒绝资源操作。监听回调异常走与生命周期相同的错误通道。
6. 独立审核账本记录上游所有者、来源、Python 签名、条件、兼容差异和验收证据。保留原始发现清单，不把正则扫描结果提升为完成状态。

实现已完成。双窗口实际验证发现配置窗口可在 setup 前调用命令，因此工作线程会等待初始化完成，期间不持有 GIL。
独立审核账本已有 24 个选定条目，焦点/关闭仅绑定未直接验收，其余选定接口记录全部或部分 Windows 验证。

验收：两个真实窗口调用同一命令并核验来源、共享状态和请求头；旧客户端 JSON/原始字节/错误/恢复；定向事件隔离与监听注销/一次回调；第一次退出被阻止、第二次允许；setup/生命周期/事件回调异常归还 Python；过期退出 API 与退出后句柄拒绝调用；3.11/3.14 wheel、源包重建、格式/类型/Clippy/覆盖核验通过。

第二阶段完成时，动态窗口和其余完整 WebView API、channel、官方插件、运行时 CSP/自定义 ACL、移动平台仍未实现。

## 第三阶段（已明确授权实施）

动态窗口创建与窗口生命周期的具体接口、线程/权限约束、清理路径和验收标准见 [第三阶段方案](window-stage-plan.md)。
授权范围已完成 Windows 验收：动态 build/from_config/build_async、选定属性与几何/RGBA、窗口代次和同步回调、精确标签本地权限。
Python 3.11/3.14 独立 wheel 与源包重建、各 51 项测试和 11 个真实桌面进程通过；动态场景包含 45 项联合检查和五种回调失败。
运行时能力、迁移契约、窗口指南与审核账本已同步。账本有 76 项：64 项已绑定并验收其调用或行为，12 项部分绑定并验收；外观未独立测量的能力单独注明。

## 第四阶段（已明确授权实施）

优先补齐 ECL 实际调用的 run_on_main_thread、EventTarget 与 ffi.Emitter.emit_str_to，以及多窗口监听作用域和 listen_any/once_any。
接口、迁移影响、任务/监听清理与验收标准见 [第四阶段方案](event-stage-plan.md)。
实现、开发环境和独立安装包验收已完成。事件发送、监听和主线程任务从 window.rs 拆到专门模块，资源统一按应用与窗口代次登记。
六种目标保留类型、原始 JSON 保留原文、窗口作用域与任意目标监听、任务进入 GUI 后的原生存活检查均已实现。
第四阶段完成时审核账本有 83 项：75 项已绑定并验收调用或行为，8 项部分绑定并验收；未将 feature 转发或独立资源形态计为全量覆盖。
Python 3.11/3.14 各 64 项测试、1 项环境跳过和 16 个真实桌面进程通过；新三窗口场景包含 26 项联合检查与四种回调失败。
源包核验和解压重建、Ruff/Pyright、Rustfmt/全 feature Clippy 通过；主线程调度与事件指南、运行时能力和迁移契约已同步。

## 第五阶段（已明确授权实施）

本阶段补齐 Builder.build 的 plugins 注册入口，以及 pytaruix.plugins.dialog 的桌面文件/消息对话框。
当前 ECL 启动时注册 dialog，文件和皮肤操作直接使用 DialogExt；RGBA 子窗口图标已支持，图像解码不是该调用链前置。
具体入口、线程/清理/权限边界及验收标准见 [第五阶段方案](plugin-dialog-stage-plan.md)。
用户“开始实施”已授权；实现、独立安装包及源包重建验收已完成。
插件注册、dialog 桌面子集及共享操作清理已实现；真实 Windows 48 个选择场景、七种关闭/异常和编译开关通过。
Python 3.11/3.14 各 85 项测试通过、1 项环境跳过，各 24 个真实桌面进程通过；源包逐字节核验 101 个文件。
修复解释器结束时未运行 App 的清理，以及固定源包时间戳导致 Cargo 缓存错用的问题。
核心账本 84 项，dialog 独立账本 37 项；创建目录开关的 macOS 效果、图标/过滤列表外观和移动/结构化结果保持明确限制。
IPC Channel、监视器、图像解码和其他插件仍按完整绑定目标分批推进。

## 第六阶段（已明确授权实施）

已补齐原生 IPC Channel 与流式 JSON/模型/字节输出，保留 PyTauri 的 JavaScriptChannelId、Channel 和 ffi.ipc 形状。
为 channel_on 提供所属窗口的 Webview 引用视图；显式关闭、GC、所有者代次及原生 fetch 缓存分别验证。
当前 ECL 没有直接使用原生 Channel，本阶段定位为通用框架核心能力补全。
具体接口、线程/权限边界和真实前端验收见 [第六阶段方案](channel-stage-plan.md)。
原生 Channel、Pydantic 兼容形状和 Webview 引用已实现，Windows 双窗口数据/终止/销毁缓存验收通过。
IPC 排队前捕获来源窗口代次，共享资源以弱引用登记通道；close、GC 和退出清理均保留明确错误契约。
开发环境 102 项测试通过、1 项符号链接权限跳过，既有 24 个桌面进程和新增 Channel 进程通过。
Python 3.11 独立 wheel 和 3.14 源包重建 wheel 各通过 102 项测试、1 项权限跳过和 25 个真实桌面进程。
Channel 场景包含 73 项联合检查，核心审核账本现有 89 项；迁移契约、能力矩阵和指南同步完成。
源包逐字节核验 112 个当前文件，解压后的绑定实际重新编译；监视器、图像解码、菜单/托盘和其他插件继续分批推进。

## 第七阶段（已明确授权实施）

建议补齐显示器查询、Monitor/PhysicalRect、工作区/DPI 信息及 PNG/ICO 的 Image.from_bytes/from_path。
Monitor 保持 PyTauri 属性形状，图像解码扩展上游能力；默认/可关闭 feature、线程和平台证据分别核验。
当前 ECL 不直接使用上述查询/解码，本阶段定位为通用桌面基础能力，为后续菜单/托盘提供图像基础。
具体接口和真实验收范围见 [第七阶段方案](display-image-stage-plan.md)。
用户“开始”已授权；显示器快照、物理矩形及原生 PNG/ICO 加载已实现并完成 Windows 验收。
格式输入按显式 feature 控制，避免 ICO 的传递 PNG/BMP 依赖扩大公开契约；默认同时开启 PNG/ICO。
Windows 当前单屏 1600×900、100% DPI；多屏/混合 DPI、热插拔与跨平台可靠性仍需后续真实环境验收。
四种格式组合实际构建并独立验证；Python 3.11/3.14 各 113 项测试、1 项权限跳过和 26 个桌面进程通过。
源包逐字节核验和实际重建完成；指南、迁移契约和核心 100 项审核账本同步。

## 第八阶段（已明确授权实施）

建议先补齐原生菜单，为后续托盘复用菜单类型与资源生命周期。
保留 menu/ffi.menu 的常用导入、构造及字符串 MenuEvent，覆盖选定菜单项、挂载/弹出、动态修改与回调。
对象所有权、GUI 调度、窗口代次和真实菜单行为分别验收；不把选定子集或 Windows 证据称为完整平台覆盖。
具体范围与验收见 [第八阶段方案](menu-stage-plan.md)。选定菜单子集已实现并完成 Windows 桌面及安装包验收。
接口、广播与共享资源的迁移约束见 [菜单指南](menus.md)。Windows 关闭前解除关联，保留被拦截的挂载和共享菜单复用。
开发环境、Python 3.11 独立 wheel 与 3.14 源包重建 wheel 各通过 132 项测试、1 项权限跳过和 29 个真实桌面进程。
菜单场景各有 73 项联合检查和两种回调失败恢复；原生文字/排序/标志、16×16 不透明图像、共享资源重建与引用清理均有独立证据。
源包逐字节核验 143 个当前文件；核心审核账本 185 项，指南、能力矩阵及迁移契约同步。
跨平台构建/打包 CI 仍为空缺，建议菜单之后作为可靠性阶段优先补齐，再继续托盘。

## 第九阶段（已明确授权实施）

用户于 2026-10-02 明确近期目标为达到可供当前 ECL 使用的程度。
以 ECL 的实际调用、配置、前端原生权限及独立程序结果为阶段标准；长期全量绑定目标保留。
具体差距、三种接入方案、改动范围和验收要求见 [ECL 接入方案](ecl-stage-plan.md)。
推荐显式使用 pytaruix，先补 TOML/宿主 capabilities、开发来源、默认图标、开发者工具和打包支持，
再在隔离 ECL 接入环境验证命令、事件、对话框、主/子窗口、插件及独立程序。
用户“开始，并且项目更名为PytaruiX”已授权；使用 pytaruix 命名空间实施，ECL 既有未提交变更须保留。
统一身份与上述宿主配置/权限/图标/开发者工具已经实现，配置窗口失败有序归还 Python 错误。
隔离 ECL 正式注册 216 个命令；三种主窗口、实际插件窗口与权限、事件、原生保存对话框及子进程链路已验证。
后端 938 项测试通过、5 项跳过；前端 525 项测试通过、1 项待办，检查与生产构建完成。
提供 16 个文件的可审核 ECL 迁移补丁；原 ECL 及参考 PyTauri 未切换，当前云端 CI 尚未运行。
Nuitka standalone 构建成功，脱离源码目录的三种窗口模式、离线插件安装及原生扩展加载均通过。
原生拖放按用户选择待验收；外部业务与平台结果单列在 [验证记录](validation.md)，正式发布条件尚未齐全。

## 第十阶段（已明确授权实施）

用户于 2026-10-16 要求继续完成未实现功能。已调研系统托盘缺口和现有菜单、图像、回调资源管理，
具体接口、线程/所有权、feature 与真实桌面/安装包验收见 [第十阶段方案](tray-stage-plan.md)。
用户已回复“开始”；正在补齐桌面托盘，复用既有菜单资源，并扩展现有 CI 工作流。
三平台 CI 文件已经存在，当前欠缺实际执行与跨平台 GUI 证据，不能继续表述为没有工作流。
用户另要求重建依赖并重新下载，沿用锁文件，在独立环境和 Cargo target 中执行；提交、推送与发布仍分别授权。

## 第十一阶段（基线已执行，裁剪与参数实验待确认）

2026-11-07 用户要求规划优化文档，并参照 ECL 为本项目制定详细规范，准备后续开发。
本次整理项目规范、开发路线和 [第十一阶段方案](optimization-foundation-stage-plan.md)，推荐先建立同源体积/性能基线，
修正 workspace、bindings、bridge 的上游默认 feature 边界，再比较 release 参数并验证候选 wheel。
用户确认执行基线后，新增 `scripts/measure_distribution.py` 与 `scripts/benchmark_runtime.py`，
在 Windows x86_64 / CPython 3.14.8 下构建默认、`devtools,tray-icon`、最小 `wry` 三组 release wheel 并采集样本。
默认组合 wheel 4.60 MiB、原生扩展 14.43 MiB、导入 P50 0.148 秒；`cargo tree` 确认 11-01：
最小组合仍经 bridge 继承 `tauri/default`，只比默认小约 0.36 MiB。完整结果见 [基线结果](performance-baseline.md)。
feature 边界修正、release 参数实验与 IPC 基准已完成；原第一至第十阶段授权继续按对应范围处理。
release 参数已按同源七组配置对比：`opt-level="s"` + `codegen-units=1` 使 wheel 从 4.52 MiB 降至 3.25 MiB（−28%），
`strip` 无收益，fat LTO 仅额外 1.4% 且构建更慢；结果见 [release 参数实验](release-profile-experiment.md)。
默认 profile 已采用 `lto="thin"` + `opt-level="s"` + `codegen-units=1`；默认 wheel 为 3.25 MiB，
独立 venv 的 `desktop_smoke` 与 `window_attributes_smoke` 均通过。

## 第十二阶段（窗口/WebView 完整化，实现完成，专项桌面证据待补）

2026-11-07 用户确认本批次，并要求先完成第十一阶段 feature 边界修正。
workspace 与 bridge 已停止继承 `tauri/default`；默认 wheel 4.50 MiB、最小组合 4.05 MiB，`cargo tree` 不再出现 default。
运行期 Builder 常用属性、缩放/主题/拖放窗口事件、标题变更与下载回调、四项窗口设置入口已实现；
Ruff、Pyright、169 项 pytest、默认与最小 feature 编译、devtools+tray Clippy、Rustfmt 与覆盖账本核验通过。
新增属性的独立真实桌面场景已加入并 7 项全通过；拖放、缩放/主题变化与 DPI 系统输入仍待补充。既有动态窗口场景 44/45 通过，焦点项受当前非前台会话影响。
方案与未绑定项见 [第十二阶段方案](window-webview-completion-stage-plan.md)。

后续资源加载、IPC、安全配置支持、当前 ECL 集成和独立发行按开发路线逐项细化。
长期完整绑定和官方插件目标保留，以下列表作为能力覆盖方向，实际执行顺序以开发路线的依赖为准。

## 后续能力覆盖

1. 核心完整绑定：逐项审核发现清单，完善 App/Builder/Context、State、事件监听、IPC 确认/背压、取消与退出控制。
2. 窗口/WebView 完整绑定：Builder、导航、新窗口、下载、请求、页面加载、尺寸、嵌入及平台专属接口。
3. 菜单、托盘、资源、协议、ACL/隔离、配置与构建：完善 Python 等价设计和条件构建测试。
4. 官方插件：一个插件一个适配模块，沿用 init 与扩展类习惯，按独立版本锁定和验证。
5. 实验性/移动平台、预编译 wheel 与独立程序：分别验证平台运行时，不用桌面测试替代移动验收。
6. PyTauri 兼容包：确认包冲突、旧前端协议、入口发现与完整调用语义，形成可执行迁移示例。

## 风险与回退

Tauri 宏与部分权限/脚本由编译期生成，运行时修改配置不保证完整等价；遇到此类接口必须明确拒绝或设计构建集成。
Cargo feature 已映射不意味着 Python 能使用其全部接口；全特性组合不等于所有平台都能编译。
不将未测试接口标为完成。遇到未支持的 cfg、ABI 或平台限制，保留源码和清单并记录具体证据。
历史原型阶段的回退范围以当时方案为准。后续变更按实际宿主、资源与数据影响制定恢复路径，隔离保护 ECL、参考仓库和其他工作区内容。

## 第十三阶段（系统交互与 WebView 策略回调，已授权实施）

2026-11-07 用户要求“系统交互与完整能力开始实现”，本批先落实三个策略钩子和系统交互收口。
新增 `on_new_window`、`on_permission_request`、`on_web_resource_request` 及不可变快照与决策类型；
资源响应先完整校验再替换，异常返回空 500；策略失败拒绝并沿原通道归还 Python。
显式 `data_directory` 使用绝对 Path，配置 dataDirectory 的绝对/遍历路径明确拒绝，测试 profile 由父进程清理。
Windows `is_focused()` 查询覆盖 WebView 子控件，旧代次继续失效；下载回调不再按可复用标签查找状态。
Windows OLE 四类事件、焦点往返及窗口主题事件 9 项通过；托盘完整正常/异常/awaitable 三进程通过。
阶段方案、未验收平台和后续完整能力批次见 [第十三阶段方案](system-webview-stage-plan.md)。
本批不提交、不推送、不发布；当前 ECL 的正式迁移不在本次修改中执行。

## 第十四阶段（路径与进程，实现完成）

2026-11-08 用户要求完成未实现功能，并明确当前以 Windows 为主、同时考虑 Linux/macOS。
本批补齐能力矩阵中「路径/进程/异步运行时」的路径与进程部分；异步运行时保持不转发。
新增 `pytaruix.path`（`BaseDirectory`、`PathResolver` 的 `resolve`/`parse` 与 21 个目录属性）
和 `pytaruix.process`（`current_pid`、`current_binary`、`restart`）。
原生侧新增 `paths` 模块与四个 `AppHandle` 入口，Windows 上去掉 `\?\` 扩展长度前缀，非 UTF-8 路径明确失败。
`tests/test_path_contract.py` 8 项契约测试通过；`scripts/path_smoke.py` 在真实窗口内 12 项检查全通过。
人工审核账本新增 25 条（21 个目录 + `resolve`/`parse` + 进程两项），当前 260 条：
219 已绑定验收、31 部分绑定、8 平台不可用、1 未绑定、1 已绑定未在自动化中触发。
Ruff、Pyright、200 项 pytest、Rustfmt、Clippy（默认 features、`-D warnings`）与账本核验通过。
本批未提交远端、未发布，ECL 正式工作区未修改。

## 第十五阶段（菜单预定义角色，实现完成）

本批补齐能力矩阵中「菜单」领域的预定义角色：此前只有 separator，其余 17 个角色与 About 元数据未实现。
新增 `copy`、`cut`、`paste`、`select_all`、`undo`、`redo`、`minimize`、`maximize`、`fullscreen`、
`hide`、`hide_others`、`show_all`、`close_window`、`quit`、`services`、`bring_all_to_front` 与 `about` 工厂。
`AboutMetadata` 为 frozen dataclass，经 JSON 边界传入原生 `AboutMetadata`，图标未绑定。
原生 `create` 新增 `metadata` 参数并扩展角色分支；`PredefinedMenuItem.kind()` 统一报告 `predefined`。
`tests/test_menu_contract.py` 21 项通过（新增角色映射与元数据序列化）；`scripts/menu_roles_smoke.py`
在真实桌面构造全部角色并挂载菜单，8 项检查全通过；macOS 专属角色在 Windows 可构造但无可见效果。
人工审核账本新增 17 条，当前 277 条：236 已绑定验收、31 部分绑定、8 平台不可用、1 未绑定、1 未在自动化中触发。
Ruff、Pyright、pytest、Rustfmt、Clippy 与账本核验通过；本批未提交远端、未发布。

## 第十六阶段（默认菜单与 NativeIcon，实现完成）

补齐「菜单」领域剩余的两个具名缺口：`Menu.default(manager)` 与 `IconMenuItem` 的原生图标入口。
`NativeIcon` 以 56 项 `StrEnum` 暴露，取值等于上游变体名，原生侧用 serde 反序列化，
不复制变体表；未知名称返回 `invalid_native_icon`。
`IconMenuItem.with_native_icon`、`with_id_and_native_icon`、`set_native_icon` 已绑定；
Windows/Linux 可设置但无可见效果，账本逐条标注该限制。
`scripts/menu_roles_smoke.py` 扩展为 12 项检查（新增默认菜单、图标构造、清除与非法名称拒绝），全部通过。
人工审核账本新增 4 条，当前 281 条：240 已绑定验收、31 部分绑定、8 平台不可用、1 未绑定、1 未在自动化中触发。
Ruff、Pyright、pytest、Rustfmt、Clippy 与账本核验通过；未提交远端、未发布。

## 第十七阶段（IPC 取消与背压，实现完成，桌面证据待补）

2026-11-08 用户要求实现 IPC 取消/背压、自定义协议与官方插件；首批插件定为「通用骨架 + fs 样板」。
本批只含 IPC 取消与背压，方案见 [第十七阶段方案](ipc-cancel-backpressure-stage-plan.md)。
上游事实：`InvokeResolver` 可 Clone 且共享 `Arc<Mutex<Option<responder>>>`，
`return_result` 对已消费 resolver 直接 panic，因此取消必须与完成竞争同一份所有权。
新增 `PendingInvocation`、按 `(窗口标签, request_id)` 的 `Requests` 登记表、
`pytaruix_cancel` 与 `pytaruix_channel_ack` 两个原生分发入口，以及注入用的 `Request` 句柄。
窗口销毁以 `window_closed`、应用退出以 `app_closed` 归还该窗口全部待应答项。
通道新增 `capacity` 与 `send(timeout=)`：`capacity > 0` 时按配额发送，配额由前端
`pytaruix.createChannel` 归还，超时报 `channel_backpressure`，提交失败回滚配额。
前端桥新增 `AbortSignal` 取消与 `createChannel`；旧 `pyfunc` 协议不参与取消与配额。
`tests/test_request_cancel.py` 5 项契约通过，全量 pytest 208 项通过、1 项跳过；
Ruff、Ruff format、Pyright、Rustfmt 与默认 features Clippy（`-D warnings`）通过。
真实 Windows 桌面取消与配额证据、最小 feature 组合构建仍待补；未提交远端、未发布。

## 第十八阶段（自定义协议，实现完成，WebView 往返证据待补）

与第十七阶段同批推进，方案见 [第十八阶段方案](custom-protocol-stage-plan.md)。
只提供异步响应版本：上游同步版本在调用线程执行回调，Python 回调可能卡住 GUI 线程，故不暴露。
新增 `crates/bindings/src/protocol.rs`（`Protocol`、`protocol_create`、异步登记与响应转换），
`Builder.build(protocols=)` 在构建期校验名称唯一性并消费描述符。
Python 侧新增 `pytaruix.protocol`：`ProtocolRequest`/`ProtocolResponse` 不可变快照与 `create_protocol`；
处理器异常、非响应返回值、非法状态或头字段归还空 500，未就绪归还 503。
scheme 规则为 ASCII 小写开头、仅小写字母/数字/`-+.`、≤32 字符，排除 `tauri`/`asset`/`http`/`https`/`ipc`/`channel`。
`tests/test_protocol_contract.py` 覆盖名称规则、请求快照、返回值类型与默认响应，全量 pytest 231 项通过、1 项跳过。
Ruff、Ruff format、Pyright 通过；真实 Windows WebView `fetch` 往返、CORS 与 Linux/macOS 行为仍待补。
本批未提交远端、未发布。

## 第十九阶段（插件骨架与 fs 样板，实现完成，桌面证据待补）

方案见 [第十九阶段方案](plugin-fs-stage-plan.md)。插件描述符改为「名称 + 装载闭包」：
`Plugin` 保存 `Box<dyn FnOnce(Builder) -> Builder + Send>`，擦除上游插件的 `Config` 类型，
使 `TauriPlugin<Wry>` 与 `TauriPlugin<Wry, Option<Config>>` 共用同一 Python 类型。
新增 `plugin-fs` feature 与 `tauri-plugin-fs = "=2.6.0"`（上游声明 `tauri` 时已 `default-features = false`，
未重新启用默认能力），默认 wheel 不含 fs。
`crates/bindings/src/fs.rs` 只绑定上游真正提供的 Rust API：`read_text`、`read_bytes`、`write_text`、`write_bytes`；
目录遍历、删除与重命名在上游只存在于命令层，Python 侧已由 `pathlib` 覆盖，不重复实现。
`Fs` 先用 `try_fs_scope()` 判断插件是否注册，避免上游 `fs()` 直接 panic。
Python 侧新增 `pytaruix.plugins.fs`（`init`、`Fs`、路径归一），`get_runtime_info()` 新增 `fs_version`
与 `plugin.fs` 能力项；`plugin_fs_available` 随构建变化。
`tests/test_plugin_fs_contract.py` 10 项契约通过（路径归一、类型拒绝、`Fs` 构造、能力报告、缺 feature 拒绝）；
全量 pytest 240 项通过、2 项跳过。默认、`plugin-fs`、最小 `wry` 三组 Clippy（`-D warnings`）与 Rustfmt 通过，
Ruff、Ruff format、Pyright 通过。
**未验证**：Windows 真实读写场景、Linux/macOS 与移动平台；上游 Rust API 不经过 capability scope，
本绑定不宣称受限访问。本批未提交远端、未发布。

## 第二十阶段（系统集成插件，实现完成，桌面行为待补）

方案见 [第二十阶段方案](plugin-extensions-stage-plan.md)。按用户指定顺序补齐四个 Python 侧做不到的能力：
single-instance 2.3.2、global-shortcut 2.3.0、notification 2.3.0、opener 2.5.0，各自独立 feature，
默认 wheel 不变。四个上游 crate 均声明 `tauri` 时 `default-features = false`，未重新启用默认能力。
`single_instance` 回调桥接 `(AppHandle, argv, cwd)`；`GlobalShortcut` 只在 `ShortcutState::Pressed` 时回调；
`Notification` 归还权限状态文本并按 `silent`/`id` 构造通知；`Opener` 提供 `open_url`/`open_path`/`reveal_item_in_dir`。
包装类先检查 `RuntimeState.plugins` 登记表，未注册时返回 `plugin_missing`，避免上游 `state()` panic。
构建器把**用户插件排在桥接插件之前**，满足 single-instance 尽早登记的要求；桥接脚本为构建期注入，
`pytauri` 只注册 `pyfunc`，顺序调整不影响既有行为。
同时启用多个插件时，Windows 依赖在并行 codegen 下会触发 rustc `STATUS_STACK_BUFFER_OVERRUN`，
构建需 `CARGO_BUILD_JOBS=1`；该限制只写在指南，不改变仓库默认命令。
`tests/test_plugin_extensions_contract.py` 覆盖可用性标志、能力报告一致性、缺 feature 拒绝、参数校验与包装类类型检查；
全量 pytest 251 项通过、3 项跳过。默认、全插件、最小 `wry` 三组 Clippy（`-D warnings`）、Rustfmt、
Ruff、Ruff format、Pyright 通过。
**未验证**：第二实例唤醒、热键冲突、通知显示、默认程序启动的真实系统行为，以及 Linux/macOS 与移动平台。
本批未提交远端、未发布。

## 第二十一阶段（插件上游审核账本补齐）

第二批工作提交后补记。`scripts/update_coverage.py` 原先把 dialog 拆分核验写死在函数里，
现改为 `PluginSpec` 清单驱动，五个插件按同一口径核验版本、源码哈希、feature 与审核账本。
可选插件依赖默认不在解析图中，`cargo metadata` 改用 `--all-features`，否则取不到插件源码路径。
新增 `docs/upstream/{fs,global-shortcut,notification,opener,single-instance}-<版本>.json` 快照与对应
`bindings-*.json` 账本：fs 9 条、global-shortcut 7 条、notification 10 条、opener 6 条、single-instance 2 条。
已绑定条目统一记为 `bound_unverified`——Python 契约测试覆盖参数与对象行为，但没有真实桌面调用证据；
上游命令层的目录、删除、重命名等接口记为 `unimplemented`，并在账本注明由 pathlib 覆盖，不重复实现。
未转发的可选 feature（fs 的 watch、notification 的 windows7-compat、single-instance 的 deep-link 与 semver）
在 `dependency_notes` 中显式说明。`--check` 通过，审查输出改为逐插件列出条目状态计数。

## 第二十二阶段（窗口状态插件，实现完成，桌面恢复待补）

按需继续铺插件，方案并入本记录。新增 `plugin-window-state` feature 与
`tauri-plugin-window-state = "=2.4.0"`（上游已声明 `tauri` 使用 `default-features = false`），
默认 wheel 不变。`crates/bindings/src/window_state_plugin.rs` 命名避开了既有的
`window_state.rs`（窗口代次管理）。
注册侧只接受静态参数：`filename`、`flags`、`denylist`、`skip_initial`；
`with_filter` 与 `map_label` 需要在构建期传入 Python 回调，未绑定并记入账本。
运行期 `WindowState.save()/restore()/filename` 都先查运行态插件登记表，未注册报 `plugin_missing`，
避免上游 `state::<PluginState>()` panic；恢复只面向已存在窗口，新窗口仍由插件在创建时完成。
标志名与上游 `StateFlags` 一一映射，未知名称报 `ValueError`，不静默降级。
`tests/test_plugin_window_state_contract.py` 13 项契约通过；全量 pytest 262 项通过、4 项跳过；
Pyright 0 错误，Ruff 与 Ruff format 通过；Rustfmt 与默认、全插件、最小 `wry` 三组 Clippy（`-D warnings`）通过。
账本新增 `bindings-window-state-2.4.0.json` 9 条（7 条 bound_unverified、2 条 unimplemented），
`update_coverage.py` 的插件清单同步扩到六项，`--check` 通过。
**未验证**：跨会话恢复、多显示器变化下的位置修正、denylist 与 skip_initial 的真实效果。
