# 显示器、DPI 与图像

## 显示器快照

```python
from pytaruix.ffi.window import Monitor
from pytaruix.dpi import PhysicalPosition, PhysicalRect, PhysicalSize

monitor = window.current_monitor()
if monitor is not None:
    work_area: PhysicalRect = monitor.work_area
    print(monitor.name, monitor.scale_factor)
    print(work_area.position.x, work_area.position.y)
    print(work_area.size.width, work_area.size.height)
```

`window` 是已运行应用中的 WebviewWindow。四种查询保留 PyTauri 的方法名称和返回形状：

- `current_monitor()`：当前窗口所在屏幕。
- `primary_monitor()`：系统主屏幕。
- `available_monitors()`：屏幕快照列表，不保证稳定顺序。
- `monitor_from_point(x, y, /)`：包含物理像素坐标的屏幕，无匹配时沿用原生 None。

Monitor 的 `name/size/position/work_area/scale_factor` 均为只读属性；原生名称可能为 None。
位置采用有符号物理像素，负坐标不截断；工作区排除任务栏等系统保留区域，平台语义沿用 Tauri。
PhysicalRect 可以用 `PhysicalRect(PhysicalPosition(-1920, 0), PhysicalSize(1920, 1080))` 构造。
物理与逻辑像素按 scale_factor 换算；整数物理尺寸存在取整，不自动纠正窗口位置。

查询释放 GIL，支持命令或独立工作线程；GUI 同步回调可能持有原生窗口表锁，返回 `blocking_callback`。
可从工作线程查询，再通过 `run_on_main_thread` 提交 UI 操作；不要在 GUI 回调内等待工作线程完成。
未运行事件循环返回 `app_not_running`，失效应用/窗口分别返回 `app_closed/window_closed`，原生失败返回 `monitor_failed`。
点坐标必须有限，NaN/Infinity 返回 `invalid_position`，错误类型返回 TypeError。

Monitor/PhysicalRect 是值快照，不拥有窗口或显示设备。关闭后仍可读取旧快照，同标签重建仍拒绝旧窗口的查询。
设备和 DPI 变化后须重新查询；没有热插拔订阅、显示模式切换或自动窗口位置恢复。
Windows 已核对单屏 1600×900、100% DPI；多屏、混合 DPI、热插拔和其他平台未验收。

## 编码图像

```python
from pathlib import Path
from pytaruix import get_runtime_info
from pytaruix.ffi.image import Image

print(get_runtime_info().image_formats)
icon = Image.from_path(Path("application.png"))
same = Image.from_bytes(Path("application.png").read_bytes())
assert icon.rgba == same.rgba
window.set_icon(icon)
```

解码使用 Tauri 的原生 image 实现，不依赖 Pillow；图像独立拥有 RGBA 字节，保留 `width/height/rgba` 属性。
原来的 `Image(rgba, width, height, /)` 不变。from_bytes 只接受 bytes，from_path 只接受 pathlib.Path，错误类型返回 TypeError。
文件读取和解码释放 GIL，可在工作线程运行；显式路径沿用普通文件语义，不依赖应用资源根目录。
文件在同一次读取后检查容器并解码，避免二次读取产生格式检查与文件替换的竞态。
不注册 fs 插件，不增加前端文件访问权限，也不绑定 Windows EXE 图标资源或句柄接口。

默认启用 `image-png/image-ico`；`RuntimeInfo.image_formats` 和 `image.png/image.ico` 能力表示该构建允许的容器。
上游 ICO 内部依赖 PNG/BMP，绑定只接受明确启用的 PNG/ICO 外部容器，BMP/JPEG/WebP/GIF 不在公开契约内。
因此仅 ICO 构建仍可处理 ICO 内部的 PNG 图片，但独立 PNG 文件会返回 `feature_unavailable`。

- `feature_unavailable`：所需容器 feature 关闭；全部关闭时 from_path 不读取文件。
- `image_decode_failed`：字节损坏、未知或不支持的外部格式。
- `image_load_failed`：显式路径读取失败、文件内容损坏或不支持的格式。

例如构建只含 ICO 的 wheel：

```powershell
uv run --no-sync maturin build --locked --jobs 1 --no-default-features --features wry,image-ico
```

去掉 image-ico 即为全关，换成 image-png 即为仅 PNG。禁用默认 features 同时关闭默认 dialog/dynamic-acl 等能力，
其他能力需按需求显式添加；这不是运行时开关，不能用 Python 设置改变已经编译的格式。
四种格式组合均实际构建、安装并验证，根包和 RGBA 构造在全关时仍可使用。

窗口构建的 icon 与 set_icon 已读取 Windows 原生小图标，32×32 不透明样本的 4,096 字节 RGBA 全部一致。
透明度另由编码样本逐像素验证；本阶段不宣称原生图标的透明度合成或任务栏大图标效果已测量。
