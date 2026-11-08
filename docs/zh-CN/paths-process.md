# 路径与进程

本文说明 `pytaurix.path` 与 `pytaurix.process` 的入口、线程约束、平台差异和未绑定范围。
接口契约与迁移差异见[迁移契约](migration-contract.md)，覆盖状态见[能力矩阵](capability-matrix.md)。

## 取得解析器

`Manager.path(manager)` 接受应用、应用句柄或窗口，返回绑定到该应用身份的 `PathResolver`。
解析只读取身份与宿主配置，不创建目录、不校验路径是否存在，也不访问网络。

```python
from pytaurix import BaseDirectory, Manager

resolver = Manager.path(app_handle)
log_dir = resolver.app_log_dir  # Path | None
config = resolver.resolve("settings.json", BaseDirectory.APP_CONFIG)
home_config = resolver.parse("$HOME/.config/app.toml")
```

## 目录入口

`PathResolver` 提供 21 个目录属性，平台不提供时返回 `None`，不折叠成空路径：

`audio_dir`、`cache_dir`、`config_dir`、`data_dir`、`local_data_dir`、`document_dir`、`download_dir`、
`picture_dir`、`public_dir`、`video_dir`、`desktop_dir`、`font_dir`、`runtime_dir`、`template_dir`、
`resource_dir`、`app_config_dir`、`app_data_dir`、`app_local_data_dir`、`app_cache_dir`、`app_log_dir`、`home_dir`。

`app_*` 系列受宿主 `appDirectoriesOverride` 影响；`resource_dir` 由打包方式决定，
未打包运行时通常指向可执行文件所在目录。

## 解析与错误

| 入口 | 返回 | 失败行为 |
| --- | --- | --- |
| `resolve(path, base)` | 绝对路径 | 目录不可用或应用已关闭时抛 `BindingError` |
| `parse(path)` | 绝对路径 | `$VARIABLE` 无法解析时抛 `path_unresolved` |
| 目录属性 | `Path` 或 `None` | 应用已关闭时抛 `BindingError`，不静默返回 None |

目录名接受 camelCase、snake_case 与 `$VARIABLE` 三种写法，比较前忽略大小写、下划线与美元符号；
未知名称抛 `invalid_base_directory`，不做前缀猜测。

Windows 返回值去掉 `\\?\` 扩展长度前缀，便于交给 Python 的 `Path`、`open` 与其他库；
非 UTF-8 路径抛 `path_not_utf8`，不使用有损转换隐藏真实文件名。

## 进程

| 入口 | 说明 |
| --- | --- |
| `process.current_pid()` | 当前进程标识，不需要应用实例 |
| `process.current_binary(manager)` | 当前可执行文件路径；Linux AppImage 与 macOS 符号链接规则沿用上游 |
| `process.restart(manager)` | 派生新进程后立即退出，不返回调用方 |

`restart` 不执行 Python 监听器、共享状态与原生资源的清理，也不返回退出码；
需要有序退出时使用 `AppHandle.exit(code)`，或自行清理后再退出。

## 线程与平台

- 所有入口在 Python 主线程或工作线程均可调用；解析不进入 GUI 队列，不阻塞事件循环。
- 应用退出后调用统一抛 `app_closed`，不复用旧代次的目录快照。
- Windows 已取得真实桌面证据（`scripts/path_smoke.py`）；Linux/macOS 行为依赖上游 `dirs` 实现，尚未取得运行证据。
- 移动平台未实现，`BaseDirectory` 中 Android 不存在的目录在该平台会返回 `None`。

## 未绑定范围

Tauri 的 `async_runtime`（`spawn`、`block_on`）明确不转发：Python 侧由调用方的 AnyIO portal 承担，
避免两套事件循环相互等待。`PathResolver` 之外的上游路径工具（`resolve_path` 自由函数、`FilePath` 校验类型）
暂未绑定，需要时按同一模式补充。
