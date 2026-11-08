# 第十阶段方案：原生系统托盘

状态：用户已于 2026-10-16 回复“开始”授权实施，当前正在实现与验收；本文不代表全部验收通过。
调研日期：2026-10-16。基线沿用 Cargo.lock 中的 Tauri 2.12.1，不在本阶段隐式升级依赖。

## 依据与选择

托盘目前只有 Cargo feature 转发，没有 Python 类型、原生绑定或行为验收。
现有菜单、PNG/ICO/RGBA 图像、GUI 调度与回调清理可以作为实现基础。
参考本地 PyTauri 的 tray/ffi.tray 公开签名和示例，独立实现，不复制其 unsafe 线程处理。

两种可行方案：仅暴露 PyTauri 常用 TrayIcon 接口，改动小，但仍缺少上游 Builder 与应用查询；
同时补齐桌面托盘的 Builder、运行时修改、查询、事件和释放，工作量更大，但可形成完整可验收的桌面能力。
推荐第二种；各平台专属效果分别记账，不把 Windows 调用成功记为跨平台完成。

前一阶段已存在 Windows/Linux/macOS × Python 3.11/3.14 的 CI 工作流，缺口是实际执行证据。
本阶段扩展现有工作流的托盘 feature 检查与 Windows 桌面脚本，不重复建立 CI。
云端任务需要可用远程与执行环境；目前不将上传仓库或触发远程任务包含在本地实施范围内。

## 接口范围

1. 新增 pytaruix.tray 与 pytaruix.ffi.tray，同一组类型重导出。
   提供 TrayIcon、TrayIconBuilder、TrayIconId、MouseButton、MouseButtonState、TrayIconEvent 与事件联合类型。
2. 保留 TrayIcon(manager) 与 with_id(manager, id) 的常用 PyTauri 形状。
   manager 接受现有 AppHandle 和 WebviewWindow，窗口仅用作取得所属应用，托盘不随该窗口销毁。
3. Builder 覆盖 new/with_id/id、menu/icon/tooltip/title/temp_dir_path/icon_as_template、
   show_menu_on_left_click、on_menu_event/on_tray_icon_event 和 build。
   不新增已弃用的 menu_on_left_click 别名；原始 Rust 闭包扩展 with_inner_tray_icon 单列为未绑定。
4. TrayIcon 覆盖 id/app_handle、set_icon/set_menu/set_tooltip/set_title/set_visible、
   set_temp_dir_path/set_icon_as_template/set_icon_with_as_template/set_show_menu_on_left_click 与 rect。
   图像复用现有 Image，菜单复用 Menu/Submenu，不把所有菜单项误作上下文菜单。
5. 应用入口提供 tray_by_id、remove_tray_by_id 和 on_tray_icon_event；
   App 通过现有 handle() 获得这些能力，Builder 应用级回调入口按当前 Python Builder 的注册方式设计。
   remove_tray_by_id 保留上游“移除应用持有引用并返回句柄”的语义，不将其等同于立即销毁。
6. 事件使用明确、不可变的 Click/DoubleClick/Enter/Move/Leave 数据，保留 id、位置、矩形、按钮和按钮状态。
   鼠标位置保留 f64 精度；补齐不可变 Rect 与物理浮点位置表达，不能复用 i32 坐标后截断。
   导出位置与签名在编码前对照本地 PyTauri 和锁定 Cargo 源码，兼容差异记录在迁移契约。
7. 提供明确的 Python close 与回调清空入口，属于本项目扩展；close 幂等，所有别名指向同一失效代次。
   close 与上游 remove_tray_by_id 的区别、应用资源表引用及 Python GC 行为必须有独立测试和文档。

## 线程、所有权与错误

- 原生创建和更新经 GUI 主线程执行，工作线程等待时释放 GIL；不新增 unsafe 绕过线程约束。
- 复用既有运行态和同步 GUI 回调限制，避免在上游持有事件监听表锁时重新注册造成死锁。
  需要等待 GUI 或重新获取原生监听锁的操作，在进入 native 前返回稳定错误。
- setup、普通工作线程和同步事件回调的可调用范围分别测试，不能因同步回调限制而让托盘恢复窗口不可实现。
  示例通过受支持的任务调度或后台命令执行显示/聚焦/关闭操作。
- 应用级与单托盘回调分开登记。托盘菜单回调遵循上游全应用菜单广播语义，不能假定事件只来自该托盘。
  单托盘鼠标监听按上游替换语义，应用级监听按上游累加语义处理。
- 原生回调只捕获弱引用或可清空槽，避免持有 AppHandle、TrayIcon 与 Python 回调形成不可释放环。
  Python 回调异常沿用有序退出、run_return 重抛；拒绝异步回调和返回 awaitable。
- 编码前以 Cargo.lock 的实际源包校验来源与哈希，再核对 ID 冲突、资源表、移除后句柄及最后引用销毁行为。
  同 ID 重建须隔离旧回调和旧句柄，不能仅按字符串 ID 判定身份。
- 显式关闭移除原生资源、释放绑定持有引用并清空回调；应用退出清理全部托盘。
  构造失败、操作失败与退出竞争不留下僵尸图标或 Python 强引用。
- 复用既有应用/资源失效错误，并补充有上下文的托盘错误码。字符串拒绝 NUL，参数严格校验类型。

## Feature 与平台

托盘保留显式 tray-icon feature，默认安装的原有能力不隐式扩大。
运行时 capabilities 按实际编译结果报告；未启用 feature 时可导入公开模块，构造明确报能力不可用。
测试开启和关闭托盘的构建，以及托盘与无默认 feature 的合理组合。

上游明确存在平台差异：Linux 不发送托盘鼠标事件、tooltip 不支持且 rect 返回 None；
Windows 不支持 title 效果；临时图像目录仅 Linux、模板图像仅 macOS 有效。
无效果的上游调用不能记录为效果已验收；Linux 菜单移除/替换限制按实际锁定实现记录。

## 文件与交付

- 原生新增 crates/bindings/src/tray.rs，接入模块注册、菜单资源访问、统一资源登记和应用句柄。
- Python 新增 tray.py、ffi/tray.py；同步 _native.pyi、几何类型、运行时能力和必要导出。
- 新增托盘示例、契约测试、真实桌面 smoke 与仅用于自有测试进程的 Windows 驱动。
- 同步 README、能力矩阵、迁移契约、托盘指南、验证记录与人工 API 账本。
- 扩展既有 CI 的 feature 检查和串行桌面任务，所有 Rust 构建仍使用 --jobs 1。

## 验收标准

1. 真实 Windows 通知区域出现自有测试图标；通过系统 UI 操作确认菜单、左击开关和双击事件。
   独立读取或定位原生图标、提示和矩形，测试隐藏、恢复、替换图像、菜单动态更新与移除。
   测试驱动不得直接调用 Python 回调或发送内部测试事件来替代系统输入。
2. 两个托盘与两个窗口验证应用级/托盘级鼠标事件、菜单广播、查询、共享菜单、窗口关闭后托盘存活。
   显示、聚焦主窗口及显式退出形成真实可用示例。
3. 验证后台线程、回调重入限制、回调异常/awaitable、错误参数和失败后恢复。
   验证 close、重复 close、应用移除引用、Python GC、同 ID 重建与应用退出；用弱引用证明回调释放。
4. Ruff check/format、Pyright、pytest、cargo fmt、Clippy 与覆盖账本核验通过。
   开关组合分别构建，关闭 feature 时不误报运行时能力。
5. Python 3.11/3.14 独立 wheel 和源包重建验收，重复解压刷新时间戳或使用新 Cargo target。
   回归现有八组桌面脚本，并增加托盘场景；只终止自己启动且记录 PID 的进程。
6. 没有相应环境时，Linux/macOS 构建、GUI 与专属效果明确保留为待验收；
   不将工作流文件或 Windows 结果解释为三平台通过。

## 后续补全顺序

托盘之后依次推进：完整菜单角色与默认菜单；窗口/WebView Builder 和下载、新窗口、请求回调；
App/Context/生命周期及事件补齐；资源/自定义协议/CSP/ACL；官方插件按独立版本逐个适配；
最后分别处理实验性接口、移动运行时和正式发行验收。
每阶段重新审核上游 API 与平台条件，保留未实现、部分绑定和未验收状态。
本方案的实施确认只授权本阶段本地实现与验证；提交、推送和发布仍须分别取得明确指令。

## 参考

- [Tauri 系统托盘指南](https://v2.tauri.app/learn/system-tray/)
- [Tauri 2.12.1 标签的托盘源码](https://github.com/tauri-apps/tauri/blob/tauri-v2.12.1/crates/tauri/src/tray/mod.rs)
- 本仓库 docs/upstream/tauri-2.12.1.json、菜单实现与资源清理代码。
- 本地参考 PyTauri 的 python/pytaurix/src/pytaurix/ffi/tray.py 及 nicegui-app 托盘示例。

Git 标签源码只用于辅助调研；最终账本行号、声明和哈希以 Cargo.lock 对应的实际源包为准。
