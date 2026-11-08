# ECL 接入指南

项目名为 PytaruiX，发行包及导入为 `pytaruix`，Rust crate 为 `pytaruix-bindings` 与 `pytaruix-bridge`。
现有磁盘目录 Tarui-PyO3 保持原路径。前端兼容入口 `window.__TAURI__.pytauri.pyInvoke` 与旧原生 plugin 协议保持。
当前提供可审核的隔离 ECL 接入版本，原 ECL 工作区没有切换；完整阶段结果见 [验证记录](validation.md)。

## 导入与构建

```python
from pytaruix import AppHandle, Commands, Manager, builder_factory, context_factory
from pytaruix.plugins.dialog import DialogExt, init as dialog_init
```

ECL 的六处直接 Python 导入、依赖清单、打包清单、宿主保护名称和测试替身需要迁移。
依赖使用 `pytaruix==0.1.0a1`，从本地 wheel 安装；本项目尚未发布到索引，不能直接假设公开安装可用。
当前 ECL 调试命令要求 wheel 构建显式开启开发者工具：

```powershell
uv run --no-sync maturin build --release --locked --jobs 1 --features devtools --out dist/phase9
```

旧插件协议属于兼容传输，不代表旧 Python 包继续存在。新入口是 `window.__TAURI__.pytaruix.pyInvoke`。
实际 ECL 命令名、响应形状和业务事件保持；窗口标签变化见下文。

## 配置与资源

```python
context = context_factory(resource_root, tauri_config={"app": {"windows": window_configs}})
development = context_factory(resource_root, dev=True)
```

resource_root 必须为明确的 Path。优先读取 tauri.conf.json，否则读取 Tauri.toml；随后读取同格式的平台文件，最后合并 tauri_config。
平台文件为 tauri.windows.conf.json / Tauri.windows.toml 等；字典递归覆盖、数组整体替换、null 删除字段，不修改输入。
生产默认使用 frontendDist 目录快照，即使配置有 devUrl 也不会自动切到开发服务器。
显式 dev=True 使用 devUrl 或 URL frontendDist；URL 必须为无凭据的 HTTP(S) 来源。
宿主 bundle.icon 在 Windows 优先 ICO、其他平台优先 PNG；按图像 feature 加载，保留自有像素。
CSP、隔离模式、JSON5、完整构建配置和移动资源暂未实现，不把 TOML 支持称为全部 Tauri 配置支持。
配置窗口仍在 Ready 初始化；创建失败有序返回 window_create_failed，避免上游自动建窗失败的 panic。

## 宿主权限与窗口标签

读取 capabilities 下的 JSON/TOML，可由 security.capabilities 选择文件标识或内联对象。
标识必须唯一；权限使用锁定版本的真实 ACL 清单，并仅保留实际注册的原生插件。
未注册 dialog 的情况下引用 dialog 权限会在原生运行时消费前失败，允许修正并重新 build。
窗口模式与 remote.urls 使用上游解析，非法权限/来源明确失败；不通过静默丢弃配置获得启动成功。
存在宿主策略时，动态窗口不再自动授予原型默认权限；空宿主能力目录拒绝全部前端调用。
旧协议需 pytauri:allow-pyfunc，新协议需应用 allow-python-command；原生窗口 JS API 则需相应 core 权限。

当前 ECL 插件描述符采用 `plugin.id.panel`，Tauri 窗口 label 不允许点号。
迁移只将原生 label 中的点号转为冒号，例如 `plugin:pytaruix-smoke:panel`；descriptorId 和插件 SDK 标识保留。
capabilities 的插件窗口模式同步为 `plugin:*`。窗口上下文仍注入实际 label，不能由 IPC 正文伪造。

## 开发者工具

open_devtools 要求调试构建或 devtools feature，并遵循工作线程、窗口代次和应用存活检查。
同步 GUI 回调中操作返回 blocking_callback；窗口/应用关闭后返回 window_closed / app_closed。
Windows 上游 Wry 不支持关闭/读取打开状态，close_devtools / is_devtools_open 返回 platform_unavailable。
不得用假状态维护来冒充原生支持。其他平台同名接口仍需要独立实际验收。

## 隔离迁移和验收

```powershell
uv run --no-sync python scripts/prepare_ecl.py E:/Projects/EuoraCraft-Launcher/EuoraCraft-Launcher
```

脚本复制当前工作区和前端子模块，保留未提交内容，生成来源提交/摘要、迁移副本和初始补丁；目标必须为新的 artifacts 子目录。
依赖与专用虚拟环境安装在副本，运行时数据和 WebView2 配置也使用独立目录，不使用原账户/游戏数据。
副本前端执行 pnpm check 与 pnpm build，使用本次实际工作区生产产物。
Windows 上用隔离副本环境运行真实前后端检查：

```powershell
artifacts/phase9-ecl/.venv/Scripts/python.exe -X utf8 scripts/ecl_desktop_smoke.py artifacts/phase9-ecl --output artifacts/ecl-new-check
```

默认分别验收三种窗口模式；包含正式 IPC、设置持久化/事件、插件注册/窗口/权限/停用、单实例恢复和正常退出。
custom 模式还操作真实系统对话框，核对背景/皮肤文件字节，以及真实子进程日志、输入和终止。
未把 CDP 脚本直接注入业务返回值作为成功；调用实际 Vue/Tauri/Python 链路。
原生拖放单独通过 --native-drop 检查；本次因模拟器窗口覆盖输入位置而待验收，不能把其他桌面检查记为拖放成功。

Nuitka 清单必须包含 pytaruix、pytaruix._native、pytaruix 发行元数据、frontend/dist、Tauri.toml、capabilities 和 ECL 资源。
Windows 本次禁用编译缓存 --disable-cache=ccache，避开内置 clcache 的本机编码错误；排除 ECL.game.tests。
HTTPX 可选命令行会引入 Pygments；使用 --noinclude-custom-mode=pygments:bytecode 保留其模块，避开 MSVC 超大模块堆空间失败。
独立程序用同一驱动的 --executable 指向 main.dist/main.exe，在源码目录以外运行。
本次 standalone 已通过三种窗口模式的实际验收；离线插件安装、重启后的纯 Python 资源和原生扩展加载也通过。
PyInstaller 清单也同步新包，但未执行 PyInstaller 产物验收；onefile、更新交接与正式发布另外验证。

最终补丁从副本重新导出，并核对每个迁移涉及的来源摘要：

```powershell
uv run --no-sync python scripts/export_ecl_patch.py artifacts/phase9-ecl-baseline.json artifacts/phase9-ecl artifacts/phase9-ecl-migration.patch
```

原 ECL 没有主题编辑器或终端窗口的已注册内置描述符，本阶段验证通用窗口与实际插件窗口，不添加新的 ECL 业务窗口。
真实 Minecraft 实例、登录、网络更新替换/重启需测试资源与外部条件；进程烟测不能代替这些完整业务验收。
Windows 实际验收与 Linux/macOS 构建/GUI 分开记录，仓库中的 CI 文件不能代替云端运行结果。
