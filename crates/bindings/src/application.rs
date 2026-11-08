//! 主线程构建与运行；非 Send 应用只由当前线程取得和释放。

use crate::{
    assets::DirectoryAssets, binding_error, ipc::PythonCommands, require_main_thread,
    runtime::RuntimeState, window::AppHandle,
};
use pyo3::prelude::*;
use std::{
    cell::RefCell,
    collections::HashSet,
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
};
use tauri::Manager;

static RUNTIME_STARTED: AtomicBool = AtomicBool::new(false);
thread_local! {
    // 不把原生 App 捕获进 detach 闭包，避免给非 Send 类型添加不成立的线程保证。
    static NATIVE_APP: RefCell<Option<tauri::App>> = const { RefCell::new(None) };
}

#[pyclass(frozen, skip_from_py_object, module = "pytaruix.ffi")]
#[derive(Clone)]
pub struct Context {
    config: tauri::Config,
    assets: DirectoryAssets,
    capabilities: Vec<tauri::utils::acl::capability::Capability>,
    host_capabilities: bool,
    icon: Option<tauri::image::Image<'static>>,
}

#[pyclass(frozen, module = "pytaruix.ffi")]
pub struct Builder;

#[pyclass(unsendable, module = "pytaruix.ffi")]
pub struct App {
    consumed: bool,
    handle: AppHandle,
}

#[pyclass(frozen, module = "pytaruix.events")]
pub struct ExitRequestApi {
    inner: Arc<Mutex<Option<tauri::ExitRequestApi>>>,
}

#[pymethods]
impl ExitRequestApi {
    fn prevent_exit(&self) -> PyResult<()> {
        let slot = self
            .inner
            .lock()
            .map_err(|_| binding_error("state_failed", "Exit request is unavailable"))?;
        let api = slot.as_ref().ok_or_else(|| {
            binding_error(
                "request_expired",
                "Exit control is valid only during its callback",
            )
        })?;
        api.prevent_exit();
        Ok(())
    }
}

#[pyfunction]
pub fn builder_factory() -> Builder {
    Builder
}

#[pyfunction]
#[pyo3(signature = (resource_path, config_json, *, capabilities_json, host_capabilities=false, icon=None))]
pub fn context_factory(
    py: Python<'_>,
    resource_path: Option<PathBuf>,
    config_json: &str,
    capabilities_json: &str,
    host_capabilities: bool,
    icon: Option<&crate::image::Image>,
) -> PyResult<Context> {
    let config: tauri::Config = serde_json::from_str(config_json)
        .map_err(|error| binding_error("invalid_config", error))?;
    if config.app.security.csp.is_some() {
        return Err(binding_error(
            "unsupported_capability",
            "Runtime CSP assets are not implemented",
        ));
    }
    let capabilities = crate::capabilities::parse(capabilities_json)?;
    let assets = match resource_path {
        Some(resource_path) => py
            .detach(|| DirectoryAssets::load(&resource_path))
            .map_err(|error| binding_error("resource_failed", error))?,
        None => DirectoryAssets::default(),
    };
    Ok(Context {
        config,
        assets,
        capabilities,
        host_capabilities,
        icon: icon.map(|image| image.inner.clone()),
    })
}

#[pymethods]
impl Builder {
    #[pyo3(signature = (*, context, invoke_handler, setup=None, plugins=None, protocols=None))]
    fn build(
        &self,
        py: Python<'_>,
        context: &Context,
        invoke_handler: Py<PyAny>,
        setup: Option<Py<PyAny>>,
        plugins: Option<Vec<Py<crate::plugin::Plugin>>>,
        protocols: Option<Vec<Py<crate::protocol::Protocol>>>,
    ) -> PyResult<App> {
        require_main_thread(py)?;
        if !invoke_handler.bind(py).is_callable() {
            return Err(binding_error(
                "invalid_handler",
                "invoke_handler must be callable",
            ));
        }
        if setup
            .as_ref()
            .is_some_and(|callback| !callback.bind(py).is_callable())
        {
            return Err(binding_error("invalid_callback", "setup must be callable"));
        }
        let plugins = plugins.unwrap_or_default();
        let names = crate::plugin::validate(py, &plugins)?;
        let protocols = protocols.unwrap_or_default();
        let mut scheme_names = HashSet::new();
        // 先校验名称唯一性；消费所有权放在运行时唯一性检查之后。
        for protocol in &protocols {
            if !scheme_names.insert(protocol.borrow(py).name().to_owned()) {
                return Err(binding_error(
                    "duplicate_protocol",
                    "Protocol names must be unique",
                ));
            }
        }
        let authority = crate::capabilities::authority(&context.capabilities, &names)?;
        if RUNTIME_STARTED.swap(true, Ordering::SeqCst) {
            return Err(binding_error(
                "runtime_consumed",
                "Only one native event loop is supported per process",
            ));
        }
        // 主线程检查和进程唯一运行时检查通过后，才消费插件所有权。
        let plugins = crate::plugin::consume(py, &plugins)?;
        let protocols = protocols
            .iter()
            .map(|protocol| {
                let protocol = protocol.borrow(py);
                Ok((protocol.name().to_owned(), protocol.take(py)?))
            })
            .collect::<PyResult<Vec<_>>>()?;
        let context = context.clone();
        let runtime = RuntimeState::new(py, names, !context.host_capabilities);
        let setup_runtime = Arc::clone(&runtime);
        let event_runtime = Arc::clone(&runtime);
        let handle = py.detach(move || {
            let mut native_context = tauri::generate_context!();
            if let Some(name) = &context.config.product_name {
                native_context.package_info_mut().name.clone_from(name);
            }
            if let Some(version) = &context.config.version {
                native_context.package_info_mut().version = version
                    .parse()
                    .map_err(|error| binding_error("invalid_config", error))?;
            }
            *native_context.config_mut() = context.config;
            // Tauri 的自动窗口 setup 对建窗失败直接 panic。由本边界创建同一配置，
            // 将 WebView2/平台错误保存为普通 Python 异常并有序退出，保持 Ready 时机。
            let configured_windows: Vec<_> = native_context
                .config_mut()
                .app
                .windows
                .iter_mut()
                .filter_map(|window| {
                    if window.create {
                        let config = window.clone();
                        window.create = false;
                        Some(config)
                    } else {
                        None
                    }
                })
                .collect();
            native_context.set_assets(Box::new(context.assets));
            *native_context.runtime_authority_mut() = authority;
            // Python EXE 没有 Tauri 的图标资源。
            native_context.set_default_window_icon(Some(context.icon.unwrap_or_else(|| {
                tauri::image::Image::new_owned([38, 105, 150, 255].repeat(32 * 32), 32, 32)
            })));
            let mut builder = tauri::Builder::default()
                .manage(PythonCommands(invoke_handler))
                .manage(Arc::clone(&runtime))
                .invoke_handler(crate::ipc::invoke_handler)
                .plugin(pytaruix_bridge::init())
                .plugin(
                    tauri::plugin::Builder::<tauri::Wry>::new("pytauri")
                        .invoke_handler(crate::ipc::legacy_handler)
                        .build(),
                )
                .on_window_event(move |window, event| {
                    crate::window_state::window_event(
                        &event_runtime,
                        window.app_handle(),
                        window.label(),
                        event,
                    );
                })
                .setup(move |app| {
                    let _scope = crate::window_state::Scope::setup();
                    for config in configured_windows {
                        if let Err(error) = tauri::WebviewWindowBuilder::from_config(app, &config)
                            .and_then(|builder| builder.build())
                        {
                            setup_runtime
                                .fail(app.handle(), binding_error("window_create_failed", error));
                            setup_runtime.finish_setup();
                            return Ok(());
                        }
                    }
                    if let Some(setup) = setup {
                        Python::attach(|py| {
                            let handle =
                                AppHandle::new(app.handle().clone(), Arc::clone(&setup_runtime));
                            if let Err(error) = setup
                                .call1(py, (handle,))
                                .and_then(|result| crate::window_state::check_sync(py, result))
                            {
                                // 返回 Ok，防止上游把 Python setup 错误转换成 panic。
                                setup_runtime.fail(app.handle(), error);
                            }
                        });
                    }
                    setup_runtime.finish_setup();
                    Ok(())
                });
            for plugin in plugins {
                builder = builder.plugin(plugin);
            }
            for (name, handler) in protocols {
                builder = crate::protocol::register(builder, name, handler);
            }
            let app = builder
                .build(native_context)
                .map_err(|error| binding_error("startup_failed", error))?;
            let handle = AppHandle::new(app.handle().clone(), runtime);
            NATIVE_APP.with(|slot| *slot.borrow_mut() = Some(app));
            Ok::<_, PyErr>(handle)
        })?;
        Ok(App {
            consumed: false,
            handle,
        })
    }
}

#[pymethods]
impl App {
    fn handle(&self, py: Python<'_>) -> PyResult<AppHandle> {
        require_main_thread(py)?;
        self.handle.runtime.ensure_active()?;
        Ok(self.handle.clone())
    }

    #[pyo3(signature = (callback=None, /))]
    fn run_return(&mut self, py: Python<'_>, callback: Option<Py<PyAny>>) -> PyResult<i32> {
        require_main_thread(py)?;
        if callback
            .as_ref()
            .is_some_and(|callback| !callback.bind(py).is_callable())
        {
            return Err(binding_error(
                "invalid_callback",
                "callback must be callable",
            ));
        }
        if self.consumed {
            return Err(binding_error(
                "app_consumed",
                "An application may run only once",
            ));
        }
        self.consumed = true;
        let handle = self.handle.clone();
        py.detach(move || {
            let app = NATIVE_APP
                .with(|slot| slot.borrow_mut().take())
                .ok_or_else(|| {
                    binding_error("app_consumed", "Native application is unavailable")
                })?;
            let runtime = Arc::clone(&handle.runtime);
            runtime.running.store(true, Ordering::SeqCst);
            let saved_runtime = Arc::clone(&runtime);
            let exit_code = app.run_return(move |native_handle, event| {
                // 此时 Tauri 已从 Manager 移除原生窗口，可以释放临时失效代次。
                if let tauri::RunEvent::WindowEvent {
                    label,
                    event: tauri::WindowEvent::Destroyed,
                    ..
                } = &event
                {
                    saved_runtime.forget_destroyed(label);
                }
                if saved_runtime.failed() {
                    return;
                }
                let (name, code, request) = match event {
                    tauri::RunEvent::Ready => ("ready", None, None),
                    tauri::RunEvent::Exit => ("exit", None, None),
                    tauri::RunEvent::ExitRequested { code, api, .. } => {
                        ("exit_requested", code, Some(api))
                    }
                    _ => return,
                };
                if let Some(callback) = &callback {
                    let request = Arc::new(Mutex::new(request));
                    Python::attach(|py| {
                        let _scope = crate::window_state::Scope::callback();
                        let api = (name == "exit_requested").then(|| ExitRequestApi {
                            inner: Arc::clone(&request),
                        });
                        let handle =
                            AppHandle::new(native_handle.clone(), Arc::clone(&saved_runtime));
                        if let Err(error) = callback
                            .call1(py, (handle, name, code, api))
                            .and_then(|result| crate::window_state::check_sync(py, result))
                        {
                            saved_runtime.fail(native_handle, error);
                        }
                    });
                    if let Ok(mut slot) = request.lock() {
                        slot.take();
                    };
                }
            });
            runtime.cleanup(&handle.inner);
            let mut error = runtime.error.lock().map_err(|_| {
                binding_error("state_failed", "Callback error state is unavailable")
            })?;
            match error.take() {
                Some(error) => Err(error),
                None => Ok(exit_code),
            }
        })
    }
}

impl Drop for App {
    fn drop(&mut self) {
        if !self.consumed {
            // PyO3 unsendable 保证只在所属线程析构；资源操作仍释放 GIL。
            let dispose = || {
                let app = NATIVE_APP
                    .try_with(|slot| slot.borrow_mut().take())
                    .ok()
                    .flatten();
                self.handle.runtime.cleanup(&self.handle.inner);
                drop(app);
            };
            if Python::try_attach(|py| py.detach(dispose)).is_none() {
                dispose();
            }
        }
    }
}
