# 系统托盘

托盘是应用资源，需显式编译 tray-icon feature；默认安装不启用。
Linux/macOS 的原生效果必须在相应平台验收，Windows 结果不代表跨平台通过。

```powershell
uv run --no-sync maturin develop --locked --jobs 1 --features tray-icon,devtools
uv run --no-sync python examples/tray/main.py
```

## 构造与修改

```python
from pytaurix.ffi.image import Image
from pytaurix.menu import Menu, MenuItem
from pytaurix.tray import TrayIconBuilder

def setup(handle):
    menu = Menu.with_items(handle, (MenuItem.with_id(handle, "show", "显示窗口", True),))
    icon = Image(bytes((25, 130, 210, 255)) * 256, 16, 16)
    tray = (
        TrayIconBuilder.with_id("main-tray")
        .icon(icon)
        .menu(menu)
        .tooltip("PyTauriX")
        .show_menu_on_left_click(False)
        .build(handle)
    )
    tray.set_visible(True)
```

TrayIcon(manager) 和 TrayIcon.with_id(manager, id) 提供 PyTauri 常用构造形状。
manager 可为 App、AppHandle 或存活的 WebviewWindow；窗口只用于取得应用句柄，窗口关闭不销毁托盘。
创建、原生修改和查询需 setup 或运行中的事件循环，工作线程等待 GUI 时释放 GIL。
Builder 本身只保存选项，id 在 build 前稳定，不在导入或配置阶段初始化 GUI。

set_menu 只接受现有 Menu/Submenu 或 None，验证同应用所有权；菜单项可在挂载后动态修改。
set_icon、set_icon_with_as_template 复用自有 Image；set_tooltip、set_title 接受 str 或 None。
set_visible、set_show_menu_on_left_click 严格接受 bool；set_temp_dir_path 接受 pathlib.Path 或 None。

## 事件与线程

on_tray_icon_event(handler) 替换该托盘的鼠标回调，参数为共享托盘句柄和不可变事件快照。
AppHandle.on_tray_icon_event(handler) 累加全应用托盘监听，参数为应用句柄和同类快照。
Builder.build(on_tray_icon_event=handler) 是在 Python setup 前登记全应用监听的等价入口。
它不是 Rust Builder 在 build 时登记的完整时机等价接口，审核账本单独注明。

TrayIconEvent 包含 Click、DoubleClick、Enter、Move、Leave，可使用 isinstance 或 match。
id 为 str；position 为 PhysicalPositionF64，保留原生 f64 小数与负坐标；rect 为带单位的 Rect。
事件不拥有系统资源，窗口或应用关闭后仍可读取。
回调中的托盘参数是同资源代次的别名，不保证与原 Python 对象具有相同的 is 身份。

on_menu_event(handler) 沿用上游全应用菜单广播语义，参数为 AppHandle 和字符串菜单 ID。
它也会收到其他托盘和窗口菜单的选择事件，不能将该入口理解为来源过滤。
单托盘菜单监听累加，close 或 clear_event_handlers 清空其 Python 引用。

回调同步运行在 GUI 主线程，不能等待 GUI 事务、创建/修改/查询托盘或重新登记监听。
这些调用在进入 native 前返回 blocking_callback；clear_event_handlers 与应用级 clear 允许在回调内调用。
恢复窗口等需要执行原生操作的场景，应将工作交给后台线程，回调及时返回，不在回调内 join 该线程。
异常使应用有序退出并由 run_return 重抛；async 函数和 callable 的异步 __call__ 提前拒绝，
同步函数返回 awaitable 时关闭该对象并按既有 invalid_callback 契约退出，不发生 Rust panic。

## 引用与关闭

应用在创建后持有原生托盘引用；丢弃 Python 变量不自动移除它。
tray_by_id 只查询本绑定创建且仍由应用持有的托盘，返回共享代次别名；未找到返回 None。
当前不接管由其他原生插件或配置创建的托盘，账本将查询标为部分绑定。

remove_tray_by_id 移除应用持有的原生引用并返回句柄；现存 Python 句柄继续有效。
当所有 Python 句柄也释放后，已移除托盘的最后原生引用释放，图标随之销毁。
若回调主动捕获托盘，需显式 close 或 clear_event_handlers 解除用户建立的引用环。

close 是本项目扩展：移除应用引用、释放内部原生引用并清空回调，让所有现存别名一起失效。
它幂等，关闭后原生操作返回 tray_closed，id 与 closed 仍可读取。
应用退出清理所有托盘和回调，随后原生操作返回 app_closed，close 仍可重复调用。
同 ID 的旧托盘即使已移除应用引用，只要仍存活，就拒绝重建；显式 close 或完全释放后允许重建。
这一约束防止上游按字符串 ID 路由的原生事件跨代次串发，属于本项目明确的限制。

## Feature 与平台差异

get_runtime_info().capabilities 仅在实际启用桌面 tray-icon 时报告 tray.icon、tray.builder、tray.events、tray.close。
未启用时仍能导入 tray 模块和事件类型；构造抛出 unsupported_capability。
AppHandle 的原生托盘扩展方法仅在启用 feature 时存在，不提供空壳资源。

| 能力 | Windows | Linux | macOS |
| --- | --- | --- | --- |
| 鼠标事件 | 支持 | 上游不派发 | 支持，双击除外 |
| DoubleClick | 支持 | 不支持 | 不支持 |
| tooltip | 支持 | 上游无效果 | 支持 |
| title | 上游无效果 | 依赖面板与图标 | 支持 |
| 临时目录 | 无效果 | 有效 | 无效果 |
| 模板图像 | 无效果 | 无效果 | 有效 |
| 左击菜单开关 | 支持 | 上游不支持 | 支持 |
| rect | 支持 | 返回 None | 支持 |

Linux 设置菜单后移除/替换受上游限制，不虚构平台效果。
set_icon_with_as_template 在 Windows/Linux 回退为更新图像；macOS 原子模板效果需单独测量。
未新增已弃用的 menu_on_left_click 别名，也未暴露依赖 Rust 闭包与内部 crate 类型的 with_inner_tray_icon。

来源为 [锁定版本托盘源码](https://github.com/tauri-apps/tauri/blob/tauri-v2.12.1/crates/tauri/src/tray/mod.rs)
和 [官方指南](https://v2.tauri.app/learn/system-tray/)，最终声明与行号以 Cargo 源包审核账本为准。
