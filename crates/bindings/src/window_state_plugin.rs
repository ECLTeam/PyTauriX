//! tauri-plugin-window-state 的 Python 入口。
//!
//! 上游在 Builder 阶段注册插件，并在窗口事件里自动保存与恢复几何，
//! 因此 Python 侧只补两件事：注册时选择标志、文件名与例外清单；运行期手动保存一次。
//! 恢复入口只在窗口已存在时使用，新建窗口仍由插件在创建时自行恢复。

use crate::{
    binding_error,
    window::{AppHandle, WebviewWindow},
};
use pyo3::prelude::*;
use tauri_plugin_window_state::{AppHandleExt, StateFlags, WindowExt};

/// 对外暴露的标志名与上游位标志的唯一映射。
const FLAGS: [(&str, StateFlags); 6] = [
    ("size", StateFlags::SIZE),
    ("position", StateFlags::POSITION),
    ("maximized", StateFlags::MAXIMIZED),
    ("visible", StateFlags::VISIBLE),
    ("decorations", StateFlags::DECORATIONS),
    ("fullscreen", StateFlags::FULLSCREEN),
];

/// 未指定标志时与上游默认一致，即全部标志。
fn parse_flags(names: Option<Vec<String>>) -> PyResult<StateFlags> {
    let Some(names) = names else {
        return Ok(StateFlags::all());
    };
    let mut flags = StateFlags::empty();
    for name in names {
        let Some((_, flag)) = FLAGS.iter().find(|(label, _)| *label == name) else {
            return Err(binding_error(
                "invalid_state_flag",
                format!("Unknown window state flag: {name}"),
            ));
        };
        flags |= *flag;
    }
    Ok(flags)
}

fn plugin_error(error: tauri_plugin_window_state::Error) -> PyErr {
    binding_error("window_state_failed", error.to_string())
}

/// 窗口级恢复走 Tauri 原生结果，错误类型与插件自身不同。
fn restore_error(error: tauri::Error) -> PyErr {
    binding_error("window_state_failed", error.to_string())
}

/// 注册插件；文件名与例外清单在构建期固定，之后不再变更。
pub fn init(
    py: Python<'_>,
    filename: Option<String>,
    flags: Option<Vec<String>>,
    denylist: Option<Vec<String>>,
    skip_initial: Option<Vec<String>>,
) -> PyResult<crate::plugin::Plugin> {
    let _ = py;
    let flags = parse_flags(flags)?;
    let denylist = denylist.unwrap_or_default();
    let skip_initial = skip_initial.unwrap_or_default();
    for label in &skip_initial {
        if label.trim().is_empty() {
            return Err(binding_error(
                "invalid_window_label",
                "Window label must not be empty",
            ));
        }
    }
    Ok(crate::plugin::Plugin::new(
        "window-state",
        Box::new(move |builder| {
            let mut native = tauri_plugin_window_state::Builder::new().with_state_flags(flags);
            if let Some(filename) = filename {
                native = native.with_filename(filename);
            }
            if !denylist.is_empty() {
                let names: Vec<&str> = denylist.iter().map(String::as_str).collect();
                native = native.with_denylist(&names);
            }
            for label in &skip_initial {
                native = native.skip_initial_state(label);
            }
            builder.plugin(native.build())
        }),
    ))
}

/// 运行期入口：手动保存全部窗口状态，或对已存在的窗口立即恢复。
#[pyclass(frozen, module = "pytaruix.plugins.window_state")]
pub struct WindowStateApi {
    handle: AppHandle,
}

impl WindowStateApi {
    /// 上游通过 `state::<PluginState>()` 取插件状态，未注册会 panic，先挡一层。
    fn ready(&self) -> PyResult<()> {
        self.handle.runtime.ensure_active()?;
        if !self.handle.runtime.plugins.contains("window-state") {
            return Err(binding_error(
                "plugin_missing",
                "Window state plugin is not registered",
            ));
        }
        Ok(())
    }
}

#[pymethods]
impl WindowStateApi {
    #[new]
    fn new(handle: &AppHandle) -> Self {
        Self {
            handle: handle.clone(),
        }
    }

    /// 保存全部打开窗口的状态到配置文件。
    #[pyo3(signature = (*, flags=None))]
    fn save(&self, py: Python<'_>, flags: Option<Vec<String>>) -> PyResult<()> {
        self.ready()?;
        let flags = parse_flags(flags)?;
        py.detach(|| self.handle.inner.save_window_state(flags))
            .map_err(plugin_error)
    }

    /// 按当前持久化内容恢复指定窗口；窗口必须存活。
    #[pyo3(signature = (window, *, flags=None))]
    fn restore(
        &self,
        py: Python<'_>,
        window: &WebviewWindow,
        flags: Option<Vec<String>>,
    ) -> PyResult<()> {
        self.ready()?;
        window.ensure_active()?;
        let flags = parse_flags(flags)?;
        py.detach(|| window.inner.restore_state(flags))
            .map_err(restore_error)
    }

    /// 插件当前使用的配置文件路径。
    #[getter]
    fn filename(&self) -> PyResult<String> {
        self.ready()?;
        Ok(self.handle.inner.filename())
    }
}
