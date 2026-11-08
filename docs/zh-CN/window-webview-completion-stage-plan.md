# 第十二阶段方案：窗口与 WebView 完整化

状态：用户于 2026-11-07 确认本批次与「先修 feature 边界」前置；实现与契约检查已完成，`window_attributes` 真实桌面场景 7 项通过，第十三阶段已补真实 OLE 拖放、窗口主题事件与焦点；缩放/DPI 系统输入仍待设备条件。
基线：Tauri 2.12.1、PyO3 0.29.3，沿用 `Cargo.lock`，不隐式升级依赖。

## 1. 目标与范围

补齐运行期窗口构建器的常用属性、WebView 回调与窗口事件，使真实应用不必退回配置窗口或 Rust 代码。保持现有线程、窗口代次、回调错误和资源清理契约，不改变公开导入布局。

前置已完成：workspace 与 bridge 不再继承 `tauri/default`；默认组合 wheel 从 4.60 MiB 降至 4.50 MiB，最小组合从 4.24 MiB 降至 4.05 MiB。Windows 保留 `common-controls-v6`，Linux 目标显式启用 `x11`、`dbus`。

## 2. 当前缺口

Python 构建器已支持标题、尺寸、最小/最大、位置、居中、可见、焦点、可调整、最大化、最小化、关闭、全屏、装饰、透明、阴影、置顶、任务栏跳过、背景色、初始化脚本、图标、导航/页面加载/窗口事件回调。

未绑定但 `WindowConfig` 已支持的字段：`user_agent`、`drag_drop_enabled`、`always_on_bottom`、`visible_on_all_workspaces`、`content_protected`、`window_classname`、`theme`、`title_bar_style`、`traffic_light_position`、`hidden_title`、`accept_first_mouse`、`tabbing_identifier`、`additional_browser_args`、`parent`、`proxy_url`、`zoom_hotkeys_enabled`、`use_https_scheme`、`devtools`。

未绑定的上游 WebView 回调：`on_document_title_changed`、`on_download`；`on_web_resource_request`、`on_new_window`、`on_permission_request` 涉及请求/响应或安全策略，本阶段明确不绑定。

未映射的窗口事件：`ScaleFactorChanged`、`ThemeChanged`、`DragDrop`（Enter/Over/Drop/Leave）。

## 3. 改动

| 位置 | 改动 |
| --- | --- |
| `python/pytaruix/webview.py` | 扩充 `WebviewWindowBuilderArgs`、字段映射与严格校验；新增 `on_document_title_changed`、`on_download` |
| `python/pytaruix/events.py` | 新增缩放因子、主题与拖放事件载荷 |
| `crates/bindings/src/window_state.rs` | 扩展回调槽与 `WindowEvent` 映射；拖放路径/位置快照 |
| `crates/bindings/src/window_builder.rs` | 注册标题变更与下载回调，弱引用运行时与窗口代次 |
| `crates/bindings/src/window.rs` | 新增 `set_theme`/`theme`、`set_always_on_bottom`、`set_content_protected`、`set_visible_on_all_workspaces` |
| `python/pytaruix/_native.pyi` | 同步新增方法与回调签名 |
| `tests/` | 构建器字段映射、未知/非法参数、事件解析、回调错误路径 |
| `scripts/dynamic_window_smoke.py` 或新增场景 | 真实 Windows 窗口属性与事件证据 |
| 文档 | `windows.md`、能力矩阵、迁移契约、运行时能力 |

## 4. 契约与校验

- 字符串选项：`user_agent`、`window_classname`、`tabbing_identifier`、`additional_browser_args`、`parent`。
- 枚举选项：`theme` 仅接受 `None`/`light`/`dark`；`title_bar_style` 仅接受 `visible`/`transparent`/`overlay`，不接受上游的静默回退。
- 布尔选项：拖放、置底、全工作区可见、内容保护、隐藏标题、首击接受、缩放热键、HTTPS scheme。
- `traffic_light_position` 使用二元有限浮点；`proxy_url` 必须为无凭据 HTTP(S) 来源；`devtools` 允许 `None` 保持上游默认。
- `parent` 引用现有窗口标签，不存在时由原生创建返回明确错误。
- 平台专属选项照常接受，但不把 Windows 调用成功记为该平台效果；文档列明 macOS/Windows 差异。
- 回调均为同步；返回 awaitable 或异常沿用 `invalid_callback` 与有序失败路径。下载回调仅在 `Requested` 阶段用返回值决定是否继续。
- 拖放事件路径为不可变字符串元组，位置为物理浮点坐标；不跟随窗口销毁复活。

## 5. 不在范围

嵌入原生视图、多 WebView unstable、移动平台、`on_web_resource_request`、`on_new_window`、`on_permission_request`、完整系统窗口特效与跨平台 GUI 验收。

## 6. 验收

1. Ruff、Ruff format、Pyright、pytest；Rustfmt 与适用 feature 组合 Clippy。
2. 默认、`devtools,tray-icon`、最小 `wry`、最小 `wry,tray-icon` 构建与能力拒绝。
3. Windows 真实窗口：新属性生效或明确平台限制；标题变更、下载回调、缩放/主题/拖放事件至少各有独立证据；错误回调恢复。
4. feature 边界前后 wheel 体积与依赖树记录在 `artifacts/phase11/experiments/feature-boundary/`。
5. 文档与 `_native.pyi`、运行时能力同步；未绑定回调明确列为未实现。

失败时回退本阶段改动与 feature 边界调整，恢复上一份可运行 wheel；不清理用户数据或 ECL 副本。
