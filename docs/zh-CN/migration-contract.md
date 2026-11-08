# PyTauri 迁移契约

参考源码：<https://github.com/pytauri/pytauri>；本地参考 checkout 提交为 `7d99c6f6c8dcefdf8ed5cf87e7c7d707a1f5d749`。
参考公开接口：`python/pytauri/src/pytauri/{__init__,ipc}.py`、`ffi/{lib,ipc}.py`、`python/pytauri-wheel`。
旧客户端协议参考：`crates/tauri-plugin-pytauri/guest-js/src/index.ts` 与原生插件命令边界。
迁移样本为 ECL 的 `ECL/adapters/tauri.py`、`api/{bridge,windows}.py` 和前端 `api/transport/tauri.ts`。
参考契约，自主实现；未复制参考仓库实现代码。未来复制或衍生时须另外记录出处与许可证。

## 导入与公共接口

| 原入口 | 新入口 | 当前状态 |
| --- | --- | --- |
| pytauri.AppHandle / Commands / Manager / Emitter / Listener | pytaruix 同名根导出 | 已实现子集 |
| pytauri.EventTarget / EventTargetType | pytaruix 根与 ffi 同名导出 | 六种目标；字符串保留 AnyLabel 语义 |
| pytauri.ffi.Emitter.emit_str / emit_str_to | pytaruix.ffi.Emitter 同名接口 | JSON 验证后保留原文，避免再次编码成字符串 |
| pytauri.State 与 Annotated[T, State()] | pytaruix.State | 原对象注入已验证；新增 State[T].value 形式 |
| pytauri.ipc.Headers / WebviewWindow | pytaruix.ipc 同名导出 | 原生请求头、真实来源窗口注入已验证 |
| pytauri.ipc.JavaScriptChannelId / Channel | pytaruix.ipc 同名接口 | Pydantic 模型/根模型、from_str/channel_on/id/send/send_model；新增 close/closed |
| pytauri.ffi.ipc.JavaScriptChannelId / Channel | pytaruix.ffi.ipc 同名接口 | 原生通道标识和 JSON/字节发送，没有公开构造器 |
| WebviewWindow.as_ref_webview | pytaruix.webview.WebviewWindow.as_ref_webview | 原始窗口代次引用；本阶段不提供完整 Webview 管理器 |
| pytauri.RunEvent / RunEventType | pytaruix 同名根导出 | Ready/Exit/ExitRequested(code, api)，支持阻止退出 |
| pytauri.ffi | pytaruix.ffi | 已实现句柄与 Context；尚未提供全部 ffi 子模块 |
| pytauri.webview.WebviewWindowBuilder | pytaruix.webview.WebviewWindowBuilder | build/from_config 的选定参数，新增 build_async |
| pytauri.WebviewUrl / dpi | pytaruix.WebviewUrl / dpi | App/External 与逻辑/物理尺寸和位置 |
| pytauri.ffi.image.Image | pytaruix.ffi.image.Image | 保留 RGBA/属性；本项目扩展 from_bytes/from_path，PNG/ICO feature 控制 |
| pytauri.ffi.window.Monitor | pytaruix.ffi.window.Monitor | 五项只读属性与窗口的四种查询，值快照不拥有设备 |
| pytauri.menu / pytauri.ffi.menu | pytaruix.menu / pytaruix.ffi.menu | 同一组菜单类型与对应构造默认值；MenuEvent 为 str |
| AppHandle/WebviewWindow 的菜单入口 | 同名 menu/set_menu/remove_menu/on_menu_event | 同步回调；新增 clear_menu_event_handlers |
| pytauri.dpi.PhysicalRect | pytaruix.dpi.PhysicalRect | position/size 属性，有符号物理坐标，复制值 |
| pytauri.plugin.Plugin | pytaruix.plugin.Plugin | 原生一次性描述符，仅当前支持的插件提供者 |
| pytauri_plugins.dialog / dialog.ffi | pytaruix.plugins.dialog / dialog.ffi | 桌面选择器、消息及选项/按钮已实现子集 |
| pytauri_wheel.lib 工厂函数 | pytaruix 根工厂函数 | 显式 JSON/TOML 上下文、宿主权限与图标；无扩展发现兼容包 |
| WebviewWindow.open_devtools | 同名接口 | 构建启用 devtools；Windows 原生打开已调用 |
| WebviewWindow.close_devtools / is_devtools_open | 同名接口 | Windows 上游不可用，明确抛 platform_unavailable |
| window.__TAURI__.pytauri.pyInvoke | 同名全局入口 | 旧 plugin/头字段/字节协议已验证 |
| 原 npm 客户端 pyInvoke | plugin:pytauri\|pyfunc | 独立模拟客户端传输契约通过真实 WebView 测试 |

默认不占用 `pytauri` 包名；零导入改动模式需要另外安装兼容包，并排斥旧发行包同时安装。
本阶段没有安装原 npm 包进行端到端验收；独立测试函数按其源码传输契约调用原生插件入口。

## 行为契约

- 保留 `@commands.command()` / `@commands.command(name)` 与 `generate_handler(portal)` 形状；命令快照、Pydantic、同步/异步和安全错误码保留。
- `AppHandle`、`WebviewWindow`、`Headers` 和状态按注解注入，前端载荷不能覆盖。请求头为字节元组列表，保留原生重复值；浏览器传输可能先规范化字段。
- `Manager.manage(app_or_handle_or_window, object)` 按具体 Python 类型注册；重复注册返回 False 并保留原值。`try_state` 未注册返回 None，`state` 抛 BindingError；None 不能注册。
- 状态原对象跨命令/窗口共享，内部并发控制由调用方负责。本阶段不提供运行时注销状态或命令取消。
- `State[T]` 注入包装器，通过 `.value` 取得 T；`Annotated[T, State()]` 直接注入 T，保持 PyTauri 的常见形式。
- `context_factory` 保留资源路径基准、递归覆盖与快照；支持 JSON/TOML、平台覆盖、宿主 capabilities 和 PNG/ICO 默认图标。
- 默认选择生产 frontendDist，开发地址必须显式 `dev=True`；宿主远程能力按来源匹配，CSP、隔离和 JSON5 仍未实现。
- 宿主策略在构建前解析，插件权限仅使用实际注册插件；无效权限明确失败。存在宿主策略时禁用原型动态窗口自动授权。
- `Builder.build` 创建原生应用，`App.handle()` 在运行前可用。Tauri 2.12.1 在 Ready 创建配置窗口并执行 setup；前端 IPC 在工作线程等待 setup 完成，避免半初始化状态。
- `build` 当前仍为关键字参数；plugins 序列已支持，完整 BuilderArgs、App.run、扩展发现和完整配置尚未提供。
- plugins=[dialog_init()] 保留常见调用形状，不修改输入序列；重复名称、无效/已消费对象在原生运行时消费前拒绝。
- DialogExt.file/message 接受 App、AppHandle、WebviewWindow；六项文件和四项消息 kwargs、同步回调及工作线程 blocking_* 保留常见形状。
- 窗口入口拥有资源代次，父窗口仅由 set_parent/parent 明确设置；Path/list[Path]/None 与消息 bool 契约有真实 Windows 证据。
- 关闭会清理待完成回调并唤醒阻塞等待；未承诺强制关闭原生选择器、移动 URI、结构化消息结果或自动授予 JS 权限。
- `ExitRequested.code` 区分程序退出码与用户请求 None；api.prevent_exit 只在同步回调内有效，过期调用抛 request_expired。
- 生命周期/setup/监听回调异常有序退出，run_return 重抛原异常；事件循环完成或未运行 App 析构时注销监听器并清除状态。失效句柄资源操作抛 app_closed。
- 事件静态入口可接收 App/句柄/窗口。listen/once 采用所属应用或窗口作用域；listen_any/once_any 监听任意目标，仍由提交的窗口代次或应用拥有。过滤发送待实现。
- 通过窗口注册应用监听的旧原型代码，应改用 window.app_handle()；窗口销毁会注销其全部监听，包括 any 变体。重复注销无副作用，活动的其他窗口编号返回 listener_owner；应用句柄可注销本绑定所有登记编号。
- emit_to 接受六种 EventTarget 或字符串标签；字符串按 AnyLabel 匹配同标签 Window/Webview/WebviewWindow，明确目标不会被降级为字符串。
- 根 Emitter 接受 Python 值/模型并编码一次，ffi.Emitter 接受 JSON 文本并验证后原文发送；无效 JSON 返回 invalid_json。
- AppHandle/窗口 run_on_main_thread 接受零参数同步回调并返回 None，只表示提交成功；GUI 线程可能立即执行。回调异常由 run_return 重抛，awaitable 返回 invalid_callback。
- Channel 采用官方原生传输，send(str) 保留有效 JSON 原文，send(bytes) 对应 ArrayBuffer；send_model 编码一次。
- channel_on 接受所属窗口的 Webview 引用，支持工作线程和命令返回后持续发送；窗口/应用失效清掉原生句柄。
- close 幂等，GC 可结束流，closed 查询状态；共享同一个 FFI 句柄的包装也共享关闭状态。同一 JS 编号只建立一个发送句柄。
- 编号不是授权凭证，不能证明 JS 回调存在；不承诺接收确认、背压或业务任务取消。详细约束见 channels.md。
- 显示查询返回独立 Monitor 快照，工作线程释放 GIL；同步 GUI 回调返回 blocking_callback，旧窗口代次查询拒绝，快照仍可读取。
- Image 的编码加载是本项目扩展；默认 PNG/ICO、显式 feature 与 RuntimeInfo.image_formats 一致，Path/bytes 严格类型和稳定错误见 displays-images.md。
- 菜单保留常用构造的对应位置参数/默认值及批量项目顺序；aliases set_as_app_menu/set_as_window_menu 返回 None，句柄 set_menu 返回前一个菜单。
- 菜单事件为全局广播，窗口参数代表订阅窗口；应用监听累加，窗口监听替换，显式清空为本项目扩展。原生闭包不捕获强 Python/Manager 引用。
- 同步 GUI 回调内原生菜单操作和监听注册返回 blocking_callback；id/app_handle 元数据及清空回调可用。菜单查询/修改须移到工作线程。
- 菜单资源属于应用，窗口关闭后已有句柄仍可用；窗口挂载与监听保持原始代次，标签复用不能恢复旧句柄。Windows 未拦截的关闭先解除 HMENU 关联。
- 上下文弹出接受 WebviewWindow 是本项目扩展；独立 Window、Menu.default、其他预定义角色/NativeIcon/AboutMetadata/完整 Builder 和托盘未绑定，详见 menus.md。
- 窗口任务归属于窗口代次，执行前检查原始原生窗口仍存在；销毁/退出清掉排队回调，旧句柄拒绝提交。已经开始的回调不会被强制中止，CloseRequested 不保证所有任务立即取消。

## 前端协议

新入口 `pytaruix.pyInvoke(name, payload, options)` 使用 python_command JSON 请求，失败拒绝 `{code, message}`。
兼容全局入口使用旧插件请求：`plugin:pytauri|pyfunc`，请求头 `pyfunc` 为命令名，普通值先 JSON 编码为 UTF-8 字节；ArrayBuffer/Uint8Array 保持原始字节。
旧客户端省略正文时，Tauri 将 undefined 转换成空对象；桥把该情况视为无正文。JSON 模型和标量按类型校验；`body: bytes` 保留请求原文。
返回 bytes 形成 ArrayBuffer，其他结果序列化为 JSON。旧协议失败保持字符串拒绝，格式为 `code: message`，不泄露原始异常内容；未声称错误文字与 PyTauri 完全一致。
自定义 InvokeHandler 的内部签名已扩展为六个参数；第一阶段内部三参数回调需要调整。Commands.generate_handler 的公开调用形状保持。

## 验收与剩余迁移

双窗口测试核验来源、共享状态、头字段、新旧入口、空正文、标量、两种字节输入、错误后恢复、注入覆盖拒绝、事件隔离与注销。
独立进程验证退出拦截、过期控制 API、setup/监听错误恢复和弱引用资源释放。
动态窗口在 setup/命令工作线程使用静态 build/from_config；异步命令可 await build_async。
回调提供 URL 字符串与 PageLoadPayload 的 url/event 属性；窗口事件处理器为每窗一个可替换槽，区别于上游累加监听。
关闭拦截仅在当前同步回调内有效，Destroyed 立即使同代所有句柄失效，同标签重建不恢复旧句柄。
无宿主策略时，原型精确标签能力仅允许本地页面，外部页面不自动获得 IPC；新增能力不可撤销，同标签重建沿用标签权限。
宿主策略支持窗口模式与显式远程来源，空宿主能力目录拒绝所有调用；不提供构建后任意权限变更。
ECL 的主线程调度 → 原始 JSON → WebviewWindow 定向发送链路已用真实前端验证。
ECL 当前文件和皮肤保存所需的 dialog 注册/路径调用形状已实现；完整迁移仍需核对其他插件、未绑定资源和完整 API，不能仅替换导入宣称完成。
第九阶段隔离 ECL 副本已验证 216 个正式命令注册和三种主窗口模式；实际背景、皮肤保存与插件窗口链路见 [ECL 指南](ecl.md)。
事件目标已验收原生应用/WebviewWindow 监听及显式 JS Window/Webview 目标，独立 Window/Webview 资源创建尚未绑定。

## 第十阶段托盘契约

新增 pytaruix.tray 与 pytaruix.ffi.tray，重导出相同 TrayIcon、TrayIconBuilder、事件与鼠标枚举。
保留 TrayIcon(manager)、with_id(manager, id)、常用 setter 和事件字段形状；需要显式 tray-icon feature。
未启用时模块仍可导入，构造返回 unsupported_capability，AppHandle 原生托盘方法不提供空壳。
AppHandle 提供 tray_by_id/remove_tray_by_id/on_tray_icon_event，查询仅管理本绑定创建的资源。
Builder.build(on_tray_icon_event=...) 在 Python setup 前登记监听，不宣称与 Rust Builder 构建时机完全等价。

菜单回调全应用广播，单托盘鼠标回调替换，应用级鼠标回调累加；同步异常有序归还 Python。
托盘回调参数为同一原生资源代次的别名，不保证 Python 对象 is 身份与原变量相同。
事件位置保留浮点物理坐标，Rect 保留位置/尺寸单位；事件和矩形均为不可变值快照。

应用默认持有托盘；remove_tray_by_id 移除该引用但不关闭其他句柄，最后引用释放才移除图标。
close 与回调清空为本项目扩展，显式关闭使所有别名失效；同 ID 的活跃或已移除但存活资源禁止重复创建。
窗口关闭不销毁托盘，应用退出清空全部原生资源与回调。用户回调主动捕获托盘时需显式解除引用环。
同步 GUI 回调内禁止等待原生事务或重新登记监听，窗口恢复需移交后台线程；清空回调允许同步调用。
Linux/macOS 效果、模板与临时目录的专属行为另行验收，Windows 无效果接口不得计为效果已验证。
完整用法与平台差异见 [托盘指南](tray.md)，Windows 证据见 [验证记录](validation.md)。

## 第十二阶段窗口契约

`WebviewWindowBuilderArgs` 新增 `user_agent`、`drag_drop_enabled`、`always_on_bottom`、`visible_on_all_workspaces`、
`content_protected`、`window_classname`、`theme`、`title_bar_style`、`traffic_light_position`、`hidden_title`、
`accept_first_mouse`、`tabbing_identifier`、`additional_browser_args`、`parent`、`proxy_url`、`zoom_hotkeys_enabled`、
`use_https_scheme` 与 `devtools`，仍以选择项覆盖单个 WindowConfig 映射。
`theme` 仅接受 None/light/dark；`title_bar_style` 仅接受 visible/transparent/overlay；`proxy_url` 必须为无凭据 HTTP(S)；
`parent` 必须为非空标签。平台专属选项照常接受，但不把 Windows 调用成功记为该平台效果。
窗口事件新增 `ScaleFactorChanged`、`ThemeChanged` 与 `DragDropEnter`/`DragDropOver`/`DragDropDrop`/`DragDropLeave`，
载荷为不可变快照。新增 `on_document_title_changed` 与 `on_download` 同步回调；下载回调返回 bool 仅控制 Requested 阶段。
运行期新增 `set_theme`/`theme`、`set_always_on_bottom`、`set_content_protected`、`set_visible_on_all_workspaces`。
第十二阶段结束时尚未绑定的三个策略回调，已在第十三阶段接入；嵌入与多 WebView 仍未绑定。

## 第十三阶段 WebView 策略契约

运行期 Builder 新增 `on_new_window(url, features)`、`on_permission_request(view, kind)` 和
`on_web_resource_request(request, response)`；同步回调异常有序退出并归还 Python，返回 awaitable 明确拒绝。
新窗口返回 `NewWindowResponse.Allow/Deny`，上游 Create 仍未绑定；权限返回 `PermissionResponse.Allow/Deny/Default`。
资源回调返回 None 保留响应，或返回完整 `WebResourceResponse`，校验后原子替换；失败返回空 500 并有序退出。
所有快照只保留 Python 拥有的数据，重复头与原始字节保留，不暴露原生借用或请求来源写入口。
新增类型从根、`ffi` 和 `webview_requests` 导出；完整行为与限制见 [策略回调指南](webview-policies.md)。
下载回调同步改为捕获创建时窗口代次，旧下载不按复用标签查找新回调。

Windows `WebviewWindow.is_focused()` 现在包含前台窗口内 WebView 子控件的键盘焦点，修复仅父窗口缓存导致的假阴性；
`WindowEvent.Focused` 仍保留上游原生窗口事件语义。旧句柄在查询期间被销毁时仍返回失效错误。
运行期 Builder 新增 `data_directory: Path`，要求绝对路径，由调用方拥有；
`WindowConfig.dataDirectory` 继续使用相对路径，绝对/遍历配置现在在动态建窗边界明确拒绝，避免上游静默忽略。

## 第十四阶段路径与进程契约

新增 `pytaruix.path`：`BaseDirectory` 为 `StrEnum`，`PathResolver` 由 `Manager.path(app|handle|window)` 取得。
`resolve(path, base)` 与 `parse(path)` 返回 `pathlib.Path`，目录不可用时抛 `BindingError`；
21 个目录属性在不可用时返回 `None`，不折叠成空路径。目录名接受 camelCase、snake_case 与 `$VARIABLE`，
未知名称抛 `invalid_base_directory`。解析只读取应用身份，不创建目录、不校验存在性。
Windows 返回值去掉 `\?\` 扩展长度前缀；非 UTF-8 路径抛 `path_not_utf8`，不做有损转换。

新增 `pytaruix.process`：`current_pid()` 不需要应用实例；`current_binary(manager)` 返回可执行文件路径；
`restart(manager)` 派生新进程后立即退出，不执行 Python 监听器与资源清理，需要有序退出时改用 `AppHandle.exit`。
PyTauri 没有对应模块，这三项是本项目扩展；异步运行时仍由调用方的 AnyIO portal 承担，不转发 Tauri 的 `async_runtime`。
