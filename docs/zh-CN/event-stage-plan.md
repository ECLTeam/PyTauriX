# 第四阶段方案：主线程调度与多窗口事件

状态：用户已明确授权实施，第四阶段实现及 Windows 验收已完成。

## 优先级依据

第三阶段已解决动态窗口与销毁代次。当前实际迁移仍有三个直接断点：

- ECL/api/windows.py 在显示、聚焦和关闭窗口时调用 run_on_main_thread，本项目尚未绑定。
- ECL/api/bridge.py 从根导入 EventTarget，使用 Any/WebviewWindow 目标，本项目缺少此类型。
- 同一桥接代码通过 ffi.Emitter.emit_str_to 发送已序列化 JSON；本项目只有对象序列化入口，直接替换会再次序列化成字符串。

另一个语义差异是 Listener 接收窗口后仍转为 AppHandle，实际注册在应用作用域；这是本项目当前记录的部分实现，下一阶段需要恢复窗口作用域并明确迁移影响。
监视器、多 WebView 嵌入、下载/新窗口/资源修改、菜单/托盘、插件等仍在总方案中，按后续批次推进。

调研对象为当前独立项目、ECL 的 api/{bridge,windows}.py、参考 PyTauri 的 ffi/{lib,webview}.py，以及锁定 Tauri 2.12.1 的 app.rs、lib.rs、event 和 webview_window.rs。
实施前再次核验最新稳定依赖，版本变化需审核源码差异和更新账本。

## 交付接口

### 主线程调度

- AppHandle.run_on_main_thread(callback) 与 WebviewWindow.run_on_main_thread(callback)，维持 PyTauri 常见名称与零参数回调形状。
- 明确区分提交任务成功与回调完成，返回 None，不把调度方法做成同步等待器。
- 回调在原生 GUI 主线程执行并 attach Python；调用方提交任务时释放 GIL。
- Python 异常进入现有 RuntimeState 错误通道，有序退出后由 run_return 重抛原异常；拒绝 coroutine，不用事件循环隐式等待。
- 已关闭应用/窗口拒绝提交；窗口销毁或应用退出时，尚未执行的任务释放回调引用，不能操作同标签重建窗口。
- 队列由共享生命周期对象登记和清理；原生闭包不永久持有 Python 回调。回调执行与销毁竞争的具体顺序需要真实验收。
- 被调度的回调也属于 GUI 回调上下文，内部同步建窗仍返回 would_block。

### 事件目标与序列化

- 根导出 EventTarget / EventTargetType，并通过 ffi 保持对应类型入口。
- 六个明确变体：Any()、App()、AnyLabel(label)、Window(label)、Webview(label)、WebviewWindow(label)。
- Emitter.emit_to 支持 EventTargetType | str；字符串继续使用 AnyLabel 语义，保留当前调用形状。
- ffi.Emitter.emit_str / emit_str_to 接受已序列化 JSON，验证编码后直接发送；根 Emitter.emit / emit_to 继续接受 Python 模型或 JSON 值并序列化一次。
- 不将 Window、Webview 和 WebviewWindow 目标统一降级为字符串；有标签相同也需要保留目标类型。
- Any 目标是事件路由语义，不能扩大窗口的 IPC 来源权限；沿用第三阶段的本地精确标签 ACL。
- JSON 对象、标量、字符串、null 与 Unicode 都需真实前端核对；无效 JSON 返回稳定错误，随后正常事件仍可发送。
- emit_filter 与 emit_str_filter 的 Python 谓词重入、部分发送和异常语义留到过滤发送批次，当前账本继续明确未实现。

### 监听作用域与资源归属

- Listener.listen / once 在 App/句柄上采用应用作用域，在窗口上采用该窗口的上游监听作用域。
- 增加 listen_any / once_any，对应上游任意目标监听，命名与参考契约一致。
- 监听登记同时保存所有者、窗口代次和注销路径；窗口销毁清理窗口所有者的监听，应用退出清理所有剩余监听。
- unlisten 保留重复注销无副作用的行为；旧窗口的编号不能影响同标签新窗口的监听。
- 同步回调、一次监听、回调异常和 awaitable 拒绝沿用已有错误处理，避免 Python 异常变成 native panic。
- 语义调整：旧代码如果通过窗口注册应用监听，应明确传 window.app_handle()；这是当前部分实现向参考语义的修正，文档和测试同时更新。
- 六种目标可完整表示；独立 Window/Webview 资源尚未绑定时，不能宣称所有独立资源形态已验收。

## 实施结构

1. 核对六个目标、序列化及作用域契约，更新迁移说明和审核账本。
2. 原生事件发送/监听从 window.rs 拆到专门事件模块；保留 RuntimeState 为共享资源登记和失败处理入口。
3. 新增主线程任务模块，以可清空任务槽关联具体窗口代次，处理执行、提交失败、销毁与退出清理。
4. Python 扩展 events、manager、ffi 和 _native.pyi；继续使用 ECL 风格、完整类型及中文公共文档。
5. 新增三窗口事件/调度示例和独立桌面验收脚本，复跑已有示例与安装包验证。

## 验收标准

1. 后台线程提交零参数任务，实际回调在 Python/GUI 主线程执行；任务期间其他 Python 线程继续运行。
2. 模拟 ECL 的 run_on_main_thread → ffi.Emitter.emit_str_to → EventTarget.WebviewWindow 链路，目标前端收到 JSON 对象且其他窗口不收到。
3. 三窗口加应用原生监听核对 Any/App/AnyLabel/Window/Webview/WebviewWindow 的路由，显式区分对象作用域；缺少独立资源形态的条目保留限制。
4. listen_any、once_any、作用域 listen/once、重复 unlisten 和一次回调引用释放均有行为证据。
5. 窗口销毁、同标签重建、应用退出和任务提交失败后，没有旧任务或旧监听越过代次；弱引用证明资源释放。
6. 主线程任务与监听回调故意抛错、返回 coroutine 时有序退出并归还 Python；任务内同步建窗及时拒绝。
7. 未授权本地标签和外部页面仍不能通过新旧 IPC，增加事件目标不改变 ACL。
8. Python 3.11/3.14 的 pytest、真实 WebView、独立 wheel、源包重建，以及 Ruff/Pyright、Rustfmt/全 feature Clippy、覆盖核验通过。

## 完成判据

本阶段目标是补齐上述实际迁移链路与多窗口事件基础，不宣称 ECL 整体迁移完成，也不宣称全部事件/窗口 API 已引出。
执行记录应分别标注接口已绑定、调用已验收、资源形态/平台未验收。保持不提交、不推送、不发布，除非另获相应授权。

参考：[Tauri 事件目标](https://docs.rs/tauri/2.12.1/tauri/enum.EventTarget.html)、[监听语义](https://docs.rs/tauri/2.12.1/tauri/trait.Listener.html)、[窗口调度接口](https://docs.rs/tauri/2.12.1/tauri/webview/struct.WebviewWindow.html#method.run_on_main_thread)。

## 执行结果

接口、任务与监听的统一资源登记、窗口代次清理已完成；真实验收发现并覆盖原生移除与 Destroyed 通知之间的任务执行间隙。
Python 3.11/3.14 独立安装环境各 64 项测试通过、1 项环境跳过，各 16 个真实桌面进程通过。
新场景核验 26 项联合行为、六种目标及四种回调失败，旧场景继续核验标签/外部来源 ACL。
源包逐字节核验与重建、格式/类型/Clippy、83 项审核账本核验通过；第四阶段结果见 [验证记录](validation-phase4.md)，用法见 [事件指南](events.md)。
独立 Window/Webview 资源、过滤发送和其他平台仍未完成，没有提交、推送或发布。
