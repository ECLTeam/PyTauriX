# IPC 命令、取消与背压

本页说明 JSON 命令协议的请求编号、协作式取消、通道流控与前端桥入口。
只存在这一条协议：`pytauri` 全局对象与 `plugin:pytauri|pyfunc` 已移除，没有不参与取消的第二入口。

## 请求编号与取消

前端带 `AbortSignal` 调用时，桥为每个请求生成编号（页面会话前缀 + 序号），
随正文提交到原生侧登记。取消有两个来源：

- 前端 `controller.abort()`：桥本地立即以 `AbortError` 拒绝 Promise，并调用 `pytaruix_cancel`。
- Python 侧 `request.cancel()`：立即拒绝前端 Promise，错误码为 `cancelled`。

```python
from pytaruix import CommandError, Commands, Request

commands = Commands()


@commands.command()
def slow_import(path: str, request: Request) -> str:
    if request.cancelled:
        raise CommandError("cancelled", "Request was cancelled")
    ...
    return "done"
```

```javascript
const controller = new AbortController();
window.__TAURI__.pytaruix.pyInvoke("slow_import", { path }, { signal: controller.signal });
controller.abort();
```

### 应答所有权

取消与完成竞争同一份 resolver，**先取走者应答，另一方丢弃结果**。这保证上游
`return_result` 只被调用一次（重复应答会 panic）。因此取消后工作线程可能仍在运行，
其结果不会被发送。

- 取消只保证应答与 `cancelled` 标志，不中断同步 Python 代码（线程不可抢占）。
- 异步命令在下一次 await 检查点观察到 `cancelled`，由命令自行提前返回。
- 重复编号返回 `duplicate_request_id`；编号只接受可打印 ASCII 且不超过 96 字符，
  否则为 `invalid_request_id`。
- 命令声明 `Request` 参数但请求没有编号时返回 `request_unavailable`，不注入空对象。
- 窗口销毁时该窗口的待应答项统一以 `window_closed` 结束，应用退出以 `app_closed` 结束。

## 通道流控

`channel_on(webview, capacity=N)` 启用配额：在途消息数小于 `N` 才允许发送。
配额由前端归还，原生不会自动扣减。

```python
channel = body.progress.channel_on(webview_window.as_ref_webview(), capacity=8)
channel.send_model(Progress(completed=1, total=8))
channel.pending  # 尚未归还的配额
```

前端必须使用本项目提供的包装，它在处理完每条消息后归还配额：

```javascript
const channel = window.__TAURI__.pytaruix.createChannel(async (progress) => {
  render(progress);
});
await window.__TAURI__.pytaruix.pyInvoke("explain", { channel });
```

- `capacity=0`（默认）不限制，保持既有行为。
- 直接 `new Channel(...)` 的前端没有 ack，**不要**启用 `capacity > 0`，否则发送会一直等到通道关闭。
- `send(data, timeout=秒)` 到期返回 `channel_backpressure`；省略 `timeout` 表示等到配额或关闭。
- 原生提交失败时回滚配额，避免容量被一条永远无法 ack 的消息占住。
- ack 只归还来源窗口自己的通道，其他窗口的编号不生效。

## 前端桥入口

| 入口 | 用途 |
| --- | --- |
| `window.__TAURI__.pytaruix.pyInvoke(command, payload, { signal, onCancelResult })` | 新协议，可取消 |
| `window.__TAURI__.pytaruix.createChannel(onmessage)` | 带配额归还的 Channel |
| `window.__TAURI__.pytauri.pyInvoke(command, body, options)` | 旧字节协议，不可取消 |

`pytaruix_cancel` 与 `pytaruix_channel_ack` 由原始分发入口处理，不执行 Python 代码；
两者都只作用于来源窗口登记的请求或通道，请求编号与通道编号都不是授权凭证。

`onCancelResult` 可选，收到原生取消入口的返回值：`true` 表示本次取消确实应答了本地登记项，
`false` 表示登记项已结束或不存在，错误对象表示这次取消请求本身没有被原生接受。
它不改变 Promise 的拒绝行为，只用于观测。

这两个入口是应用命令，**必须在 `build.rs` 的 `AppManifest::commands` 里声明**，
并在窗口的 capability 中授予 `allow-pytaruix-cancel` 与 `allow-pytaruix-channel-ack`；
缺任一条，前端会收到 `not allowed`，取消与配额归还都不会生效。

## 边界

不提供跨窗口广播取消、强制中止同步调用、优先级队列、分片重传或前端 Codec 分帧策略。
Windows 桌面证据由 `scripts/acceptance_desktop.py` 产出：取消以 `AbortError` 结束、
原生取消入口返回 `true`、Python 在检查点观察到 `cancelled`，见[桌面验收](desktop-acceptance.md)。
Linux/macOS 与移动平台另行验收。
