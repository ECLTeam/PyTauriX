# 第十八阶段方案：自定义协议

状态：2026-11-08 与第十七阶段同批推进；实现完成，真实 WebView 往返证据待补。
基线：Tauri 2.12.1、PyO3 0.29.3，沿用 `Cargo.lock`。

## 1. 目标与约束

为 Python 提供注册自定义 URI scheme 的能力，替代无法在运行期配置的上游资源协议。

- 上游有同步 `register_uri_scheme_protocol` 与异步 `register_asynchronous_uri_scheme_protocol`。
  同步版本在调用线程执行回调，Python 回调可能直接卡住 GUI 线程，因此**只提供异步版本**。
- 异步版本回调带 `UriSchemeResponder`，可以在任意线程 `respond`；Python 处理放在
  `spawn_blocking` 工作线程，等待应用初始化后才读取运行时状态。
- 协议必须在构建期登记，运行期不能再添加；描述符一次性消费。

## 2. 契约

- `create_protocol(name, handler)` 返回描述符，`Builder.build(protocols=[...])` 消费。
- scheme：ASCII 小写字母开头，只含小写字母、数字、`-`、`+`、`.`，长度 ≤ 32，
  并排除 `tauri`/`asset`/`http`/`https`/`ipc`/`channel`。非法为 `invalid_protocol_name`。
- 处理器必须同步；异步函数在 Python 侧以 `ValueError` 拒绝。
- `ProtocolRequest` 为不可变快照（uri/method/headers/body/webview_label）。
- `ProtocolResponse` 默认 200/无头/空正文；头字段按顺序追加，允许重复名称。
- 处理器异常、返回类型错误、状态码或头字段非法 → 空 500；应用未就绪 → 503。
- 名称重复为 `duplicate_protocol`，重复消费为 `protocol_consumed`。
- 协议不经过命令 ACL，也不扩大资源协议授权；CORS 头不由本层补充。

## 3. 改动

| 位置 | 改动 |
| --- | --- |
| `crates/bindings/src/protocol.rs` | 新增 `Protocol`、`protocol_create`、异步注册与响应转换 |
| `crates/bindings/src/application.rs` | `Builder.build(protocols=)`、名称唯一性校验与构建期登记 |
| `crates/bindings/src/lib.rs` | 模块注册 |
| `python/pytaruix/protocol.py` | `ProtocolRequest`、`ProtocolResponse`、`create_protocol`、原生适配 |
| `python/pytaruix/application.py` | `protocols` 参数与描述符校验 |
| `python/pytaruix/_native.pyi`、`__init__.py` | 类型与导出 |
| `tests/test_protocol_contract.py` | 名称校验、请求快照、返回值类型、默认响应 |
| 文档 | 新增 `protocols.md`，同步 features / 矩阵 / 迁移契约 |

## 4. 不在范围

同步协议回调、HTTPS scheme 开关、CORS 自动处理、CSP 哈希、响应流式分片、移动平台验收。

## 5. 验收

1. Ruff、Ruff format、Pyright、pytest；Rustfmt 与默认/最小 feature Clippy（`-D warnings`）。
2. 契约测试覆盖名称规则、快照字段、非响应返回值、默认响应与描述符状态。
3. Windows 真实 WebView `fetch` 往返与 500/503 行为待补；缺失时如实记录。
4. 文档与类型存根同步；未绑定的上游能力明确列在能力矩阵。

失败时回退本阶段改动，不影响第十七阶段已完成的取消与流控。
