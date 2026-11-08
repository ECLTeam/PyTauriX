//! 单窗口代次、可清空回调及同步 GUI 回调上下文。
use crate::{binding_error, runtime::RuntimeState};
use pyo3::{prelude::*, types::PyBool};
use serde_json::json;
use std::{
    cell::Cell,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
};

thread_local! {
    static IN_CALLBACK: Cell<bool> = const { Cell::new(false) };
    static IN_SETUP: Cell<bool> = const { Cell::new(false) };
}

pub struct Scope {
    callback: bool,
    previous: bool,
}
impl Scope {
    pub fn callback() -> Self {
        let previous = IN_CALLBACK.with(|slot| slot.replace(true));
        Self {
            callback: true,
            previous,
        }
    }
    pub fn setup() -> Self {
        let previous = IN_SETUP.with(|slot| slot.replace(true));
        Self {
            callback: false,
            previous,
        }
    }
    pub fn can_build_on_main() -> bool {
        IN_SETUP.with(Cell::get) && !Self::in_callback()
    }
    pub fn in_callback() -> bool {
        IN_CALLBACK.with(Cell::get)
    }
}
impl Drop for Scope {
    fn drop(&mut self) {
        if self.callback {
            IN_CALLBACK.with(|slot| slot.set(self.previous));
        } else {
            IN_SETUP.with(|slot| slot.set(self.previous));
        }
    }
}

#[derive(Default)]
pub struct Callbacks {
    pub navigation: Option<Py<PyAny>>,
    pub page_load: Option<Py<PyAny>>,
    pub window_event: Option<Py<PyAny>>,
    pub title_changed: Option<Py<PyAny>>,
    pub download: Option<Py<PyAny>>,
    pub new_window: Option<Py<PyAny>>,
    pub permission: Option<Py<PyAny>>,
    pub resource: Option<Py<PyAny>>,
}

pub struct WindowState {
    pub active: AtomicBool,
    pub callbacks: Mutex<Callbacks>,
    #[cfg(target_os = "windows")]
    pub menu_hwnd: std::sync::atomic::AtomicIsize,
}
impl WindowState {
    pub fn new(callbacks: Callbacks) -> Arc<Self> {
        Arc::new(Self {
            active: AtomicBool::new(true),
            callbacks: Mutex::new(callbacks),
            #[cfg(target_os = "windows")]
            menu_hwnd: std::sync::atomic::AtomicIsize::new(0),
        })
    }
    pub fn ensure_active(&self) -> PyResult<()> {
        if self.active.load(Ordering::SeqCst) {
            Ok(())
        } else {
            Err(binding_error(
                "window_closed",
                "This native window has been destroyed",
            ))
        }
    }
    pub fn clear(&self) {
        self.active.store(false, Ordering::SeqCst);
        let removed = self
            .callbacks
            .lock()
            .map(|mut slot| std::mem::take(&mut *slot))
            .ok();
        // 不在注册表锁内释放 Python 对象，析构可能重入框架。
        drop(removed);
    }
    pub fn callback(&self, py: Python<'_>, kind: &str) -> PyResult<Option<Py<PyAny>>> {
        let slot = self
            .callbacks
            .lock()
            .map_err(|_| binding_error("state_failed", "Window callbacks unavailable"))?;
        let callback = match kind {
            "navigation" => &slot.navigation,
            "page_load" => &slot.page_load,
            "title_changed" => &slot.title_changed,
            "download" => &slot.download,
            "new_window" => &slot.new_window,
            "permission" => &slot.permission,
            "resource" => &slot.resource,
            _ => &slot.window_event,
        };
        Ok(callback.as_ref().map(|value| value.clone_ref(py)))
    }
}

pub fn check_sync(py: Python<'_>, result: Py<PyAny>) -> PyResult<()> {
    if result.is_none(py) {
        return Ok(());
    }
    let inspect = py.import("inspect")?;
    if inspect
        .call_method1("isawaitable", (result.bind(py),))?
        .is_truthy()?
    {
        if inspect
            .call_method1("iscoroutine", (result.bind(py),))?
            .is_truthy()?
        {
            result.call_method0(py, "close")?;
        }
        return Err(binding_error(
            "invalid_callback",
            "Native callbacks must be synchronous",
        ));
    }
    Ok(())
}

#[pyclass(frozen, module = "pytaurix.events")]
pub struct CloseRequestApi {
    inner: Arc<Mutex<Option<tauri::CloseRequestApi>>>,
    prevented: Arc<AtomicBool>,
}
#[pymethods]
impl CloseRequestApi {
    /// 在同步关闭回调内阻止本次关闭，回调结束后失效。
    fn prevent_close(&self) -> PyResult<()> {
        let slot = self
            .inner
            .lock()
            .map_err(|_| binding_error("state_failed", "Close request unavailable"))?;
        let api = slot.as_ref().ok_or_else(|| {
            binding_error(
                "request_expired",
                "Close control is valid only during its callback",
            )
        })?;
        api.prevent_close();
        self.prevented.store(true, Ordering::SeqCst);
        Ok(())
    }
}

pub fn window_event(
    runtime: &RuntimeState,
    handle: &tauri::AppHandle,
    label: &str,
    event: &tauri::WindowEvent,
) {
    let Ok(state) = runtime.window_state(label) else {
        return;
    };
    let destroyed = matches!(event, tauri::WindowEvent::Destroyed);
    if destroyed {
        state.active.store(false, Ordering::SeqCst);
    }
    let (name, data, api) = match event {
        tauri::WindowEvent::CloseRequested { api, .. } => {
            ("close_requested", json!(null), Some(api.clone()))
        }
        tauri::WindowEvent::Destroyed => ("destroyed", json!(null), None),
        tauri::WindowEvent::Focused(value) => ("focused", json!(value), None),
        tauri::WindowEvent::Resized(size) => ("resized", json!([size.width, size.height]), None),
        tauri::WindowEvent::Moved(position) => ("moved", json!([position.x, position.y]), None),
        tauri::WindowEvent::ScaleFactorChanged {
            scale_factor,
            new_inner_size,
            ..
        } => (
            "scale_factor_changed",
            json!([scale_factor, new_inner_size.width, new_inner_size.height]),
            None,
        ),
        tauri::WindowEvent::ThemeChanged(theme) => (
            "theme_changed",
            json!(format!("{theme:?}").to_lowercase()),
            None,
        ),
        tauri::WindowEvent::DragDrop(event) => {
            let paths = |paths: &[std::path::PathBuf]| {
                paths
                    .iter()
                    .map(|path| path.to_string_lossy().into_owned())
                    .collect::<Vec<_>>()
            };
            match event {
                tauri::DragDropEvent::Enter {
                    paths: items,
                    position,
                } => (
                    "drag_drop_enter",
                    json!({"paths": paths(items), "position": [position.x, position.y]}),
                    None,
                ),
                tauri::DragDropEvent::Over { position } => (
                    "drag_drop_over",
                    json!({"position": [position.x, position.y]}),
                    None,
                ),
                tauri::DragDropEvent::Drop {
                    paths: items,
                    position,
                } => (
                    "drag_drop_drop",
                    json!({"paths": paths(items), "position": [position.x, position.y]}),
                    None,
                ),
                tauri::DragDropEvent::Leave => ("drag_drop_leave", json!(null), None),
                _ => return,
            }
        }
        _ => return,
    };
    let request = Arc::new(Mutex::new(api));
    let prevented = Arc::new(AtomicBool::new(false));
    Python::attach(|py| {
        let _scope = Scope::callback();
        let result = (|| {
            if runtime.failed() {
                return Ok(());
            }
            if let Some(callback) = state.callback(py, "window_event")? {
                let api = (name == "close_requested").then(|| CloseRequestApi {
                    inner: Arc::clone(&request),
                    prevented: Arc::clone(&prevented),
                });
                let event = py
                    .import("pytaurix.events")?
                    .getattr("_window_event")?
                    .call1((name, data.to_string(), api))?;
                let result = callback.call1(py, (event,))?;
                check_sync(py, result)?;
            }
            Ok::<_, PyErr>(())
        })();
        if let Err(error) = result {
            runtime.fail(handle, error);
        }
    });
    if let Ok(mut slot) = request.lock() {
        slot.take();
    }
    #[cfg(target_os = "windows")]
    if name == "close_requested" && !prevented.load(Ordering::SeqCst) {
        crate::menu::detach_closing_window(&state);
    }
    if destroyed {
        runtime.remove_window(label, &state, handle);
    }
}

pub fn navigation(
    runtime: &RuntimeState,
    state: &WindowState,
    handle: &tauri::AppHandle,
    url: &str,
) -> bool {
    Python::attach(|py| {
        let _scope = Scope::callback();
        if runtime.failed() || state.ensure_active().is_err() {
            return false;
        }
        let result = (|| {
            let Some(callback) = state.callback(py, "navigation")? else {
                return Ok(true);
            };
            let result = callback.call1(py, (url,))?;
            if !result.bind(py).is_instance_of::<PyBool>() {
                check_sync(py, result)?;
                return Err(binding_error(
                    "invalid_callback",
                    "Navigation callback must return bool",
                ));
            }
            result.extract::<bool>(py)
        })();
        match result {
            Ok(allowed) => allowed,
            Err(error) => {
                runtime.fail(handle, error);
                false
            }
        }
    })
}
