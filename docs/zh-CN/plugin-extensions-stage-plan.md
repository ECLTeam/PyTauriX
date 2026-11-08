# 第二十阶段方案：系统集成插件

状态：2026-11-08 实现完成，真实桌面行为待补。
基线：Tauri 2.12.1、PyO3 0.29.3；新增 single-instance 2.3.2、global-shortcut 2.3.0、
notification 2.3.0、opener 2.5.0（均锁定，本地 `Cargo.lock` 解析）。

## 1. 目标

补齐 Python 侧无法自行实现的能力：进程级单实例、系统级热键、系统通知、调用默认程序。
四个插件各自独立 feature，默认 wheel 不变。

## 2. 契约

| 插件 | Python 入口 | 关键约束 |
| --- | --- | --- |
| single-instance | `init(handler)` | 回调 `(AppHandle, argv, cwd)`；须尽早登记 |
| global-shortcut | `init()` + `GlobalShortcut(handle)` | 只在按下回调；非法文本 `shortcut_failed`；重复注册由上游拒绝 |
| notification | `init()` + `Notification(handle)` | `send()` 只表示上游提交；桌面权限通常恒为 granted |
| opener | `init()` + `Opener(handle)` | 三个入口都不确认外部程序已启动 |

共同点：

- `init()` 不初始化 GUI；未启用 feature 抛 `unsupported_capability`。
- 包装类要求 `AppHandle`；未注册插件返回 `plugin_missing`，避免上游 `state()` panic。
- 回调异常沿用同步回调语义：记录并退出应用，由 `run_return` 重抛。
- 能力报告随构建出现在 `get_runtime_info().capabilities`。

## 3. 关键调整

- **构建器登记顺序**：single-instance 要求自身尽量靠前，用户插件改为在桥接插件之前登记。
  桥接脚本由构建期注入、`pytauri` 只注册 `pyfunc` 处理器，位置调整不影响既有行为。
- **并发编译**：同时启用多个插件时，某些 Windows 依赖在并行 codegen 下会触发 rustc
  `STATUS_STACK_BUFFER_OVERRUN`；构建需限制为单作业（`CARGO_BUILD_JOBS=1`）。
  该限制写在指南中，不改变仓库默认构建命令。

## 4. 改动

| 位置 | 改动 |
| --- | --- |
| `crates/bindings/Cargo.toml` | 四个可选依赖与 feature |
| `crates/bindings/src/plugin.rs` | 四个 init 入口 |
| `crates/bindings/src/single_instance.rs` | 回调桥接 |
| `crates/bindings/src/global_shortcut.rs` | 注册/注销/查询与按下事件桥接 |
| `crates/bindings/src/notification.rs` | 权限状态与发送 |
| `crates/bindings/src/opener.rs` | URL/路径打开与定位 |
| `crates/bindings/src/application.rs` | 用户插件先于桥接插件登记 |
| `python/pytaruix/plugins/*/` | 四个 Python 模块 |
| `python/pytaruix/{_native.pyi,runtime.py}` | 类型与能力报告 |
| `tests/test_plugin_extensions_contract.py` | 契约测试 |
| 文档 | `plugins-extensions.md`、features、矩阵、迁移契约、README |

## 5. 不在范围

移动平台、插件间依赖（如 single-instance 的 deep-link 集成）、通知图标与操作按钮、
快捷键方案持久化、真实系统行为验收。

## 6. 验收

1. Ruff、Ruff format、Pyright、pytest；Rustfmt 与默认/全插件/最小 `wry` 三组 Clippy（`-D warnings`）。
2. 契约测试覆盖可用性标志、能力报告、缺 feature 拒绝、参数校验与包装类类型检查。
3. 无 feature 与有 feature 两种构建均可导入，导入不初始化 GUI。
4. 第二实例唤醒、热键冲突、通知显示与默认程序启动的真实证据待补，缺失时如实记录。

失败时移除对应依赖与 feature；`Cargo.lock` 随之回退，不影响已完成的前序阶段。
