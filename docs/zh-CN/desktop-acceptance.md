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

Linux 与 macOS 没有运行证据；通知的 `silent=True` 实际静默效果、热键与输入法的冲突、
多显示器变化下的窗口位置修正仍未验证。这三项之外的原“需要人手确认”部分已由下面的插件行为验收覆盖。

## 插件行为验收

`global-shortcut`、`notification`、`opener` 的真实行为需要按键、肉眼与外部程序，
不适合放进上面那套全自动判据。第二十五阶段新增了独立入口：

```bash
.venv/Scripts/python scripts/plugin_behavior_acceptance.py
```

驱动脚本拉起 `examples/plugin_behavior`，后者在 Ready 后于后台线程依次执行三组检查。
能自动判定的部分不留人工环节，只有无法机器观察的三项用原生消息框询问：

| 判据 | 判定方式 | 做法 |
| --- | --- | --- |
| `shortcut_registered` | 自动 | 注册后 `is_registered` 为真 |
| `shortcut_fired` | 自动 | 应用用 `SendInput` 合成 Ctrl+Alt+F9，处理器收到 `control+alt+F9` |
| `shortcut_duplicate_rejected` | 自动 | 重复注册同一快捷键返回 `shortcut_failed` |
| `shortcut_unregistered` | 自动 | 注销后 `is_registered` 为假 |
| `shortcut_unregister_all` | 自动 | 批量注销后 `is_registered` 为假 |
| `notification_permission_granted` | 自动 | `permission_state` 与 `request_permission` 均为 `granted` |
| `notification_visible` | 人工 | 消息框询问是否看到带时间戳的通知 |
| `opener_url_hit` | 自动 | 默认浏览器访问本地 HTTP 服务，收到真实请求 |
| `opener_path_opened` | 人工 | 消息框询问记事本是否打开了探测文件 |
| `opener_revealed` | 人工 | 消息框询问文件管理器是否选中该文件 |

合成按键失败时退化为人手按键：窗口置顶并把标题改成提示文本，30 秒内等待回调，
结果里的 `shortcut_manual` 记录这一轮走的是哪条路径。报告写到
`artifacts/plugin-behavior-<时间戳>/`，包含 `raw.json`、`report.json`、`report.md` 与 `console.log`。

首轮执行暴露一个示例自身的问题：确认框依赖 dialog 插件，而示例只注册了三个被测插件，
第一项人工确认直接报 `plugin_missing`。补上 `dialog_init()` 后十项全部通过。
这也说明人工环节不该隐式依赖未声明的插件。
