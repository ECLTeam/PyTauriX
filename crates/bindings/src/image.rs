//! 自有 RGBA 图像与显式 feature 控制的原生 PNG/ICO 解码。
use crate::binding_error;
use pyo3::{
    exceptions::PyTypeError,
    prelude::*,
    types::{PyBytes, PyType},
};

pub fn formats() -> Vec<&'static str> {
    let mut formats = Vec::new();
    if cfg!(feature = "image-png") {
        formats.push("png");
    }
    if cfg!(feature = "image-ico") {
        formats.push("ico");
    }
    formats
}

#[cfg(any(feature = "image-png", feature = "image-ico"))]
fn check_format(bytes: &[u8]) -> Result<(), (&'static str, &'static str)> {
    // image/ico 间接启用 PNG/BMP；只允许本绑定明确启用的外部容器格式。
    let enabled = if bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        cfg!(feature = "image-png")
    } else if bytes.starts_with(b"\x00\x00\x01\x00") {
        cfg!(feature = "image-ico")
    } else {
        return Err((
            "image_decode_failed",
            "Only PNG and ICO containers are supported",
        ));
    };
    if !enabled {
        return Err((
            "feature_unavailable",
            "The image container decoder is disabled",
        ));
    }
    Ok(())
}

#[pyclass(frozen, module = "pytaurix.ffi.image")]
pub struct Image {
    pub inner: tauri::image::Image<'static>,
}

#[pymethods]
impl Image {
    /// 从编码字节解码 PNG/ICO，返回拥有独立 RGBA 数据的图像。
    ///
    /// encoded 必须为 bytes；错误类型返回 TypeError。释放 GIL，可在工作线程使用。
    /// 所需解码 feature 关闭时返回 feature_unavailable；损坏或不支持格式
    /// 返回 image_decode_failed。具体启用格式见 RuntimeInfo.image_formats。
    #[classmethod]
    #[pyo3(signature = (encoded, /))]
    fn from_bytes(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        encoded: &Bound<'_, PyBytes>,
    ) -> PyResult<Self> {
        #[cfg(any(feature = "image-png", feature = "image-ico"))]
        {
            let bytes = encoded.as_bytes().to_vec();
            py.detach(|| {
                check_format(&bytes).map_err(|(code, message)| binding_error(code, message))?;
                tauri::image::Image::from_bytes(&bytes)
                    .map(|inner| Self { inner })
                    .map_err(|error| binding_error("image_decode_failed", error))
            })
        }
        #[cfg(not(any(feature = "image-png", feature = "image-ico")))]
        {
            let _ = (py, encoded);
            Err(binding_error(
                "feature_unavailable",
                "Image decoding requires image-png or image-ico",
            ))
        }
    }

    /// 从显式 pathlib.Path 读取并解码图像，返回拥有独立 RGBA 的 Image。
    ///
    /// path 必须为 Path；错误类型返回 TypeError。文件读取和解码释放 GIL。
    /// 此路径不依赖应用资源根目录；读取/解码失败返回 image_load_failed，
    /// 所需解码 feature 关闭时返回 feature_unavailable；全部关闭时不访问磁盘。
    #[classmethod]
    #[pyo3(signature = (path, /))]
    fn from_path(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        path: &Bound<'_, PyAny>,
    ) -> PyResult<Self> {
        if !path.is_instance(&py.import("pathlib")?.getattr("Path")?)? {
            return Err(PyTypeError::new_err("path must be pathlib.Path"));
        }
        let path = path.extract::<std::path::PathBuf>()?;
        #[cfg(any(feature = "image-png", feature = "image-ico"))]
        {
            py.detach(|| {
                // 与上游 from_path 一样读取一次，避免格式检查与解码间的文件替换竞态。
                let bytes = std::fs::read(&path)
                    .map_err(|error| binding_error("image_load_failed", error))?;
                check_format(&bytes).map_err(|(code, message)| {
                    binding_error(
                        if code == "feature_unavailable" {
                            code
                        } else {
                            "image_load_failed"
                        },
                        message,
                    )
                })?;
                tauri::image::Image::from_bytes(&bytes)
                    .map(|inner| Self { inner })
                    .map_err(|error| binding_error("image_load_failed", error))
            })
        }
        #[cfg(not(any(feature = "image-png", feature = "image-ico")))]
        {
            let _ = path;
            Err(binding_error(
                "feature_unavailable",
                "Image decoding requires image-png or image-ico",
            ))
        }
    }

    /// 根据 RGBA 字节和正整数尺寸创建图像，校验数据长度。
    #[new]
    #[pyo3(signature = (rgba, width, height, /))]
    fn new(rgba: &Bound<'_, PyBytes>, width: u32, height: u32) -> PyResult<Self> {
        let expected = (width as usize)
            .checked_mul(height as usize)
            .and_then(|size| size.checked_mul(4));
        if width == 0 || height == 0 || expected != Some(rgba.as_bytes().len()) {
            return Err(binding_error(
                "invalid_image",
                "RGBA data length must match positive dimensions",
            ));
        }
        Ok(Self {
            inner: tauri::image::Image::new_owned(rgba.as_bytes().to_vec(), width, height),
        })
    }
    /// 取得不可变 RGBA 字节副本。
    #[getter]
    fn rgba<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, self.inner.rgba())
    }
    /// 取得像素宽度。
    #[getter]
    fn width(&self) -> u32 {
        self.inner.width()
    }
    /// 取得像素高度。
    #[getter]
    fn height(&self) -> u32 {
        self.inner.height()
    }
}
