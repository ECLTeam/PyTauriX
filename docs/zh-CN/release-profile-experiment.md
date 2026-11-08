# 第十一阶段 release 参数实验

日期：2026-11-07。范围：Windows x86_64、CPython 3.14.8、默认 features，同一源码与 `Cargo.lock`。
所有变体仅通过 `CARGO_PROFILE_RELEASE_*` 环境变量覆盖，未修改 `Cargo.toml`；构建统一 `--release --locked --jobs 1`。

## 1. 结果

| 变体 | wheel 字节 | MiB | 相对基线 | 原生解压 | 包目录 | 构建耗时 |
| --- | --- | --- | --- | --- | --- | --- |
| 基线（thin LTO / opt3 / cgu16） | 4,736,316 | 4.516 | — | 14,943,232 | 15,177,079 | 170.3 s |
| `strip=symbols` | 4,738,756 | 4.519 | +2,440（+0.05%） | 14,944,256 | 15,178,055 | 396.2 s |
| `opt-level=s` | 3,572,701 | 3.407 | −1,163,615（−24.57%） | 10,895,872 | 11,129,671 | 257.4 s |
| `codegen-units=1` | 4,436,257 | 4.230 | −300,059（−6.34%） | 13,699,584 | 13,933,367 | 293.3 s |
| `lto=fat` + `cgu=1` | 4,286,954 | 4.088 | −449,362（−9.49%） | 13,146,112 | 13,380,023 | 306.5 s |
| `opt-level=s` + `cgu=1` | 3,412,398 | 3.254 | −1,323,918（−27.95%） | 10,143,744 | 10,377,623 | 196.1 s |
| 组合候选（`opt=s`+`cgu=1`+`fat`+`strip`） | 3,365,204 | 3.209 | −1,371,112（−28.95%） | 9,837,056 | 10,070,919 | 259.8 s |

每个变体在独立 venv 安装后，`import pytaurix` 与 `context_factory(examples/minimal)` 各采样 20 次（预热 1 次）：

| 变体 | 导入 P50 / P95 | Context P50 / P95 |
| --- | --- | --- |
| 基线 | 0.1389 / 0.1420 | 0.1411 / 0.1476 |
| `strip` | 0.1398 / 0.1425 | 0.1406 / 0.1441 |
| `opt-s` | 0.1421 / 0.1592 | 0.1519 / 0.1651 |
| `cgu1` | 0.1414 / 0.1592 | 0.1507 / 0.1920 |
| `fat`+`cgu1` | 0.1438 / 0.1585 | 0.1439 / 0.1767 |
| `opt-s`+`cgu1` | 0.1396 / 0.1438 | 0.1437 / 0.1579 |
| 组合候选 | 0.1394 / 0.1480 | 0.1428 / 0.1497 |

真实 WebView IPC 基准（`examples/performance`，1000 次小 JSON + 500 次 Pydantic + 500 次 50 并发；基线与候选各 5 批）：

| 变体 | 小 JSON P50 / P95 | Pydantic P50 | 并发吞吐中位数 | 错误后恢复 |
| --- | --- | --- | --- | --- |
| 基线 | 0.9 / 1.2 ms | 0.9 ms | 4,888 次/秒 | 5/5 |
| `opt-s`+`cgu1` | 0.8 / 1.2 ms | 0.9 ms | 5,010 次/秒 | 5/5 |

并发原始值基线为 4,082–5,376 次/秒、候选为 4,322–5,453 次/秒，区间重叠；误差受 `performance.now` 0.1 ms 分辨率与调度影响。

## 2. 结论

- `strip=symbols` 无收益：release 原生模块没有调试段，单独剥离后归档反而增加 2.4 KB（压缩噪声）。不作为候选。
- 单项最大收益来自 `opt-level="s"`：wheel 减少 1.16 MB（24.57%），原生减少约 4.05 MB。
- `codegen-units=1` 单独减少 6.34%，与 `opt-level="s"` 组合后减少 27.95%；导入与 Context P50 与基线持平，构建耗时 196 s（基线 170 s）。
- 再加 `fat LTO` 与 `strip` 只多减少 47 KB（1.4%），构建增至 260 s；`strip` 本身无贡献，收益来自 fat LTO，性价比低。
- 导入/Context 差异均在测量噪声内；真实 WebView 小 JSON、Pydantic 与 50 并发吞吐未见明确退化，命令内部 CPU 成本与大载荷未单独测量。

## 3. 推荐（已采用）

采用：`opt-level = "s"` + `codegen-units = 1`，保留 `lto = "thin"`，不启用 `strip`。
在默认能力集下 wheel 约 3.25 MiB，比当前 4.52 MiB 减少 28%；导入、Context 与 IPC 基准均未观察到明确退化，因此已写入根 `Cargo.toml` 的 `[profile.release]`。

`fat LTO` 只额外减少 1.4% 且增加约 33% 构建时间，不纳入默认配置；需要极限体积时可按环境变量临时启用。

## 4. 采用验证

根 `Cargo.toml` 已写入 `lto="thin"`、`opt-level="s"`、`codegen-units=1`。重新构建的默认 wheel 为 3,412,398 B（3.25 MiB），
原生解压 10,143,744 B，安装后包目录 10,377,575 B；增量构建约 97 s。
该 wheel 在独立 venv 中执行 `desktop_smoke.py` 与 `window_attributes_smoke.py`，均通过。

## 5. 证据

- `artifacts/phase11/experiments/release-params/<变体>/`：wheel、`report.json`（体积/安装/源码身份）、`benchmark.json`（20 样本原始值）。
- 组合候选已用独立 venv 执行 `desktop_smoke.py` 与 `window_attributes_smoke.py`，均通过；说明裁剪后桌面与窗口扩展能力未回归。
- 复现命令：

```powershell
$env:VIRTUAL_ENV = (Resolve-Path .venv).Path
$env:CARGO_PROFILE_RELEASE_OPT_LEVEL='s'
$env:CARGO_PROFILE_RELEASE_CODEGEN_UNITS='1'
.\.venv\Scripts\maturin.exe build --release --locked --jobs 1 --out artifacts\phase11\experiments\release-params\opt-s-cgu1
```

## 5. 未覆盖

- 大载荷（64 KiB / 1 MiB 二进制）、Channel 连续推送与长时间并发压力。
- 窗口可见与首次有效 IPC 耗时、冷缓存启动。
- Linux/macOS 与 Python 3.11 构建、安装和 GUI 行为。
