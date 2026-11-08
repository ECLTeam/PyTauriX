# 第八阶段验证记录

验证日期：2026-10-01，Asia/Shanghai。范围：原生菜单、菜单项、挂载与弹出、事件和共享资源生命周期。
Windows 开发环境、独立 wheel 与实际源包重建验收；历史见 [第七阶段](validation-phase7.md)。

## 环境与执行结果

Windows x86_64、真实 WebView2；Rust 1.97.1，最低 1.90；CPython 3.11.16 / 3.14.7，最低 Python 3.11。
阶段开始从 crates.io 重新核验 Tauri 2.12.1、tauri-build 2.7.1、tauri-utils 2.10.1、PyO3 0.29.3 和 dialog 2.8.1，沿用最新稳定基线。
本地包 0.1.0a1，未提交、推送或发布。

| 检查 | 结果 |
| --- | --- |
| Ruff check/format、Pyright、Rustfmt | 通过 |
| 开发环境 / 3.11 wheel / 3.14 源包重建 wheel 的 pytest | 各 132 通过、1 跳过 |
| 每版七个桌面脚本 | 29 个成功进程：desktop 5、dynamic 6、event 5、dialog 8、channel 1、display/image 1、menu 3 |
| 菜单正常场景 | 每版 73 项联合检查，另有退出后四项 app_closed 检查 |
| 菜单失败场景 | 原异常和 awaitable 两个独立进程均恢复并释放 Python 引用 |
| 全 feature / 无默认 feature、仅 wry 的 Clippy | 均通过 |
| 源包 | 逐字节核验 143 个当前文件，另核对 README、清单与 Cargo.lock；解压路径下绑定实际重新编译 |
| 核心人工审核账本 | 185 项：171 bound_tested、14 partial_tested |
| 核心发现 / dialog 账本 | 保持 36 features / 1,260 候选；dialog 独立账本 37 项 |

跳过为 Windows 权限无法创建测试符号链接，不计为通过。GUI 串行运行，日志在 artifacts/phase8-checks。
此前六组桌面测试全部回归；最终菜单场景增加勾选项实际选择和 Submenu 默认弹出检查后，三种环境分别重新通过菜单三进程验收。
Ruff/Pyright 和 pytest 随最终源码重新核验；菜单签名测试覆盖两个导入路径、对应构造位置参数和默认值。

## 原生菜单证据

scripts/menu_smoke.py 在真实窗口中执行菜单栏和上下文菜单选择，事件经过原生菜单循环与 Tauri 派发。
独立 Win32 驱动使用本进程窗口 HWND、SC_KEYMENU、菜单助记符/WM_CHAR，不伪造 WM_COMMAND、不直接调用 Python 回调、不发送全局鼠标点击。
原生前台激活有时延迟，驱动只对其拥有的窗口有限重试，不停止未知进程。
GetMenu/GetMenuItemInfo 独立核对实际菜单文字、排序、启用与勾选；真实选择勾选项后，再对照原生标志和 Python 状态变化。

菜单及子菜单、普通/勾选/图像/分隔项的选定构造与动态修改、挂载/替换/移除、默认和指定位置弹出均覆盖。
共享项、多父菜单、重复插入/ID、按 ID 移除、移除后句柄存活、直接/传递循环拒绝、批量顺序和修改失败后恢复分别检查。
NUL、非法类型/索引和快捷键在边界拒绝；快捷键使用同一 muda 解析器，避免上游构造器静默忽略非法输入。
工作线程释放 GIL；同步 GUI 回调和原生模态菜单重入拒绝，退出/窗口关闭会结束排队等待。

图像菜单项使用 Image.from_path 读取 16×16 不透明 PNG；通过借用 HBITMAP 和 GetDIBits 读回全部 1,024 字节 RGBA，与原始解码结果一致。
不销毁借用的菜单位图，明确释放工具创建的 GDI DC。muda 在 Windows 将菜单图像渲染成 16×16；更大样本的缩放和透明度合成外观没有计为像素验收。

应用入口累加监听，窗口入口替换；Tauri 将菜单事件广播给应用和所有窗口订阅，窗口参数表示订阅者。
原生闭包仅捕获弱引用；显式清空停止 Python 派发，不宣称物理移除上游永久保留的闭包。
回调异常由 run_return 有序归还，误返回协程会关闭并报 invalid_callback；引用释放在下一次 GUI 调度或 portal 关闭后的适当时机核对。
应用、窗口和替换监听的最终弱引用均释放；同标签重建不复活旧窗口句柄或回调。

## Windows 关闭与共享菜单

实测发现 Windows 自动销毁关闭窗口仍挂载的 HMENU，导致共享菜单的缓存项目可读、实际重新挂载却失败。
现缓存原始 WindowState 的 HWND，在未被 Python prevent_close 拦截的 GUI CloseRequested 通知内调用 Win32 SetMenu(hwnd, NULL)。
该路径只解除关联，不销毁菜单；muda 的 NCDESTROY 负责自身登记清理。
不在 Destroyed 通知后访问失效 HWND，也不重入 Wry 已持有的窗口表锁，不使用 unsafe 绕过 Send/Sync。
动态窗口也缓存句柄，覆盖应用菜单继承。真实系统 SC_CLOSE、关闭拦截后的原挂载、共享菜单同标签重建后的原生读回和选择均通过。

## Feature 与依赖

菜单为桌面内置能力，不启用 tray-icon、不注册菜单前端插件、不扩大现有 IPC/ACL。
沿用 36 个核心 feature 映射及现有默认组合，运行时新增菜单资源、挂载、弹出、事件和显式清理能力项。
直接依赖锁定已有 muda 0.20.0 进行快捷键校验，Windows 直接依赖已有 windows-sys 0.61.2 进行关闭前解除关联。
Cargo.lock 仅调整绑定的依赖边，未锁定新的包版本；全 feature 和无默认 feature、仅 wry 的构建均通过。
第七阶段的图像四组合验收保留在历史记录，菜单阶段没有重复计为新图像 feature 验收。

账本新增 85 个选定菜单 API；两个 set_as_* 保留 PyTauri 的 None 返回形状、两个 ContextMenu 方法使用现有 WebviewWindow，按部分绑定记录。
trait 方法和正则发现候选并非同一集合，不以 185 / 1,260 计算全量完成率。
dialog 独立账本保持 24 项绑定验收、5 项部分验收、1 项平台效果未验证、7 项未实现。

## 复现与交付

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
uv run --no-sync python scripts/channel_smoke.py
uv run --no-sync python scripts/display_image_smoke.py
uv run --no-sync python scripts/menu_smoke.py
uv run --no-sync maturin build --locked --jobs 1 --interpreter artifacts/python311-venv/Scripts/python.exe --out dist/phase8
uv run --no-sync maturin sdist --out dist/phase8
uv run --no-sync python scripts/check_sdist.py dist/phase8/tauri_pyo3-0.1.0a1.tar.gz
uv run --no-sync python scripts/extract_sdist.py dist/phase8/tauri_pyo3-0.1.0a1.tar.gz artifacts/phase8-source
```

3.14 在 artifacts/phase8-source/tauri_pyo3-0.1.0a1 下实际执行 maturin build，复用 target 中无关依赖。
解压刷新变化文件时间戳；build-source-cp314.log 与 build-source-cp314-final.log 确认绑定来自解压路径。
文档收尾后再次解压并构建，核对最终 wheel 的 Python/原生载荷与已验收安装包相同，防止交付漂移。
独立环境为 artifacts/python311-venv / artifacts/wheel-venv，包和原生扩展来自各自 site-packages。
产物为 dist/phase8 下两个 Windows wheel 和 tauri_pyo3-0.1.0a1.tar.gz；指南、迁移契约、矩阵、账本、样本和历史记录纳入源包。
参考 PyTauri/ECL 仓库没有修改。

原生 Tauri 在 Python EXE 中查询默认图标资源可能输出资源缺失诊断，宿主提供 RGBA 默认图标。
构建仍有原型清单缺少发布元数据及 MSVC 链接器输出诊断；没有计为生产发布验收。
Linux/macOS、移动平台、物理快捷键、多屏/DPI、透明图像外观、跨应用实例均未实测。
每进程单应用使跨应用所有权边界只完成代码审核；其他预定义角色、AboutMetadata、NativeIcon、Menu.default、完整 Builder、托盘及 CI 仍待后续阶段。
