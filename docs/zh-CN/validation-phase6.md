# 第六阶段验证记录

验证日期：2026-10-01，Asia/Shanghai。范围为原生 IPC Channel、Pydantic 兼容形状、Webview 引用、流生命周期。
Windows 开发环境、独立安装包与源包重建完整验收通过。
历史结果见 [第五阶段](validation-phase5.md)、[第四阶段](validation-phase4.md)、[第三阶段](validation-phase3.md)。

## 环境与版本

Windows x86_64，真实 WebView2；Rust 1.97.1，最低 1.90；CPython 3.11.16 / 3.14.7，最低 Python 3.11。
启动前从 crates.io 重新核验 Tauri 2.12.1、tauri-build 2.7.1、PyO3 0.29.3 和 dialog 2.8.1，沿用最新稳定基线。
本地包 0.1.0a1，未提交、推送或发布。

## 执行结果

| 检查 | 结果 |
| --- | --- |
| Ruff check / format --check、Pyright、Rustfmt | 通过 |
| 开发环境 3.14 pytest | 102 通过、1 跳过 |
| 开发环境真实桌面回归 | 原有 24 个进程及新增 Channel 双窗口进程通过 |
| 全 feature Clippy / 无默认 feature、仅 wry 的 Clippy | 均通过 |
| 3.11 独立 wheel、测试与 25 个桌面进程 | 102 通过、1 权限跳过；25 个真实进程通过 |
| 3.14 源包重建 wheel、测试与 25 个桌面进程 | 102 通过、1 权限跳过；25 个真实进程通过 |
| 源包当前文件逐字节核验 | 112 个文件全部一致，解压绑定实际重新编译 |
| 核心账本 | 89 项：79 bound_tested、10 partial_tested |
| 核心发现清单 | 36 features / 1,260 候选，未改变 |
| dialog 独立账本 | 保持 37 项和既有平台限制 |

pytest 跳过项为当前 Windows 权限不允许创建测试符号链接，没有计为通过。
本阶段没有增加依赖、前端插件权限、远程能力或通配标签。

## 原生 Channel 证据

scripts/channel_smoke.py 启动真实双 WebView，使用当前宿主内置的官方 SDK Channel。
两版均通过 73 项联合检查及退出后资源清理；日志位于 artifacts/phase6-checks。
传输仍使用原生序号、JSON/Raw 和内部 fetch，未使用事件替代通道。
前端仅暂缓真实 fetch 请求，用于验证先到的终止帧/小消息等待大消息补齐，返回载荷未伪造。

- 模型进度、Unicode 字符串、null、bool、数字、嵌套 JSON、日志和原始负零文本；模型字段/根模型、新旧协议。
- 空/小/131072 字节 ArrayBuffer，JSON 8191/8192/8193 字节与字节 1023/1024/1025 的阈值两侧。
- 每窗 19 条串行混合数据、四个 Python 线程各 20 条消息，完整性、串行及每个生产者内部顺序。
- 命令返回后后台继续发送；未释放句柄的通道保持活跃，显式 close/重复 close/GC 正确结束前端回调。
- FFI 与类型化包装共享原生句柄；其中一个关闭后另一个 closed 为真，send 稳定拒绝。
- 无效标识/JSON/模型/载荷类型，关闭后无效载荷仍先返回 channel_closed；不承诺检查未知 JS 回调。
- 同编号 0 的缓存分别返回本窗口 owner，重复取回及无效/缺失请求头拒绝；dialog JS 请求继续拒绝。
- 另一个待拉取的大消息留在 secondary 原生缓存；销毁、同标签重建后拉取旧编号失败。
- 原始窗口/Webview/Channel 代次失效，应用退出后所有者清理；close 在退出后仍幂等。

既有 dynamic_window_smoke 回归核验未授权页面的新旧 IPC 拒绝。
既有 desktop/dynamic/event/dialog 脚本均串行运行，测试只操作自己创建的进程。

## 实现约束

通道资源登记持 Weak，不延长最后一个 Python 句柄寿命；关闭/销毁/退出取出原生句柄并在登记锁外释放。
原生 send、close、channel_on 释放 GIL，发送和关闭通过每个通道槽的 Mutex 协调。
IPC 入队前捕获来源 WindowState，工作线程不能在标签重建后重新取得新代次。
应用/窗口状态检查优先于显式通道关闭，原生操作前再次复核状态。
不增加 unsafe、不开放 Python 回调构造原生 Channel、不将回调错误转换成 panic。

上游内部 fetch 绕过普通 ACL，以调用 Webview 标签限定一次性队列。
队列插入检查原生注册状态，窗口关闭由原生清理；绑定另行检查原始窗口代次。
编号不代表授权或前端确认。close 只结束流，不取消业务任务、等待确认或提供背压。

## 可复现命令

```powershell
uv run --no-sync maturin develop --locked --jobs 1
uv run --no-sync ruff check python tests scripts examples
uv run --no-sync ruff format --check python tests scripts examples
uv run --no-sync pyright
uv run --no-sync pytest -q
cargo fmt --all --check
$env:PYO3_PYTHON = (Resolve-Path .venv/Scripts/python.exe).Path
cargo clippy --all-features --locked --jobs 1 -- -D warnings
cargo clippy --no-default-features --features wry --locked --jobs 1 -- -D warnings
uv run --no-sync python scripts/update_coverage.py --check
uv run --no-sync python scripts/channel_smoke.py
uv run --no-sync python scripts/desktop_smoke.py
uv run --no-sync python scripts/dynamic_window_smoke.py
uv run --no-sync python scripts/event_dispatch_smoke.py
uv run --no-sync python scripts/dialog_smoke.py
uv run --no-sync maturin build --locked --jobs 1 --interpreter artifacts/python311-venv/Scripts/python.exe --out dist/phase6
uv run --no-sync maturin sdist --out dist/phase6
uv run --no-sync python scripts/check_sdist.py dist/phase6/tauri_pyo3-0.1.0a1.tar.gz
uv run --no-sync python scripts/extract_sdist.py dist/phase6/tauri_pyo3-0.1.0a1.tar.gz artifacts/phase6-source
```

源包逐字节核验包含原生绑定、桥、Python、示例、脚本、测试与文档，排除 pyd/pdb/pyc。
解压重建刷新变更文件时间戳，避免固定归档时间让 Cargo 错用旧二进制。
本地产物位于 dist/phase6；3.11 安装于 artifacts/python311-venv，3.14 安装于 artifacts/wheel-venv，
两者均确认从独立 site-packages 加载包和原生扩展。
源包解压位置为 artifacts/phase6-source/tauri_pyo3-0.1.0a1；以该目录为 cwd 编译 3.14 wheel，
使用已安装的 3.14 wheel 运行解压包内的测试及五个桌面脚本。
Cargo 编译串行且 jobs=1，共享无关依赖缓存；日志确认新解压的 bridge/bindings 已重新编译。
最终文档重新归档、逐字节核验、解压，并再次打包当前内容及核验安装行为。

## 限制

仅 Windows 真实验收，Linux/macOS/移动平台需对应环境验证。
Channel 没有任意 Rust IpcResponse、Python 回调构造器、接收确认、自动背压、重连和业务任务取消。
同一 JS 编号应建立一个发送句柄，再共享 FFI/类型化包装；反复独立 channel_on 沿用上游独立序号流行为。
Webview 仅提供现有窗口引用、label/app_handle，没有独立/嵌入创建与完整管理器。
图像解码、监视器、菜单/托盘、其他插件及独立程序打包仍待后续阶段。
第五阶段 dialog 的 macOS 创建目录效果、消息图标/过滤排除外观和移动/结构化消息限制保持。
Python 宿主图标和 WebView2 偶发窗口类注销诊断仍可见，实际退出与资源清理通过。
项目名称和许可证待确定，本地 wheel/源包不发布。
