# 第十九阶段方案：插件骨架与 fs 样板

状态：2026-11-08 实现完成，桌面证据待补。
基线：Tauri 2.12.1、PyO3 0.29.3、`tauri-plugin-fs 2.6.0`（新增，本地锁定）。

## 1. 目标

打通「crate 依赖 → feature → init → Python 模块 → 能力报告 → 契约测试 → 文档」的插件链路，
并用 fs 作为第一个样板，使后续每个插件的成本可预估。

## 2. 前置发现与调整

- 上游 fs 的 Rust API 只有 `open` / `read` / `read_to_string`，且**不经过 capability scope**：
  `desktop.rs` 直接调用 `std::fs`。scope 只在前端命令层生效。
  因此本绑定不宣称"受限文件访问"——Python 侧本来就能用 `pathlib` 访问任意路径，
  再叠一层 scope 只是安全剧场。
- 顺带结论：目录遍历、删除、重命名在上游只存在于命令层。为了不把 `std::fs` 重写一遍，
  这些能力不绑定，文档明确指向 `pathlib`。
- 上游 `tauri-plugin-fs` 声明 `tauri` 时已 `default-features = false`，不会重新启用被裁剪的默认能力。
- 上游 `tauri_plugin_fs::init()` 返回 `TauriPlugin<R, Option<Config>>`，与 dialog 的 `TauriPlugin<R>` 类型不同。
  插件描述符改为保存"装载闭包"，擦除 `Config`，避免为每个插件增加枚举分支。

## 3. 契约

- `Plugin` 内部为「名称 + `FnOnce(Builder) -> Builder`」；Python 侧形状不变（`name`、`consumed`）。
- `pytaurix.plugins.fs.init()` 返回描述符；未启用 `plugin-fs` 时抛 `BindingError`（`unsupported_capability`）。
- `Fs(handle)` 要求 `AppHandle`；未注册插件返回 `plugin_missing`，不让上游 `fs()` panic。
- `read_text`/`read_bytes`/`write_text`/`write_bytes`；路径接受 `str`/`Path`，只做类型归一。
- 读写失败为 `fs_failed`，附带 `io::ErrorKind`；不返回默认值或空内容。
- `get_runtime_info()` 增加 `fs_version` 与 `plugin.fs` 能力项。

## 4. 改动

| 位置 | 改动 |
| --- | --- |
| `crates/bindings/Cargo.toml` | 新增可选依赖与 `plugin-fs` feature |
| `crates/bindings/src/plugin.rs` | 描述符改为装载闭包，新增 `fs_init` |
| `crates/bindings/src/fs.rs` | `Fs` pyclass 与四个读写入口 |
| `crates/bindings/src/application.rs` | 插件消费改为应用装载闭包 |
| `crates/bindings/src/lib.rs` | 模块与可用性标志注册 |
| `python/pytaurix/plugins/fs/` | `init`、`Fs`、路径归一与文档 |
| `python/pytaurix/runtime.py` | 能力项与 `fs_version` |
| `python/pytaurix/_native.pyi` | 类型存根 |
| `tests/test_plugin_fs_contract.py` | 契约测试 |
| 文档 | `plugins-fs.md`、features、矩阵、迁移契约、README |

## 5. 不在范围

目录遍历/删除/重命名、watch、scope 动态增删、前端 ACL 调整、移动平台、
其它插件（single-instance、global-shortcut、notification、opener 等）。

## 6. 验收

1. Ruff、Ruff format、Pyright、pytest；Rustfmt 与默认/`plugin-fs`/最小 `wry` 三组 Clippy（`-D warnings`）。
2. 契约测试覆盖路径归一、类型拒绝、`Fs` 构造、能力报告一致性与缺 feature 的拒绝。
3. 无 feature 与有 feature 两种构建都可导入，导入不初始化 GUI。
4. Windows 真实读写场景待补；缺失时如实记录，不以前端命令层证据替代。

失败时移除依赖与 feature，恢复到仅 dialog 的插件集合；`Cargo.lock` 随之回退。
