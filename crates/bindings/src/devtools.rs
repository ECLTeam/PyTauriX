//! 开发者工具共享窗口代次检查；同步状态查询不得重入 GUI 回调。
use crate::{binding_error, window::WebviewWindow, window_state::Scope};
use pyo3::prelude::*;
use std::sync::atomic::Ordering;

pub fn operate(py: Python<'_>, window: &WebviewWindow, action: &str) -> PyResult<bool> {
    window.ensure_active()?;
    if Scope::in_callback() {
        return Err(binding_error(
            "blocking_callback",
            "Devtools operations cannot run in synchronous GUI callbacks",
        ));
    }
    if !window.handle.runtime.running.load(Ordering::SeqCst) {
        return Err(binding_error(
            "app_not_running",
            "Devtools require the running event loop",
        ));
    }
    if cfg!(target_os = "windows") && action != "open" {
        // Wry 0.57.0 的 Windows close_devtools 是空操作，状态查询固定返回 false。
        // 明确暴露平台限制，避免把占位返回值描述成真实关闭/状态。
        return Err(binding_error(
            "platform_unavailable",
            "WebView2 supports opening devtools; closing and state queries are unavailable upstream",
        ));
    }
    #[cfg(any(debug_assertions, feature = "devtools"))]
    {
        let opened = py.detach(|| match action {
            "open" => {
                window.inner.open_devtools();
                false
            }
            "close" => {
                window.inner.close_devtools();
                false
            }
            _ => window.inner.is_devtools_open(),
        });
        window.ensure_active()?;
        Ok(opened)
    }
    #[cfg(not(any(debug_assertions, feature = "devtools")))]
    {
        let _ = (py, action);
        Err(binding_error(
            "feature_unavailable",
            "Build with the devtools feature to enable devtools",
        ))
    }
}
