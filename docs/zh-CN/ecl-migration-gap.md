# ECL 迁移差距报告

这份报告回答一个问题：**把 ECL 从 PyTauri 换到 PytaruiX，要改多少东西。**

结论先说：**业务代码只依赖 19 个上游符号，全部能在 PytaruiX 找到对应物，
关键调用形状也一致。这是导入路径替换，不是重写。**
但这只证明"接得上"，不证明"跑得对"——行为等价性还没有验证，见文末的风险清单。

## 口径

- 扫描目标：`EuoraCraft-Launcher` 仓库的 Python 业务代码，共 **3158 个文件**
- 排除：`.venv`、`build`、`ECL_data`、`__pycache__`、`node_modules`、`dist`
- 方法：AST 解析 `Import` / `ImportFrom`，统计 `pytauri*` 前缀的模块与符号
- 复核：对每个符号用 `importlib` 在 PytaruiX 里反射查找，再人工核对调用形状

第一次扫描时把 ECL 自己的 `.venv` 也算进去了，得出 234 个符号、39 个模块的结论——
那 90% 是 PyTauri 与 `pytauri_plugins` 自己的内部实现。排除虚拟环境后才是真实依赖面。

## 符号映射

| # | ECL 导入 | PytaruiX 对应 | 次数 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | `pytauri.AppHandle` | `pytaruix.AppHandle` | 47 | 改名 |
| 2 | `pytauri.WebviewUrl` | `pytaruix.WebviewUrl` | 31 | 改名 |
| 3 | `pytauri.Commands` | `pytaruix.Commands` | 28 | 改名 |
| 4 | `pytauri_wheel.lib.builder_factory` | `pytaruix.builder_factory` | 28 | 改路径 |
| 5 | `pytauri_wheel.lib.context_factory` | `pytaruix.context_factory` | 28 | 改路径 |
| 6 | `pytauri.ffi.webview.WebviewWindowBuilder` | `pytaruix.webview.WebviewWindowBuilder` | 26 | 改路径 |
| 7 | `pytauri.ffi.webview.WebviewWindow` | `pytaruix.webview.WebviewWindow` | 20 | 改路径 |
| 8 | `pytauri.ipc.WebviewWindow` | `pytaruix.ipc.WebviewWindow` | 13 | 改包名 |
| 9 | `pytauri_plugins.dialog.DialogExt` | `pytaruix.plugins.dialog.DialogExt` | 10 | 改路径 |
| 10 | `pytauri.ffi.webview_version` | 无对应 | 6 | **仅测试桩使用，业务无依赖** |
| 11 | `pytauri.EventTarget` | `pytaruix.EventTarget` | 5 | 改名 |
| 12 | `pytauri.ffi.Emitter` | `pytaruix.ffi.Emitter` | 5 | 改路径 |
| 13 | `pytauri.ffi.image.Image` | `pytaruix.ffi.image.Image` | 5 | 改包名 |
| 14 | `pytauri.Manager` | `pytaruix.Manager` | 5 | 改名 |
| 15 | `pytauri.RunEvent` | `pytaruix.RunEvent` | 5 | 改名 |
| 16 | `pytauri.RunEventType` | `pytaruix.RunEventType` | 5 | 改名 |
| 17 | `pytauri_plugins.dialog.init` | `pytaruix.plugins.dialog.init` | 5 | 改路径 |
| 18 | `pytauri.WindowEvent` | `pytaruix.WindowEvent` | 3 | 改名 |
| 19 | `pytauri.webview.WebviewWindowBuilder` | `pytaruix.webview.WebviewWindowBuilder` | 5 | 改路径 |

`webview_version` 的 6 次出现全部在 `.pytest_tmp/` 与 `build/` 下的测试桩里，
业务代码没有引用，迁移时可忽略。

## 调用形状核对

符号能导入不等于能用。逐处比对了 ECL 的实际调用与 PytaruiX 的签名：

### 上下文与应用构建

```python
# ECL/host/tauri.py
context = context_factory(self.resource_path, tauri_config=tauri_config)
app = builder_factory().build(
    context=context,
    invoke_handler=self.commands.generate_handler(portal),
    plugins=[dialog_init()],
    setup=self._setup_plugin_windows,
)
```

```python
# PytaruiX 签名
def context_factory(resource_path, /, *, tauri_config=None, dev=False) -> Context
Builder.build(*, context, invoke_handler, setup=None, plugins=(), protocols=(), on_tray_icon_event=None)
Commands.generate_handler(portal=None)
```

三个关键字全部对得上：`tauri_config` 支持递归合并覆盖，`generate_handler(portal)` 用于异步命令，
`setup` 在 Ready 时执行。`protocols` 是 PytaruiX 的额外可选参数，ECL 不传也不影响。

### 动态建窗

```python
# ECL/api/windows.py
webview = WebviewWindowBuilder.build(app_handle, label, WebviewUrl.App(url), **builder_options)
```

ECL 传入的键：`title`、`inner_size`、`min_inner_size`、`decorations`、`transparent`、
`visible`、`resizable`、`initialization_script`、`background_color`、`icon`、`position`。

PytaruiX 的 `WebviewWindowBuilderArgs` 有 50 个选项，上述 11 个全部在内，值类型也一致：

| 选项 | ECL 传的值 | PytaruiX 声明 |
| --- | --- | --- |
| `inner_size` / `min_inner_size` / `position` | `(float, float)` 元组 | `tuple[float, float]`，按逻辑像素 |
| `background_color` | `(r, g, b, a)` 四元组 | `tuple[int, int, int, int]` |
| `icon` | `Image(bytes, w, h)` | `Image(rgba, width, height)` |

`WebviewWindowBuilder.build` 的签名是 `(manager, label, url, /, **kwargs)`，与 ECL 的调用一致。

### 事件与对话框

```python
# ECL/plugins/runtime/custom_ui.py
if isinstance(value, WindowEvent.CloseRequested): ...
elif isinstance(value, WindowEvent.Destroyed): ...
```

PytaruiX 的 `WindowEvent` 提供 `CloseRequested`、`Destroyed`、`Focused`、`Moved`、`Resized`、
`ThemeChanged`、`ScaleFactorChanged` 与四个 `DragDrop*` 变体，ECL 用到的两个都在。

```python
# ECL/api/accounts.py
DialogExt.file(self._webview).blocking_save_file(
    add_filter=("PNG 图片", ["png"]), set_file_name=..., set_title=...
)
```

`pytaruix.plugins.dialog` 的重导出清单里就有 `DialogExt`、`FileDialogBuilder`、`MessageDialogBuilder`，
注释写明是"保留常见迁移导入布局"。

## 迁移方式

两条路，按风险从低到高：

**A. 先做命名空间垫片。** 添加一个仅用于过渡的 `pytauri` / `pytauri_wheel` / `pytauri_plugins`
包，把导入转发到 `pytaruix`，ECL 代码零改动先启动。好处是能最快证实"能不能跑起来"，
坏处是多一层间接，且垫片本身要维护。

**B. 直接改名。** 3158 个文件里只有 19 个符号、约 250 处导入需要改，集中在
`ECL/host/tauri.py`、`ECL/api/{windows,accounts,files}.py`、`ECL/plugins/runtime/custom_ui.py`
这几个入口。用 `ruff` 的 `--fix` 配合自定义映射可以批量完成。

建议先用 A 跑通一次启动与建窗，再切 B。

## 未验证的风险

符号与签名对上，只说明"代码不会因为 ImportError 或 TypeError 立刻挂掉"。以下都没有证据：

1. **200 个命令的真实执行**：ECL 注册了 200 个 `@commands.command`，参数模型、并发、
   取消与背压行为都没有在 PytaruiX 上跑过。
2. **`pytauri_plugins` 的其它插件**：ECL 业务只直接用到 dialog，但插件管理器可能按需加载
   fs、clipboard-manager、deep-link、autostart 等。PytaruiX 目前只有 6 个插件，
   缺的插件对应的功能会在运行期报错。
3. **菜单、托盘、拖放、主题**：这些 PytaruiX 有绑定，但 ECL 的具体用法（默认菜单、托盘事件、
   拖放文件到窗口）没有对照过。
4. **TS 类型生成**：PyTauri 有 `pytauri._gen_ts`，PytaruiX 没有对应能力，前端契约需要另想办法。
5. **打包与资源**：`pytauri_wheel` 涉及 wheel 内的资源布局，PytaruiX 的 `context_factory`
   资源解析规则是否覆盖 ECL 的 `resource_path` 结构，未验证。

## 下一步建议

先做**最小启动验证**：在 ECL 的隔离副本里，只把 `ECL/host/tauri.py` 的四个入口换成 PytaruiX，
其余模块加一层导入垫片，看能否起窗口、能否调用一个命令。这一步能证伪大部分风险，
成本大约是一次会话。

按项目规范，ECL 集成要用隔离副本与专用数据，改动前需要单独授权。

## 2026-11-08 第二轮复核更新

隔离副本上的真实桌面复核已完成（三种窗口模式，见[实施记录](implementation-plan.md)第二十六阶段），
以上风险清单逐项更新：

1. **200 个命令的真实执行**：已验证。240 个命令经真实 Vue 前端调用，设置读写、事件、
   非法请求恢复、单实例移交、对话框与子进程控制在三种窗口模式下全部通过。
2. **`pytauri_plugins` 的其它插件**：不成立。排除虚拟环境后 ECL 业务只导入 dialog，
   六个已落地插件覆盖有余。但 ECL 插件管线自身已重构（清单 v2、审阅前置、Worker API），
   冒烟驱动按现行流程更新后审阅/启用/列表全绿；插件贡献窗口的授权检查仍读旧式权限，
   与新清单模型冲突——当晚 ECL 侧整体移除插件权限系统并落地窗口授权修复（ECL `067ed7c`），
   插件窗口全链路已在三种窗口模式验证通过，不再是缺口。
3. **菜单、托盘、拖放、主题**：托盘/菜单未在 ECL 链路验证；原生拖放仍待验收。
4. **TS 类型生成**：不变，仍缺。
5. **打包与资源**：`context_factory` 资源解析已验证（生产 frontendDist 快照正确服务），
   但 ECL 的 Nuitka/PyInstaller/CI 清单仍引用 pytauri 与自维护 runtime 分支，待 ECL 侧改写。

新发现的迁移事实（已完成）：前端 4 个文件的 `pytauri` 全局改名；capabilities 的
`pytauri:default` → `allow-python-command`；副本必须剔除开发者本机 `.env`（会把窗口指向
Vite 开发服务器）；ECL 的 `webview_version`、`plugin:pytauri|pyfunc` 已无对应物，
依赖它们的隔离门禁测试需要重新设计。
