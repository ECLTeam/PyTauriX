//! 同步原生创建：精确标签权限、回调槽与构建失败回滚。
use crate::{
    binding_error,
    image::Image,
    window::{AppHandle, WebviewWindow},
    window_state::{Callbacks, Scope},
};
use pyo3::prelude::*;
use pyo3::types::PyBool;
use std::sync::{atomic::Ordering, Arc};
use tauri::Manager;

#[pyfunction]
#[pyo3(signature = (handle, config_json, *, initialization_script=None, icon=None, navigation=None, page_load=None, window_event=None, title_changed=None, download=None, new_window=None, permission=None, resource=None, data_directory=None))]
#[allow(clippy::too_many_arguments)]
pub fn build_window(
    py: Python<'_>,
    handle: &AppHandle,
    config_json: &str,
    initialization_script: Option<String>,
    icon: Option<PyRef<'_, Image>>,
    navigation: Option<Py<PyAny>>,
    page_load: Option<Py<PyAny>>,
    window_event: Option<Py<PyAny>>,
    title_changed: Option<Py<PyAny>>,
    download: Option<Py<PyAny>>,
    new_window: Option<Py<PyAny>>,
    permission: Option<Py<PyAny>>,
    resource: Option<Py<PyAny>>,
    data_directory: Option<std::path::PathBuf>,
) -> PyResult<WebviewWindow> {
    handle.runtime.ensure_active()?;
    if Scope::in_callback() {
        return Err(binding_error(
            "would_block",
            "Synchronous creation is unavailable inside native callbacks",
        ));
    }
    if !handle.runtime.running.load(Ordering::SeqCst) && !Scope::can_build_on_main() {
        return Err(binding_error(
            "app_not_running",
            "Create windows in setup or while the event loop is running",
        ));
    }
    let threading = py.import("threading")?;
    if threading
        .call_method0("current_thread")?
        .is(&threading.call_method0("main_thread")?)
        && !Scope::can_build_on_main()
    {
        return Err(binding_error(
            "would_block",
            "Use a command worker or asynchronous creation",
        ));
    }
    let config: tauri::utils::config::WindowConfig = serde_json::from_str(config_json)
        .map_err(|error| binding_error("invalid_window_config", error))?;
    validate_config(&config)?;
    if data_directory
        .as_ref()
        .is_some_and(|path| !path.is_absolute())
    {
        return Err(binding_error(
            "invalid_window_config",
            "WebView data directory must be absolute",
        ));
    }
    for callback in [
        &navigation,
        &page_load,
        &window_event,
        &title_changed,
        &download,
        &new_window,
        &permission,
        &resource,
    ]
    .into_iter()
    .flatten()
    {
        if !callback.bind(py).is_callable() {
            return Err(binding_error(
                "invalid_callback",
                "Window callback must be callable",
            ));
        }
    }
    if handle.inner.get_webview_window(&config.label).is_some() {
        return Err(binding_error(
            "duplicate_window",
            "Window label is already in use",
        ));
    }
    let policy_hooks = (
        new_window.is_some(),
        permission.is_some(),
        resource.is_some(),
    );
    let callbacks = Callbacks {
        navigation,
        page_load,
        window_event,
        title_changed,
        download,
        new_window,
        permission,
        resource,
    };
    let state = handle.runtime.reserve_window(&config.label, callbacks)?;
    let handle = handle.clone();
    let icon = icon.map(|value| value.inner.clone());
    py.detach(move || {
        let label = config.label.clone();
        let result = (|| {
            if matches!(config.url, tauri::WebviewUrl::App(_)) {
                register_capability(&handle, &label)?;
            }
            let mut builder = tauri::WebviewWindowBuilder::from_config(&handle.inner, &config)
                .map_err(|error| binding_error("window_create_failed", error))?;
            if let Some(path) = data_directory {
                builder = builder.data_directory(path);
            }
            if let Some(script) = initialization_script {
                builder = builder.initialization_script(script);
            }
            if let Some(icon) = icon {
                builder = builder
                    .icon(icon)
                    .map_err(|error| binding_error("invalid_image", error))?;
            }
            let nav_runtime = Arc::downgrade(&handle.runtime);
            let nav_state = Arc::downgrade(&state);
            let nav_handle = handle.inner.clone();
            builder = builder.on_navigation(move |url| {
                match (nav_runtime.upgrade(), nav_state.upgrade()) {
                    (Some(runtime), Some(state)) => {
                        crate::window_state::navigation(&runtime, &state, &nav_handle, url.as_str())
                    }
                    _ => false,
                }
            });
            let page_runtime = Arc::downgrade(&handle.runtime);
            let page_state = Arc::downgrade(&state);
            let page_handle = handle.inner.clone();
            builder = builder.on_page_load(move |window, payload| {
                if let (Some(runtime), Some(state)) = (page_runtime.upgrade(), page_state.upgrade())
                {
                    if runtime.failed() || state.ensure_active().is_err() {
                        return;
                    }
                    Python::attach(|py| {
                        let _scope = Scope::callback();
                        let result = (|| {
                            if let Some(callback) = state.callback(py, "page_load")? {
                                let handle = AppHandle::new(
                                    window.app_handle().clone(),
                                    Arc::clone(&runtime),
                                );
                                let window = WebviewWindow {
                                    inner: window,
                                    handle,
                                    state: Arc::clone(&state),
                                };
                                let name = match payload.event() {
                                    tauri::webview::PageLoadEvent::Started => "started",
                                    tauri::webview::PageLoadEvent::Finished => "finished",
                                };
                                let event = py
                                    .import("pytaruix.events")?
                                    .getattr("_page_load")?
                                    .call1((payload.url().as_str(), name))?;
                                let result = callback.call1(py, (window, event))?;
                                crate::window_state::check_sync(py, result)?;
                            }
                            Ok::<_, PyErr>(())
                        })();
                        if let Err(error) = result {
                            runtime.fail(&page_handle, error);
                        }
                    });
                }
            });
            let title_runtime = Arc::downgrade(&handle.runtime);
            let title_state = Arc::downgrade(&state);
            let title_handle = handle.inner.clone();
            builder = builder.on_document_title_changed(move |window, title| {
                if let (Some(runtime), Some(state)) =
                    (title_runtime.upgrade(), title_state.upgrade())
                {
                    if runtime.failed() || state.ensure_active().is_err() {
                        return;
                    }
                    Python::attach(|py| {
                        let _scope = Scope::callback();
                        let result = (|| {
                            if let Some(callback) = state.callback(py, "title_changed")? {
                                let handle = AppHandle::new(
                                    window.app_handle().clone(),
                                    Arc::clone(&runtime),
                                );
                                let window = WebviewWindow {
                                    inner: window,
                                    handle,
                                    state: Arc::clone(&state),
                                };
                                let result = callback.call1(py, (window, title))?;
                                crate::window_state::check_sync(py, result)?;
                            }
                            Ok::<_, PyErr>(())
                        })();
                        if let Err(error) = result {
                            runtime.fail(&title_handle, error);
                        }
                    });
                }
            });
            let download_runtime = Arc::downgrade(&handle.runtime);
            let download_handle = handle.inner.clone();
            let download_state = Arc::downgrade(&state);
            builder = builder.on_download(move |webview, event| {
                let Some(runtime) = download_runtime.upgrade() else {
                    return false;
                };
                if runtime.failed() {
                    return false;
                }
                let Some(state) = download_state.upgrade() else {
                    return false;
                };
                if runtime.ensure_active().is_err() || state.ensure_active().is_err() {
                    return false;
                }
                let requested = matches!(&event, tauri::webview::DownloadEvent::Requested { .. });
                let allowed = Python::attach(|py| {
                    let _scope = Scope::callback();
                    let result = (|| -> PyResult<bool> {
                        let Some(callback) = state.callback(py, "download")? else {
                            return Ok(true);
                        };
                        let handle =
                            AppHandle::new(webview.app_handle().clone(), Arc::clone(&runtime));
                        let view = crate::channel::Webview::from_native(
                            webview.clone(),
                            handle,
                            Arc::clone(&state),
                        );
                        let events = py.import("pytaruix.events")?;
                        let payload = match &event {
                            tauri::webview::DownloadEvent::Requested { url, destination } => {
                                events.getattr("DownloadRequested")?.call1((
                                    url.as_str(),
                                    destination.to_string_lossy().into_owned(),
                                ))?
                            }
                            tauri::webview::DownloadEvent::Finished { url, path, success } => {
                                let path = path
                                    .as_ref()
                                    .map(|value| value.to_string_lossy().into_owned());
                                events.getattr("DownloadFinished")?.call1((
                                    url.as_str(),
                                    path,
                                    *success,
                                ))?
                            }
                            _ => return Ok(true),
                        };
                        let result = callback.call1(py, (view, payload))?;
                        if requested {
                            if !result.bind(py).is_instance_of::<PyBool>() {
                                crate::window_state::check_sync(py, result)?;
                                return Err(binding_error(
                                    "invalid_callback",
                                    "Download callback must return bool",
                                ));
                            }
                            result.extract::<bool>(py)
                        } else {
                            crate::window_state::check_sync(py, result)?;
                            Ok(true)
                        }
                    })();
                    match result {
                        Ok(value) => value,
                        Err(error) => {
                            runtime.fail(&download_handle, error);
                            false
                        }
                    }
                });
                if requested {
                    allowed
                } else {
                    true
                }
            });
            builder = crate::webview_requests::register(
                builder,
                &handle,
                &state,
                policy_hooks.0,
                policy_hooks.1,
                policy_hooks.2,
            );
            let inner = builder
                .build()
                .map_err(|error| binding_error("window_create_failed", error))?;
            state.ensure_active()?;
            #[cfg(target_os = "windows")]
            crate::menu::cache_window(&inner, &handle)?;
            Ok(WebviewWindow {
                inner,
                handle: handle.clone(),
                state: Arc::clone(&state),
            })
        })();
        if result.is_err() {
            handle
                .runtime
                .remove_window(&config.label, &state, &handle.inner);
        }
        result
    })
}

fn validate_config(config: &tauri::utils::config::WindowConfig) -> PyResult<()> {
    if config.data_directory.as_ref().is_some_and(|path| {
        path.is_absolute()
            || path.components().any(|part| {
                !matches!(
                    part,
                    std::path::Component::Normal(_) | std::path::Component::CurDir
                )
            })
    }) {
        return Err(binding_error(
            "invalid_window_config",
            "WindowConfig dataDirectory must be a safe relative path; use the data_directory option for an absolute path",
        ));
    }
    if config.label.is_empty()
        || !config
            .label
            .chars()
            .all(|c| c.is_alphanumeric() || matches!(c, '-' | '/' | ':' | '_' | '.'))
    {
        return Err(binding_error(
            "invalid_label",
            "Window label contains invalid characters",
        ));
    }
    for dimension in [
        Some(config.width),
        Some(config.height),
        config.min_width,
        config.min_height,
        config.max_width,
        config.max_height,
    ]
    .into_iter()
    .flatten()
    {
        if !dimension.is_finite() || dimension <= 0.0 || dimension > i32::MAX as f64 {
            return Err(binding_error(
                "invalid_size",
                "Window dimensions must be finite, positive and representable",
            ));
        }
    }
    if config
        .min_width
        .zip(config.max_width)
        .is_some_and(|(min, max)| min > max)
        || config
            .min_height
            .zip(config.max_height)
            .is_some_and(|(min, max)| min > max)
    {
        return Err(binding_error(
            "invalid_size",
            "Minimum size exceeds maximum size",
        ));
    }
    for position in [config.x, config.y].into_iter().flatten() {
        if !position.is_finite() || position.abs() > i32::MAX as f64 {
            return Err(binding_error(
                "invalid_position",
                "Window position is not representable",
            ));
        }
    }
    if let tauri::WebviewUrl::App(path) = &config.url {
        if path.is_absolute()
            || path.components().any(|part| {
                !matches!(
                    part,
                    std::path::Component::Normal(_) | std::path::Component::CurDir
                )
            })
        {
            return Err(binding_error(
                "invalid_url",
                "App URL must stay within application assets",
            ));
        }
    }
    Ok(())
}

#[cfg(feature = "dynamic-acl")]
fn register_capability(handle: &AppHandle, label: &str) -> PyResult<()> {
    if !handle.runtime.automatic_local_acl {
        // 显式宿主能力完整决定新窗口权限，不能被原型自动授权覆盖。
        return Ok(());
    }
    let capability = tauri::ipc::CapabilityBuilder::new(format!("python-window-{label}"))
        .window(label)
        .permission("core:default")
        .permission("pytauri:allow-pyfunc")
        .permission("allow-python-command");
    handle
        .inner
        .add_capability(capability)
        .map_err(|error| binding_error("capability_failed", error))
}
#[cfg(not(feature = "dynamic-acl"))]
fn register_capability(handle: &AppHandle, _label: &str) -> PyResult<()> {
    if !handle.runtime.automatic_local_acl {
        return Ok(());
    }
    Err(binding_error(
        "unsupported_capability",
        "Local window IPC requires the dynamic-acl build feature",
    ))
}
