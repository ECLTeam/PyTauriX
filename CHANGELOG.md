# 变更记录

本文件记录所有对外可见的变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [PEP 440](https://peps.python.org/pep-0440/)。

## [0.1.0a1]

首个公开预发布（PyPI）。Windows 通过真实桌面验收，Linux/macOS 仅有构建工作流，移动端未实现。

### 移除

- 移除 PyTauri 运行时兼容层：`pytauri` 前端全局入口、`plugin:pytauri|pyfunc` 旧字节协议、
  `pytauri:allow-pyfunc` 权限与 `ipc.legacy_pytauri` 能力项。
- 移除 `InvokeHandler` 与 `Commands.generate_handler()` 返回值的 `legacy` 参数。

### 变更

- 前端只保留 `window.__TAURI__.pytaurix.pyInvoke` 与 `createChannel`。
- `IPC 错误`统一为 `{code, message}` 对象，不再有旧协议的字符串形态。
- 字节正文命令（`body: bytes`）的载荷语义明确为：前端传字符串，按 UTF-8 取字节；
  Python 侧直接调用仍接受 `bytes`。
- README 重写为项目介绍，工程细节移入 `docs/` 与 `CONTRIBUTING.md`。

### 新增

- 采用 Apache-2.0 许可证，补充 `NOTICE`、`CONTRIBUTING.md`、`SECURITY.md` 与贡献模板。
- 应用与生命周期、命令与状态注入、原生 IPC Channel、事件与主线程调度。
- 动态窗口、WebView 策略回调、显示器与图像、菜单、托盘。
- IPC 协作式取消与通道配额流控。
- 构建期注册自定义 URI scheme。
- 官方插件：dialog、fs、single-instance、global-shortcut、notification、opener、window-state。
