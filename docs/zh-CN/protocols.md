# 自定义 URI scheme 协议

本绑定只提供**异步响应**版本的自定义协议：Python 回调在阻塞工作线程执行，
GUI 线程不等待。上游同步版本会在调用线程直接跑回调，由 Python 承担该风险没有安全收益，
因此不暴露。

## 用法

```python
from pytaurix import ProtocolResponse, builder_factory, context_factory, create_protocol

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
- 同步处理器在阻塞工作线程执行；协程函数作为处理器时必须显式提供
  `create_protocol(name, handler, portal=...)` 的阻塞 portal（与命令桥的
  `start_blocking_portal` 设施一致），缺失或形状不符在创建时以 `ValueError` 拒绝。
  协程经 portal 事件循环调度并阻塞等待，阻塞发生在工作线程，GUI 线程不受影响。
- 请求不可取消：连接提前断开时处理器仍执行完毕，最终响应由原生丢弃。
- 处理器抛异常、返回非 `ProtocolResponse`、状态码或头字段非法：原生归还**空 500**，
  异常不进入前端，也不终止应用。portal 关闭后到达的请求同样归还空 500。
- 应用尚未完成初始化时到达的请求归还 `503`，与 IPC 的等待语义一致。
- 回调不占用 GUI 线程，可以执行文件读取与编码转换；命令与协议共用同一套主线程约束。

## 大文件与媒体流

上游 Tauri 2.12.1 的自定义协议响应体只支持一次性字节，不提供流式交付。大文件的
替代形态是 **Range/206 分块协作**：WebView 按 `Range` 逐块请求，处理器每次只读
并返回一块，内存无压力。

- `ProtocolRequest.range` 解析单个 `Range` 头，支持 `bytes=A-B`、`bytes=A-` 与
  `bytes=-N`；缺失、多范围或畸形头归一为 `None`（明确拒绝，不做部分降级）。
- `RangeRequest.resolve(total_size)` 产出 `(start, length)`；空资源、`suffix`
  非正或 `start` 越界返回 `None`，调用方回退全量 200。
- `file_range_response(path, mime, range=..., if_range=...)` 从文件构建响应：
  可满足时返回 206 与 `Content-Range`/`Accept-Ranges`/`ETag`；`If-Range` 只做
  ETag 强比较，弱 ETag 与日期形态按不匹配回退全量；全量回退会读取整个文件，
  应仅用于能被 WebView 按 Range 逐块请求的场景。
- `ETag` 由文件修改时间与大小生成；文件被替换后浏览器缓存自然失效。
- 与前端快照资源同路径的 URL 会命中前端快照而不是自定义协议处理器；
  协议承载的媒体文件不要放进 `frontendDist` 目录。
- 前端要读取 `ETag`/`Accept-Ranges`/`Content-Range` 等响应头时，处理器必须返回
  `access-control-expose-headers`（CORS 安全清单外的响应头对 JS 不可见）。
- 请求带 `If-Range` 这类非安全清单请求头时，WebView 会先发 OPTIONS 预检
  （`access-control-request-headers: if-range`）；处理器必须应答预检
  （200/204 + `access-control-allow-headers`），否则 fetch 直接网络级失败。
  以上两条均经 Windows 桌面场景实测确认。

## 安全边界

自定义协议不经过命令 ACL，也不扩大资源协议的授权范围。处理器拿到的是请求快照，
其中的来源标签由原生注入，不能由正文覆盖；需要按窗口区分数据时必须显式校验 `webview_label`。
响应不会自动添加 CORS 头，也不参与 CSP 哈希计算。页面与 scheme 属于不同 origin，
从页面 `fetch` 时必须由处理器显式返回 `access-control-allow-origin`，否则浏览器会拦下请求；
这条在 Windows 实测中确认过。

## 验收状态

契约测试覆盖名称校验、请求快照、返回值类型与默认响应、异步处理器经 portal 调度、
`Range` 解析与 `file_range_response` 的 200/206 分支。Windows 真实 WebView 的 `fetch`
往返已通过[桌面验收](desktop-acceptance.md)验证：`http://acceptance.localhost/ping` 返回 200
且正文与处理器一致。异步处理器与媒体流 Range 已由 `scripts/protocol_scenarios_smoke.py`
在 Windows 真实 WebView 上验收：协程处理器 fetch 往返、4 MiB 模式文件 16 块 Range
步进拼接、206/Content-Range、If-Range 协商与回退全部通过。
Linux/macOS 与移动平台另行验收。
