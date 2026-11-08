# 第二阶段验证记录

验证日期：2026-10-01，Asia/Shanghai。范围为核心生命周期、注入、旧协议、事件子集，不代表全量 Tauri API 完成。

## 环境与版本

- Windows x86_64，真实原生窗口与 WebView2。
- Rust 1.97.1；项目最低 Rust 1.90。
- CPython 3.11.16、3.14.7；项目最低 Python 3.11。
- Tauri 2.12.1、tauri-build 2.7.1、tauri-utils 2.10.1、PyO3 0.29.3。
- 本地调试包 0.1.0a1 / Rust crate 0.1.0-alpha.1；未提交、推送或发布。

## 已执行结果

| 验证 | 结果 |
| --- | --- |
| Ruff check / format --check | 通过 |
| Pyright | 0 错误、0 警告 |
| Python 3.11 已安装 wheel 的 pytest | 29 通过、1 跳过 |
| Python 3.14 从 sdist 重建并安装 wheel 的 pytest | 29 通过、1 跳过 |
| cargo fmt --all --check | 通过 |
| cargo clippy --all-features --locked --jobs 1 -- -D warnings | 通过，Windows 全 feature 组合 |
| 上游发现清单 | 36 个 feature 映射、1,260 条公开声明候选，与锁定源码一致 |
| 人工审核 API 账本 | 24 项：15 项绑定并验证、7 项部分绑定并验证、2 项仅绑定未直接验收 |
| Python 3.11 / 3.14 wheel 构建与安装 | 通过，确认从独立虚拟环境 site-packages 加载 |
| 源包文件核验及从解压源重建 3.14 wheel | 通过，包含桥接 crate/脚本、原生配置/图标、文档、测试与两个示例 |
| 两个 Python 版本真实桌面验收 | 通过，每个版本运行五个独立桌面进程 |

跳过项为资源链接逃逸测试：Windows 当前环境不允许创建测试符号链接；未计为通过。
原生焦点/关闭接口已有绑定，但没有直接行为验收，账本保留未验证状态。

## 真实桌面行为证据

`scripts/desktop_smoke.py` 每次运行五个独立进程，实际执行 WebView 内的 JavaScript：

1. 单窗口验证异步/Pydantic、后台线程、事件、异常/参数/未注册错误、失败后恢复和原生标题，共八项。
2. Ready 回调故意抛异常，事件循环退出后捕获原异常，输出 CALLBACK_RECOVERED。
3. 双窗口各自回传十八项：真实来源、新旧入口请求头、setup 初始化、共享状态、旧无正文/标量/全局入口、ArrayBuffer 与 Uint8Array 原始字节往返、旧错误字符串、无效编码、未注册命令、拒绝覆盖注入参数、失败后恢复、原生监听/一次监听、定向事件隔离、前端已注销监听和活跃监听再次注销。
4. setup 故意失败，Python 捕获原 ValueError，输出 FAILURE_RECOVERED setup。
5. 原生事件监听故意失败，Python 捕获原 LookupError，输出 FAILURE_RECOVERED listener。

双窗口进程同时核验 BUILD_HANDLE_OK、SETUP_OK、EXIT_PREVENTED、EXIT_API_EXPIRED_OK、EXIT_ALLOWED。
后两类失败以及正常退出均核验 RESOURCES_RELEASED_OK，通过弱引用确认共享对象和监听回调释放；已关闭句柄拒绝资源操作。
第一阶段的重复 App 运行与第二次原生 build 分别核验 app_consumed / runtime_consumed。
另有独立子进程测试主线程所有权、工作线程拒绝 run_return/handle、重复状态注册、None 状态拒绝，以及未运行 App 析构清理。
所有桌面验收进程以 0 退出，脚本输出 DESKTOP_SMOKE_PASSED。

旧客户端测试采用按参考源码契约编写的独立前端函数，直接调用 plugin:pytauri|pyfunc；没有安装原 npm 包作为测试依赖。

## 验证发现与修复

- 保留第一阶段的官方全局脚本加载顺序、源包桥接 include 和可选 Specta std 支持修复。
- build 即创建原生应用，但配置窗口与 setup 在上游 Ready 执行；采用线程局部所有权保存非 Send 应用，释放 GIL 时不跨线程移动原生 App。
- 第一个页面可在第二窗口构建和 setup 之前调用 Python：命令工作线程等待初始化完成，不持有 GIL 或占用 GUI 线程。
- 旧客户端省略正文被 Tauri 默认参数转为空对象：旧入口把该情况识别为无正文。
- 原生退出控制保存后可能调用上游失效通道：回调结束主动使 API 失效，后续调用返回 request_expired。
- 回调与状态可能被原生监听器引用保留：退出和未运行析构路径显式注销/清空；一次监听移除自己的登记编号。
- 源包现在显式纳入示例、测试、文档和审核账本，解压后能够独立重建。

Windows Python 宿主仍可产生缺少 EXE 图标资源的诊断；配置窗口已有开发图标。WebView2 在退出时偶尔输出窗口类注销诊断；验收进程退出码与资源清理检查均正常。

## 可复现命令

```powershell
uv sync --locked --no-install-project
uv run --no-sync maturin develop --locked --jobs 1
uv run --no-sync ruff check python tests scripts examples
uv run --no-sync ruff format --check python tests scripts examples
uv run --no-sync pyright
uv run --no-sync pytest -q
cargo fmt --all --check
$env:PYO3_PYTHON = (Resolve-Path .venv/Scripts/python.exe).Path
cargo clippy --all-features --locked --jobs 1 -- -D warnings
uv run --no-sync python scripts/update_coverage.py --check
uv run --no-sync python scripts/desktop_smoke.py
uv run --no-sync maturin build --locked --jobs 1 --out dist/phase2
uv run --no-sync maturin sdist --out dist/phase2
```

本次产物位于 dist/phase2；3.14 wheel 来自 artifacts/phase2-source 内的源包重建。
测试使用仓库级默认 Wry 原生运行时，未启用所有 feature 的行为测试；Clippy 全 feature 检查仅证明该 Windows 构建组合通过。

## 尚未验证或实现

macOS/Linux、Android/iOS 尚未完成构建和真实窗口验收；不能用 Windows 结果替代。
完整窗口/WebView Builder 与回调、channel/取消、菜单/托盘、官方插件、完整 ACL/CSP/隔离仍待实现。
事件目标目前仅支持标签，监听为应用级；状态的内部并发同步由调用方负责。每进程一个原生应用。
项目名与许可证尚未确定，不发布软件包。
