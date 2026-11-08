# PytaruiX

用 Python 写 Tauri 桌面应用。

PytaruiX 是独立实现的 Tauri 2 Python 绑定：Rust 侧通过 PyO3 暴露原生能力，Python 侧提供
命令、事件、窗口、菜单等 API，前端用注入的桥调用 Python 函数。你写 Python，得到的是真正的
原生窗口和系统集成，而不是另起一套 UI 框架。

它不是 PyTauri 的分支、也不提供 PyTauri 兼容层——没有 `pytauri` 导入路径，没有旧版前端协议。
API 由本项目自行定义与维护。

## 特性

- **命令即函数**：`@commands.command()` 装饰器，支持同步与 `async`，参数由 Pydantic 校验，
  可注入来源窗口、请求头、应用句柄与共享状态。
- **可取消的调用**：前端传 `AbortSignal`，Python 侧拿到 `Request` 句柄，在检查点协作退出。
- **流控通道**：原生 IPC Channel 支持 JSON 与二进制，可按配额发送并等待前端归还。
- **事件与线程**：窗口级与全局事件、定向发送、主线程调度，GUI 始终在 Python 主线程。
- **窗口与 WebView**：动态建窗、导航与新窗口策略回调、显示器与图像、混合 DPI 几何。
- **系统集成**：菜单、托盘、对话框，以及单实例唤醒、全局热键、系统通知、默认程序打开、
  窗口状态记忆。
- **自定义协议**：构建期注册 URI scheme，由 Python 处理请求。
- **官方插件**：dialog、fs、single-instance、global-shortcut、notification、opener、window-state，
  各自独立 feature，默认包不引入。

## 安装

需要 Python 3.11+、Rust 1.90+ 与对应平台的 Tauri 系统依赖（Windows 为 MSVC 构建工具与 WebView2）。

```powershell
uv sync --locked --no-install-project
uv run --no-sync maturin develop --locked --jobs 1
```

## 最小示例

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

前端调用：

```javascript
const greeting = await window.__TAURI__.pytaruix.pyInvoke("greet", { name: "World" });
```

完整示例见 [`examples/`](examples)：最小应用、双窗口、动态建窗、通道、菜单、托盘、对话框、
宿主配置与桌面验收。

## 平台与状态

预发布 `0.1.0a1`，基线 Tauri 2.12.1 + PyO3 0.29.3。

| 平台 | 状态 |
| --- | --- |
| Windows | 已通过真实桌面验收 |
| Linux / macOS | 有构建工作流，尚无运行证据 |
| 移动端 | 未实现 |

各领域的能力覆盖与缺口见[能力矩阵](docs/zh-CN/capability-matrix.md)。

## 文档

- [功能清单](docs/zh-CN/features.md) — 已绑定的接口
- [能力矩阵](docs/zh-CN/capability-matrix.md) — 覆盖范围、平台限制与缺口
- [迁移契约](docs/zh-CN/migration-contract.md) — 对外契约与不兼容变更
- [开发路线](docs/zh-CN/development-roadmap.md) — 里程碑与依赖

参与开发前先读 [AGENTS.md](AGENTS.md)，其中包含工程规范、验证命令与提交约定。

## 许可证

[Apache-2.0](LICENSE)。本项目为独立实现，未复制 PyTauri 的代码。
