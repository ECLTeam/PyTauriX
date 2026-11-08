# 原生菜单

第八阶段绑定桌面菜单子集；使用 Tauri 2.12.1 与同版本锁定的 muda 0.20.0。
默认桌面运行时提供菜单，无需启用 tray-icon 或注册前端插件，也不扩大现有 IPC/ACL。
Linux/macOS 尚未实测；移动平台导入模块不会创建 GUI，构造明确返回 platform_unavailable。

## 导入与构造

```python
from pytaruix.menu import Menu, Submenu, MenuItem, CheckMenuItem
from pytaruix.ffi.menu import IconMenuItem, PredefinedMenuItem, ContextMenu
from pytaruix.ffi.image import Image


def setup(handle):
    open_item = MenuItem.with_id(handle, "open", "打开", True, "Ctrl+O")
    checked = CheckMenuItem.with_id(handle, "visible", "显示", True, True)
    submenu = Submenu.with_items(handle, "文件", True, [open_item, checked])
    menu = Menu.with_items(handle, [submenu])
    menu.set_as_app_menu()
    handle.on_menu_event(on_menu)


def on_menu(handle, event):
    if event == "open":
        # 将菜单查询、修改或业务工作提交到已有工作线程。
        print("打开")
```

menu 与 ffi.menu 重导出同一组类型，MenuID 和 MenuEvent 均为 str。
构造器、with_id、with_items、with_id_and_items 保留对应位置参数与默认值；
MenuItem 的 accelerator 默认 None，IconMenuItem 的 icon/accelerator 默认 None。
管理器可为 App、AppHandle、WebviewWindow；App 取句柄仍遵循其 Python 主线程限制。

资源属于应用；用窗口作为管理器创建不会让资源归属该窗口。
窗口关闭后已有菜单/项目句柄仍可用，不能再用关闭的窗口构造新菜单。
应用退出后 id/app_handle 及所有原生资源操作返回 app_closed。

## 项目、顺序与挂载

Menu/Submenu 提供 append/append_items、prepend/prepend_items、insert/insert_items、remove/remove_at、get/items。
items 返回有序共享句柄；get 只查直接子项中首个匹配 ID，不递归查嵌套项。
非负 remove_at 超出项目数返回 None；insert 的位置可以等于项目数，不能更大。
负数、bool 和非整数位置返回 invalid_index。索引校验和单项插入在同一个 GUI 任务内执行。
批量接口和构造工厂与上游一样逐项执行，中途原生失败可保留此前修改，不承诺事务回滚。

允许原生共享项目、多父菜单、重复插入和重复 ID。
remove 按 ID 移除全部原生匹配项，get 选择第一个，因此建议业务事件使用唯一 ID。
移除不销毁 Python 项目句柄。直接和传递子菜单循环由 muda 拒绝，返回 menu_failed。
跨应用资源返回 menu_owner；每进程一个应用的限制使跨应用场景仅审核了代码边界，未做双应用实测。

普通、勾选和图像项支持 text/set_text、is_enabled/set_enabled、set_accelerator；
Submenu 提供文字与启用状态，CheckMenuItem 额外提供 is_checked/set_checked。
IconMenuItem 支持 set_icon(Image | None)，不保留借用的 Python 像素缓冲区。
PredefinedMenuItem 当前仅提供 separator 工厂，其 text/set_text 沿用原生缓存，不保证显示分隔线文字。
启用与勾选参数严格要求 bool；文字/ID 拒绝 NUL。快捷键用同一 muda 解析器校验，
invalid_accelerator 在修改前拒绝无效输入，避免 Tauri 构造器静默忽略错误快捷键。

AppHandle/WebviewWindow 的 menu、set_menu、remove_menu 查询或返回前一个 Menu，未挂载时返回 None。
Menu.set_as_app_menu/set_as_window_menu 保留 PyTauri 的 None 返回形状。
macOS 只提供应用菜单，窗口独立菜单不受支持，且根菜单只能包含 Submenu。
Windows 的关闭路径在未被 Python prevent_close 拦截时解除 HMENU 关联，避免系统随窗口销毁共享菜单。
该处理使用原窗口代次缓存的 HWND，在 GUI CloseRequested 通知中执行，不重入 Wry 窗口查询。
关闭拦截保留原挂载；实际系统关闭请求、菜单复用和同标签重建均有 Windows 证据。

## 上下文菜单与线程

```python
from pytaruix.dpi import LogicalPosition

# 在 IPC 命令工作线程或已有后台线程执行：
ContextMenu.popup(menu, window)
ContextMenu.popup_at(submenu, window, LogicalPosition(80, 80))
window.popup_menu_at(menu, LogicalPosition(100, 100))
```

Menu/Submenu 均可弹出；位置使用已绑定逻辑/物理位置类型，坐标相对窗口，具体基准沿用平台。
当前接受 WebviewWindow 是本项目扩展；未提供 PyTauri 独立 Window。
弹出可能等待用户选择或取消，不承诺异步返回或返回所选项目；选择通过 MenuEvent 派发。

创建、读取、修改、挂载和弹出在桌面 setup 或运行期间执行，工作线程释放 GIL。
运行前返回 app_not_running；Python 同步 GUI 回调中返回 blocking_callback，禁止注册菜单回调重入。
原生模态菜单循环若重入 GUI 菜单任务，同样拒绝，避免上游菜单借用冲突。
排队等待期间会检查应用/窗口关闭状态；不强制关闭正在显示的原生上下文菜单。
id/app_handle 是元数据读取，可在同步回调中执行。

## 事件与资源清理

on_menu_event 的回调参数为订阅者句柄和字符串 ID，执行在 Python 主线程，必须同步。
Tauri 将菜单事件广播给所有应用与窗口订阅；窗口参数是订阅窗口，不表示点击来源。
应用入口累加监听，窗口入口替换同一原始代次的监听。
clear_menu_event_handlers 只清空当前入口拥有的 Python 回调，允许在回调内调用。
已经开始的回调不会被强制中止；注销不能撤销已取得的回调引用。

上游没有菜单监听的物理注销 API；原生闭包只捕获弱引用，清空槽后停止后续 Python 派发。
窗口关闭清除其原始代次，标签复用不会复活旧监听；应用退出清除全部槽。
Python 引用析构遵循 PyO3 attach 时机，最终清理在 portal 关闭后核对。
回调异常由 run_return 有序归还；误返回 awaitable 抛 invalid_callback，原生协程会关闭，不能引发 Rust panic。

## 验收与未覆盖范围

scripts/menu_smoke.py 通过真实 Windows 菜单栏和上下文菜单选择验证事件，
独立使用 GetMenu/GetMenuItemInfo 和 HBITMAP/GetDIBits 读回状态及 16×16 不透明样本的全部 RGBA。
选择驱动使用目标进程窗口的系统菜单助记符及字符输入，进入原生菜单循环；
没有伪造 WM_COMMAND 或直接调用 Python 回调，也不发送全局鼠标点击。
Windows muda 将菜单图像渲染成 16×16；更大图像的缩放/透明合成外观没有计为像素验收。
前台激活时机可能延迟，驱动仅对其拥有的窗口有限重试；不会停止未知进程。

AboutMetadata、NativeIcon、其他预定义角色、Menu.default、完整 Builder、托盘及移动菜单仍未绑定。
窗口菜单隐藏/显示入口、构建器直接附带菜单、任意 Rust 资源表和前端菜单适配不在本阶段范围。
Linux/macOS 行为、菜单快捷键的物理键盘触发、跨应用实例和 DPI 组合外观仍需单独验收。

## 预定义角色

`PredefinedMenuItem` 提供 17 个平台角色，构造签名为 `(manager, text=None)`，`about` 额外接受 `AboutMetadata`：

- 编辑：`copy`、`cut`、`paste`、`select_all`、`undo`、`redo`
- 窗口：`minimize`、`maximize`、`fullscreen`、`close_window`
- 应用：`quit`、`hide`、`hide_others`、`show_all`、`services`、`bring_all_to_front`
- 其他：`separator`、`about`

`text` 只覆盖显示文案，角色行为与快捷键仍由平台决定；`set_text` 可在构造后修改文案。
`hide`、`hide_others`、`show_all`、`services`、`bring_all_to_front` 仅 macOS 有可见效果，
Windows 上可以构造但不产生界面变化。`AboutMetadata` 省略空字段，图标尚未绑定。

```python
from pytaruix.menu import AboutMetadata, Menu, PredefinedMenuItem

menu = Menu.with_items(
    app_handle,
    [
        PredefinedMenuItem.copy(app_handle),
        PredefinedMenuItem.paste(app_handle),
        PredefinedMenuItem.separator(app_handle),
        PredefinedMenuItem.about(app_handle, "About", AboutMetadata(name="PytaruiX", version="0.1.0")),
        PredefinedMenuItem.quit(app_handle),
    ],
)
app_handle.set_menu(menu)
```

菜单资源操作不能在同步 GUI 回调（如 `Ready`）内执行，应在 `setup(AppHandle)` 或运行期调用。

## 默认菜单与原生图标

`Menu.default(manager)` 返回上游默认应用菜单，结构与可用角色由 Tauri 按平台决定，本项目不复制其内容。
`IconMenuItem` 支持 `with_native_icon`、`with_id_and_native_icon` 与 `set_native_icon`，
图标取自 56 项 `NativeIcon` 枚举，取值等于上游变体名：

```python
from pytaruix.menu import IconMenuItem, Menu, NativeIcon

default = Menu.default(app_handle)
folder = IconMenuItem.with_native_icon(app_handle, "Open Folder", True, NativeIcon.FOLDER)
folder.set_native_icon(NativeIcon.FOLDER_SMART)
folder.set_native_icon(None)
```

原生图标只在 macOS 显示；Windows/Linux 接受设置但不产生可见效果。未知名称抛 `invalid_native_icon`，
不会静默退化为无图标。
