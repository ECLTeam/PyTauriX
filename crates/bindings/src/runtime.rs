//! 应用所有权、回调失败和 Python 资源的统一生命周期。

use crate::binding_error;
use crate::window_state::{Callbacks, WindowState};
use pyo3::{prelude::*, types::PyDict};
use std::{
    collections::{HashMap, HashSet},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Condvar, Mutex,
    },
};

pub struct RuntimeState {
    #[cfg(all(desktop, feature = "tray-icon"))]
    pub trays: crate::tray::Registry,
    pub plugins: HashSet<String>,
    pub automatic_local_acl: bool,
    pub active: AtomicBool,
    pub error: Mutex<Option<PyErr>>,
    pub resources: crate::resources::Resources,
    pub states: Py<PyDict>,
    pub running: AtomicBool,
    windows: Mutex<HashMap<String, Arc<WindowState>>>,
    startup: Mutex<bool>,
    started: Condvar,
}

impl RuntimeState {
    pub fn new(py: Python<'_>, plugins: HashSet<String>, automatic_local_acl: bool) -> Arc<Self> {
        Arc::new(Self {
            #[cfg(all(desktop, feature = "tray-icon"))]
            trays: crate::tray::Registry::default(),
            plugins,
            automatic_local_acl,
            active: AtomicBool::new(true),
            error: Mutex::new(None),
            resources: crate::resources::Resources::default(),
            states: PyDict::new(py).unbind(),
            running: AtomicBool::new(false),
            windows: Mutex::new(HashMap::new()),
            startup: Mutex::new(false),
            started: Condvar::new(),
        })
    }
    pub fn ensure_active(&self) -> PyResult<()> {
        if self.active.load(Ordering::SeqCst) {
            Ok(())
        } else {
            Err(binding_error(
                "app_closed",
                "Application resources have been released",
            ))
        }
    }
    pub fn window_state(&self, label: &str) -> PyResult<Arc<WindowState>> {
        let mut windows = self
            .windows
            .lock()
            .map_err(|_| binding_error("state_failed", "Window registry unavailable"))?;
        Ok(Arc::clone(
            windows
                .entry(label.to_owned())
                .or_insert_with(|| WindowState::new(Callbacks::default())),
        ))
    }
    pub fn reserve_window(&self, label: &str, callbacks: Callbacks) -> PyResult<Arc<WindowState>> {
        let mut windows = self
            .windows
            .lock()
            .map_err(|_| binding_error("state_failed", "Window registry unavailable"))?;
        self.ensure_active()?;
        if windows
            .get(label)
            .is_some_and(|state| state.active.load(Ordering::SeqCst))
        {
            return Err(binding_error(
                "duplicate_window",
                "Window label is already in use",
            ));
        }
        let state = WindowState::new(callbacks);
        windows.insert(label.to_owned(), Arc::clone(&state));
        Ok(state)
    }
    pub fn remove_window(&self, state: &Arc<WindowState>, handle: &tauri::AppHandle) {
        // 保留无回调的失效代次，避免 Tauri 移除原生窗口前的查询重新激活旧句柄。
        // 同名创建仅在原生窗口已移除后才能用 reserve_window 替换；退出清空注册表。
        state.clear();
        self.resources.clear(handle, Some(state));
    }
    pub fn forget_destroyed(&self, label: &str) {
        if let Ok(mut windows) = self.windows.lock() {
            if windows
                .get(label)
                .is_some_and(|state| !state.active.load(Ordering::SeqCst))
            {
                windows.remove(label);
            }
        }
    }
    pub fn failed(&self) -> bool {
        self.error.lock().map_or(true, |slot| slot.is_some())
    }
    pub fn finish_setup(&self) {
        if let Ok(mut started) = self.startup.lock() {
            *started = true;
        }
        self.started.notify_all();
    }
    pub fn wait_for_setup(&self) -> bool {
        let Ok(mut started) = self.startup.lock() else {
            return false;
        };
        while !*started {
            match self.started.wait(started) {
                Ok(value) => started = value,
                Err(_) => return false,
            }
        }
        self.active.load(Ordering::SeqCst) && !self.failed()
    }
    pub fn fail(&self, handle: &tauri::AppHandle, error: PyErr) {
        if let Ok(mut slot) = self.error.lock() {
            if slot.is_none() {
                *slot = Some(error);
            }
        }
        handle.exit(1);
    }
    pub fn cleanup(&self, handle: &tauri::AppHandle) {
        self.active.store(false, Ordering::SeqCst);
        self.running.store(false, Ordering::SeqCst);
        self.finish_setup();
        let windows = self
            .windows
            .lock()
            .map(|mut slots| slots.drain().map(|(_, state)| state).collect::<Vec<_>>())
            .unwrap_or_default();
        for state in windows {
            state.clear();
        }
        self.resources.clear(handle, None);
        #[cfg(all(desktop, feature = "tray-icon"))]
        self.trays.cleanup(handle);
        // 解释器关闭时不再强行 attach；原生登记及等待仍先完成清理。
        Python::try_attach(|py| self.states.bind(py).clear());
    }
}
