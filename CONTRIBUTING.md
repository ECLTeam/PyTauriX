# 贡献指南

PyTauriX 是独立实现的 Tauri Python 绑定。为避免返工，提交代码前请先阅读
[AGENTS.md](AGENTS.md)——那是本仓库的规范入口，包含变更流程、Python/Rust 约定、
线程与资源边界以及完整的验证命令表。本文件只说明外部贡献者需要知道的部分。

## 开发环境

需要 Python 3.11+、Rust 1.90+（CI 使用 1.97.1）与平台对应的 Tauri 系统依赖。
Windows 另需 MSVC 构建工具与 WebView2。

```powershell
uv sync --locked --no-install-project
uv run --no-sync maturin develop --locked --jobs 1
uv run --no-sync python examples/minimal/main.py
```

Rust 构建统一使用 `--jobs 1`，并行 codegen 在部分依赖组合下会失败。

## 变更流程

1. 先开 Issue 说明目标、使用场景、影响平台与可观察的验收标准。
2. 涉及公开契约、依赖、features 或构建行为的改动，先给出方案再实施。
3. 一次提交只做一件事；行为变更附带能复现原缺陷的测试。
4. PR 描述里写清改动范围、验证结果和未覆盖的部分。

不提供其他框架的兼容层。不要把「顺手兼容 PyTauri」当作理由新增别名或垫片。

## 提交信息

使用 [Conventional Commits](https://www.conventionalcommits.org/)，描述用中文：

```
feat: 支持命令协作式取消
fix: 修正配置窗口缺失本地授权
docs: 补齐 fs 插件指南
chore: 升级 tauri-plugin-fs 到 2.6.0
```

正文说明「为什么」而不是「改了什么」。不兼容变更用 `!` 标记，并在正文列出消费方与迁移方法。

## 提交前检查

按改动范围选择最小充分集合，完整命令见 [AGENTS.md](AGENTS.md) 第 8.2 节。

```powershell
uv run --no-sync ruff check python tests scripts examples
uv run --no-sync ruff format --check python tests scripts examples
uv run --no-sync pyright
uv run --no-sync pytest -q
cargo fmt --all --check
cargo clippy --locked --jobs 1 -- -D warnings
uv run --no-sync python scripts/update_coverage.py --check
```

涉及真实窗口、系统集成或平台行为时，说明是否跑过桌面场景；没跑就说没跑，
不要把契约测试当成桌面证据。

## 代码风格

- Python：3.11+、行宽 120、双引号；公开接口写中文 docstring，注明参数、返回、异常与线程约束。
- Rust：rustfmt 默认配置；可恢复路径避免 `unwrap`/`expect`；新增 `unsafe` 需说明安全不变量。
- 跨语言边界：输入在校验后才进入内部；错误使用稳定错误码，不用空值掩盖失败。

## 文档

公开行为变化要同步更新对应指南、`docs/zh-CN/migration-contract.md` 与能力矩阵。
文档用中文，标识符、命令和外部术语保留原文。

## 许可证

提交即表示同意以 [Apache-2.0](LICENSE) 授权你的贡献。
