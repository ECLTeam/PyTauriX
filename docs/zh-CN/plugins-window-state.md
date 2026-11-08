# 窗口状态插件

`tauri-plugin-window-state` 2.4.0，构建时启用 `plugin-window-state`。默认 wheel 不包含该插件，
未启用时 `init()` 报 `unsupported_capability`。

这个插件补的是 Python 侧做不到的部分：窗口几何的保存与恢复挂在 Tauri 的窗口事件里，
需要和窗口创建、关闭、最大化、全屏这些时机对齐，自己用 Python 轮询既不准也容易漏。

## 注册

```python
from pytaruix import builder_factory
from pytaruix.plugins.window_state import init as window_state

app = builder_factory().build(
    context=context,
    invoke_handler=commands.generate_handler(),
    plugins=[
        window_state(
            filename=".window-state.json",
            flags=("size", "position", "maximized"),
            denylist=("splash",),
            skip_initial=("wizard",),
        )
    ],
)
```

注册之后，插件在窗口创建与关闭时自动恢复、保存，Python 不需要参与。

| 参数 | 含义 | 默认 |
| --- | --- | --- |
| `filename` | 状态文件名 | 上游 `.window-state.json` |
| `flags` | 参与持久化的状态位 | 全部 |
| `denylist` | 完全不参与持久化的窗口标签 | 空 |
| `skip_initial` | 首次创建时不恢复的窗口标签 | 空 |

## 标志

| 名称 | 上游位 |
| --- | --- |
| `size` | `StateFlags::SIZE` |
| `position` | `StateFlags::POSITION` |
| `maximized` | `StateFlags::MAXIMIZED` |
| `visible` | `StateFlags::VISIBLE` |
| `decorations` | `StateFlags::DECORATIONS` |
| `fullscreen` | `StateFlags::FULLSCREEN` |

不传 `flags` 时与上游 `StateFlags::default()` 一致，即全部标志。未知名称报
`ValueError: unknown state flag`，不会静默降级。

## 运行期

```python
from pytaruix.plugins.window_state import WindowState

state = WindowState(handle)
state.save()                                # 立即把全部窗口状态落盘
state.restore(window)                       # 对已存在的窗口立即恢复
state.save(flags=("size", "position"))      # 只写指定状态
state.filename                              # 当前状态文件名
```

`save` 与 `restore` 都在工作线程执行，释放 GIL。

## 边界

- **未注册插件时报 `plugin_missing`**：上游通过这些入口取 `state::<PluginState>()`，未注册会 panic，
  包装类先查运行态登记表挡住。
- **恢复只面向已存在的窗口**：新建窗口的恢复由插件在创建时自行完成，`restore()` 只用于
  “窗口已经在了，我要按文件内容再摆一次”。
- **`with_filter` 与 `map_label` 未暴露**：两者都需要在构建期传入 Python 回调，
  当前插件描述符只接受静态参数。
- **`filename` 是插件内部文件名，不是完整路径**：上游把它拼到应用配置目录下。
- Windows 已通过[桌面验收](desktop-acceptance.md)验证跨进程恢复：第一轮固定 820×560 并保存，
  第二轮读到相同尺寸。多显示器变化、denylist 与 skip_initial 的真实效果仍未验证。
