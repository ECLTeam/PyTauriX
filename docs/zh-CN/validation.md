# 第九阶段验证记录

日期：2026-10-02，Windows x86_64、WebView2；范围为 PyTauriX 更名与当前 ECL 接入。
第八阶段原始记录保留在 [历史快照](validation-phase8.md)，未改写其旧包名或执行结果。
本阶段实现与本地验收已授权；未提交、推送、发布，也未将原 ECL 切换到新框架。

## 来源与版本

ECL HEAD 为 eaa6973a1d2cfd6501ae35b92f4d0d7d387800e6，复制当前工作区而非仅 HEAD。
ECL/utils/config.py、Tauri.toml 和 frontend 的已有变更包含在隔离副本，来源保持原有状态。
806 个来源文件的摘要及前端子模块提交记录于 artifacts/phase9-ecl-baseline.json。
参考 PyTauri HEAD 为 7d99c6f6c8dcefdf8ed5cf87e7c7d707a1f5d749，仅作为只读契约参考。

当前品牌 PyTauriX，Python pytaurix 0.1.0a1，Rust pytaurix-bindings / pytaurix-bridge。
本次通过 crates.io 重新核对最新稳定基线：Tauri 2.12.1、tauri-build 2.7.1、tauri-utils 2.10.1、PyO3 0.29.3、dialog 2.8.1。
Rust 1.97.1，最低 1.90；Python 最低 3.11，本地开发 3.14.7、独立 3.11.16、ECL 专用环境 3.13.9。
ECL 仅安装新框架，使用独立虚拟环境、数据和 WebView2 目录，不使用旧 pytauri/pytauri-wheel。
隔离依赖实际含 AnyIO 4.15.1、Pydantic 2.13.5 / core 2.46.5，不宣称与原环境逐版本相同。

## 框架结果

| 检查 | 本次结果 |
| --- | --- |
| Ruff check/format、Pyright、Rustfmt | 通过 |
| 全 features、devtools 与无默认 feature、仅 wry 的 Clippy | 通过 |
| 开发环境 pytest | 151 通过、1 跳过 |
| Python 3.11 独立 release wheel pytest | 151 通过、1 跳过 |
| 三种环境的八组桌面脚本 | 各 32 个真实进程通过 |
| Python 3.14 源包重建 release wheel pytest | 151 通过、1 跳过；绑定确实来自解压路径 |
| 核心人工账本 | 191 项：171 bound_tested、18 partial_tested、2 platform_unavailable |
| dialog 人工账本 | 37 项：24 bound_tested、5 partial_tested、1 bound_unverified、7 unimplemented |
| 发现清单 | 核心 36 features / 1,260 候选；dialog 3 features / 59 候选 |

每环境的八组包括 desktop 5、dynamic_window 6、event_dispatch 5、dialog 8、channel 1、display_image 1、menu 3、host_config 3。
日志为 artifacts/phase9-{dev,cp311,cp314}-*.log，源包构建日志为 artifacts/phase9-source-cp314-build.log。
最终源包逐字节核验 163 个当前文件，重新解压并构建；26 个 Python 包/原生扩展文件与已通过验收的安装包逐字节相同。
最终复核日志为 artifacts/phase9-source-final-build.log，文档、迁移脚本和 CI 清单均包含在源包中。
窗口焦点用有限重试后真实读回，未移除焦点断言。
唯一框架跳过为 Windows 符号链接权限，不计为通过。其他平台尚未执行本次实际构建与 GUI。

新增宿主用例分别运行生产、显式开发地址和空权限目录：
核对 TOML、平台与显式覆盖、宿主包信息、图标像素、来源窗口/应用注入、窗口模式、原生 JS 权限、远程/未知标签拒绝和错误后恢复。
真实主窗口、theme-studio、plugin:smoke 获准，rogue 与未授权外部来源被拒绝；空宿主权限不回退到示例能力。
错误权限、未注册插件、非法远程模式在运行时消费前失败；修正后 build 可重试。
无效配置窗口 label 在 Ready 归还 window_create_failed，未产生 Rust panic。

宿主默认图标及 RuntimeAuthority 通过 Python 配置入口实现，未提供完整可变 Context API。
Windows 上游 Wry 不支持关闭开发者工具或读取状态，这两个接口明确返回 platform_unavailable。
open_devtools 已调用并取得原生面板页面证据；其他平台效果、完整开发者工具管理未验收。

## 当前 ECL 真实桌面结果

正式命令注册 count=216；未把全部命令注册成功解释为全部业务已执行。
副本前端 pnpm check 与 pnpm build 通过：112 个测试文件、525 通过、1 待办；类型/格式/检查均通过。
生产构建含 3,416 个模块，大块产物警告保留，未扩展本阶段范围处理。
ECL Python 回归为 938 通过、5 跳过，Ruff 与格式检查通过；最终以 -X utf8 完整复核，无先前 GBK 解码线程警告。

artifacts/phase9-ecl-acceptance/{custom,native,system_shadow}.json 与对应日志保存结果：
custom 31 项、native 24 项、system_shadow 24 项全部为 true，包括 clean_exit。
通过当前真实 Vue 前端调用正式 Python 命令，核对生产 tauri.localhost 来源、窗口装饰、设置读写和事件、错误响应与后续恢复。
插件贡献实际子窗口，验证创建、复用、几何、就绪注入、允许命令、拒绝越权命令和停用清理。
单实例第二进程完成真实移交并恢复主窗口，实际系统 close 退出；未停止原 ECL 或未知进程。
custom 额外操作系统目录/保存对话框，验证取消为空字符串、默认文件名，以及背景 PNG/皮肤导出文件字节一致。
实际自有子进程的输出通过 ECL 后端事件到前端，stdin 输入和终止成功；并非直接构造返回数据。

插件 descriptorId 继续使用点号；原生 label 将点号改为冒号，capabilities 同步为 plugin:*。
当前 ECL 内置窗口描述符注册表为空，未添加主题编辑器/终端业务；通用 theme-studio 是框架宿主用例。
原生 OLE 文件拖放待验收：当前 MuMuNxDevice 覆盖 1600×900 桌面，驱动无法确认测试输入归属。
用户明确暂时保留模拟器，记录待验收；不操作该进程，不计入上述成功检查。失败日志保留在 artifacts。
真实 Minecraft、账户登录、完整更新下载/替换/重启仍未完成独立业务验收。

## 独立程序与 CI

Nuitka 4.1.3 在隔离副本构建真实 ECL standalone，包含新原生扩展、发行元数据、生产前端、宿主配置/能力与 ECL 资源。
本机内置 clcache 的 mbcs 解码失败已定位；UTF-8 环境不足以修复，禁用 --disable-cache=ccache 后重试。
随后发现 Pygments 模板模块触发 MSVC C1002 堆空间错误；HTTPX 可选 CLI 引入它，改为以字节码保留完整模块后重新构建。
standalone 构建成功，564 个 C 对象；产物为 artifacts/phase9-ecl-standalone/main.dist/main.exe。
独立程序从源码目录以外运行，三种窗口模式重复上述真实前端验收：custom 31 项、native 与 system_shadow 各 24 项全部通过。
结果位于 artifacts/phase9-ecl-packaged-acceptance，包含真实对话框、背景/皮肤字节、子进程链路和正常退出。
真实打包程序的离线插件安装与重启加载用例通过：纯 Python 资源 wheel 与 xxhash 3.6.0 原生 wheel 均从离线包安装。
重启后插件使用宿主 SDK/上下文，并在宿主同一进程读取资源、执行原生扩展；日志为 artifacts/phase9-ecl-packaged-plugin.log。
原生 wheel 经官方 PyPI 摘要核验；未启用可选浏览器替身，不将该用例解释为插件安装界面验收。
onefile、PyInstaller 产物、更新交接/重启和正式发行未执行。

.github/workflows/ci.yml 包含 Windows/Linux/macOS × Python 3.11/3.14 构建、静态/行为检查、源包核验。
手动桌面任务要求 self-hosted Windows 交互会话，串行运行八组脚本。
仓库没有可用远程，本次未运行云端 CI；工作流文件不构成跨平台通过证据。

## 可审核交付与复现

迁移副本为 artifacts/phase9-ecl，补丁为 artifacts/phase9-ecl-migration.patch，共 16 个文件。
补丁重新核对涉及的来源摘要，保留未变行的混合换行，并在原工作区执行 git apply --check 成功。
补丁没有应用到原 ECL；六处 Python 导入、宿主保护、依赖/打包、窗口标签/权限与测试替身均包含。
历史原型源包另存 artifacts/phase9-baseline/phase8-original.tar.gz。

```powershell
uv run --no-sync maturin develop --locked --jobs 1 --features devtools
uv run --no-sync python scripts/host_config_smoke.py
artifacts/phase9-ecl/.venv/Scripts/python.exe -X utf8 scripts/ecl_desktop_smoke.py artifacts/phase9-ecl --output artifacts/ecl-new-check
artifacts/phase9-ecl/.venv/Scripts/python.exe -X utf8 scripts/ecl_desktop_smoke.py artifacts/phase9-ecl --executable artifacts/phase9-ecl-standalone/main.dist/main.exe --output artifacts/ecl-packaged-new-check
uv run --no-sync python scripts/export_ecl_patch.py artifacts/phase9-ecl-baseline.json artifacts/phase9-ecl artifacts/phase9-ecl-migration.patch
```

完整导入、权限、资源与打包约束见 [ECL 接入指南](ecl.md)。
本阶段已有可用于评估 ECL 接入的开发版本；剩余实际验收条件须关闭后再宣称正式发布就绪。
