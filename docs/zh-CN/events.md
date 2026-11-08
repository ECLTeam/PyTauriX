# 事件与主线程调度

第四阶段提供六种明确目标、原始 JSON 发送、应用/窗口监听作用域和可清理的 GUI 任务。
根入口沿用 PyTauri 常见名称；尚未绑定过滤发送或独立 Window/Webview 资源创建。

## ECL 桥接调用

```python
from pytaruix import EventTarget
from pytaruix.ffi import Emitter


def update_ui() -> None:
    window.set_title("已更新")
    Emitter.emit_str_to(window, EventTarget.WebviewWindow(window.label()), "updated", '{"ready":true}')


window.run_on_main_thread(update_ui)
```

run_on_main_thread 接受零参数同步回调，返回 None，只表示原生提交成功。后台线程提交后即可继续，GUI 线程调用时上游可能立即执行回调。
执行时 attach Python，回调异常有序退出并由 App.run_return 重抛；返回 coroutine 会关闭它并返回 invalid_callback。
调度方法不会等待任务结束，不要在 GUI 回调内等待依赖 GUI 队列的工作线程。
任务也属于 GUI 回调上下文，同步建窗返回 would_block；异步命令建窗使用 WebviewWindowBuilder.build_async。

应用/窗口关闭后提交返回 app_closed/window_closed。窗口任务归属于原始代次，进入 Python 前核对代次与原生窗口是否仍存在。
原生窗口可能先移除，随后才派发 Destroyed；任务额外检查原始原生窗口 ID，覆盖这个间隙。
CloseRequested 后仍可能先执行一个任务；已经开始的回调不会被强制终止。窗口销毁和应用退出释放剩余任务引用。

## 目标路由

```python
from pytaruix import Emitter, EventTarget, Listener

Emitter.emit_to(app_handle, EventTarget.WebviewWindow("child"), "updated", {"ready": True})
listener_id = Listener.listen(window, "updated", lambda event: print(event.payload()))
Listener.unlisten(window, listener_id)
```

| 目标 | 匹配 |
| --- | --- |
| Any() | 全部监听作用域与窗口 |
| App() | 应用目标 |
| AnyLabel(label) 或字符串 | 同标签 Window/Webview/WebviewWindow 目标 |
| Window(label) | 指定 Window 目标 |
| Webview(label) | 指定 Webview 目标 |
| WebviewWindow(label) | 指定 WebviewWindow 目标 |

任意目标监听器本身会收到所有定向事件，包括没有对应窗口的目标。定向发送不会自动把 Any 监听器变成隔离监听器。
官方前端 event.listen 默认采用 Any；需要隔离时显式指定 `{ target: { kind: "WebviewWindow", label } }`，或使用当前 WebviewWindow 的 listen 方法。
事件目标不改变 IPC 权限：未授权标签和外部来源仍被原生 ACL 拒绝。

根 Emitter.emit/emit_to 接受模型或 JSON 值并编码一次；ffi.Emitter.emit_str/emit_str_to 接受已经编码的 JSON 文本。
原生层用 serde_json 验证后调用上游 emit_str/emit_str_to，保留原始文本、Unicode 和数字字面量，不将整个 JSON 再编码成字符串。
无效 JSON 返回 invalid_json，事件名非法返回 invalid_event；拒绝发送不关闭应用，随后仍可发送正常事件。

## 监听作用域与清理

- Listener.listen/once：App 或 AppHandle 使用 App 作用域，窗口使用该 WebviewWindow 作用域。
- Listener.listen_any/once_any：监听所有目标；由提交的应用或窗口代次拥有。
- 窗口销毁清理其 scoped/any 监听；应用退出或未运行 App 析构清理剩余监听和排队任务。
- 一次监听在调用前取走回调并注销；递归发送不会重复执行，也不会触发上游一次回调的二次取值 panic。
- 回调必须同步，可在发出事件的线程执行；共享状态由使用者同步。异常和 awaitable 与 GUI 任务使用相同失败通道。
- 重复/未知编号注销无副作用；活动的其他窗口编号返回 listener_owner。应用句柄可以注销本绑定所有登记编号，不能用该入口注销任意插件原生监听。

旧原型把窗口监听归一成应用监听；需要保持应用作用域的旧代码应传 window.app_handle()。
同标签重建产生新代次，旧句柄无法注销新窗口监听或提交新任务。

## 验收边界

examples/event_dispatch 与 scripts/event_dispatch_smoke.py 使用三个实际 WebView，核对六种目标、JSON 载荷、后台线程调度、任务上下文、窗口关闭/重建、弱引用释放及四种回调失败。
独立进程单元测试另验收主循环前丢弃 App 时排队任务释放、关闭后拒绝提交、一次监听递归发送和原始 JSON 文本保持。
Windows 上验证原生 App/WebviewWindow 监听与显式 JS Window/Webview 目标；未创建独立 Window/Webview 或多嵌入 WebView，其他平台尚未验收。
