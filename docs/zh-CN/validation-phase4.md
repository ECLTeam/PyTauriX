# 第四阶段验证记录

验证日期：2026-10-01，Asia/Shanghai。范围为主线程任务、六种事件目标、原始 JSON、监听作用域及资源清理。
开发环境、独立安装包及源包重建验收已通过。历史结果见 [第三阶段](validation-phase3.md) 与 [第二阶段](validation-phase2.md)。

## 环境与版本

- Windows x86_64，真实原生窗口与 WebView2。
- Rust 1.97.1，最低 1.90；CPython 3.11.16、3.14.7，最低 Python 3.11。
- 本阶段再次核验稳定依赖：Tauri 2.12.1、tauri-build 2.7.1、tauri-utils 2.10.1、PyO3 0.29.3。
- 本地调试包 0.1.0a1；没有提交、推送或发布。

## 执行结果

| 验证 | 结果 |
| --- | --- |
| Ruff check / format --check | 通过 |
| Pyright | 0 错误、0 警告 |
| 开发环境 Python 3.14 pytest | 64 通过、1 跳过 |
| Python 3.11 独立 wheel 安装与 pytest | 64 通过、1 跳过，确认从独立环境 site-packages 加载 |
| Python 3.14 源包重建后安装与 pytest | 64 通过、1 跳过，确认从独立环境 site-packages 加载 |
| cargo fmt --all --check | 通过 |
| cargo clippy --all-features --locked --jobs 1 -- -D warnings | 通过 |
| cargo check --no-default-features --features wry --locked --jobs 1 | 通过 |
| 上游发现清单 | 36 个 feature 映射、1,260 条候选，锁定源码一致 |
| 人工审核账本 | 83 项：75 项绑定并验收调用或行为，8 项部分绑定并验收 |
| 开发环境既有桌面回归 | 五个单/双窗口及六个动态窗口真实进程通过 |
| 开发环境事件/任务桌面验收 | 五个真实进程通过：26 项联合检查及四种回调失败 |
| 两个版本独立安装环境全部桌面验收 | 均通过，各 16 个真实进程；3.11 补跑窗口/应用双调度场景 |
| 源包逐字节核验及解压重建 | 通过，83 个当前源文件及文档/示例，无 pyd/pdb/pyc |

pytest 跳过项仍是 Windows 当前权限不允许创建测试符号链接的资源逃逸检查，未计为通过。
全 feature Clippy 证明 Windows 构建组合通过；行为测试和安装包采用默认 Wry feature 集。

## 三窗口验收

scripts/event_dispatch_smoke.py 使用三个真实 WebView；alpha/beta 由 setup 动态创建并按精确标签授权。
前端各注册 Any、Window、Webview、WebviewWindow 目标，main 另外注册 App；原生注册 App、三个窗口和任意目标监听。
九个发送案例涵盖六种目标、原始 JSON 广播、字符串标签及不存在的目标，逐窗逐种目标比较实际收到的事件序列。

正常场景 26 项检查包括：

- 后台线程向 GUI 提交零参数任务，核验 Python 主线程、后台线程继续运行、任务内同步建窗返回 would_block。
- ECL 调度 → ffi.Emitter.emit_str_to → EventTarget.WebviewWindow 链路；只有 alpha 的明确窗口监听收到最终 JSON 对象。
- 对象、整数、字符串、null、bool、数组、浮点、Unicode 载荷；无效 JSON 被拒绝后继续发送正常事件。
- 六种目标的原生和前端路由、Any 监听始终可接收定向事件，明确 Window/Webview/WebviewWindow 类型不互相降级。
- 应用/窗口 listen、listen_any、once、once_any、重复 unlisten、活动的其他窗口编号拒绝注销、一次回调弱引用释放。
- CloseRequested 与实际移除之间允许任务先执行；最后一个排队任务在销毁时取消，回调引用释放。
- 窗口 scoped/any 监听释放，同标签重建保持新监听可用，旧句柄无法提交任务或注销新监听。
- 应用 Exit 回调中由后台线程提交的任务未执行，退出后弱引用证明回调释放。

四个故意失败的进程分别运行任务异常、任务 coroutine、监听异常、监听 coroutine。
均有序退出，将 LookupError 或 invalid_callback 归还 Python，弱引用证明监听/任务释放。
脚本要求 EVENT_RESULT 完整通过、四个 EVENT_FAILURE_RECOVERED、各进程 EVENT_RESOURCES_RELEASED，最终输出 EVENT_DISPATCH_SMOKE_PASSED。

单元测试的独立原生进程另验证：主循环前排队任务被丢弃 App 清理、关闭后拒绝提交不保留引用、一次监听递归发送仅执行一次、原始 JSON 的空白/Unicode/大整数字面量保持不变。

## 修复和清理设计

任务与监听共用按应用/窗口代次拥有的资源登记；原生队列不永久捕获 Python 回调。
执行和清理先取走回调或登记，再在锁外执行 Python 析构、原生注销，避免析构重入注册表锁。
一次监听自行在调用前取走回调并注销，避免上游 FnOnce 在递归发送时二次取值 panic。
窗口后端可能先移除资源，后续才收到 Destroyed；主线程任务执行前在 GUI 查询原始原生窗口，覆盖代次标记更新前的间隙。
原始 JSON 验证后使用上游 emit_str/emit_str_to，保持原文；根对象入口只编码一次。
窗口 listen/once 恢复上游作用域；需要原有应用监听的调用方传 window.app_handle()，具体差异见 [事件指南](events.md)。

既有动态窗口回归仍核验 45 项，包括未授权本地标签和外部页面的新旧 IPC 拒绝；事件目标没有改变 ACL。

## 可复现命令

```powershell
uv run --no-sync maturin develop --locked --jobs 1
uv run --no-sync ruff check
uv run --no-sync ruff format --check
uv run --no-sync pyright
uv run --no-sync pytest -q
cargo fmt --all --check
$env:PYO3_PYTHON = (Resolve-Path .venv/Scripts/python.exe).Path
cargo clippy --all-features --locked --jobs 1 -- -D warnings
cargo check --no-default-features --features wry --locked --jobs 1
uv run --no-sync python scripts/update_coverage.py --check
uv run --no-sync python scripts/desktop_smoke.py
uv run --no-sync python scripts/dynamic_window_smoke.py
uv run --no-sync python scripts/event_dispatch_smoke.py
uv run --no-sync maturin build --locked --jobs 1 --out dist/phase4
uv run --no-sync maturin sdist --out dist/phase4
uv run --no-sync python scripts/check_sdist.py dist/phase4/tauri_pyo3-0.1.0a1.tar.gz
```

产物位于 dist/phase4：cp311、cp314 Windows x86_64 wheel 和源包。
Python 3.11 wheel 已安装到 artifacts/python311-venv；3.14 wheel 从 artifacts/phase4-source 解压源重建，安装到 artifacts/wheel-venv。
桌面验收串行运行，防止焦点相互干扰；只终止验收脚本自己创建的超时进程。

## 限制

Windows 已验收 App/WebviewWindow 监听与显式 JS Window/Webview 目标；独立 Window/Webview、多嵌入 WebView、其他桌面和移动平台尚未验收。
emit_filter/emit_str_filter、完整窗口/WebView API、监视器、下载/新窗口/请求修改、channel、菜单/托盘、官方插件和图像文件解码仍待实现。
动态权限不可撤销，通用 ACL/CSP/隔离未绑定。图标、阴影、任务栏等原生调用已有证据，外观未独立测量。
Python 宿主缺少 EXE 图标资源及 WebView2 退出偶发窗口类注销诊断仍可见，验收进程退出与资源清理正常。
项目名与许可证尚待确定，不发布软件包；83 项账本与 36 个 feature 转发不能理解为全量 API 覆盖率。
