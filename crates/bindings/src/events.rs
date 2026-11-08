//! 精确事件目标、序列化边界及可清理的所有者监听。
use crate::{
    binding_error,
    resources::CallbackSlot,
    window::AppHandle,
    window_state::{check_sync, Scope, WindowState},
};
use pyo3::prelude::*;
use std::sync::Arc;
use tauri::{Emitter, Listener};

#[pyclass(frozen, module = "pytaurix.events")]
pub struct Event {
    id: u32,
    payload: String,
}
#[pymethods]
impl Event {
    fn id(&self) -> u32 {
        self.id
    }
    fn payload(&self) -> &str {
        &self.payload
    }
}

fn validate_event(event: &str) -> PyResult<()> {
    if event
        .chars()
        .all(|c| c.is_alphanumeric() || matches!(c, '-' | '/' | ':' | '_'))
    {
        Ok(())
    } else {
        Err(binding_error(
            "invalid_event",
            "Event name contains unsupported characters",
        ))
    }
}

pub fn emit(
    py: Python<'_>,
    handle: &AppHandle,
    target: Option<tauri::EventTarget>,
    event: &str,
    payload_json: &str,
) -> PyResult<()> {
    handle.runtime.ensure_active()?;
    validate_event(event)?;
    let _: serde_json::Value =
        serde_json::from_str(payload_json).map_err(|error| binding_error("invalid_json", error))?;
    let payload = payload_json.to_owned();
    py.detach(|| match target {
        Some(target) => handle.inner.emit_str_to(target, event, payload),
        None => handle.inner.emit_str(event, payload),
    })
    .map_err(|error| binding_error("event_failed", error))
}
pub fn emit_target(
    py: Python<'_>,
    handle: &AppHandle,
    target_json: &str,
    event: &str,
    payload_json: &str,
) -> PyResult<()> {
    let target = serde_json::from_str(target_json)
        .map_err(|error| binding_error("invalid_target", error))?;
    emit(py, handle, Some(target), event, payload_json)
}

pub fn listen(
    py: Python<'_>,
    handle: &AppHandle,
    window: Option<&crate::window::WebviewWindow>,
    event: &str,
    callback: Py<PyAny>,
    once: bool,
    any_target: bool,
) -> PyResult<u32> {
    handle.runtime.ensure_active()?;
    validate_event(event)?;
    if let Some(window) = window {
        window.state.ensure_active()?;
    }
    if !callback.bind(py).is_callable() {
        return Err(binding_error(
            "invalid_callback",
            "Listener must be callable",
        ));
    }
    let slot = CallbackSlot::new(window.map(|window| Arc::clone(&window.state)), callback);
    let weak_slot = Arc::downgrade(&slot);
    let weak_runtime = Arc::downgrade(&handle.runtime);
    let native_handle = handle.inner.clone();
    let receive = move |event: tauri::Event| {
        let (Some(runtime), Some(slot)) = (weak_runtime.upgrade(), weak_slot.upgrade()) else {
            return;
        };
        Python::attach(|py| {
            let _scope = Scope::callback();
            let result = (|| {
                if runtime.ensure_active().is_err()
                    || runtime.failed()
                    || slot.check_owner().is_err()
                {
                    return Ok(());
                }
                // 自行取走一次回调；递归发送不会触发上游 FnOnce 的二次 take panic。
                if let Some(callback) = slot.callback(py, once)? {
                    if once {
                        runtime.resources.remove_listener(event.id(), None)?;
                        native_handle.unlisten(event.id());
                    }
                    check_sync(
                        py,
                        callback.call1(
                            py,
                            (Event {
                                id: event.id(),
                                payload: event.payload().to_owned(),
                            },),
                        )?,
                    )?;
                }
                Ok::<_, PyErr>(())
            })();
            if let Err(error) = result {
                runtime.fail(&native_handle, error);
            }
        });
    };
    let id = py.detach(|| match (window, any_target) {
        (_, true) => handle.inner.listen_any(event, receive),
        (Some(window), false) => window.inner.listen(event, receive),
        (None, false) => handle.inner.listen(event, receive),
    });
    if let Err(error) = handle
        .runtime
        .resources
        .add_listener(&handle.runtime, id, &slot)
    {
        slot.clear();
        py.detach(|| handle.inner.unlisten(id));
        return Err(error);
    }
    if !slot.present() {
        py.detach(|| handle.inner.unlisten(id));
    }
    Ok(id)
}
pub fn unlisten(
    py: Python<'_>,
    handle: &AppHandle,
    owner: Option<&Arc<WindowState>>,
    id: u32,
) -> PyResult<()> {
    handle.runtime.ensure_active()?;
    if let Some(owner) = owner {
        owner.ensure_active()?;
    }
    if let Some(slot) = handle.runtime.resources.remove_listener(id, owner)? {
        slot.clear();
        py.detach(|| handle.inner.unlisten(id));
    }
    Ok(())
}
