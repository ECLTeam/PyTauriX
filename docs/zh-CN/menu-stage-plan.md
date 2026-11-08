# 第八阶段建议：原生菜单

状态：用户已授权“开始第八阶段”，选定菜单子集已实现并完成 Windows 开发环境、双版本安装包及源包重建验收，见 [第八阶段验证记录](validation-phase8.md)。

## 推荐依据

本阶段开始时核心账本已有 100 个选定条目，Windows 窗口、事件、Channel、显示查询和 PNG/ICO 已验收。
当时菜单和托盘未绑定；原生菜单可以用于窗口及托盘，先建立菜单对象与回调生命周期，后续托盘可复用。
参考 PyTauri 的 menu/ffi.menu 导出及 nicegui-app 菜单/托盘示例；保持常用构造与导入形状。
本次在当前 ECL 的 Python 源码检索，未发现原生菜单/托盘直接调用；本阶段属于通用框架能力补全。

## 建议实现范围

1. 导入路径：pytaurix.menu 和 pytaurix.ffi.menu，重导出同一底层类型。
2. 类型：Menu、Submenu、MenuItem、CheckMenuItem、IconMenuItem，及 PredefinedMenuItem.separator。
   MenuID 使用 str；MenuEvent 保留 PyTauri 的字符串菜单 ID 形状。
3. 构造：沿用 new/with_id/with_items 等对应 Python 构造或静态工厂形状，逐项核对签名、默认值与位置参数。
4. 菜单管理：选定 append/insert/remove/get/items 及顺序；菜单项文本、启用、勾选、图像与快捷键更新。
5. 应用与 WebviewWindow：菜单挂载、查询、替换和移除；选定上下文菜单 popup/popup_at。
   当前不创建独立 Window；接受 WebviewWindow 属于本项目明确扩展，不宣称完整 Window 兼容。
6. 菜单事件：应用/窗口入口的同步 Python 回调；明确来源参数、字符串事件、异常归还及注销/替换契约。

不一次承诺所有平台预定义角色、AboutMetadata、NativeIcon、完整 Rust Builder 或 Menu.default 的平台默认菜单。
预定义项除 separator 外列为未实现；全部上游菜单能力继续进入发现/审核清单，不能将本阶段子集称为完整菜单绑定。
托盘、其他插件、移动菜单和独立程序发布另设阶段。

## 对象与线程边界

- 原生菜单和菜单项属于应用资源；从窗口构造时需明确转换为所属应用，不能隐式延长窗口寿命。
- 从父菜单移除项目不等于销毁菜单项，现存 Python 句柄可按原生语义继续使用。
- 绑定前审核共享项、多父菜单、重复 ID、重复插入、跨应用对象、索引与快捷键失败的原生行为。
  不自行虚构上游规则，采用明确的 Python 校验和稳定错误码。
- 窗口菜单挂载与窗口监听按原始 WindowState 管理；同标签重建不能复活旧窗口句柄或其回调。
- 窗口关闭后应用级菜单可仍有效；应用退出后所有原生资源操作拒绝，回调引用须清除。
- 后台线程的原生操作释放 GIL。创建、更新和 popup 的主线程调度依据锁定源码设计。
  可能同步等待 GUI 的操作必须防止回调重入，不能用 unsafe 绕过 Send/Sync。
- Python 回调异常不能引发 Rust panic；不把 async 回调静默当成同步回调。
- 原生 API 若不支持物理注销监听，可使用可清空槽与弱引用停止 Python 派发；文档明确两种清理的区别。
- 锁定源码将菜单事件广播给应用及所有已注册窗口；窗口参数表示订阅窗口，不表示点击来源。
  窗口入口替换原回调，应用入口累加回调；显式清空停止 Python 派发，窗口关闭清除该代次引用。
- 桌面限制在导入和构造边界区分，不在导入阶段初始化 GUI；不扩大前端菜单/IPC 权限。

## 验收标准

1. 真实 Windows 双窗口：挂载、替换、移除、嵌套菜单、上下文弹出与窗口作用域。
2. 独立读取原生菜单，核对文字、排序、enabled/checked；真实菜单选择或快捷键触发事件。
   直接调用 Python 回调或只向 WebView 打印预期结果不能替代菜单行为验收。
3. 图像加载用于 IconMenuItem；核对实际原生图标数据，环境无法测量的外观单独标记。
4. 动态更新、错误 ID/类型/索引/快捷键与失败后恢复；共享菜单/项目的所有权按源码审核结果验证。
5. 工作线程、同步 GUI 回调约束、回调异常/awaitable、引用释放、窗口关闭/同标签重建/退出。
6. Python 3.11/3.14 独立 wheel、源包逐字节核验与解压后实际重建，回归既有六个桌面脚本。
7. Ruff/Pyright/pytest、Rustfmt/Clippy、迁移契约、运行时能力、菜单指南和人工审核账本同步。

实施前重新核验依赖稳定版本，先完成线程、回调、签名和所有权审核再扩展运行时。
Windows 验收不能替代 Linux/macOS，尤其应用菜单与窗口菜单的系统行为。
当前没有项目 CI；建议菜单之后优先建立 Windows/Linux/macOS 构建与 wheel 检查，真实 GUI 结果独立记录。

参考：[Tauri 原生窗口菜单](https://v2.tauri.app/zh-cn/learn/window-menu/)、
[锁定版本菜单源码](https://docs.rs/crate/tauri/2.12.1/source/src/menu/)。
