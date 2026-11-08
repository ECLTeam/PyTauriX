# Tauri 全量能力覆盖矩阵

基线为 Tauri 2.12.1；所有能力最终目标为可用的 Python 接口或明确的构建集成。
状态：待审核、未实现、部分绑定、仅构建映射、已绑定、已验证、平台不可用。
转发 Cargo feature 与完成 API 绑定分别核验，不用模块存在或构建成功代替功能测试。

## 核心领域

| 领域 | 当前覆盖 | 未完成内容/条件 |
| --- | --- | --- |
| App/Builder/Context | 部分绑定 | build/handle/setup/run_return 和插件序列已验证；run、任意插件和完整配置待实现 |
| AppHandle/Manager | 部分绑定 | 窗口查询、类型状态、退出与主线程调度已验证；其他管理器 API 待实现 |
| 生命周期 | 部分绑定 | Ready/Exit/ExitRequested(code, api) 已验证；窗口/设备/平台事件待实现 |
| 窗口/WebView | 部分绑定 | 扩展构建属性、主题读写、标题变更与 blob 下载有 Windows 真实桌面证据；拖放/缩放/主题变化事件与显示查询、几何、销毁、显示器/DPI/工作区快照已绑定，其中拖放与 DPI 专项证据待补；独立 profile 与新窗口/资源/权限策略已接入；完整 Builder、嵌入与 Create 待实现 |
| WebView 回调 | 部分绑定 | 同步导航、页面加载、标题变更与下载有 Windows 证据；新窗口 Deny、应用资源响应替换、Geolocation 拒绝及失败恢复有 Windows 证据；新窗口 Create、Allow/Default 平台效果待补 |
| IPC/命令 | 部分绑定 | 状态/来源窗口/头字段、旧字节协议与原生 Channel 已验证；取消、背压、TS 生成待实现 |
| 事件 | 部分绑定 | 六种目标、原始 JSON、应用/窗口/任意目标监听已验证；过滤发送与独立 Window/Webview 资源待实现 |
| 资源/图像 | 部分绑定 | 文件快照、RGBA、PNG/ICO 原生解码及四种 feature 组合已验证；其他资源来源、CSP 哈希待实现 |
| 菜单 | 部分绑定 | 六种资源、17 种预定义角色与 About 元数据、默认菜单、NativeIcon、项目顺序/动态修改、挂载/弹出/广播事件及清理有 Windows 证据；NativeIcon 在 Windows 无可见效果，完整 Builder 待实现 |
| 托盘 | 部分绑定 | 桌面 Builder、图标/菜单、鼠标事件、应用查询和显式关闭已绑定；Rust 内部闭包扩展未绑定，平台限制单列 |
| 路径/进程/异步运行时 | 部分绑定 | 21 个目录、`resolve`/`parse` 与进程查询/重启已绑定并有 Windows 证据；Tauri `async_runtime` 明确不转发，移动平台区别待建 |
| 自定义协议 | 未实现 | 同步/异步响应与资源、请求边界 |
| ACL/隔离/权限 | 部分绑定 | 宿主 JSON/TOML、窗口模式、远程来源、实际插件权限和空策略拒绝已验证；撤销、隔离、schema 待实现 |
| 配置/构建/打包 | 部分绑定 | JSON/TOML、平台覆盖、生产资源快照、显式开发地址与 wheel；JSON5/CSP、正式打包发布待验收 |
| 实验性接口 | 仅构建映射 | unstable 多 WebView 等逐项验证 |
| Android/iOS | 未实现 | Python 运行时、原生宿主集成、平台设备验收 |

## 源码与 feature 清单

`../upstream/tauri-2.12.1.json` 保存锁定 Cargo 源码的 feature、源码 SHA256、公开声明候选。
每条声明用源码位置标识并初始标记待审核；它是发现清单，不是 Rust 语义解析器。
当前共有 36 个 feature 映射、1,260 条公开声明候选。Windows 全 feature 组合通过 Clippy 构建核验。
Specta 固定为 2.0.0-rc.25 并显式启用 std，补齐其 PhantomData 类型支持；默认运行时不启用此可选依赖。
扫描包含 cfg 禁用、内部模块、测试和重导出相关候选，可能漏掉宏生成接口、trait 方法、枚举变体与公开字段。
人工审核必须补齐这些项、确定所属类型与平台，关联 Python 入口、签名和测试，才能评估全量完成率。
升级先重新生成发现清单，评估增删差异，更新矩阵和迁移契约；不能覆盖掉人工审核结论。

`../upstream/bindings-2.12.1.json` 为独立人工审核账本，当前有 281 个选定 API 条目：
240 个选定接口已绑定并有 Windows 调用或行为证据，31 个已验证其部分绑定，8 个在 Windows 上游不可用，
1 个内部 Rust 闭包扩展明确未绑定，1 个进程重启入口已绑定但不在自动化运行中触发。
窗口焦点/关闭已有真实行为验收；PNG/ICO 图标已读取 Windows 小图标并逐像素核对不透明样本，
阴影、任务栏大图标、透明度合成等外观未独立测量，账本单独注明。
每条记录所有者、锁定源码位置/声明、Python 签名、条件、实测平台、证据文件和限制。
核验脚本检查条目唯一性、来源声明与测试证据是否存在；不重新覆盖审核结果，也不计算全量完成率。
账本包含正则发现清单漏掉的 trait 方法和重导出，因此不能以 281 / 1,260 计算 API 覆盖率。

宿主配置通过 context_factory 的 Python 等价入口，默认图标和包信息不提供完整可变 Context 接口。
开发者工具显式依赖 devtools feature；Windows 上游关闭无操作、状态恒为 false，因此这两个接口明确报告平台不可用。
ECL Windows 源码副本已完成实际接入检查；原生文件拖放、账户/真实游戏与完整更新发布仍分别验收。

菜单六种资源及选定构造/修改/挂载/弹出接口已有 Windows 原生读回和实际选择证据。
Menu 的两个 set_as_* 保留 PyTauri 的 None 返回值；ContextMenu 接受现有 WebviewWindow 是显式扩展，
这四项按部分绑定记录。事件广播给应用和所有窗口订阅，窗口参数不是点击来源。
关闭拦截保留挂载；实际系统关闭请求解除 HMENU 关联，共享菜单可用于同标签重建窗口。
16×16 不透明菜单图像已逐像素核验；大图缩放、透明合成、物理快捷键和 Linux/macOS 未独立验收。

原生 Channel 已验收标识、模型字段/根模型、JSON/ArrayBuffer、大载荷 fetch、并发与命令返回后发送、
关闭/GC 终止、原始窗口代次和销毁缓存；现有 Webview 引用只提供 label/app_handle。
send 不代表接收确认，不包含任意 Rust IpcResponse、Python 回调构造通道或完整 channel_interceptor。

显示器查询与 Monitor 五项属性、PhysicalRect 已绑定；快照在窗口关闭后保留可读值，原始句柄不跨代次复活。
Windows 单屏 1600×900、100% DPI 已独立对照；多屏/混合 DPI、设备拔插与 Linux/macOS 未验收。
图像默认 PNG/ICO，能力信息随显式 feature 改变；ICO 的传递 PNG/BMP 依赖不扩大外部容器支持范围。

原生托盘显式依赖 tray-icon feature，默认不启用；关闭 feature 时仍可导入事件与公开模块，但构造拒绝。
应用持有引用与 Python close 分别处理，移除引用不关闭别名，同 ID 的存活资源拒绝重复创建。
应用查询只管理本绑定创建的托盘，回调参数为同代次别名，不保证 Python is 身份，故相应接口记为部分绑定。
Windows 原生图标、提示、菜单、五类鼠标事件与资源清理记录在验证文档；Linux/macOS 及其专属效果仍待验收。
标题、模板图像和临时目录的无效果平台分别记录，未把 Windows 成功调用算作专属效果已验证。

## 官方插件范围

以下全部纳入目标，dialog 已完成桌面子集，其余仍未绑定：autostart、barcode-scanner、biometric、cli、clipboard-manager、deep-link、dialog、
fs、geolocation、global-shortcut、haptics、http、localhost、log、nfc、notification、opener、os、persisted-scope、
positioner、process、shell、single-instance、sql、store、stronghold、updater、upload、websocket、window-state。
列表来自 [官方插件仓库](https://github.com/tauri-apps/plugins-workspace)，在每次插件阶段开始时更新；移动专属插件需要相应移动运行时。
各插件有独立 crate 与版本，不能以 Tauri 核心版本代替。每个插件记录 API/平台/feature/版本/测试证据。

dialog 锁定 2.8.1；`../upstream/dialog-2.8.1.json` 有 3 个 feature 映射及 59 条声明候选。
独立 `bindings-dialog-2.8.1.json` 记录 37 个审核条目：24 项绑定并验收，5 项部分绑定并验收，
1 项已绑定但目标平台效果未验证（创建目录开关仅 macOS 有效），7 项未实现。
回调/阻塞文件与消息接口、七种按钮和资源清理已在 Windows 验证；移动模式和结构化消息结果未绑定。
过滤器排除列表和消息图标外观仍待独立测量；注册不会扩大前端 ACL，也不开放 fs 传递依赖。

## 验收依据

原型能力的具体测试与执行结果记录在 validation.md；本矩阵的部分绑定状态不能理解为整领域已完成。
Windows 实际验证以后，macOS/Linux 仍需真实 WebView 测试。移动平台必须单独构建与实机/模拟器验收。

第十三阶段补充：Windows 真实 OLE Enter/Over/Leave/Drop、窗口主题事件与焦点取得/失去/恢复均通过。
`is_focused()` 包含前台 WebView 子控件；全局系统主题切换、ScaleFactorChanged 与混合 DPI 仍待设备条件。
策略回调的 Allow/Default 未计为实际授权通过；具体限制见 [策略指南](webview-policies.md)。
