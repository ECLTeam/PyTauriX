//! tauri-plugin-fs 的 Python 入口。
//!
//! 只封装上游真正提供的 Rust API（`open`/`read`/`read_to_string`）。
//! 目录遍历、删除、重命名等能力在上游只存在于命令层，Python 侧已有 `pathlib`，
//! 因此不在这里用 `std::fs` 重新实现一套。
//!
//! 注意：上游 Rust API 不经过 capability scope 校验（`desktop.rs` 直接调用 `std::fs`），
//! 因此本绑定不宣称受限访问；scope 只约束前端 JS 调用。

use crate::{binding_error, window::AppHandle};
use pyo3::{prelude::*, types::PyBytes};
use std::{io::Write, path::Path as FsPath};
use tauri_plugin_fs::{FsExt, OpenOptions};

/// 单次调用的文件系统入口，归属应用运行期。
#[pyclass(frozen, module = "pytaurix.plugins.fs")]
pub struct Fs {
    handle: AppHandle,
}

fn io_error(error: std::io::Error) -> PyErr {
    binding_error("fs_failed", format!("{:?}: {error}", error.kind()))
}

impl Fs {
    /// 应用必须存活且已注册 fs 插件，否则上游 `fs()` 会直接 panic。
    fn ready(&self) -> PyResult<()> {
        self.handle.runtime.ensure_active()?;
        if self.handle.inner.try_fs_scope().is_none() {
            return Err(binding_error(
                "plugin_missing",
                "Register the fs plugin before using Fs",
            ));
        }
        Ok(())
    }
}

#[pymethods]
impl Fs {
    #[new]
    fn new(handle: &AppHandle) -> Self {
        Self {
            handle: handle.clone(),
        }
    }

    /// 读取 UTF-8 文本；非 UTF-8 或读取失败为 fs_failed。
    ///
    /// 参数 path 为字符串路径，原生读写释放 GIL。
    fn read_text(&self, py: Python<'_>, path: &str) -> PyResult<String> {
        self.ready()?;
        py.detach(|| {
            self.handle
                .inner
                .fs()
                .read_to_string(FsPath::new(path))
                .map_err(io_error)
        })
    }

    /// 读取原始字节，返回 ArrayBuffer。
    fn read_bytes(&self, py: Python<'_>, path: &str) -> PyResult<Py<PyBytes>> {
        self.ready()?;
        let data = py.detach(|| {
            self.handle
                .inner
                .fs()
                .read(FsPath::new(path))
                .map_err(io_error)
        })?;
        Ok(PyBytes::new(py, &data).unbind())
    }

    /// 以写模式创建或截断文件后写入文本；不追加、不改权限。
    fn write_text(&self, py: Python<'_>, path: &str, contents: &str) -> PyResult<()> {
        self.ready()?;
        let data = contents.as_bytes().to_vec();
        py.detach(|| write(&self.handle, path, &data))
    }

    /// 以写模式创建或截断文件后写入字节。
    fn write_bytes(&self, py: Python<'_>, path: &str, data: &[u8]) -> PyResult<()> {
        self.ready()?;
        let data = data.to_vec();
        py.detach(|| write(&self.handle, path, &data))
    }
}

fn write(handle: &AppHandle, path: &str, data: &[u8]) -> PyResult<()> {
    let fs = handle.inner.fs();
    // 上游字段私有，只能用构建器；语义等价于写模式 + 创建 + 截断。
    let mut options = OpenOptions::new();
    options.write(true).create(true).truncate(true);
    let mut file = fs.open(FsPath::new(path), options).map_err(io_error)?;
    file.write_all(data).map_err(io_error)
}
