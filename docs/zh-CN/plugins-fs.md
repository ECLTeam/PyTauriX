# fs 插件

本页说明 `tauri-plugin-fs` 的 Python 入口。当前锁定 `2.6.0`，需要构建时启用 `plugin-fs` feature；
默认 wheel 不包含它。

## 用法

```python
from pytaurix import builder_factory
from pytaurix.plugins.fs import Fs, init

app = builder_factory().build(
    context=context,
    invoke_handler=commands.generate_handler(),
    plugins=[init()],
)

def setup(handle):
    fs = Fs(handle)
    fs.write_text("config.json", '{"theme":"dark"}')
    print(fs.read_text("config.json"))
```

`init()` 只创建描述符，不初始化 GUI；未启用 feature 时抛 `BindingError`（`unsupported_capability`）。
`Fs` 必须在已注册 fs 插件的应用里使用，否则返回 `plugin_missing`，不会让上游 `fs()` 直接 panic。

## 接口

| 方法 | 说明 |
| --- | --- |
| `read_text(path)` | 读取 UTF-8 文本；非 UTF-8 为 `fs_failed` |
| `read_bytes(path)` | 读取原始字节 |
| `write_text(path, contents)` | 写模式 + 创建 + 截断后写入 |
| `write_bytes(path, data)` | 同上，写字节 |

`path` 接受 `str` 或 `Path`，只做类型归一，不做规范化、不做存在性检查。
所有读写都在释放 GIL 的路径上执行。

## 一个必须说明的限制

上游的 Rust API（`Fs::open` / `read` / `read_to_string`）**不经过 capability scope 校验**：
`desktop.rs` 里就是对 `std::fs` 的直接封装。scope 只在前端命令层生效。

所以本绑定不提供"受限文件访问"：Python 侧本来就能用 `pathlib` 打开任意文件，
在这里加一层 scope 只是安全剧场。需要限制访问范围时，请在业务层显式校验路径。

同理，目录遍历、删除、重命名在上游只存在于命令层；Python 侧用 `pathlib` 做这些更直接，
本绑定不重复实现。

## 构建与验收

```powershell
uv run --no-sync maturin develop --locked --features plugin-fs
```

- 契约测试覆盖路径归一、类型拒绝、`Fs` 构造与运行时能力报告；未启用 feature 时的
  `init()` 拒绝由 `tests/test_plugin_fs_contract.py` 覆盖。
- Windows 真实读写在桌面场景中验证；Linux/macOS 与移动平台另行验收。
- `get_runtime_info()` 的 `fs_version` 与 `capabilities` 中的 `plugin.fs` 随 feature 变化。
