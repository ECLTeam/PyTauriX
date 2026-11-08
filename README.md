# PytaruiX

用 Python 写桌面应用，底层是 Tauri。

PytaruiX 通过 PyO3 把 Tauri 2 的原生能力带到 Python：窗口、WebView、菜单、托盘和系统集成
由 Rust 侧提供，业务逻辑用 Python 写，前端用 HTML 与 JavaScript 调用 Python 函数。
不需要写 Rust，拿到的是真正的原生窗口，而不是另一套 UI 框架。

## 特性

**命令**

`@commands.command()` 装饰器即可注册命令，同步与 `async` 都支持。参数由 Pydantic 校验，
可以注入来源窗口、请求头、应用句柄与共享状态。

**取消与流控**

前端传 `AbortSignal`，Python 侧拿到 `Request` 句柄，在检查点协作退出。
原生 Channel 支持 JSON 与二进制，可按配额发送并等待前端归还。

**窗口**

动态建窗、导航与新窗口策略回调、显示器信息、图像、混合 DPI 几何，以及跨会话的位置与尺寸记忆。

**系统集成**

菜单、托盘、对话框，以及单实例唤醒、全局热键、系统通知、默认程序打开。

**协议**

构建期注册 URI scheme，请求交给 Python 处理。

## 安装

需要 Python 3.11+、Rust 1.90+，以及对应平台的 Tauri 系统依赖
（Windows 为 MSVC 构建工具与 WebView2）。

```powershell
uv sync --locked --no-install-project
uv run --no-sync maturin develop --locked --jobs 1
```

## 快速开始

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

```javascript
const greeting = await window.__TAURI__.pytaruix.pyInvoke("greet", { name: "World" });
```

更多示例见 [`examples/`](examples)：双窗口、动态建窗、通道、菜单、托盘、对话框、宿主配置。

## 平台

| 平台 | 状态 |
| --- | --- |
| Windows | 可用，通过真实桌面验收 |
| Linux / macOS | 构建通过，尚无运行验证 |
| 移动端 | 未实现 |

当前版本 `0.1.0a1`，基于 Tauri 2.12.1 与 PyO3 0.29.3。各领域的能力覆盖与限制见
[能力矩阵](docs/zh-CN/capability-matrix.md)。

## 文档

| 文档 | 内容 |
| --- | --- |
| [功能清单](docs/zh-CN/features.md) | 已绑定的接口 |
| [能力矩阵](docs/zh-CN/capability-matrix.md) | 覆盖范围、平台限制与缺口 |
| [迁移契约](docs/zh-CN/migration-contract.md) | 对外契约与不兼容变更 |
| [开发路线](docs/zh-CN/development-roadmap.md) | 里程碑与依赖 |
| [贡献指南](CONTRIBUTING.md) | 开发环境、提交规范与验证命令 |

## 许可证

[Apache-2.0](LICENSE)
