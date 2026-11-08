# 第十七阶段方案：IPC 取消与背压

状态：2026-11-08 用户要求实现 IPC 取消/背压、自定义协议与官方插件；首批插件定为「通用骨架 + fs 样板」。
本阶段只含 IPC 取消与背压；自定义协议与插件适配分别在后续阶段方案记录。
基线：Tauri 2.12.1、PyO3 0.29.3，沿用 `Cargo.lock`，不隐式升级依赖。

## 1. 上游事实与约束

- `InvokeResolver` 在 2.12.1 中实现 `Clone`，共享同一个 `Arc<Mutex<Option<responder>>>`。
- `InvokeResolver::return_result` 内部为 `responder.lock().unwrap().take().expect("resolver consumed")`。
  同一请求第二次应答会 panic，因此取消不能"再 reject 一次"。
- `InvokeMessage.payload` 不接受额外方法；前端 `invoke` 的 `options` 只使用 `headers`，
  `AbortSignal` 必须由前端桥自行实现。
- `Channel::send` 只表示提交成功，没有接收确认；上游不存在背压或流控设施。
- 自定义 `invoke_handler` 是原始分发入口，不经过插件 ACL；取消只作用于同一窗口标签登记的请求。

## 2. 取消契约

- 编号：前端生成 `request_id`（页面会话前缀 + 序号，≤96 字符），随新协议正文提交。
- 登记：原生按 `(窗口标签, request_id)` 登记 `PendingInvocation`；重复编号拒绝为 `duplicate_request_id`。
- 应答所有权：resolver 存放在 `Mutex<Option<_>>` 中，**取消与完成先取走者应答**，另一方静默丢弃结果。
- 取消来源：前端 `AbortSignal` → `pytaurix_cancel`；Python `Request.cancel()`。
- 结果：前端收到 `cancelled` 拒绝码；桥同时在本地立即以 `AbortError` 拒绝原 Promise。
- 旧协议（`plugin:pytauri|pyfunc`）没有编号，不参与取消，行为不变。
- 命令声明 `Request` 参数但请求没有编号时返回 `request_unavailable`，不静默注入空对象。
- **限制**：同步 Python 命令无法被中断（线程不可抢占），取消只保证应答与标志；
  异步命令在下一次 await 检查点观察到 `cancelled`，由命令自行提前返回。

## 3. 背压契约

- `Channel` 新增 `capacity`（默认 `0` = 不限制，保持现有语义）。
- `capacity > 0` 时启用窗口流控：在途数小于容量才允许发送，否则等待；等待期间通道关闭返回 `channel_closed`。
- 配额归还需前端配合：`pytaurix.createChannel(handler)` 在处理完消息后调用 `pytaurix_channel_ack`。
- 直接使用 `new Channel(...)` 的前端没有 ack，不得启用 `capacity > 0`；文档与指南必须写明。
- 显式 `timeout` 到期返回 `channel_backpressure`，不无限等待；不传 `timeout` 时等到配额或关闭。
- 发送失败（原生提交错误）回滚配额，避免泄漏容量。

## 4. 改动

| 位置 | 改动 |
| --- | --- |
| `crates/bindings/src/ipc.rs` | `PendingInvocation`、请求登记表、`Request` pyclass、取消与 ack 分发入口 |
| `crates/bindings/src/runtime.rs` | 持有请求登记表；退出时以 `app_closed` 拒绝全部待应答项 |
| `crates/bindings/src/channel.rs` | 通道流控窗口、配额获取/归还、`capacity` 与 `timeout` 参数 |
| `crates/bindings/src/resources.rs` | 按编号查找通道以归还配额 |
| `python/pytaurix/ipc.py` | `Request` 包装与注入、`invoke` 新参数、`channel_on(capacity=)`、`send(timeout=)` |
| `python/pytaurix/_native.pyi`、`ffi/ipc.py`、`__init__.py` | 同步类型与导出 |
| `frontend/bridge.js` | `AbortSignal` 取消、`createChannel` 配额归还包装 |
| `tests/test_request_cancel.py` | 注入、缺失编号、取消标志与重复注册契约 |
| 文档 | `ipc.md`、`channels.md`、`features.md`、能力矩阵、迁移契约 |

## 5. 不在范围

跨窗口广播取消、强制中止同步 Python 调用、任意 Rust `IpcResponse` 构造、ACK 之外的分片/优先级队列、
自定义协议与插件适配（另立阶段）。

## 6. 验收

1. Ruff、Ruff format、Pyright、pytest；Rustfmt 与适用 feature 组合 Clippy（`-D warnings`）。
2. 默认与最小 `wry` 组合构建；关闭 `custom-protocol` 等无关 feature 不受影响。
3. 契约测试覆盖：编号校验、重复编号拒绝、无编号时 `request_unavailable`、容量为 0 时行为不变。
4. 真实桌面证据：取消后前端 Promise 以 `AbortError`/`cancelled` 结束且工作线程结果被丢弃；
   容量生效时发送按配额推进。缺 Windows 会话时如实记录缺口。
5. 文档、类型存根与运行时能力同步；上游审核账本不为本阶段自有扩展新增条目（无对应上游声明）。

失败时回退本阶段源码改动，恢复上一份可运行 wheel；不改动 ECL 工作区与用户数据。
