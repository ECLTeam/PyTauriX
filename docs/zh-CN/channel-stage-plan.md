# 第六阶段方案：原生 IPC Channel 与流式消息

状态：用户已明确“开始”授权，范围实现及 Windows 双版本 wheel、源包重建验收完成。

交付：102 项测试通过、1 项符号链接权限跳过；每个版本 25 个真实桌面进程通过。
Channel 双窗口场景有 73 项联合检查；核心审核账本 89 项，具体证据见 validation.md 和 channels.md。

## 优先级依据

第五阶段已完成 dialog 桌面子集、插件注册与关闭清理。
当前 ECL 仍在 ECL/api/bridge.py 通过 run_on_main_thread 和 emit_str_to 发送进度事件；
ECL/api/windows.py 直接构造 RGBA 图标。核对当前代码，没有发现原生 Tauri Channel 或监视器调用。
因此 Channel 是通用框架完整绑定的下一项核心能力，不把它称为 ECL 当前迁移的必要前置。

本阶段支持后端持续输出任务进度、日志和二进制片段。
官方将 Channel 用于流式数据；锁定 Tauri 2.12.1 已实现消息序号、JSON/原始字节路径和大载荷拉取。
参考当前 PyTauri 的 ipc.JavaScriptChannelId/Channel、ffi.ipc，以及锁定上游 src/ipc/channel.rs。
不修改 ECL、参考 checkout 或原有事件协议。

## 公开接口与迁移形状

- pytaruix.ffi.ipc：原生 JavaScriptChannelId.from_str、channel_on，以及 Channel.id/send。
- pytaruix.ipc：Pydantic 可用的 JavaScriptChannelId[T] 和 Channel[T]，保留 from_str、channel_on、id、send、send_model。
- WebviewWindow.as_ref_webview()：提供归属于现有窗口代次的 Webview 引用视图，用于参考的 channel_on 形状。
- Webview 引用不拥有新窗口；本阶段不开放独立 Webview 建造、多嵌入 Webview 或完整 Webview 管理器。
- 本项目新增 Channel.close() 与 closed，给后台持有通道的调用方提供明确的资源结束方式；保留旧方法和默认行为。

建议使用形状：

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

Channel 必须来自真正的前端 Tauri Channel，使用其原生标识与传输机制。
不把事件发送重新包装为 Channel；标识解析和 Pydantic 模型字段均有独立行为检查。

## 载荷、线程和生命周期

1. send(str) 对齐参考的原始 JSON 文本语义，验证 JSON 后保留原文；send(bytes) 对应前端 ArrayBuffer。
   send_model 只编码一次；类型校验边界及 from_str 错误逐项定义，不用类型注解冒充运行时校验。
2. 操作保持支持工作线程和 AnyIO 命令；原生发送释放 GIL，访问 Python 对象正确 attach。
   不开放任意 Python 回调构造原生 Channel，以免引入额外回调/线程协议。
3. 通道绑定应用和原始 WebviewWindow 代次；关闭、显式 close 和 GC 可释放原生通道，
   不能因共享登记无限延长最后一个 Python 通道句柄的寿命。
4. 显式 close 幂等，之后 send 返回 channel_closed；所有者退出/销毁按 app_closed/window_closed 处理。
   同标签重建不能复活旧通道，终止帧和待拉取载荷的清理需用真实前端验证。
5. 合法 Channel 编号只是回调标识，不是授权凭证。典型命令用注入的来源窗口建立通道。
   from_str 不能证明前端回调存在；send 成功只表示原生接受提交，不代表前端业务回调处理完成。
6. close 只结束通道，不承诺取消后台业务任务、等待前端确认或提供自动背压。
   通用命令取消、重连、确认协议与全量 channel_interceptor 留待后续设计。

## 原生传输与权限审核

Tauri 2.12.1 小 JSON 和小字节数据直接执行，大载荷通过内部 fetch 命令取回；
当前源码阈值分别为 8192 和 1024 字节，验收同时覆盖两侧及混合发送，不能只测小载荷。
内部缓存按 Webview 标签划分，插入时检查原生注册状态，销毁时清理；
绑定还须核验窗口代次、关闭时机和同标签重建，不能仅依赖字符串标签。

实施时审核内部 plugin:__TAURI_CHANNEL__|fetch 与 Tauri-Channel-Id 请求头、一次性取回及来源检查。
保留精确本地标签策略；不增加通配窗口、远程来源或 dialog JS 权限。
真实前端核验跨窗口缓存隔离、重复/非法取回和未授权页面的新旧 IPC 拒绝。
不要把 Native SDK 没有提供的回调存在检查或接收确认写成绑定承诺。

## 验收与交付

- 两个以上真实 WebView 接收各自的模型进度、日志 JSON 与二进制片段。
- 字符串/null/嵌套 JSON/Unicode、原始 JSON 文本、Pydantic、空与较大字节载荷均核验实际前端值。
- 串行发送顺序与混合大小数据完整性，多线程发送和命令返回后继续发送；不虚构跨线程业务总顺序。
- 无效标识/JSON/模型明确拒绝；有效但未注册的 JS 回调不宣称可自动检测。
- close/GC 终止帧、窗口销毁、应用退出、同标签重建、旧句柄拒绝和原生缓存隔离。
- Windows Python 3.11/3.14 独立 wheel、源包逐字节核验与解压重建；
  既有四个桌面脚本回归，Ruff/Pyright/pytest、Rustfmt/Clippy 和审核账本通过。
- 更新迁移契约、能力矩阵、运行时能力和 Channel 指南；选定条目加入核心账本，不把声明数当覆盖率。

实施前重新核验稳定依赖；如需改变已审核基线，先说明差异，不静默升级。
本阶段不同时扩展菜单/托盘、图像解码、监视器、其他官方插件、独立程序打包或移动平台。
其他桌面平台需后续在对应环境真实验收；不提交、推送或发布。

参考：[官方 Channel 指南](https://v2.tauri.app/develop/calling-rust/#channels)、
[锁定源码](https://docs.rs/tauri/2.12.1/src/tauri/ipc/channel.rs.html)、
[当前能力矩阵](capability-matrix.md)。

