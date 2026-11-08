# 第三阶段验证记录

验证日期：2026-10-01，Asia/Shanghai。范围为动态窗口、选定控制与图像/几何类型、销毁及同步回调、标签权限；不代表全量 Tauri API 完成。
历史结果保存在 [第二阶段验证记录](validation-phase2.md)。

## 环境与版本

- Windows x86_64，真实原生窗口与 WebView2。
- Rust 1.97.1，项目最低 1.90；CPython 3.11.16、3.14.7，项目最低 Python 3.11。
- 本次再次核验稳定版本，保持 Tauri 2.12.1、tauri-build 2.7.1、tauri-utils 2.10.1、PyO3 0.29.3。
- 本地调试包 0.1.0a1 / Rust crate 0.1.0-alpha.1；没有提交、推送或发布。

## 已执行结果

| 验证 | 结果 |
| --- | --- |
| Ruff check / format --check | 通过 |
| Pyright | 0 错误、0 警告 |
| Python 3.11 独立安装 wheel 的 pytest | 51 通过、1 跳过 |
| Python 3.14 源包重建 wheel 后独立安装的 pytest | 51 通过、1 跳过 |
| cargo fmt --all --check | 通过 |
| cargo clippy --all-features --locked --jobs 1 -- -D warnings | 通过，Windows 全 feature 组合 |
| cargo check --no-default-features --features wry --locked --jobs 1 | 通过，缺少绑定 dynamic-acl 分支可构建 |
| 上游发现清单 | 36 个 feature 映射、1,260 条声明候选，与锁定源码一致 |
| 人工审核账本 | 76 项：64 项绑定并验收调用或行为、12 项部分绑定并验收 |
| Python 3.11 / 3.14 wheel 构建与安装 | 通过，确认从各自独立环境的 site-packages 加载 |
| 源包核验和解压后重建 3.14 wheel | 通过，逐字节核对当前源码/文档/测试/示例，排除 pyd/pdb/pyc |
| 既有桌面验收 | 两个版本各五个真实桌面进程通过 |
| 动态窗口桌面验收 | 两个版本各六个真实桌面进程通过，正常场景各 45 项检查通过 |

跳过项仍为 Windows 当前权限不允许创建测试符号链接的资源逃逸检查；未计为通过。
安装包使用默认 Wry feature 集；全 feature Clippy 只证明该 Windows 构建组合通过，没有声称全 feature 行为验收。

## 动态窗口行为证据

`scripts/dynamic_window_smoke.py` 每次启动六个独立桌面进程，实际执行 WebView JavaScript。

正常进程核验 45 项：

- setup 同步创建、命令工作线程创建、异步入口创建、运行前拒绝、GUI 回调中同步建窗拒绝和 Python 后台线程继续运行。
- 随机标签子窗口的新旧 IPC、真实来源、初始化脚本、隐藏创建、窗口管理器与定向前端事件隔离。
- 标题、显隐、物理和逻辑几何、焦点、最大化/恢复、最小化/恢复、全屏/恢复，以及选定属性查询和更新。
- Resized/Moved/Focused 回调载荷；导航拒绝与允许、加载 Started/Finished。
- 首次关闭被阻止、过期 prevent_close 返回 request_expired、再次关闭销毁窗口；Destroyed 回调内窗口查询/映射已排除该窗口。
- 构建器返回、单独查询及映射查询获得的三个旧句柄同时失效；同标签重建不会恢复旧句柄。
- 窗口关闭与替换处理器的弱引用释放；from_config 不修改输入；无效标签/尺寸、重复创建有明确错误。
- 使用上游不支持的 FTP 代理触发真实原生创建失败，释放回调后同标签能继续创建成功。
- 未授权本地标签和独立本机 HTTP 外部来源分别被两条 IPC 路由拒绝；拒绝发生在 Tauri 原生 ACL 检查。

其余五个进程分别故意触发导航异常、导航错误返回类型、页面加载异常、页面加载 coroutine、窗口事件异常。
每次均有序退出，归还原异常或 invalid_callback，弱引用证明回调释放；输出 DYNAMIC_FAILURE_RECOVERED 和 DYNAMIC_RESOURCES_RELEASED。
正常场景输出 DYNAMIC_RESULT，脚本最终输出 DYNAMIC_WINDOW_SMOKE_PASSED。

RGBA 构建图标及运行期图标更新经过真实原生调用。图标、阴影、任务栏、居中等没有独立外观/桌面 shell 测量；账本记录这一限制。
Builder 覆盖选定参数；运行期属性有调用或状态证据，不能由此宣称全部构建参数或全部平台语义已验证。

## 发现与修复

- 动态窗口先登记共享代次和可清空回调槽，再进入原生构建，允许页面回调早于 Python 工厂返回；失败释放回调。
- Destroyed 在用户回调开始前使本代全部句柄失效；短暂保留无回调代次，待 Tauri 移除原生窗口后清理，防止查询重新激活。
- 窗口映射和单独查询过滤失效代次；同标签重建使用新状态。
- 原生操作释放 GIL，GUI 回调上下文拒绝同步建窗；异步入口使用 AnyIO 工作线程。
- 关闭控制 API 在回调结束后失效，避免调用上游过期通道；导航要求 bool，其他回调拒绝 awaitable。
- 旧 plugin 命令与新 app 命令均登记原生 manifest 权限，按精确本地标签授权；没有窗口通配符。
- 前端全局事件监听具有 Any 目标语义；窗口隔离验收显式使用 WebviewWindow 目标。

## 可复现命令与产物

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
uv run --no-sync python scripts/dynamic_window_smoke.py
uv run --no-sync maturin build --locked --jobs 1 --out dist/phase3
uv run --no-sync maturin sdist --out dist/phase3
uv run --no-sync python scripts/check_sdist.py dist/phase3/tauri_pyo3-0.1.0a1.tar.gz
```

产物位于 dist/phase3：cp311、cp314 Windows x86_64 wheel 与源包。
3.14 wheel 从 artifacts/phase3-source 解压源构建，安装到 artifacts/wheel-venv；3.11 安装到 artifacts/python311-venv。
桌面验收串行运行，避免同时启动的窗口干扰焦点判定。未使用 MockRuntime 代替真实 WebView。

## 实际限制

macOS/Linux、Android/iOS 尚未验收。窗口事件目前五个变体和每窗一个可替换回调；导航参数和加载载荷采用 Python 字符串/属性模型。
动态权限仅增补本地标签；关闭不撤销该标签权限，通用远程授权、自定义 ACL/CSP/隔离仍待实现。
完整窗口/WebView API、监视器/嵌入、下载/新窗口/资源修改、channel、菜单/托盘、官方插件及图像文件解码仍待实现。
Python 宿主缺少 EXE 图标资源及 WebView2 退出时偶发窗口类注销诊断仍可见；验收进程退出码与资源清理正常。
项目名与许可证尚未确定，不发布软件包。
