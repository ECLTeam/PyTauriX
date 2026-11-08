# PytaruiX

用 PyO3 把 Tauri 2 的桌面能力带到 Python 的独立框架。发行包与导入名均为 `pytaruix`，
公开 API 布局参考 PyTauri，线程、资源与错误语义按本仓库规范维护。

**状态**：预发布 `0.1.0a1`。基线为 Tauri 2.12.1、tauri-build 2.7.1、PyO3 0.29.3，
要求 Rust 1.90+ 与 Python 3.11+。Windows 已取得真实桌面验收；Linux/macOS 已有工作流文件
但尚无运行证据；移动端未实现。详见[能力矩阵](docs/zh-CN/capability-matrix.md)。

## 快速开始

Windows 另需 MSVC 构建工具与 WebView2；其他平台需对应 Tauri 系统依赖。

```powershell
uv sync --locked --no-install-project
uv run --no-sync maturin develop --locked --jobs 1
uv run --no-sync python examples/minimal/main.py
```

最小应用：

```python
from pathlib import Path

from pytaruix import Commands, builder_factory, context_factory

commands = Commands()


@commands.command()
def greet(name: str) -> str:
    return f"Hello, {name}"


context = context_factory(Path("examples/minimal"))
app = builder_factory().build(context=context, invoke_handler=commands.generate_handler())
app.run_return()
```

`Builder.build()` 即构建原生应用，`App.handle()` 在运行前取得句柄；每个进程只允许一个原生应用。
配置窗口与 `setup(AppHandle)` 沿用上游 Ready 初始化时机，早到的前端 IPC 等待 setup 完成。
资源目录在启动前读取为内存快照，配置与资源路径由调用方显式传入。
异步命令依赖调用方提供的 AnyIO portal，运行期间必须保持开启。

## 能力摘要

应用与生命周期、命令与状态注入、原生 IPC Channel、事件与主线程调度、动态窗口与 WebView
策略回调、显示器与图像、菜单、托盘、对话框插件、宿主配置与权限、路径与进程查询均已绑定。
命令支持前端 `AbortSignal` 与注入 `Request` 的协作式取消，通道支持 `capacity` 配额流控；
支持构建期注册自定义 URI scheme，官方插件已接入 dialog、fs、single-instance、global-shortcut、notification 与 opener。
完整清单见[功能清单](docs/zh-CN/features.md)，各领域缺口与平台限制见能力矩阵。

## 文档

| 主题 | 入口 |
| --- | --- |
| 开发路线与阶段出口 | [development-roadmap.md](docs/zh-CN/development-roadmap.md) |
| 阶段实施记录 | [implementation-plan.md](docs/zh-CN/implementation-plan.md) |
| 能力覆盖与缺口 | [capability-matrix.md](docs/zh-CN/capability-matrix.md) |
| 迁移与兼容契约 | [migration-contract.md](docs/zh-CN/migration-contract.md) |
| 工程规范与验收命令 | [AGENTS.md](AGENTS.md) |
| 功能指南 | [窗口](docs/zh-CN/windows.md) · [事件](docs/zh-CN/events.md) · [IPC 取消与背压](docs/zh-CN/ipc.md) · [IPC Channel](docs/zh-CN/channels.md) · [自定义协议](docs/zh-CN/protocols.md) · [菜单](docs/zh-CN/menus.md) · [托盘](docs/zh-CN/tray.md) · [对话框](docs/zh-CN/plugins-dialog.md) · [fs 插件](docs/zh-CN/plugins-fs.md) · [系统集成插件](docs/zh-CN/plugins-extensions.md) · [显示器与图像](docs/zh-CN/displays-images.md) · [WebView 策略](docs/zh-CN/webview-policies.md) · [路径与进程](docs/zh-CN/paths-process.md) |

## 目录结构

| 路径 | 内容 |
| --- | --- |
| `crates/bindings` | 原生边界：应用、窗口、IPC、事件、菜单、托盘、图像 |
| `crates/bridge` | 前端桥的构建期集成 |
| `python/pytaruix` | 公共 API、`ffi` 层与类型存根 |
| `frontend/bridge.js` | 前端 `pyInvoke` 入口 |
| `tests`、`scripts` | 行为测试与真实桌面验收场景 |
| `docs` | 阶段记录、能力矩阵与上游发现清单 |

## 许可证

尚未确定，当前不发布软件包。未复制 PyTauri 实现代码，参考来源见迁移契约。
