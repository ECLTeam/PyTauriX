# 第五阶段验证记录

验证日期：2026-10-01，Asia/Shanghai。范围为插件注册、dialog 桌面子集、回调/阻塞等待、关闭与权限。
开发环境、编译开关、双版本独立安装包及源包重建验收通过。
历史结果见 [第四阶段](validation-phase4.md)、[第三阶段](validation-phase3.md) 和 [第二阶段](validation-phase2.md)。

## 环境与版本

Windows x86_64，真实 WebView2、系统 COM 文件选择器/TaskDialog；Rust 1.97.1，最低 1.90；
CPython 3.11.16 / 3.14.7，最低 Python 3.11。
Tauri 2.12.1、tauri-build 2.7.1、tauri-utils 2.10.1、PyO3 0.29.3，dialog 独立锁定 2.8.1。
本地包 0.1.0a1，未提交、推送或发布。

## 执行结果

| 检查 | 结果 |
| --- | --- |
| Ruff check / format --check、Pyright | 通过；0 类型错误/警告 |
| 开发环境 3.14 pytest | 85 通过、1 跳过 |
| 3.11 独立 wheel pytest | 85 通过、1 跳过 |
| 3.11 独立环境桌面/对话框回归 | 24 个真实进程通过：原有 16 个及 dialog 8 个 |
| 3.14 源包重建、安装、pytest 及桌面回归 | 85 通过、1 跳过；24 个真实进程通过 |
| Rustfmt、全 feature Clippy | 通过，最终源码核验完成 |
| 禁用默认 feature、仅 wry 的 Clippy | 通过 |
| 禁用 dialog 的独立 wheel | 根导入、能力标记、插件 ImportError 及真实最小桌面 IPC 通过 |
| 核心账本和发现清单 | 84 项：75 验收、9 部分验收；36 features / 1,260 候选 |
| dialog 账本和发现清单 | 37 项：24 验收、5 部分验收、1 未验证、7 未实现；3 features / 59 候选 |
| 开发环境真实 dialog 正常场景 | 48 场景、57 项检查及 168 项原生控件观察通过 |
| 开发环境 dialog 关闭与异常 | 七个独立真实进程通过 |

pytest 跳过项为 Windows 当前权限不允许创建测试符号链接的资源逃逸检查，没有计为通过。
Windows 全 feature 构建不能替代 Linux/macOS/移动行为验收。

## 系统对话框与关闭

scripts/dialog_smoke.py 只操作自己创建的应用进程：核验 venv 启动器后代关系、PID、唯一标题及 #32770 类。
输入直接发给对应控件，没有全局 SendKeys。失败/超时仅终止本次启动进程及后代；桌面场景串行运行。

正常进程用真实 WebView 核验 AnyIO → to_thread.run_sync → blocking_* → Path → 前端响应；
回调版通过原生线程 attach Python 并交付结果：

- 五种路径操作各运行回调/阻塞、选择/取消，共 20 个系统文件/目录/保存窗口。
- 中文路径、一个和多个文件/目录、默认保存文件名、None 取消及 Path/list[Path] 类型均核验。
- 七种标准/自定义按钮分别运行回调和阻塞，点击各可见选择，共 28 个系统消息框。
- 自定义 Unicode 标签逐项对照控件；肯定 True，否定/取消 False。
- 48 个标题、48 个父窗口/无父窗口、20 个初始目录、12 个默认文件名、12 个过滤器文本及 28 个按钮观察。
- GUI 和原生回调内阻塞立即返回 would_block；None 回调不能落入私有阻塞接口。
- 等待期间后台 Python 线程继续运行，回调执行后弱引用释放，保存不创建目标文件。
- 未授权前端 plugin:dialog|open 仍被 ACL 拒绝。

另外七个真实进程覆盖 callback_exception、callback_awaitable、window_callback、parent_callback、
window_blocking、app_callback、app_blocking。
原始 LookupError 或 invalid_callback 有序归还；窗口入口和显式父窗口拥有操作资源，
销毁/退出释放 Python 引用并唤醒等待；同标签重建、旧句柄拒绝和晚到结果取消均通过。
应用退出的阻塞操作返回 app_closed，无需等待用户关闭系统选择器。

## 实现约束与账本

Plugin 是无公开构造器的原生描述符；init 不启动 GUI，不修改输入，重复/无效/已消费对象在运行时消费前拒绝。
上游阻塞接口用带 unwrap 的通道等待，绑定改用非阻塞接口和共享登记/Condvar；
销毁时唤醒等待，返回前再次检查状态。原生队列只持编号和 weak runtime，Python 引用可在锁外清理。
拿到 GIL 后复核应用及窗口代次，防止等待期间所有者销毁；异常统一通过 run_return 归还。

未运行的 App 在解释器结束时通过 try_attach 清理，避免 finalization 阶段强行 attach 触发 panic。
新增独立进程回归核验插件、共享状态和全局 App 的结束，明确检查 stderr 中没有原生 panic。
按钮 NUL 校验直接检查原始标签，避免把合法的反斜杠转义字面文本误判为 NUL；源包重建后也执行此回归。

注册不授予 dialog:default，也不注册 tauri-plugin-fs。
fs 2.6.0 是 FilePath 传递依赖，未绑定其 API、filesystem scope 或通用动态权限。
版本升级分别核验 dialog 源码/feature/声明与审核账本，不与核心候选混算。

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
uv run --no-sync python scripts/desktop_smoke.py
uv run --no-sync python scripts/dynamic_window_smoke.py
uv run --no-sync python scripts/event_dispatch_smoke.py
uv run --no-sync python scripts/dialog_smoke.py
uv run --no-sync maturin build --locked --jobs 1 --out dist/phase5
uv run --no-sync maturin sdist --out dist/phase5
uv run --no-sync python scripts/check_sdist.py dist/phase5/tauri_pyo3-0.1.0a1.tar.gz
uv run --no-sync python scripts/extract_sdist.py dist/phase5/tauri_pyo3-0.1.0a1.tar.gz artifacts/phase5-source
```

产物位于 dist/phase5：cp311/cp314 Windows x86_64 wheel 和源包。
3.11 安装在 artifacts/python311-venv；3.14 从 artifacts/phase5-source 重建后安装在 artifacts/wheel-venv。
已确认两个环境均从独立 site-packages 加载扩展。
源包逐字节核验 101 个当前文件，排除 pyd/pdb/pyc；解压后的源码实际编译并经过安装行为检查。
可复现源包采用固定历史时间，重复解压时 extract_sdist 刷新变更文件的 mtime，避免 Cargo 错用旧缓存。
最终归档的文档更新会重新核验、解压和重建；保持内容相同的源码和依赖缓存。

## 限制

set_can_create_directories 仅 macOS 有效果：已转发，Windows 不证明该效果，独立记为 bound_unverified。
消息图标具体外观、过滤列表对排除文件的隐藏效果未独立测量。
上游 rfd 对取消及部分后端失败均返回 None，不能区分全部系统错误；
清理 Python 操作也不保证程序化关闭原生选择器。

MessageDialogResult、show_with_result、blocking_show_with_result、移动 PickerMode/FileAccessMode
及其两项选项未实现。其他插件、IPC Channel、监视器、图像解码、菜单/托盘、完整 Webview/Window 和移动宿主仍待后续阶段。
未安装原 pytauri_plugins 或原 npm 客户端联合测试，验收基于独立实现的公开形状和真实传输行为。
Python 宿主图标资源和 WebView2 偶发窗口类注销诊断仍可见，实际退出与资源释放通过。
项目名与许可证待确定；源包和 wheel 为本地验证产物，不发布。

