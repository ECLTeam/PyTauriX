# 桌面验收

`scripts/acceptance_desktop.py` 一次跑完两轮真实窗口，覆盖第十七至第二十二阶段的主要行为。
它需要真实 WebView，不能在没有桌面的环境里跑。

## 前置

构建必须包含四个插件：

```bash
CARGO_BUILD_JOBS=1 maturin develop --locked --features \
  plugin-fs,plugin-global-shortcut,plugin-notification,plugin-opener,\
plugin-single-instance,plugin-window-state
```

缺少插件时脚本直接退出码 2，并打印所需构建命令。

## 运行

```bash
.venv/Scripts/python scripts/acceptance_desktop.py
```

会依次弹出两个窗口，全程约十秒：

| 轮次 | 做的事 |
| --- | --- |
| 第一轮 | 固定窗口尺寸 → 触发取消 → fetch 自定义协议 → fs 写读 → 拉起第二实例 → 保存窗口状态 → 退出 |
| 第二轮 | 只读窗口尺寸，验证上一轮保存的几何是否被恢复 |

第二实例由脚本在第一轮检查完成后拉起，触发 single-instance 回调并把 argv 与 cwd 回传，
之后它自行退出。

## 判据

| 判据 | 含义 |
| --- | --- |
| `cancel_abort` | 前端 Promise 以 `AbortError` 结束 |
| `cancel_ack` | 原生的取消入口返回 `true`，即确实应答了本地登记项 |
| `protocol_status` | 自定义 scheme 的 `fetch` 返回 200 |
| `protocol_body` | 响应正文是协议处理器给出的 JSON |
| `fs_roundtrip` | 通过 fs 插件写入再读出的字节完全一致 |
| `python_saw_cancel` | Python 侧在检查点观察到 `request.cancelled` |
| `second_instance` | 第二实例的回调在第一实例收到 |
| `window_state_restored` | 第二轮的窗口尺寸与第一轮一致（容差 2 像素） |

全部通过时退出码 0，否则 1。

## 报告位置

每次运行在 `artifacts/desktop-acceptance-<时间戳>/` 下产出三份文件：

- `report.json`：判据、两轮结构化结果、问题列表
- `summary.md`：供人阅读的结论表
- `transcript.log`：两个进程的完整输出，失败时先看这里

`artifacts/` 不进版本库，报告是本地产物；账本里登记的证据指向脚本与示例源码，
而不是某一次运行目录。

## 这一轮跑出了什么

首次执行时 `cancel_ack` 与 `python_saw_cancel` 双失败，暴露出一个契约测试照不出的问题：

1. `pytaruix_cancel` 与 `pytaruix_channel_ack` 没有在 `build.rs` 的 `AppManifest::commands`
   里声明，ACL 直接报 `Command not found`；
2. 声明之后仍然被拒，因为本地自动授权只覆盖动态创建的窗口，
   配置文件声明的窗口拿不到这几条权限。

修复方式是两处补齐：`crates/bindings/build.rs` 声明三个命令，
`window_builder.rs` 的本地授权清单加上取消与配额归还，并在应用构建后为配置声明的窗口补授权。

自定义协议这一项也实测出必须显式返回 `access-control-allow-origin`，
否则页面 `fetch` 会被浏览器拦下——这条已写进[协议指南](protocols.md)。

## 还没覆盖的

`global-shortcut`、`notification`、`opener` 需要人手按键、肉眼确认通知、真实唤起默认程序，
不适合自动判定，账本里仍是 `bound_unverified`。Linux 与 macOS 也没有运行证据。
