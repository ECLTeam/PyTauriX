# 原生 IPC Channel

本绑定使用 Tauri 2.12.1 的原生 Channel，适合任务进度、日志和二进制片段。
公开形状参考 PyTauri：`pytaruix.ipc.JavaScriptChannelId[T]`、`Channel[T]`，
底层接口位于 `pytaruix.ffi.ipc`。不需要额外插件注册或前端 Channel 权限。

## 模型与来源窗口

```python
from pydantic import BaseModel
from pytaruix import Commands
from pytaruix.ipc import JavaScriptChannelId, WebviewWindow

commands = Commands()


class Progress(BaseModel):
    completed: int
    total: int


class Request(BaseModel):
    channel: JavaScriptChannelId[Progress]


@commands.command()
async def stream(body: Request, webview_window: WebviewWindow) -> None:
    channel = body.channel.channel_on(webview_window.as_ref_webview())
    try:
        channel.send_model(Progress(completed=1, total=1))
    finally:
        channel.close()
```

前端创建官方 SDK Channel，然后通过本项目的命令桥传入：

```javascript
import { Channel } from "@tauri-apps/api/core";

const channel = new Channel();
channel.onmessage = progress => console.log(progress);
await window.__TAURI__.pytaruix.pyInvoke("stream", { channel });
```

启用全局 SDK 的当前宿主也支持 `new window.__TAURI__.core.Channel()`。
旧 `window.__TAURI__.pytauri.pyInvoke` 字节协议同样可携带 Channel 字段或根模型。
Channel 标识在 JSON 中是 `__CHANNEL__:<u32>`，Pydantic 支持字符串输入、原生标识实例、根模型和模型字段。
模型校验失败产生 ValidationError；命令正文转换为 invalid_payload。
显式 from_str 的格式错误产生 BindingError 的 invalid_channel_id；错误类型遵循 Python TypeError。
序列化输出保留标识文本，schema 标注字符串，实际校验包含 u32 范围。

## 数据与线程

- `send(str)` 发送有效原始 JSON 文本，验证后保留原文。`send('"日志"')` 接收字符串，`send("null")` 接收 null。
- `send(bytes)` 接收 ArrayBuffer，空字节也保留二进制类型。bytearray、memoryview 和任意对象不会自动转换。
- `send_model(BaseModel)` 使用 model_dump_json 编码一次。泛型提供静态提示；运行时检查 BaseModel，不按泛型参数重新校验。
- JSON 与字节共用原生序号；小载荷直接执行，大载荷通过 Tauri 内部 fetch 取回。前端 SDK 缓冲失序帧。
- AnyIO 命令、后台 Python 线程和命令返回后的持续发送均支持；原生 send、close、channel_on 释放 GIL。
- 串行顺序与单生产者顺序保持。并发生产者的业务先后应由调用方协调，不规定线程之间的启动总顺序。

原生 JSON 与字节直传阈值分别为小于 8192 和 1024 字节；阈值及其附近均通过 Windows 真实 WebView2 验收。
`id()` 返回前端回调编号，关闭后仍可读取。

## 所有权与结束

`WebviewWindow.as_ref_webview()` 提供现有窗口的引用视图，保留原始窗口代次。
Webview 仅提供 label/app_handle，不能创建独立或嵌入 Webview，不能代表完整管理器接口。
同标签重建不会恢复旧 Webview 或 Channel。IPC 分发在排队前捕获来源窗口代次。

`close()` 是本项目提供的幂等扩展，所有包装共享同一个原生句柄的关闭状态。
之后 send 返回 channel_closed；窗口销毁返回 window_closed，应用退出返回 app_closed。
原生 send 的所有者状态错误优先于载荷校验；send_model 先由 Pydantic 编码再调用 send。
`closed` 包含显式关闭和所有者失效状态。
资源登记持弱引用，最后一个 Python 句柄释放也会 drop 原生 Channel，并由 Tauri 提交终止帧。
官方 SDK 在之前的消息收齐后注销回调；显式关闭不丢弃已经进入原生队列的消息。
窗口/应用清理会释放仍被后台持有的原生通道，窗口销毁清掉所属未拉取缓存。

每个前端 Channel 只建立一个原生发送句柄，再共享该句柄；重复 channel_on 同一编号会创建独立序号流和终止状态，
沿用上游行为，可能使接收方提前结束。不要为同一 JS Channel 重复建立互不共享的发送句柄。

## 权限与边界

编号不证明 JS 回调存在，也不是授权凭证；典型命令使用注入的来源窗口，不接受正文伪造来源。
from_str 只能验证格式，send 成功只表示原生接受提交，不确认前端业务处理完成。
不提供自动背压、接收确认、重连、业务任务取消或任意 Python 回调构造原生 Channel。

内部 `plugin:__TAURI_CHANNEL__|fetch` 在上游绕过普通命令 ACL；它用调用 Webview 标签及 Tauri-Channel-Id 查找一次性数据。
每个 Webview 有独立编号序列，窗口销毁由原生清理。该内部机制不授予 python_command、旧 pyfunc 或 dialog JS 权限。
本阶段未扩大本地精确标签策略，未授予远程页面权限。对应新旧 IPC 拒绝由既有动态窗口回归验证。
真实双窗口检查同编号的所有者隔离、重复/无效/缺失头字段拉取、销毁缓存和同标签重建。

运行 `python scripts/channel_smoke.py` 验收；完整可复现场景位于 examples/channel。
Windows 结果不能替代 Linux/macOS/移动平台验收。
参考：[官方指南](https://v2.tauri.app/develop/calling-rust/#channels)、
[锁定原生源码](https://docs.rs/tauri/2.12.1/src/tauri/ipc/channel.rs.html)。
