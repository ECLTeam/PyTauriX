//! 具有明确单位的尺寸与位置；拒绝无效原生几何数据。
use crate::binding_error;
use pyo3::prelude::*;

#[pyclass(frozen, get_all, module = "pytaurix.dpi")]
pub struct LogicalSize {
    pub width: f64,
    pub height: f64,
}
#[pyclass(frozen, get_all, module = "pytaurix.dpi")]
pub struct PhysicalSize {
    pub width: u32,
    pub height: u32,
}
#[pyclass(frozen, get_all, module = "pytaurix.dpi")]
pub struct LogicalPosition {
    pub x: f64,
    pub y: f64,
}
#[pyclass(frozen, get_all, module = "pytaurix.dpi")]
pub struct PhysicalPosition {
    pub x: i32,
    pub y: i32,
}

/// 保存有符号物理位置与无符号尺寸的不可变矩形。
///
/// 不拥有原生资源，工作区等查询使用此类型返回值快照。
#[pyclass(frozen, module = "pytaurix.dpi")]
pub struct PhysicalRect {
    pub inner: tauri::PhysicalRect<i32, u32>,
}

#[pymethods]
impl PhysicalRect {
    /// 创建物理像素矩形，复制有符号位置与无符号尺寸。
    ///
    /// 参数须为 PhysicalPosition 和 PhysicalSize；类型错误返回 TypeError。
    /// 返回不可变值快照，可跨线程读取，不拥有窗口或显示设备。
    #[new]
    fn new(position: &PhysicalPosition, size: &PhysicalSize) -> Self {
        Self {
            inner: tauri::PhysicalRect {
                position: tauri::PhysicalPosition::new(position.x, position.y),
                size: tauri::PhysicalSize::new(size.width, size.height),
            },
        }
    }

    /// 返回有符号物理位置副本。
    ///
    /// 无线程或窗口状态限制；修改返回值不会改变快照。
    #[getter]
    fn position(&self) -> PhysicalPosition {
        PhysicalPosition {
            x: self.inner.position.x,
            y: self.inner.position.y,
        }
    }

    /// 返回无符号物理尺寸副本，保留原生零尺寸。
    ///
    /// 无线程或窗口状态限制；不重新查询系统显示器。
    #[getter]
    fn size(&self) -> PhysicalSize {
        PhysicalSize {
            width: self.inner.size.width,
            height: self.inner.size.height,
        }
    }
}

#[pyfunction]
pub fn physical_size_payload(width: u32, height: u32) -> PhysicalSize {
    PhysicalSize { width, height }
}

#[pymethods]
impl LogicalSize {
    /// 创建逻辑像素尺寸，要求有限的正数。
    #[new]
    fn new(width: f64, height: f64) -> PyResult<Self> {
        if !width.is_finite() || !height.is_finite() || width <= 0.0 || height <= 0.0 {
            return Err(binding_error(
                "invalid_size",
                "Dimensions must be finite and positive",
            ));
        }
        Ok(Self { width, height })
    }
}
#[pymethods]
impl PhysicalSize {
    /// 创建物理像素尺寸，要求正整数。
    #[new]
    fn new(width: u32, height: u32) -> PyResult<Self> {
        if width == 0 || height == 0 {
            return Err(binding_error("invalid_size", "Dimensions must be positive"));
        }
        Ok(Self { width, height })
    }
}
#[pymethods]
impl LogicalPosition {
    /// 创建逻辑像素位置，允许有限负坐标。
    #[new]
    fn new(x: f64, y: f64) -> PyResult<Self> {
        if !x.is_finite() || !y.is_finite() {
            return Err(binding_error(
                "invalid_position",
                "Coordinates must be finite",
            ));
        }
        Ok(Self { x, y })
    }
}
#[pymethods]
impl PhysicalPosition {
    /// 创建有符号物理像素位置。
    #[new]
    fn new(x: i32, y: i32) -> Self {
        Self { x, y }
    }
}

pub fn size(value: &Bound<'_, PyAny>) -> PyResult<tauri::Size> {
    if let Ok(value) = value.extract::<PyRef<LogicalSize>>() {
        Ok(tauri::LogicalSize::new(value.width, value.height).into())
    } else if let Ok(value) = value.extract::<PyRef<PhysicalSize>>() {
        Ok(tauri::PhysicalSize::new(value.width, value.height).into())
    } else {
        Err(binding_error(
            "invalid_size",
            "Expected LogicalSize or PhysicalSize",
        ))
    }
}
pub fn position(value: &Bound<'_, PyAny>) -> PyResult<tauri::Position> {
    if let Ok(value) = value.extract::<PyRef<LogicalPosition>>() {
        Ok(tauri::LogicalPosition::new(value.x, value.y).into())
    } else if let Ok(value) = value.extract::<PyRef<PhysicalPosition>>() {
        Ok(tauri::PhysicalPosition::new(value.x, value.y).into())
    } else {
        Err(binding_error(
            "invalid_position",
            "Expected LogicalPosition or PhysicalPosition",
        ))
    }
}
