//! Tauri/Python 边界：模块注册与真实运行时入口。

mod application;
mod assets;
mod capabilities;
mod channel;
mod devtools;
#[cfg(all(feature = "plugin-dialog", desktop))]
mod dialog;
mod dispatch;
mod dpi;
mod events;
#[cfg(feature = "plugin-fs")]
mod fs;
#[cfg(feature = "plugin-global-shortcut")]
mod global_shortcut;
mod image;
mod ipc;
#[cfg(desktop)]
mod menu;
mod monitor;
#[cfg(feature = "plugin-notification")]
mod notification;
#[cfg(feature = "plugin-opener")]
mod opener;
mod paths;
mod plugin;
mod protocol;
mod resources;
mod runtime;
#[cfg(all(desktop, feature = "plugin-single-instance"))]
mod single_instance;
#[cfg(all(desktop, feature = "tray-icon"))]
mod tray;
mod webview_requests;
mod window;
mod window_builder;
mod window_state;
#[cfg(feature = "plugin-window-state")]
mod window_state_plugin;

use pyo3::{exceptions::PyRuntimeError, prelude::*};

pyo3::create_exception!(_native, BindingError, PyRuntimeError);

fn binding_error(code: &str, message: impl std::fmt::Display) -> PyErr {
    BindingError::new_err(format!("{code}: {message}"))
}

fn require_main_thread(py: Python<'_>) -> PyResult<()> {
    let threading = py.import("threading")?;
    if !threading
        .call_method0("current_thread")?
        .is(&threading.call_method0("main_thread")?)
    {
        return Err(binding_error(
            "wrong_thread",
            "GUI must run on the Python main thread",
        ));
    }
    Ok(())
}

/// 返回当前进程标识，不依赖应用实例。
#[pyfunction]
fn current_pid() -> u32 {
    std::process::id()
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("BindingError", module.py().get_type::<BindingError>())?;
    module.add_class::<application::Context>()?;
    module.add_class::<application::Builder>()?;
    module.add_class::<plugin::Plugin>()?;
    module.add_class::<protocol::Protocol>()?;
    module.add_function(wrap_pyfunction!(protocol::protocol_create, module)?)?;
    module.add("plugin_fs_available", cfg!(feature = "plugin-fs"))?;
    module.add(
        "plugin_global_shortcut_available",
        cfg!(feature = "plugin-global-shortcut"),
    )?;
    module.add(
        "plugin_notification_available",
        cfg!(feature = "plugin-notification"),
    )?;
    module.add("plugin_opener_available", cfg!(feature = "plugin-opener"))?;
    module.add(
        "plugin_window_state_available",
        cfg!(feature = "plugin-window-state"),
    )?;
    module.add(
        "plugin_single_instance_available",
        cfg!(all(desktop, feature = "plugin-single-instance")),
    )?;
    #[cfg(feature = "plugin-global-shortcut")]
    {
        module.add_function(wrap_pyfunction!(plugin::global_shortcut_init, module)?)?;
        module.add_class::<global_shortcut::GlobalShortcutApi>()?;
    }
    #[cfg(feature = "plugin-notification")]
    {
        module.add_function(wrap_pyfunction!(plugin::notification_init, module)?)?;
        module.add_class::<notification::NotificationApi>()?;
    }
    #[cfg(feature = "plugin-opener")]
    {
        module.add_function(wrap_pyfunction!(plugin::opener_init, module)?)?;
        module.add_class::<opener::OpenerApi>()?;
    }
    #[cfg(all(desktop, feature = "plugin-single-instance"))]
    module.add_function(wrap_pyfunction!(plugin::single_instance_init, module)?)?;
    #[cfg(feature = "plugin-fs")]
    {
        module.add_function(wrap_pyfunction!(plugin::fs_init, module)?)?;
        module.add_class::<fs::Fs>()?;
    }
    #[cfg(feature = "plugin-window-state")]
    {
        module.add_function(wrap_pyfunction!(plugin::window_state_init, module)?)?;
        module.add_class::<window_state_plugin::WindowStateApi>()?;
    }
    module.add(
        "plugin_dialog_available",
        cfg!(all(feature = "plugin-dialog", desktop)),
    )?;
    #[cfg(all(feature = "plugin-dialog", desktop))]
    {
        module.add_function(wrap_pyfunction!(plugin::dialog_init, module)?)?;
        module.add_class::<dialog::Dialog>()?;
        module.add_function(wrap_pyfunction!(dialog::dialog_factory, module)?)?;
    }
    module.add_class::<application::App>()?;
    module.add_class::<application::ExitRequestApi>()?;
    module.add_class::<events::Event>()?;
    module.add_class::<window::AppHandle>()?;
    module.add_class::<window::WebviewWindow>()?;
    module.add_class::<channel::Webview>()?;
    module.add_class::<channel::JavaScriptChannelId>()?;
    module.add_class::<channel::Channel>()?;
    module.add_class::<ipc::Request>()?;
    module.add_class::<window_state::CloseRequestApi>()?;
    module.add_class::<image::Image>()?;
    module.add("image_decode_formats", image::formats())?;
    module.add_class::<monitor::Monitor>()?;
    module.add("menu_available", cfg!(desktop))?;
    module.add("tray_available", cfg!(all(desktop, feature = "tray-icon")))?;
    #[cfg(all(desktop, feature = "tray-icon"))]
    module.add_class::<tray::TrayResource>()?;
    module.add(
        "devtools_available",
        cfg!(any(debug_assertions, feature = "devtools")),
    )?;
    #[cfg(desktop)]
    module.add_class::<menu::MenuResource>()?;
    module.add_class::<dpi::LogicalSize>()?;
    module.add_class::<dpi::PhysicalSize>()?;
    module.add_class::<dpi::LogicalPosition>()?;
    module.add_class::<dpi::PhysicalPosition>()?;
    module.add_class::<dpi::PhysicalRect>()?;
    module.add_function(wrap_pyfunction!(dpi::physical_size_payload, module)?)?;
    module.add_function(wrap_pyfunction!(window_builder::build_window, module)?)?;
    module.add_function(wrap_pyfunction!(application::context_factory, module)?)?;
    module.add_function(wrap_pyfunction!(application::builder_factory, module)?)?;
    module.add_function(wrap_pyfunction!(current_pid, module)?)?;
    module.add("tauri_version", "2.12.1")?;
    module.add("pyo3_version", "0.29.3")?;
    Ok(())
}
