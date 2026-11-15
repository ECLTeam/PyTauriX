# 协议扩展阶段方案：异步处理器、媒体流、window-state 回调与默认 features

状态：**阶段 A、B、C 已实施并提交（14e2a12 / a437e09，2026-11-15，桌面场景脚本待补）；
阶段 D 随 0.1.0a2 发版执行**

## 0. 背景与上游边界（先读）

- 使用方：ECL 已在自定义协议上落地 `ecl-img` 图片管线，并以「受控 URL + 令牌」模式替代了
  base64 Data URL 传输；ECL 仍为背景视频自维护一台本地回环 HTTP 服务
  （`ECL/desktop/background_media.py`，ThreadingHTTPServer + 令牌 + Range）。
- **上游硬边界（已锁定源码核实）**：Tauri 2.12.1 的 `UriSchemeResponder::respond`
  只接受 `T: Into<Cow<'static, [u8]>>`，自定义协议响应体**不支持流式**。
  「Python 生成器逐块交付、原生侧消费」的真正流式在本上游版本不可实现，
  记入 [能力矩阵](capability-matrix.md) 上游缺口；替代形态是 **Range/206 分块协作**：
  WebView 按 Range 逐块请求，处理器每次只读并返回一块，内存无压力——与
  BackgroundMediaService 的实际工作方式一致。
- [window-state 插件](plugins-window-state.md) 上游 2.4.0 提供 `with_filter(Fn(&str)->bool)`
  与 `map_label(Fn(&str)->&str)`；后者返回借用引用，Python 回调无法在不出借内存的前提下
  满足该签名，**map_label 暂缓**（方案见 §4 风险）。

## 1. 阶段 A：协议异步处理器（Python 层，零 Rust 改动）

目标：`create_protocol` 接受协程函数，ECL 的异步下载管线可直接作为协议处理器。

- `python/pytaurix/protocol.py`：`create_protocol(name, handler, *, portal=None)`。
  - 同步处理器：行为不变。
  - 协程函数：必须提供 portal（复用 commands 的 AnyIO portal 设施，规范 3.2
    「复用 AnyIO portal 与原生调度」）；缺 portal 时创建即报 `ValueError`，不静默自建循环。
  - 包装层语义：请求仍由 Rust 在阻塞工作线程调用包装函数；包装内经 portal 提交协程并
    等待结果（阻塞等待发生在线程，GUI 线程不受影响）。请求不可取消：连接提前断开时
    协程仍执行完毕，最终响应被原生丢弃——文档写明，不假装支持取消。
  - portal 关闭后到达的请求归还空 500（与现有异常路径一致）。
- 改动位置：`protocol.py`（`create_protocol`、`_serve` 包装）；无 Rust、无契约 breaking
  （新增可选关键字参数，预发布阶段按迁移契约记录）。
- 测试：同步行为回归不变；协程处理器经 portal 往返；缺 portal 报错；portal 关闭后请求 500。
- 验收：桌面场景新增 `async_protocol`（异步处理器经真实 WebView fetch 往返）。

## 2. 阶段 B：媒体流一等支持（Range/206 协作）

目标：把「用自定义协议服务大文件/视频」从调用方自行拼装升级为一等支持，为 ECL
`ecl-media` 替代 BackgroundMediaService 提供框架侧依据。

- `protocol.py`：`ProtocolRequest` 增加 `range` 只读属性——解析单范围 `Range` 头，
  返回 `RangeRequest(start, end, suffix)` 便捷结构；多范围/畸形头归一为 `None`
  （明确拒绝，不做部分降级）。`RangeRequest.resolve(total_size)` 产出
  `(start, length)` 并校验越界回退为全量 200。
- 提供响应助手 `file_range_response(path, mime, range)`：读块、生成
  206/Content-Range/Accept-Ranges/ETag 头；文件读取发生在 Rust 已提供的工作线程，
  不新增线程设施。`If-Range` 只支持 ETag 强校验（弱比较退化为全量）。
- 文档：[protocols.md](protocols.md) 增加「大文件与媒体流」章节；记录「多范围请求
  归一为全量」「连接断开不中断读取」两项明确行为。
- Rust 不改；`ProtocolResponse` 形状不变（bytes-only 上游边界不变）。
- 测试：Range 解析矩阵（正常/多范围/畸形/suffix/越界）、206/200 分支、If-Range。
- 验收：桌面场景扩展 `display_image` 或新增 `media_range`（真实 WebView `<video>` 播放）。

## 3. 阶段 C：window-state `with_filter` 暴露

目标：支持按 label 排除窗口，服务 ECL「非 singleton 插件窗口不参与持久化」与
临时窗口场景。

- Rust（`crates/bindings/src/plugins/window_state.rs` 或现有登记点）：描述符接受可选
  `filter` Python 回调，注册到上游 `Builder::with_filter`。
- 线程与安全边界（规范 4）：上游在窗口创建/保存时机调用 filter；回调内
  `Python::attach`，异常捕获后按「不保存该窗口」处理并记录日志，不 panic；
  回调仅访问 label 字符串，不注入应用句柄。
- Python：`init(handler 参数不变, filter=None)`；filter 必须同步可调用、返回布尔；
  非法在 `init` 时拒绝。
- `map_label` 暂缓：上游签名要求返回 `&str` 借用，Python 无法安全满足；记录于
  [plugins-window-state.md](plugins-window-state.md) 边界。
- 测试：filter 注册、异常降级、denylist 与 filter 组合语义；桌面验收复用现有
  window-state 场景加 denylist-like 过滤断言。

## 4. 阶段 D：默认 features 调整（发行窗口执行）

- `crates/bindings/Cargo.toml` default 增加 `plugin-window-state`、`plugin-single-instance`。
- 按[规范 6](../..//AGENTS.md)：核对最终 Cargo 依赖树（含 bridge 传递）、wheel 体积基线对比、
  sdist 重建、干净安装验收；`get_runtime_info()` 能力报告同步。
- 风险：所有依赖默认 wheel 的消费方（含 ECL CI）行为变化——ECL 侧 wheel 来源统一后
  删除本地重建说明；发版时确认 `0.1.0a1`（或下一个 alpha）不再有内容歧义 wheel。
- 本阶段在 A–C 完成后随发版执行，不阻塞前三阶段；发布另行授权。

## 5. 实施顺序与验证

1. 阶段 A → 阶段 B（同为 protocol.py，一次会话可连续完成）；
2. 阶段 C（Rust 改动，需 `--jobs 1` 构建 + 桌面验收）；
3. 阶段 D（发版窗口）。

验证命令沿用 [AGENTS 8.2](../../AGENTS.md)；每阶段提交前执行受影响仓库定向质量检查，
阶段 C/D 收口时按 API/构建变更类别执行全量要求。ECL 侧（`ecl-media` 替代
BackgroundMediaService）属 ECL 仓库独立方案，不在本文范围。

## 6. 待决策项

| # | 事项 | 说明 |
| --- | --- | --- |
| 1 | portal 注入形态 | 阶段 A 采用 `create_protocol(..., portal=...)` 显式注入；如希望与 `generate_handler(portal)` 同款由 Builder 统一注入，改动面扩大到 Rust，默认不选 |
| 2 | map_label 暂缓 | 上游借用签名限制；如确有需求需上游覆盖设计，单独立项 |
| 3 | 阶段 B 命名 | 助手函数归属 `protocol.py` 顶层还是独立 `media.py`，实施时按导入成本定 |
