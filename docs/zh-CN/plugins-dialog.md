# 原生插件与对话框

第五阶段提供构建时插件注册，以及 tauri-plugin-dialog 2.8.1 的桌面文件/消息子集。
编译能力、应用注册和前端权限是三个独立条件；不支持的移动和结果接口见独立账本。

## 注册与导入

```python
from pytaurix import builder_factory
from pytaurix.plugin import Plugin
from pytaurix.plugins.dialog import DialogExt, init as dialog_init

plugins: list[Plugin] = [dialog_init()]
app = builder_factory().build(
    context=context,
    invoke_handler=commands.generate_handler(portal),
    plugins=plugins,
)
```

init 不创建窗口。build 复制输入序列，不修改调用方列表；无效、重复名称、已消费描述符分别返回
invalid_plugin、duplicate_plugin、plugin_consumed。通过验证并进入原生构建后，描述符被消费；原生启动失败也不会恢复。
当前只提供 dialog 描述符，不支持任意 Python 插件、运行期注册/卸载或原生插件构造器。

插件入口采用 pytaurix.plugins.dialog；同名公共类型也从其 ffi 模块重导出。
迁移 PyTauri 常用代码通常只需修改导入和包名，但不承诺完整 PyTauri 或 ECL 等价。
默认构建开启 plugin-dialog 和 dialog-gtk3；可用 dialog-xdg-portal 选择另一 Linux 后端，平台行为仍须分别验收。
使用 --no-default-features --features wry 构建可关闭 dialog；根包仍正常导入，导入插件模块抛明确 ImportError。
get_runtime_info 的 plugin.dialog 和 dialog_version 只报告编译能力，不代表某个应用已注册插件。

## 选择路径

```python
from anyio import to_thread
from pytaurix.plugins.dialog import DialogExt

picked = await to_thread.run_sync(
    lambda: DialogExt.file(window).blocking_pick_file(
        add_filter=("资源文件", ["jar", "zip"]),
        set_directory=resources_dir,
        set_title="选择资源文件",
        set_parent=window,
    )
)
```

file 和 message 接受 App、AppHandle、WebviewWindow。使用 App 的工厂入口需要在主线程取得句柄；
工作线程通常直接使用注入的 AppHandle 或 WebviewWindow。未注册插件返回 plugin_missing。

| 操作 | 阻塞版 | 结果 |
| --- | --- | --- |
| pick_file | blocking_pick_file | Path 或 None |
| pick_files | blocking_pick_files | list[Path] 或 None |
| pick_folder | blocking_pick_folder | Path 或 None |
| pick_folders | blocking_pick_folders | list[Path] 或 None |
| save_file | blocking_save_file | Path 或 None |

回调版采用 pick_file(handler, **kwargs) 等形状；handler 接收表中的结果，调用本身返回 None。
FileDialogBuilderArgs 定义六个选项：add_filter、set_directory、set_file_name、set_parent、set_title、set_can_create_directories。
选项随每次操作传入，没有链式修改方法；未知选项及非法值明确拒绝。
Path 或字符串目录均保留路径语义，不把移动 URI 转换成本地路径。

窗口入口用于资源所有权，不隐式指定原生父窗口；set_parent 必须显式传入。
保存仅选择路径，不创建或覆盖文件。取消是 None；锁定上游 rfd 同样用 None 表示部分后端失败，
因此当前接口无法区分所有系统失败和取消，不虚构额外诊断。

set_can_create_directories 的上游效果仅适用于 macOS；Windows 已验证参数传递，尚未验证 macOS 效果。
过滤器标题已在真实控件中核验；实际列表对被过滤文件的隐藏效果仍待独立人工检查。

## 消息框

```python
from pytaurix.plugins.dialog import DialogExt, MessageDialogButtons, MessageDialogKind

confirmed = await to_thread.run_sync(
    lambda: DialogExt.message(window, "是否继续？").blocking_show(
        title="确认",
        parent=window,
        kind=MessageDialogKind.Warning,
        buttons=MessageDialogButtons.OkCancelCustom("继续", "取消"),
    )
)
```

show(handler, **kwargs) 是回调版；MessageDialogBuilderArgs 包含 title、parent、kind、buttons。
Info、Warning、Error 均可用；系统决定具体图标，外观没有单独测量。
按钮包括 Ok、OkCancel、YesNo、YesNoCancel、OkCustom、OkCancelCustom、YesNoCancelCustom。
自定义标签类型保留 tuple、位置参数、_0/_1/_2 和模式匹配形状。

bool 只表达肯定选择：OK/Yes/自定义肯定按钮为 True，其余为 False。
目前没有 MessageDialogResult、show_with_result、blocking_show_with_result，不能通过 bool 区分否定和取消。
移动 PickerMode、FileAccessMode 及对应选项也未绑定。

## 线程、关闭和错误

应用运行前不能提交操作。阻塞版只允许事件循环运行中的工作线程调用，并释放 GIL 等待。
GUI 主线程以及原生同步回调中阻塞会返回 would_block；AnyIO 命令需通过 to_thread.run_sync 调用。
回调不保证 GUI 线程，需要操作 UI 时使用 run_on_main_thread；返回值须同步。
异常触发有序退出并由 run_return 重抛；coroutine 会关闭并返回 invalid_callback。

待完成操作按应用、创建入口的窗口代次和显式父窗口登记。
窗口销毁或应用退出清掉 Python 引用、唤醒等待；阻塞版分别返回 window_closed 或 app_closed。
同标签重建不能复活旧构建器；晚到的原生结果不会调用已清理的回调。
等待 GIL 后再次复核所有者，避免关闭期间从原生线程进入旧回调；已经开始的回调不会被强制中止。

清理 Python 操作不保证强制关闭系统对话框，上游没有统一的程序化取消接口。
Windows 验收包含显示中的选择器、所有者销毁、同标签重建和晚到结果，不能推广为其他平台行为。

## 权限与验证

注册 dialog 不自动授予 dialog:default；原生 Python 调用可用，未授权的前端 plugin:dialog|open 仍被 ACL 拒绝。
无宿主策略的原型保留精确标签权限；第九阶段宿主 capabilities 可选择实际插件权限与来源，见 [ECL 指南](ecl.md)。
没有提供构建后任意 capabilities 修改或 filesystem scope 扩展。
tauri-plugin-fs 2.6.0 是 FilePath 的传递依赖，未注册 fs 插件，也未绑定 filesystem API。

```powershell
uv run --no-sync python scripts/dialog_smoke.py
uv run --no-sync python scripts/update_coverage.py --check
```

验收脚本通过本脚本创建的进程后代关系、PID 和唯一标题定位系统窗口，仅向对应控件发送消息。
48 个正常选择场景和七种关闭/异常进程分别运行；完整结果见 [验证记录](validation.md)。
核心账本和 dialog 账本分别统计，不用 Cargo features 或声明候选计算全量完成率。

