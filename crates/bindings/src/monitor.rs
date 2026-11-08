//! 显示器只读快照；查询共享窗口代次和应用运行状态检查。
use crate::{
    binding_error,
    dpi::{PhysicalPosition, PhysicalRect, PhysicalSize},
    window::WebviewWindow,
    window_state::Scope,
};
use pyo3::prelude::*;
use std::sync::atomic::Ordering;

/// 保存名称、物理几何与缩放比的不可变显示器快照。
///
/// 只能通过窗口查询获得；窗口关闭后仍可读取，不自动反映设备变化。
#[pyclass(frozen, module = "pytaruix.ffi.window")]
pub struct Monitor {
    pub inner: tauri::window::Monitor,
}

#[pymethods]
impl Monitor {
    /// 返回显示器名称，原生未提供名称时返回 None。
    ///
    /// 本属性读取查询时快照，可跨线程读取，窗口关闭后仍有效。
    #[getter]
    fn name(&self) -> Option<String> {
        self.inner.name().cloned()
    }

    /// 返回显示器物理像素尺寸副本。
    ///
    /// 本属性读取查询时快照，无窗口状态或线程限制。
    #[getter]
    fn size(&self) -> PhysicalSize {
        PhysicalSize {
            width: self.inner.size().width,
            height: self.inner.size().height,
        }
    }

    /// 返回显示器在虚拟桌面的有符号物理位置副本。
    ///
    /// 负坐标保持原值；本属性读取快照，不随设备变化自动刷新。
    #[getter]
    fn position(&self) -> PhysicalPosition {
        PhysicalPosition {
            x: self.inner.position().x,
            y: self.inner.position().y,
        }
    }

    /// 返回排除任务栏等系统区域的物理工作区副本。
    ///
    /// 平台语义沿用 Tauri；本属性可跨线程读取，不拥有显示设备。
    #[getter]
    fn work_area(&self) -> PhysicalRect {
        PhysicalRect {
            inner: *self.inner.work_area(),
        }
    }

    /// 返回查询时的物理像素与逻辑像素缩放比。
    ///
    /// 平台语义沿用 Tauri；设备变化后须重新查询取得新快照。
    #[getter]
    fn scale_factor(&self) -> f64 {
        self.inner.scale_factor()
    }
}

pub fn query<T: Send>(
    py: Python<'_>,
    window: &WebviewWindow,
    operation: impl FnOnce() -> tauri::Result<T> + Send,
) -> PyResult<T> {
    window.ensure_active()?;
    // 同步 GUI 回调可能已持有 Wry 的窗口表锁；禁止重入原生显示查询。
    if Scope::in_callback() {
        return Err(binding_error(
            "blocking_callback",
            "Monitor queries cannot run in synchronous GUI callbacks",
        ));
    }
    if !window.handle.runtime.running.load(Ordering::SeqCst) {
        return Err(binding_error(
            "app_not_running",
            "Monitor queries require the running event loop",
        ));
    }
    let result = py.detach(operation);
    window.ensure_active()?;
    result.map_err(|error| binding_error("monitor_failed", error))
}
