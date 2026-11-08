//! 全局快捷键插件。
//!
//! 只在按键按下时回调 Python，避免按下/释放各触发一次；回调异常沿用同步回调语义。

use crate::{binding_error, runtime::RuntimeState, window::AppHandle};
use pyo3::prelude::*;
use std::sync::Arc;
use tauri::Manager;
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

/// 已注册快捷键的句柄，归属应用运行期。
#[pyclass(frozen, module = "pytaurix.plugins.global_shortcut")]
pub struct GlobalShortcutApi {
    handle: AppHandle,
}

impl GlobalShortcutApi {
    fn ready(&self) -> PyResult<()> {
        self.handle.runtime.ensure_active()?;
        // 未注册插件时上游 global_shortcut() 会 panic，先用登记表挡住。
        if !self.handle.runtime.plugins.contains("global-shortcut") {
            return Err(binding_error(
                "plugin_missing",
                "Register the global-shortcut plugin before using GlobalShortcut",
            ));
        }
        Ok(())
    }
}

fn shortcut_error(error: tauri_plugin_global_shortcut::Error) -> PyErr {
    binding_error("shortcut_failed", error)
}

#[pymethods]
impl GlobalShortcutApi {
    #[new]
    fn new(handle: &AppHandle) -> Self {
        Self {
            handle: handle.clone(),
        }
    }

    /// 注册快捷键并在按下时调用 handler；同一快捷键重复注册返回 shortcut_failed。
    ///
    /// 参数 accelerator 为字符串形式（如 `Ctrl+Shift+K`），handler 接收应用句柄与规范化字符串。
    fn register(&self, py: Python<'_>, accelerator: &str, handler: Py<PyAny>) -> PyResult<()> {
        self.ready()?;
        if !handler.bind(py).is_callable() {
            return Err(binding_error(
                "invalid_callback",
                "shortcut handler must be callable",
            ));
        }
        let native = self.handle.inner.global_shortcut();
        py.detach(|| {
            native
                .on_shortcut(accelerator, move |app, shortcut, event| {
                    if event.state() != ShortcutState::Pressed {
                        return;
                    }
                    let runtime = Arc::clone(app.state::<Arc<RuntimeState>>().inner());
                    Python::attach(|py| {
                        let handle = AppHandle::new(app.clone(), Arc::clone(&runtime));
                        let result = handler
                            .call1(py, (handle, shortcut.to_string()))
                            .and_then(|value| crate::window_state::check_sync(py, value));
                        if let Err(error) = result {
                            runtime.fail(app, error);
                        }
                    });
                })
                .map_err(shortcut_error)
        })
    }

    /// 注销快捷键；未注册时由上游返回错误。
    fn unregister(&self, py: Python<'_>, accelerator: &str) -> PyResult<()> {
        self.ready()?;
        py.detach(|| {
            self.handle
                .inner
                .global_shortcut()
                .unregister(accelerator)
                .map_err(shortcut_error)
        })
    }

    /// 注销本应用注册的全部快捷键。
    fn unregister_all(&self, py: Python<'_>) -> PyResult<()> {
        self.ready()?;
        py.detach(|| {
            self.handle
                .inner
                .global_shortcut()
                .unregister_all()
                .map_err(shortcut_error)
        })
    }

    /// 查询快捷键是否已注册。
    fn is_registered(&self, accelerator: &str) -> PyResult<bool> {
        self.ready()?;
        Ok(self
            .handle
            .inner
            .global_shortcut()
            .is_registered(accelerator))
    }
}
