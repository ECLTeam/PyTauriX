# 第十一阶段基线：体积、导入与 Context 准备

日期：2026-11-07。状态：基线已采集；feature 边界修正与 release 参数实验待确认后执行。
范围仅为 Windows x86_64、CPython 3.14.8 的本机结果，不代表 Linux/macOS 或 Python 3.11 结论。

## 1. 环境与身份

| 项目 | 值 |
| --- | --- |
| 分支 | `codex/bootstrap`（尚无首次提交） |
| 源码身份 | 184 个文件清单及 SHA-256，见 `artifacts/phase11/baseline/reports/*.json` 的 `source` 字段 |
| Python | CPython 3.14.8 |
| Rust | rustc/cargo 1.99.0（本地；CI 固定 1.97.1） |
| maturin / uv | 1.15.0 / 0.13.1 |
| 锁文件 | `Cargo.lock`、`uv.lock` 未修改，构建使用 `--locked` |

原生模块以 editable 方式装入 `.venv`，release wheel 在独立目录构建，并在独立 venv 中安装核验。

## 2. 构建矩阵与耗时

| 组合 | 命令 | 编译耗时 |
| --- | --- | --- |
| 默认 | `maturin build --release --locked --jobs 1` | 6 分 02 秒 |
| 开发 | 追加 `--features devtools,tray-icon` | 2 分 52 秒（复用依赖） |
| 最小 | `--no-default-features --features wry` | 2 分 30 秒 |

三组均构建成功，产物位于 `artifacts/phase11/baseline/wheels/<组合>/`。

## 3. 体积

| 组合 | wheel 归档 | 原生扩展解压 | 安装后包目录 | 完整 site-packages |
| --- | --- | --- | --- | --- |
| 默认 | 4,825,808 B（4.60 MiB） | 15,131,136 B（14.43 MiB） | 15,353,972 B（14.64 MiB） | 27,025,766 B（25.77 MiB） |
| 开发 | 5,020,466 B（4.79 MiB） | 15,797,760 B（15.07 MiB） | 16,020,532 B（15.28 MiB） | 27,692,071 B（26.41 MiB） |
| 最小 | 4,444,339 B（4.24 MiB） | 14,121,984 B（13.47 MiB） | 14,344,820 B（13.68 MiB） | 25,994,121 B（24.79 MiB） |

wheel 共 32 个条目；默认组合中 `_native` 压缩后约 4.50 MiB，占归档体积绝大部分。
完整 site-packages 含 anyio、pydantic、pydantic-core、typing-extensions 等运行时依赖。

## 4. 导入与 Context 准备

每个场景预热 1 次、采样 20 个独立进程，单调时钟计墙钟时间；被测解释器为独立 venv 中的已安装 wheel。

| 场景 | 组合 | P50 | P95 |
| --- | --- | --- | --- |
| 解释器空启动 | 默认 | 0.0211 s | 0.0225 s |
| `import pytaurix` | 默认 | 0.1476 s | 0.1550 s |
| `get_runtime_info()` | 默认 | 0.1586 s | 0.1768 s |
| `context_factory(examples/minimal)` | 默认 | 0.1509 s | 0.1627 s |
| `import pytaurix` | 开发 | 0.1528 s | 0.1801 s |
| `context_factory(examples/minimal)` | 开发 | 0.1553 s | 0.1553 s |
| `import pytaurix` | 最小 | 0.1431 s | 0.1482 s |
| `context_factory(examples/minimal)` | 最小 | 0.1462 s | 0.1462 s |

导入相对空解释器增加约 126 ms；`context_factory` 与单独导入接近，说明示例规模（`examples/minimal`）的目录快照成本低于测量噪声。
这三组能力差异主要影响原生体积，导入耗时差异约 5–10 ms，不构成量级差别。

## 5. 已确认问题 11-01

最小组合仍启用 `tauri/default`（修复前）。`cargo tree --no-default-features --features wry -e features -i tauri` 显示：

```text
tauri feature "default"
└── pytaurix-bridge v0.1.0-alpha.1
    └── pytaurix-bridge feature "default"
```

`crates/bridge` 以 `tauri.workspace = true` 继承 workspace 依赖的默认 features，抵消了 bindings 的 `--no-default-features`。
修复后 workspace 统一 `default-features = false`，bridge 只显式启用 `wry`；bindings 默认改为显式 `wry`、`dynamic-acl` 与 dialog/图像组合，
Windows 目标保留 `common-controls-v6`，Linux 目标显式启用 `x11`、`dbus`。
修复后默认 wheel 为 4,720,547 B（4.50 MiB，较修复前减少 105,261 B），最小组合为 4,250,086 B（4.05 MiB，减少 194,253 B）；
`cargo tree` 已不再出现 `tauri feature "default"`。原始证据见 `artifacts/phase11/experiments/feature-boundary/`。
此后默认 release profile 采用 `opt-level="s"` + `codegen-units=1` + thin LTO，默认 wheel 进一步降至 3,412,398 B（3.25 MiB），
原生解压 10,143,744 B；详见 [release 参数实验](release-profile-experiment.md)。

## 6. 未覆盖项

- 窗口可见、首次有效 IPC、真实桌面交互耗时未采集：需要实际 GUI 会话与前端桥观测，当前脚本不覆盖。
- 冷缓存启动未测试；本结果仅为重复启动样本。
- 符号剥离、`opt-level`、`codegen-units`、LTO 组合未比较，留待 5.4。
- Linux/macOS 与 Python 3.11 未构建；CI 桌面任务需 self-hosted 交互式 Windows 会话。
- 本机源码目录中的 162 MiB `.pdb` 为调试符号，未计入上述体积；发行迁移方案需单独处理。

## 7. 复现

```powershell
# 构建
$env:VIRTUAL_ENV = (Resolve-Path .venv).Path
.\.venv\Scripts\maturin.exe build --release --locked --jobs 1 --out artifacts\phase11\baseline\wheels\default
.\.venv\Scripts\maturin.exe build --release --locked --jobs 1 --features devtools,tray-icon --out artifacts\phase11\baseline\wheels\dev
.\.venv\Scripts\maturin.exe build --release --locked --jobs 1 --no-default-features --features wry --out artifacts\phase11\baseline\wheels\minimal

# 体积与独立安装（uv 为外部工具路径）
python scripts/measure_distribution.py --label default --wheel <wheel> --out artifacts/phase11/baseline/reports/default.json --uv <uv.exe>

# 导入与 Context
python scripts/benchmark_runtime.py --label default --python <venv>/Scripts/python.exe --out artifacts/phase11/baseline/reports/benchmark-default.json --samples 20
```

## 8. 原始证据

- `artifacts/phase11/baseline/reports/default.json`、`dev.json`、`minimal.json`：源码清单、锁文件、工具链、wheel 条目与安装占用。
- `artifacts/phase11/baseline/reports/benchmark-{default,dev,minimal}.json`：20 个样本原始值与 P50/P95。
- `artifacts/phase11/baseline/reports/cargo-tree-{default,minimal}.txt`：tauri feature 来源。
- `artifacts/phase11/baseline/wheels/`：三组 release 产物。
