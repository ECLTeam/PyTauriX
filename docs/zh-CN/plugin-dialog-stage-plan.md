# 第五阶段方案：插件注册与原生对话框

状态：用户已明确授权实施，第五阶段实现及 Windows 安装包验收已完成。

## 优先级依据

第四阶段已补齐主线程调度、事件目标、原始 JSON 和窗口监听作用域。核对当前 ECL 后，下一处直接迁移断点是：

- ECL/adapters/tauri.py 使用 plugins=[dialog_init()]，当前 Builder.build 尚不接受 plugins。
- ECL/api/files.py 使用 DialogExt.file(window)，选择文件、多个文件、目录和保存路径。
- ECL/api/accounts.py 使用同一接口保存皮肤，依赖过滤器、默认文件名和标题。
- ECL 子窗口图标当前直接构造 RGBA Image，已在第三阶段支持；图像文件解码并非这一调用链的必要前置。

因此建议本阶段建立可扩展的插件注册入口，并以 dialog 作为第一个实用插件。
IPC Channel、监视器、图像解码、菜单/托盘继续属于完整绑定目标，后续分批实施。

调研对象是当前独立项目、ECL 的上述代码、本地 PyTauri 参考的 pytauri_plugins/dialog/{__init__,ffi}.py 和对应 Rust 绑定，以及官方 dialog 文档。
不复制参考仓库实现，也不改动 ECL 或参考 PyTauri checkout。

## 版本与能力边界

2026-10-01 从 crates.io 核验最新稳定版本：Tauri 2.12.1、PyO3 0.29.3、tauri-plugin-dialog 2.8.1。
插件独立锁定版本；实施时先审核 2.8.1 源码、Cargo features、依赖和权限，不以文档网站缓存的 latest 版本替代锁定源码。
本阶段绑定 PyTauri 常用的桌面对话框接口；新增移动专属类型、独立 Window/Webview 资源及其扩展接口继续明确登记未实现。

## 插件注册入口

- 新增 pytaruix.plugin.Plugin，表达绑定支持的原生插件与一次性所有权。
- Builder.build 增加 plugins 参数，默认空序列，维持已有关键字调用；用户列表不被修改。
- 新入口采用 pytaruix.plugins.dialog，保留 init、DialogExt、FileDialogBuilder、MessageDialogBuilder 等常见名称，以及 ffi 重导出布局。
- init() 不创建 GUI；调用形状为 plugins=[dialog_init()]。同一原生插件不可重复消费，重复名称和无效对象在进入原生构建前拒绝。
- Cargo 增加 plugin-dialog feature，候选默认桌面构建开启；feature 关闭时根包仍可导入，插件模块明确报告能力缺失。
- 注册机制按模块组织，为后续插件复用；本阶段不开放任意 Python 对象伪装原生插件，不增加运行期插件装卸。
- 编译能力、应用是否注册插件、前端权限分别核验；未注册插件返回稳定错误，不触发上游状态读取 panic。

建议迁移后的启动形状：

```python
from pytaruix import builder_factory
from pytaruix.plugins.dialog import init as dialog_init

app = builder_factory().build(
    context=context,
    invoke_handler=handler,
    plugins=[dialog_init()],
)
```

## 文件与消息对话框

DialogExt.file / message 接受 App、AppHandle 和 WebviewWindow，保留参考的静态入口。
窗口入口保留所属代次；父窗口仅通过明确的 set_parent / parent 选项设置，不暗中改变参考的默认行为。

文件接口包括 pick_file、pick_files、pick_folder、pick_folders、save_file 的回调版及 blocking_* 版。
选项采用类型化参数并保留 add_filter、set_directory、set_file_name、set_parent、set_title、set_can_create_directories 名称。
桌面返回 pathlib.Path、路径列表或 None；用户取消是正常结果，与无效参数、缺少插件及原生错误区别处理。
新上游选项逐项审核后记入账本，未实现项明确拒绝，不能忽略参数或把移动 URI 当成本地 Path。

消息接口包括 show / blocking_show、标题、父窗口、Info/Warning/Error 及参考的标准/自定义按钮。
返回值先对齐 PyTauri 的常见 bool 契约，额外上游结果类型单独审核，不把新增类型伪装成已覆盖。

ECL 异步调用可以继续使用原有工作线程形状：

```python
from anyio import to_thread
from pytaruix.plugins.dialog import DialogExt

picked = await to_thread.run_sync(
    lambda: DialogExt.file(window).blocking_pick_file(
        add_filter=("资源文件", ["jar", "zip"]),
        set_title="选择资源文件",
    )
)
```

## 线程、资源与权限

- 阻塞接口只允许应用运行中的工作线程调用，等待期间释放 GIL；GUI 主线程及原生回调中直接阻塞应及时返回 would_block。
- 回调接口不承诺执行在 GUI 主线程，回调访问 GUI 时使用已提供的 run_on_main_thread；执行时正确 attach Python。
- 回调必须同步；异常有序退出并由 run_return 重抛，awaitable 按既有规则拒绝。
- 待完成回调复用共享资源登记，以应用或具体窗口代次拥有；调用前取走回调，销毁/退出释放引用，晚到的原生结果不能进入旧 Python 回调。
- 原生对话框显示后，上游不一定提供程序化取消接口；清理 Python 回调不等于强制关闭系统对话框。阻塞操作返回时再次检查所有者，关闭场景的真实平台行为须验收后记录。
- 保存对话框只选择目标路径，不自动创建或覆盖文件；文件选择不等于已绑定 filesystem 插件。
- 本阶段优先打通 Python → 原生 dialog 调用。插件 JS 命令仍服从原生 ACL，不自动增加 dialog:default 或窗口通配符；未授权前端调用需要继续拒绝。
- 通用运行期自定义 capabilities、远程授权和 filesystem scope 扩展不并入本阶段，后续另行设计。

## 实施结构

1. 审核插件源码与独立版本，建立插件 feature/权限/接口账本；更新迁移契约和能力矩阵。
2. 原生插件注册与 dialog 各自独立模块；Builder 只负责验证、消费和装配。
3. 扩展共享生命周期资源登记，承接晚到的对话框回调；不为每种选择器复制一套清理路径。
4. Python plugin、plugins/dialog 与 ffi、类型声明和中文指南；继续保持 ECL 编码风格。
5. 新增模拟 ECL 的文件选择/保存示例与真实系统对话框验收，复跑既有三个桌面验收脚本及安装包检查。

## 验收标准

1. 保留现有 build 调用；正确注册 dialog，拒绝重复/无效/已消费插件；未注册和禁用 feature 时明确报错。
2. 实际系统窗口选择一个/多个临时文件、一个/多个目录、保存路径及取消，核验 Path 返回值、Unicode、过滤器、标题、默认目录/文件名及父窗口。
3. 实际消息框核验确认/取消、消息类型及自定义按钮；未独立验收的选项继续注明限制。
4. ECL 的 AnyIO 工作线程 → blocking_* → 路径 → 前端响应链路通过真实 WebView，等待时其他 Python 线程继续运行。
5. GUI 阻塞拒绝、回调异常/awaitable、关闭/退出时资源释放、同标签重建与晚到回调均有行为证据。
6. 无权限的插件 JS 命令仍被 ACL 拒绝；既有未授权标签与外部页面的新旧 IPC 拒绝继续通过。
7. 系统对话框验收只操作本脚本启动的 PID 和唯一测试标题，不对未知窗口发送输入或关闭消息。无法自动化的具体行为记为待人工验收，不用模拟结果冒充真实验收。
8. Python 3.11/3.14 的测试、独立 wheel、源包重建、真实桌面回归，以及 Ruff/Pyright、Rustfmt/Clippy、feature 开关和独立账本核验通过。

## 完成判据

本阶段完成插件构建入口与已列出的桌面 dialog 子集，降低 ECL 文件/皮肤操作的迁移成本。
不宣称 ECL 整体迁移、整个 dialog crate、全部官方插件或移动平台完成；未提交、推送或发布。

实施结果：Python 3.11/3.14 各 85 项测试通过、1 项环境跳过，各 24 个真实桌面进程通过。
dialog 正常进程有 48 个系统选择场景、57 项检查及 168 项控件观察，另外七种关闭/异常通过。
禁用插件的独立 wheel 仍可导入和运行基础桌面 IPC；源包 101 个文件逐字节核验及解压重建通过。
macOS 创建目录开关、过滤列表/消息图标外观和未实现移动/结构化结果继续明确登记。
用法见 [对话框指南](plugins-dialog.md)，完整证据见 [验证记录](validation.md)。

参考：[官方 Dialog 指南](https://v2.tauri.app/plugin/dialog/)、[插件 2.8.1](https://crates.io/crates/tauri-plugin-dialog/2.8.1)、[当前独立项目迁移契约](migration-contract.md)。
