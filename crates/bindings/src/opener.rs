//! 用系统默认程序打开链接或文件，并在文件管理器中定位条目。

use crate::{binding_error, window::AppHandle};
use pyo3::prelude::*;
use std::path::Path;
use tauri_plugin_opener::OpenerExt;

/// 系统打开入口，归属应用运行期。
#[pyclass(frozen, module = "pytaurix.plugins.opener")]
pub struct OpenerApi {
    handle: AppHandle,
}

impl OpenerApi {
    fn ready(&self) -> PyResult<()> {
        self.handle.runtime.ensure_active()?;
        if !self.handle.runtime.plugins.contains("opener") {
            return Err(binding_error(
                "plugin_missing",
                "Register the opener plugin before using Opener",
            ));
        }
        Ok(())
    }
}

fn opener_error(error: tauri_plugin_opener::Error) -> PyErr {
    binding_error("opener_failed", error)
}

#[pymethods]
impl OpenerApi {
    #[new]
    fn new(handle: &AppHandle) -> Self {
        Self {
            handle: handle.clone(),
        }
    }

    #[pyo3(signature = (url, *, with_app=None))]
    /// 用系统默认浏览器打开链接；with_app 指定处理程序时由系统解析。
    ///
    /// 返回 None 只表示请求已提交，不确认外部程序已启动。
    fn open_url(&self, py: Python<'_>, url: &str, with_app: Option<String>) -> PyResult<()> {
        self.ready()?;
        py.detach(move || {
            self.handle
                .inner
                .opener()
                .open_url(url, with_app)
                .map_err(opener_error)
        })
    }

    #[pyo3(signature = (path, *, with_app=None))]
    /// 用默认程序打开文件或目录。
    fn open_path(&self, py: Python<'_>, path: &str, with_app: Option<String>) -> PyResult<()> {
        self.ready()?;
        py.detach(move || {
            self.handle
                .inner
                .opener()
                .open_path(path.to_owned(), with_app)
                .map_err(opener_error)
        })
    }

    /// 在系统文件管理器中定位并选中条目。
    fn reveal_item_in_dir(&self, py: Python<'_>, path: &str) -> PyResult<()> {
        self.ready()?;
        py.detach(move || {
            self.handle
                .inner
                .opener()
                .reveal_item_in_dir(Path::new(path))
                .map_err(opener_error)
        })
    }
}
