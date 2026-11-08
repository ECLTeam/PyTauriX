# 自定义 URI scheme 协议

本绑定只提供**异步响应**版本的自定义协议：Python 回调在阻塞工作线程执行，
GUI 线程不等待。上游同步版本会在调用线程直接跑回调，由 Python 承担该风险没有安全收益，
因此不暴露。

## 用法

```python
from pytaruix import ProtocolResponse, builder_factory, context_factory, create_protocol

assets = create_protocol("appdata", lambda request: ProtocolResponse(body=b"ok"))


def themes(request):
    if request.method != "GET":
        return ProtocolResponse(status=405)
    return ProtocolResponse(
        status=200,
        headers=(("content-type", "application/json"), ("cache-control", "no-store")),
        body=b'{"themes":["dark","light"]}',
    )


context = context_factory(Path("examples/minimal"))
app = builder_factory().build(
    context=context,
    invoke_handler=commands.generate_handler(),
    protocols=[assets, create_protocol("appthemes", themes)],
)
app.run_return()
```

描述符在构建时被消费，重复使用会返回 `protocol_consumed`；名称重复返回 `duplicate_protocol`。

## 请求与响应

`ProtocolRequest` 是不可变快照：

| 字段 | 说明 |
| --- | --- |
| `uri` | 完整请求 URI |
| `method` | 大写方法名 |
| `headers` | 原始名称/值字符串元组 |
| `body` | 原始请求字节 |
| `webview_label` | 发起请求的 WebView 标签 |

`ProtocolResponse` 默认 `200`、无头字段、空正文。头字段按顺序追加，允许同名多次出现。

## 平台差异

自定义协议的 Origin 在不同平台不同，前端 `fetch` 若受 CORS 约束必须自行匹配：

- Windows / Android：`http://<scheme>.localhost/<path>`
- macOS / iOS / Linux：`<scheme>://localhost/<path>`

在 Windows 上使用 `https` 变体需要 WebView 的 HTTPS scheme 支持，当前未绑定该开关。

## 错误与线程

- scheme 必须是 ASCII 小写字母开头、只含小写字母/数字/`-+.`，长度不超过 32，
  且不能是 `tauri`、`asset`、`http`、`https`、`ipc`、`channel`。非法名称在创建时拒绝。
- 处理器必须是同步函数；异步函数在创建时以 `ValueError` 拒绝，避免运行时静默变成 500。
- 处理器抛异常、返回非 `ProtocolResponse`、状态码或头字段非法：原生归还**空 500**，
  异常不进入前端，也不终止应用。
- 应用尚未完成初始化时到达的请求归还 `503`，与 IPC 的等待语义一致。
- 回调不占用 GUI 线程，可以执行文件读取与编码转换；命令与协议共用同一套主线程约束。

## 安全边界

自定义协议不经过命令 ACL，也不扩大资源协议的授权范围。处理器拿到的是请求快照，
其中的来源标签由原生注入，不能由正文覆盖；需要按窗口区分数据时必须显式校验 `webview_label`。
响应不会自动添加 CORS 头，也不参与 CSP 哈希计算。

## 验收状态

契约测试覆盖名称校验、请求快照、返回值类型与默认响应；Windows 真实 WebView 的
`fetch` 往返证据待补，Linux/macOS 与移动平台另行验收。
