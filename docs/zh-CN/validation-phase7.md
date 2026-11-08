# 第七阶段验证记录

验证日期：2026-10-01，Asia/Shanghai。范围：显示器/DPI、物理矩形、图像加载及格式开关。
Windows 开发环境、独立 wheel 与实际源包重建验收；历史见 [第六阶段](validation-phase6.md)。

## 环境与执行结果

Windows x86_64、真实 WebView2；Rust 1.97.1，最低 1.90；CPython 3.11.16 / 3.14.7，最低 Python 3.11。
阶段开始从 crates.io 重新核验 Tauri 2.12.1、tauri-build 2.7.1、tauri-utils 2.10.1、PyO3 0.29.3 和 dialog 2.8.1，沿用最新稳定基线。
本地包 0.1.0a1，未提交、推送或发布。

| 检查 | 结果 |
| --- | --- |
| Ruff check/format、Pyright、Rustfmt | 通过 |
| 开发环境 / 3.11 wheel / 3.14 源包重建 wheel 的 pytest | 各 113 通过、1 跳过 |
| 每版六个桌面脚本 | 26 个成功进程：desktop 5、dynamic 6、event 5、dialog 8、channel 1、display/image 1 |
| 全 feature / 无默认 feature、仅 wry 的 Clippy | 均通过 |
| 图像全关 / 仅 PNG / 仅 ICO / 两者开启 | 四个 wheel 实际构建、独立安装，各通过 11 项契约测试 |
| 源包 | 逐字节核验 129 个当前文件；解压路径下绑定实际重新编译 |
| 核心人工审核账本 | 100 项：90 bound_tested、10 partial_tested |
| 核心发现 / dialog 账本 | 保持 36 features / 1,260 候选；dialog 独立账本 37 项 |

跳过为 Windows 权限无法创建测试符号链接，不计为通过。GUI 串行运行，日志在 artifacts/phase7-checks。
开发环境初轮焦点状态曾失败，串行回归通过；前台焦点仍受桌面环境影响。
清理验收曾抢在异步建窗命令/异常帧释放前检查弱引用；现等待建窗结束，并在关闭 portal 后核对最终引用。
没有修改原生焦点契约，也不强制取消业务任务。

## 显示器与图标证据

scripts/display_image_smoke.py 通过真实 IPC 工作线程执行四种查询，独立使用 Win32 EnumDisplayMonitors、
GetMonitorInfo、GetDpiForMonitor、MonitorFromWindow、GetDpiForWindow 对照。
当前一个 DISPLAY1，物理尺寸 1600×900，位置 (0, 0)，工作区 1600×900，缩放 1.0。
环境无任务栏占用工作区；工作区差异、多屏/负屏幕位置、混合 DPI、热插拔未验收。

每版 30 项联合检查，以及退出后四种查询的 app_closed 检查：

- 主屏/所在屏/枚举、Monitor 五项只读属性、工作区中心点和所有屏幕之外的 None。
- 独立工作线程、同步 GUI 回调拒绝、非有限坐标和错误类型。
- 逻辑/物理尺寸及位置换算、关闭与同标签重建、旧句柄拒绝、旧快照保留可读值。
- 窗口构建 icon 与 set_icon，读取 WM_GETICON 小图标和 GetIconInfo/GetDIBits。
  两张 32×32 不透明图标的全部 4,096 字节 RGBA 分别与解码结果一致。

Win32 本进程窗口标题/图标读取在 GUI 线程完成，避免工具跨线程重入 Python 窗口回调。
不释放借用 HICON，明确释放 GetIconInfo 位图与 GDI DC。
任务栏大图标、透明度合成、Linux/macOS 外观效果没有计为验收。

PNG 与 DIB ICO 的 2×2 样本逐像素核对 RGBA 和 alpha 255/128/0/64，bytes/Path 加载一致。
16 次工作线程文件加载、中文文件名/不同扩展名、缺失文件/目录、截断数据、不支持格式和错误类型均覆盖。
有效 BMP 输入明确拒绝；ICO 的传递 BMP 解码能力没有扩大外部容器支持。

## Feature 与体积

默认新增 image-png/image-ico，Cargo.lock 与第六阶段源包逐字节一致。
新默认激活 image 0.25.10 及 PNG/ICO 解码链，没有 Pillow、fs 注册或额外前端权限。
上游 ICO 间接启用 PNG/BMP，因此外部容器按显式 feature 检查；PNG 关闭时独立 PNG 返回 feature_unavailable。
文件只读取一次，检查后使用 Tauri 原生解码，避免二次读取的替换竞态。
全关仍可导入根包、类型及构造 RGBA；所需格式关闭明确拒绝，全关的 Path 调用不读文件。
无默认 feature 同时关闭 dialog/dynamic-acl，其他能力须按需添加；image_formats 仅描述图像容器。

本机根目录 dev profile 初次构建的压缩 wheel：3.11 为 7,176,278 字节，比第六阶段增加 372,430 字节，约 5.47%；
3.14 为 7,155,737 字节，增加 367,596 字节，约 5.42%。
此为当前构建观察值，不代表 release/LTO 或其他平台的最终体积；源包重建的调试路径可能造成小幅差异。

## 复现与交付

```powershell
uv run --no-sync maturin develop --locked --jobs 1
uv run --no-sync ruff check
uv run --no-sync ruff format --check
uv run --no-sync pyright
uv run --no-sync pytest -q
cargo fmt --all --check
$env:PYO3_PYTHON = (Resolve-Path .venv/Scripts/python.exe).Path
cargo clippy --all-features --locked --jobs 1 -- -D warnings
cargo clippy --no-default-features --features wry --locked --jobs 1 -- -D warnings
uv run --no-sync python scripts/update_coverage.py --check
uv run --no-sync python scripts/display_image_smoke.py
uv run --no-sync maturin build --locked --jobs 1 --interpreter artifacts/python311-venv/Scripts/python.exe --out dist/phase7
uv run --no-sync maturin sdist --out dist/phase7
uv run --no-sync python scripts/check_sdist.py dist/phase7/tauri_pyo3-0.1.0a1.tar.gz
uv run --no-sync python scripts/extract_sdist.py dist/phase7/tauri_pyo3-0.1.0a1.tar.gz artifacts/phase7-source
```

3.14 在 artifacts/phase7-source/tauri_pyo3-0.1.0a1 下实际执行 maturin build，复用 target 中无关依赖。
解压刷新变化文件时间戳；编译日志确认绑定来自解压路径，不以旧二进制或目录存在替代重建证据。
独立环境为 artifacts/python311-venv / artifacts/wheel-venv，确认包和原生扩展均来自独立 site-packages。
样本、指南、迁移契约、矩阵与账本纳入源包，参考 PyTauri/ECL 仓库没有修改。

原生 Tauri 在 Python EXE 中查询默认图标资源会输出资源缺失诊断，宿主随后提供 RGBA 默认图标，实际图标验收通过。
菜单/托盘、Windows EXE 图标资源、移动平台和独立程序发布不在本阶段范围；Linux/macOS 与多屏/混合 DPI 待另外验证。
