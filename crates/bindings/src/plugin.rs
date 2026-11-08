//! 可验证、一次性消费的原生插件；导入与创建描述符不初始化 GUI。
use crate::binding_error;
use pyo3::prelude::*;
use std::{collections::HashSet, sync::Mutex};

#[pyclass(frozen, module = "pytaruix.plugin")]
pub struct Plugin {
    name: &'static str,
    inner: Mutex<Option<tauri::plugin::TauriPlugin<tauri::Wry>>>,
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
            .inner
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

pub fn consume(
    py: Python<'_>,
    plugins: &[Py<Plugin>],
) -> PyResult<Vec<tauri::plugin::TauriPlugin<tauri::Wry>>> {
    plugins
        .iter()
        .map(|plugin| {
            plugin
                .borrow(py)
                .inner
                .lock()
                .map_err(|_| binding_error("state_failed", "Plugin unavailable"))?
                .take()
                .ok_or_else(|| binding_error("plugin_consumed", "Plugin was already consumed"))
        })
        .collect()
}

#[cfg(all(feature = "plugin-dialog", desktop))]
#[pyfunction]
pub fn dialog_init() -> Plugin {
    Plugin {
        name: "dialog",
        inner: Mutex::new(Some(tauri_plugin_dialog::init())),
    }
}
