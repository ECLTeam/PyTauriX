<div align="center">

# PytaruiX

**用 Python 写桌面应用，底层是 Tauri 2**

[![CI](https://github.com/ECLTeam/PyTauriX/actions/workflows/ci.yml/badge.svg)](https://github.com/ECLTeam/PyTauriX/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pytaruix)](https://pypi.org/project/pytaruix/)
[![Python](https://img.shields.io/pypi/pyversions/pytaruix)](https://pypi.org/project/pytaruix/)
[![License](https://img.shields.io/pypi/l/pytaruix)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-blue)](#平台支持)

通过 PyO3 把 Tauri 2 的原生能力带到 Python：窗口、WebView、菜单、托盘和系统集成由 Rust
侧提供，业务逻辑用 Python 写，前端用 HTML 与 JavaScript 调用 Python 函数。
**不需要写一行 Rust**，拿到的是真正的原生窗口，而不是另一套 UI 框架。

[快速开始](#快速开始) · [特性](#特性) · [示例](examples) · [文档](#文档) · [CHANGELOG](CHANGELOG.md)

</div>

## 为什么选 PytaruiX

| | PytaruiX | 传统 Python GUI |
| --- | --- | --- |
| 渲染 | 系统 WebView（Chromium / WebKit） | 自绘控件或内嵌浏览器 |
| 外观 | 原生窗口、原生菜单、系统托盘 | 框架自绘 |
| 前端技术 | 任意：Vue / React / 原生 HTML | 框架专属组件体系 |
| 后端语言 | Python，可复用全部生态 | — |
| 安装体积 | 共享系统 WebView，无需打包浏览器 | 常需打包 Chromium（100MB+） |

## 特性

**命令与状态** — `@commands.command()` 一行注册，同步与 `async` 均可；参数由 Pydantic
校验，可注入来源窗口、请求头、应用句柄与共享状态。

**取消与流控** — 前端传 `AbortSignal`，Python 侧拿到 `Request` 句柄在检查点协作退出；
原生 Channel 支持 JSON 与二进制，按配额发送并等待前端归还。

**窗口** — 动态建窗、导航与新窗口策略回调、显示器信息、图像、混合 DPI 几何，
以及跨会话的位置与尺寸记忆。

**系统集成** — 菜单、托盘、对话框、单实例唤醒、全局热键、系统通知、默认程序打开。

**自定义协议** — 构建期注册 URI scheme，请求直接交给 Python 处理。

## 安装

**预编译 wheel（推荐）**——无需安装 Rust 或任何构建工具：

```bash
pip install --pre pytaruix
```

> [!NOTE]
> 当前为 alpha 预发布版本，pip 默认不安装预发布包，需加 `--pre`。
> 需要系统已装 WebView2（Windows 10/11 一般自带）。

**从源码构建**（备选，仅当需要修改绑定本身；需要 Rust 1.90+）：

```bash
git clone https://github.com/ECLTeam/PyTauriX
cd PyTauriX
uv sync --locked --no-install-project
uv run --no-sync maturin develop --locked --jobs 1
```

## 快速开始

`main.py`：

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

`frontend/index.html`：

```javascript
const greeting = await window.__TAURI__.pytaruix.pyInvoke("greet", { name: "World" });
```

克隆仓库后即可体验全部示例（双窗口、动态建窗、通道、菜单、托盘、对话框、宿主配置）：

```bash
uv run --no-sync python examples/minimal/main.py
```

## 平台支持

| 平台 | 状态 |
| --- | --- |
| Windows | ✅ 可用，通过真实桌面验收 |
| Linux | ⚠️ 构建通过，尚无运行验证 |
| macOS | ⚠️ 构建通过，尚无运行验证 |
| 移动端 | ❌ 未实现 |

当前版本基于 Tauri 2.12.1 与 PyO3 0.29.3。各领域的能力覆盖与限制见
[能力矩阵](docs/zh-CN/capability-matrix.md)。

## 文档

| 文档 | 内容 |
| --- | --- |
| [功能清单](docs/zh-CN/features.md) | 已绑定的接口 |
| [能力矩阵](docs/zh-CN/capability-matrix.md) | 覆盖范围、平台限制与缺口 |
| [迁移契约](docs/zh-CN/migration-contract.md) | 对外契约与不兼容变更 |
| [开发路线](docs/zh-CN/development-roadmap.md) | 里程碑与依赖 |
| [贡献指南](CONTRIBUTING.md) | 开发环境、提交规范与验证命令 |

## 反馈与贡献

遇到问题请提交 [Issue](https://github.com/ECLTeam/PyTauriX/issues)；
安全漏洞请参考 [安全策略](SECURITY.md) 私下报告。
欢迎按 [贡献指南](CONTRIBUTING.md) 参与开发。

## 许可证

[Apache-2.0](LICENSE)
