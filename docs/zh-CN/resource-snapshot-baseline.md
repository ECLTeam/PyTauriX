# 资源快照规模基线：Context 准备的时间与内存曲线

日期：2026-11-09。状态：测量完成，结论为**维持启动快照方案**；懒加载作为超大规模宿主的候选，未有消费方需求前不实施。
范围仅为 Windows x86_64、CPython 3.14.8、editable 安装的本地结果，冷 OS 文件缓存未测量。

## 1. 背景

Context 创建期间把 `frontendDist` 目录读取为 `DirectoryAssets`（`BTreeMap<String, Vec<u8>>`）内存快照。
[开发路线](development-roadmap.md)第 2 节要求测量目录规模、耗时与内存后再选择资源方案。
本轮补充规模曲线与单请求成本，回答两个问题：现有方案在真实宿主规模下是否构成瓶颈；
懒加载在什么规模才值得引入一致性与路径校验的额外复杂度。

## 2. 方法

`scripts/measure_resource_snapshot.py` 生成合成前端目录（`tauri.conf.json` + `frontendDist: "."`），
每个样本在独立子进程以单调时钟测量 `context_factory` 墙钟时间，并经 `GetProcessMemoryInfo`
采集调用前后工作集与提交内存增量；Context 在采样结束前持有，避免提前释放。
每档预热即采样，5 个样本取 P50/P95 与中位数；热 OS 文件缓存。

单请求成本另以 Python `Path.read_bytes` 与 `Path.resolve` 各 500 次取中位数，估算懒加载每次请求的下限。

## 3. 规模曲线（5 样本，热缓存）

| 档位 | 文件数 | 总字节 | context P50 | context P95 | 提交内存 Δ | 工作集 Δ |
| --- | --- | --- | --- | --- | --- | --- |
| xs | 4 | 8 KiB | 3.3 ms | 3.4 ms | 0.3 MiB | 3.2 MiB |
| s（ECL 形状） | 92 | 6 MiB | 11.4 ms | 12.8 ms | 4.7 MiB | 7.6 MiB |
| m | 500 | 30 MiB | 44.7 ms | 46.7 ms | 23.4 MiB | 26.2 MiB |
| l | 2000 | 120 MiB | 171 ms | 179 ms | 93.7 MiB | 96.3 MiB |
| xl | 5000 | 300 MiB | 415 ms | 447 ms | 234 MiB | 237 MiB |

线性拟合约 **1.35 ms/MiB** 起步，300 MiB 处升至约 1.38 ms/MiB；提交内存增量约为目录字节的 0.75–0.80 倍
（分配器页复用），工作集增量略高于提交。xs 档的工作集增量（3.2 MiB）是导入后首次触页的基线噪声，不代表资源成本。

当前主要消费方 ECL 的真实前端为 **92 个文件、6.0 MiB**：快照约 11 ms、常驻约 5 MiB——与 11 阶段
`examples/minimal` 的测量噪声结论一致，远低于可观察阈值。

## 4. 懒加载单请求成本估算

| 操作 | 中位数 |
| --- | --- |
| 读取 69 KiB 单文件 | 0.025 ms |
| 读取 98 KiB 单文件 | 0.026 ms |
| `Path.resolve`（路径校验所需） | 0.044 ms |

每次请求约 0.07–0.1 ms（热缓存，Python 侧下限；Rust 实现同数量级）。逐请求成本可忽略，
懒加载的收益只在**启动时间与常驻内存**：120 MiB 以上目录可省约 170 ms 启动与 100 MiB 常驻。

## 5. 结论与决策

1. **维持启动快照方案**。≤30 MiB 前端的成本（≤45 ms、≤24 MiB）不构成瓶颈；快照同时提供
   内容一致性（请求期间文件变动不影响已启动应用）、无逐请求路径校验和 O(1) 查找。
2. **懒加载列为待需求候选**，触发条件写成预算：前端目录 ≥100 MiB 或启动时间超出宿主预算时，
   另写方案并验收（需覆盖内容一致性、缓存失效、并发读取、符号链接拒绝与发行更新语义，见 AGENTS.md 5.2）。
3. 文档新增规模预算表，供宿主开发时对照；不预先承诺对外性能指标。

## 6. 复现

```powershell
# xs/s/m/l 一组报告
.venv\Scripts\python.exe scripts\measure_resource_snapshot.py --out artifacts\resource-snapshot\report.json --samples 5 --scales xs,s,m,l
# xl 单独报告
.venv\Scripts\python.exe scripts\measure_resource_snapshot.py --out artifacts\resource-snapshot\report-xl.json --samples 5 --scales xl
```

## 7. 原始证据

- `artifacts/resource-snapshot/report.json`（xs/s/m/l 原始样本与统计）
- `artifacts/resource-snapshot/report-xl.json`（xl 原始样本）
- `artifacts/resource-snapshot/frontend-*/`（合成前端目录，未跟踪）
