# 系统集成插件：单实例、全局快捷键、通知、opener

这四个插件补的都是 Python 侧做不到的能力：进程级单实例、系统级热键、系统通知、调用默认程序。
全部按需构建，默认 wheel 不包含；各自锁定独立版本。

## 单实例（single-instance 2.3.2）

```python
from pytaruix.plugins.single_instance import init

def activated(handle, argv, cwd):
    print("第二个实例的参数：", argv, cwd)

app = builder_factory().build(
    context=context,
    invoke_handler=commands.generate_handler(),
    plugins=[init(activated)],   # 放最前面
)
```

- 第二个进程启动时回调第一个进程，参数为 `(AppHandle, tuple[str, ...], cwd)`。
- 回调必须是同步函数；返回 awaitable 或抛异常会结束应用并由 `run_return` 重抛。
- 上游要求该插件尽量先登记。构建器已把用户插件排在桥接插件之前，满足这一要求。
- 构建时启用 `plugin-single-instance`。

## 全局快捷键（global-shortcut 2.3.0）

```python
from pytaruix.plugins.global_shortcut import GlobalShortcut, init

def on_hotkey(handle, accelerator):
    print("按下", accelerator)

def setup(handle):
    shortcuts = GlobalShortcut(handle)
    shortcuts.register("Ctrl+Shift+K", on_hotkey)
    print(shortcuts.is_registered("Ctrl+Shift+K"))
```

- 只在按下时回调，不会因释放重复触发；快捷键文本由上游解析，非法时返回 `shortcut_failed`。
- 同一快捷键重复注册由上游拒绝；`unregister` / `unregister_all` 显式释放。
- 需要 `plugin-global-shortcut`。Linux 下依赖桌面环境的全局热键支持。

## 通知（notification 2.3.0）

```python
from pytaruix.plugins.notification import Notification, init

def setup(handle):
    n = Notification(handle)
    print(n.permission_state())        # 桌面端通常是 granted
    n.send("下载完成", "1.20.1 已就绪", silent=True, id=1)
```

- `permission_state()` / `request_permission()` 直接归还上游状态文本。
- `send()` 成功只表示上游已提交；Windows 未打包应用缺少应用标识时通知可能不显示。
- 同名 `id` 用于替换同一条通知；`silent=True` 关闭提示音。
- 需要 `plugin-notification`。

## opener（opener 2.5.0）

```python
from pytaruix.plugins.opener import Opener, init

def setup(handle):
    opener = Opener(handle)
    opener.open_url("https://example.com")
    opener.open_path(some_file)          # 用默认程序打开
    opener.reveal_item_in_dir(some_file) # 在文件管理器中选中
```

- 三个入口都只提交请求，不确认外部程序已启动；失败为 `opener_failed`。
- `open_url` / `open_path` 可用 `with_app` 指定处理程序。
- 需要 `plugin-opener`。

## 共同契约

- `init()` 只创建描述符，不初始化 GUI；未启用对应 feature 时抛 `BindingError`（`unsupported_capability`）。
- 包装类（`GlobalShortcut` / `Notification` / `Opener`）要求 `AppHandle`，未注册插件时返回 `plugin_missing`，
  不让上游的 `state()` 直接 panic。
- 回调异常沿用同步回调语义：记录并退出应用，由 `run_return` 重抛，不静默吞掉。
- `get_runtime_info().capabilities` 会随构建出现 `plugin.global_shortcut`、`plugin.notification`、
  `plugin.opener`、`plugin.single_instance`。

## 构建

```powershell
$env:CARGO_BUILD_JOBS=1
uv run --no-sync maturin develop --locked --features plugin-single-instance,plugin-global-shortcut,plugin-notification,plugin-opener
```

同时启用多个插件时请限制并发编译：某些 Windows 依赖（如 `windows-sys`）在并行 codegen 下会触发
rustc 的栈溢出崩溃（`STATUS_STACK_BUFFER_OVERRUN`），单作业可以稳定完成。

## 验收状态

契约测试覆盖可用性标志、能力报告一致性、缺失 feature 的拒绝、参数校验与包装类类型检查。
第二实例唤醒已在 Windows 真实桌面验证：回调带回第二进程的 argv 与 cwd，见[桌面验收](desktop-acceptance.md)。
热键按下回调、通知显示与默认程序启动同样已有真实桌面证据：热键由 `SendInput` 合成事件触发，
通知与默认程序通过原生消息框取得人工确认，十项判据见[插件行为验收](desktop-acceptance.md#插件行为验收)。
仍缺证据的是热键与其他程序冲突、通知的 `silent=True` 静默效果，以及 Linux/macOS。
