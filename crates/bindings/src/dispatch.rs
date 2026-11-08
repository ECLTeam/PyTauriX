//! 主线程任务通过共享登记取得可清空回调，不永久捕获 Python 对象。
use crate::{
    binding_error,
    resources::CallbackSlot,
    window::AppHandle,
    window_state::{check_sync, Scope},
};
use pyo3::prelude::*;
use std::sync::Arc;

pub fn submit(
    py: Python<'_>,
    handle: &AppHandle,
    window: Option<&crate::window::WebviewWindow>,
    callback: Py<PyAny>,
) -> PyResult<()> {
    handle.runtime.ensure_active()?;
    if let Some(window) = window {
        window.state.ensure_active()?;
    }
    if !callback.bind(py).is_callable() {
        return Err(binding_error(
            "invalid_callback",
            "Main-thread task must be callable",
        ));
    }
    let slot = CallbackSlot::new(window.map(|window| Arc::clone(&window.state)), callback);
    let id = handle.runtime.resources.add_task(&handle.runtime, &slot)?;
    let weak_runtime = Arc::downgrade(&handle.runtime);
    let native_handle = handle.inner.clone();
    let native_window = window.map(|window| window.inner.clone());
    let result = py.detach(|| {
        handle.inner.run_on_main_thread(move || {
            let Some(runtime) = weak_runtime.upgrade() else {
                return;
            };
            let Some(slot) = runtime.resources.take_task(id) else {
                return;
            };
            // 后端可能先移除窗口，随后才派发 Destroyed；在 GUI 线程核对原始原生 ID。
            if native_window.is_some_and(|window| window.is_visible().is_err()) {
                slot.clear();
                return;
            }
            Python::attach(|py| {
                let _scope = Scope::callback();
                let result = (|| {
                    // 进入 Python 前再次检查代次，已开始的回调不承诺强制中止。
                    if runtime.ensure_active().is_err()
                        || runtime.failed()
                        || slot.check_owner().is_err()
                    {
                        slot.clear();
                        return Ok(());
                    }
                    if let Some(callback) = slot.callback(py, true)? {
                        check_sync(py, callback.call0(py)?)?;
                    }
                    Ok::<_, PyErr>(())
                })();
                if let Err(error) = result {
                    runtime.fail(&native_handle, error);
                }
            });
        })
    });
    if let Err(error) = result {
        if let Some(slot) = handle.runtime.resources.take_task(id) {
            slot.clear();
        }
        return Err(binding_error("dispatch_failed", error));
    }
    Ok(())
}
