# 第七阶段方案：显示器、DPI 与图像加载

状态：已获用户“开始”授权，实施及 Windows/双版本打包验收完成。结果见 [验证记录](validation.md)。

## 推荐依据

第六阶段已完成原生 Channel，窗口、事件、dialog 与流式 IPC 的核心链路已有 Windows 真实验收。
当前矩阵仍缺显示器查询和编码图像解码；它们可沿用现有窗口代次、几何类型、RGBA 图像和 feature 转发。
显示器信息让应用自行处理多屏定位、工作区域和 DPI 换算；图像加载为窗口、后续菜单/托盘提供图标来源。

再次核对当前 ECL/adapters、ECL/api：只注册 dialog，窗口图标直接构造 RGBA。
没有发现 Monitor 查询或 TauriImage.from_bytes/from_path，因此本阶段不是当前 ECL 迁移的必要前置。
PyTauri 参考提供 Monitor 的五项属性及四种查询；其当前 Image Python 接口仅有 RGBA 构造和属性。
图像解码是本项目直接补齐上游 Tauri 能力的扩展，不宣称已存在同名 PyTauri 调用契约。

## 显示器与物理矩形

- WebviewWindow.current_monitor()/primary_monitor() -> Monitor | None。
- WebviewWindow.available_monitors() -> list[Monitor]。
- WebviewWindow.monitor_from_point(x, y, /) -> Monitor | None，坐标单位沿用上游物理像素，校验有限数值。
- pytaurix.ffi.window.Monitor：保留 name、size、position、work_area、scale_factor 属性形状。
- pytaurix.dpi.PhysicalRect：position 为 PhysicalPosition，size 为 PhysicalSize，保留有符号位置与无符号尺寸。

Monitor 是只读值快照，不拥有显示设备或窗口；重新查询才能取得新状态，旧快照不会自动反映设备拔插。
原生返回 None 不改写成异常；调用者窗口或应用失效仍用 window_closed/app_closed。
查询释放 GIL，支持工作线程；GUI 同步回调若存在阻塞约束须明确拒绝，不能留下挂起行为。
不隐式纠正窗口位置，不提供显示器模式切换或热插拔订阅，也不承诺所有设备有名称。
同标签重建继续拒绝旧窗口句柄。

## 图像加载与构建开关

- 沿用 pytaurix.ffi.image.Image，增加 from_bytes(encoded: bytes, /) 和 from_path(path: pathlib.Path, /)。
- 返回拥有 RGBA 的 Image，width/height/rgba 与现有构造结果一致；不引入 Pillow 或替代原生解码路径。
- 使用上游 image-png/image-ico；明确只承诺启用格式的 PNG/ICO，不默认宣称 JPEG/WebP/GIF 支持。
- 默认构建建议启用 PNG/ICO，保留显式关闭选项；需审核体积/依赖变化并记录。
- 关闭解码 feature 的构建保持根包、RGBA 构造与类型导入可用；解码调用明确返回 feature_unavailable。
- 从磁盘读取与解码释放 GIL；非 bytes/Path、损坏文件、未知格式、缺失路径和原生解码失败明确报错。

读取显式 Python 路径，沿用上游文件语义；不将图像路径混同于 context_factory 的资源根目录。
加载不注册 fs 插件，也不授予前端文件访问或图像插件权限。
RGBA 构造的默认参数和既有 API 不变；不同时扩展 Windows EXE 图标资源/句柄接口。

## 验收与交付

1. 使用真实 WebView 和独立系统显示查询对照主屏、所在屏、枚举、工作区、尺寸、位置及缩放。
   测试点位于工作区内部及全部显示器之外；当前硬件若只有单屏或单一 DPI，明确标记多屏/混合 DPI 未验收。
2. 用实际可用的屏幕/DPI 验证物理与逻辑位置/尺寸关系、负坐标类型和 None 语义。
   模拟值测试仅用于输入/类型契约，不能替代真实多屏、热插拔或混合 DPI 验收。
3. PNG/ICO 已知像素样本逐像素核对 RGBA、透明度与尺寸，比较字节和 Path 加载；验证损坏/不支持输入。
4. 加载结果用于真实窗口的构建图标及 set_icon；用原生窗口图标读取对照像素/尺寸。
   若环境不能验证外观，单独记录调用证据，不能提升为视觉效果验收。
5. 验证解码全关、仅 PNG、仅 ICO 和两者开启的构建/导入/错误行为；格式支持以对应构建为准。
6. 关闭、退出、同标签重建和工作线程行为；Python 3.11/3.14 独立 wheel、源包内容核验与实际重建。
7. 既有五个真实桌面脚本回归，Ruff/Pyright/pytest、Rustfmt/Clippy、能力矩阵和审核账本更新。

阶段开始前重新核验依赖稳定版本；default feature 的变化和解码依赖不得静默扩大平台/API 声明。
不同时实现菜单/托盘、其他插件、完整 Webview 管理、自动窗口位置恢复、移动平台或独立程序发布。
CI 跨平台验收仍是后续可靠性工作；Windows 结果不替代 Linux/macOS。

参考：[Tauri 窗口接口](https://docs.rs/tauri/2.12.1/tauri/webview/struct.WebviewWindow.html)、
[Monitor](https://docs.rs/tauri/2.12.1/tauri/window/struct.Monitor.html)、
[图像解码接口](https://docs.rs/tauri/2.12.1/tauri/image/struct.Image.html)。
