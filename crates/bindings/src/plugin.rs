//! 可验证、一次性消费的原生插件；导入与创建描述符不初始化 GUI。
//!
//! 插件描述符只保存名称与"装到构建器上"的闭包，擦除各插件的配置类型，
//! 使带不同 `Config` 的上游插件能共用一个 Python 类型。

use crate::binding_error;
use pyo3::prelude::*;
use std::{collections::HashSet, sync::Mutex};

/// 原生应用构建器。
pub type Builder = tauri::Builder<tauri::Wry>;

/// 消费时把插件登记到构建器；闭包捕获插件实例而非 Python 对象。
pub type ApplyFn = Box<dyn FnOnce(Builder) -> Builder + Send>;

#[pyclass(frozen, module = "pytaurix.plugin")]
pub struct Plugin {
    name: &'static str,
    apply: Mutex<Option<ApplyFn>>,
}

impl Plugin {
    // 精简构建可能没有任何插件构造器，此时该入口只在有插件 feature 时被调用。
    #[allow(dead_code)]
    pub(crate) fn new(name: &'static str, apply: ApplyFn) -> Self {
        Self {
            name,
            apply: Mutex::new(Some(apply)),
        }
    }
}

#[pymethods]
impl Plugin {
    #[getter]
    fn name(&self) -> &str {
        self.name
    }
    #[getter]
    fn consumed(&self) -> PyResult<bool> {
        Ok(self
            .apply
            .lock()
            .map_err(|_| binding_error("state_failed", "Plugin unavailable"))?
            .is_none())
    }
}

pub fn validate(py: Python<'_>, plugins: &[Py<Plugin>]) -> PyResult<HashSet<String>> {
    let mut names = HashSet::new();
    for plugin in plugins {
        let plugin = plugin.borrow(py);
        if !names.insert(plugin.name.to_owned()) {
            return Err(binding_error(
                "duplicate_plugin",
                "Plugin names must be unique",
            ));
        }
        if plugin.consumed()? {
            return Err(binding_error(
                "plugin_consumed",
                "Plugin was already consumed",
            ));
        }
    }
    Ok(names)
}

pub fn consume(py: Python<'_>, plugins: &[Py<Plugin>]) -> PyResult<Vec<ApplyFn>> {
    plugins
        .iter()
        .map(|plugin| {
            let plugin = plugin.borrow(py);
            let taken = plugin
                .apply
                .lock()
                .map_err(|_| binding_error("state_failed", "Plugin unavailable"))?
                .take();
            taken.ok_or_else(|| binding_error("plugin_consumed", "Plugin was already consumed"))
        })
        .collect()
}

#[cfg(all(feature = "plugin-dialog", desktop))]
#[pyfunction]
pub fn dialog_init() -> Plugin {
    Plugin::new(
        "dialog",
        Box::new(|builder| builder.plugin(tauri_plugin_dialog::init())),
    )
}

#[cfg(feature = "plugin-fs")]
#[pyfunction]
pub fn fs_init() -> Plugin {
    Plugin::new(
        "fs",
        Box::new(|builder| builder.plugin(tauri_plugin_fs::init())),
    )
}

#[cfg(feature = "plugin-global-shortcut")]
#[pyfunction]
pub fn global_shortcut_init() -> Plugin {
    Plugin::new(
        "global-shortcut",
        Box::new(|builder| builder.plugin(tauri_plugin_global_shortcut::Builder::new().build())),
    )
}

#[cfg(feature = "plugin-notification")]
#[pyfunction]
pub fn notification_init() -> Plugin {
    Plugin::new(
        "notification",
        Box::new(|builder| builder.plugin(tauri_plugin_notification::init())),
    )
}

#[cfg(feature = "plugin-opener")]
#[pyfunction]
pub fn opener_init() -> Plugin {
    Plugin::new(
        "opener",
        Box::new(|builder| builder.plugin(tauri_plugin_opener::init())),
    )
}

#[cfg(all(desktop, feature = "plugin-single-instance"))]
#[pyfunction]
pub fn single_instance_init(py: Python<'_>, handler: Py<PyAny>) -> PyResult<Plugin> {
    crate::single_instance::init(py, handler)
}

#[cfg(feature = "plugin-window-state")]
#[pyfunction]
#[pyo3(signature = (*, filename=None, flags=None, denylist=None, skip_initial=None))]
pub fn window_state_init(
    py: Python<'_>,
    filename: Option<String>,
    flags: Option<Vec<String>>,
    denylist: Option<Vec<String>>,
    skip_initial: Option<Vec<String>>,
) -> PyResult<Plugin> {
    crate::window_state_plugin::init(py, filename, flags, denylist, skip_initial)
}
