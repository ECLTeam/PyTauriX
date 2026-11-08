//! 桌面对话框通过共享登记交付结果；阻塞等待可随资源销毁唤醒。
use crate::{
    binding_error,
    resources::CallbackSlot,
    window::AppHandle,
    window_state::{check_sync, Scope, WindowState},
};
use pyo3::prelude::*;
use serde::Deserialize;
use std::{
    path::PathBuf,
    sync::{atomic::Ordering, Arc, Condvar, Mutex},
};
use tauri::Manager;
use tauri_plugin_dialog::{FilePath, MessageDialogButtons, MessageDialogKind};

#[derive(Clone)]
struct Owner {
    state: Arc<WindowState>,
    window: tauri::WebviewWindow,
}
impl Owner {
    fn from_window(window: &crate::window::WebviewWindow, handle: &AppHandle) -> PyResult<Self> {
        if !Arc::ptr_eq(&window.handle.runtime, &handle.runtime) {
            return Err(binding_error(
                "invalid_parent",
                "Parent belongs to another application",
            ));
        }
        window.state.ensure_active()?;
        Ok(Self {
            state: Arc::clone(&window.state),
            window: window.inner.clone(),
        })
    }
}

#[derive(Clone)]
pub struct Failure {
    code: &'static str,
    message: &'static str,
}
impl Failure {
    fn error(&self) -> PyErr {
        binding_error(self.code, self.message)
    }
}
#[derive(Clone)]
enum Value {
    File(Option<PathBuf>),
    Files(Option<Vec<PathBuf>>),
    Message(bool),
}
impl Value {
    fn python(self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(match self {
            Self::File(value) => value.into_pyobject(py)?.into_any().unbind(),
            Self::Files(value) => value.into_pyobject(py)?.into_any().unbind(),
            Self::Message(value) => value.into_pyobject(py)?.to_owned().into_any().unbind(),
        })
    }
}
type Outcome = Result<Value, Failure>;

pub struct Operation {
    owners: Vec<Owner>,
    callback: Option<Arc<CallbackSlot>>,
    outcome: Mutex<Option<Outcome>>,
    ready: Condvar,
}
impl Operation {
    pub fn check_owner(&self) -> PyResult<()> {
        for owner in &self.owners {
            owner.state.ensure_active()?;
        }
        Ok(())
    }
    pub fn belongs_to(&self, state: &Arc<WindowState>) -> bool {
        self.owners
            .iter()
            .any(|owner| Arc::ptr_eq(&owner.state, state))
    }
    pub fn cancel(&self, code: &'static str) {
        if let Some(callback) = &self.callback {
            callback.clear();
        }
        self.complete(Err(Failure {
            code,
            message: "Dialog owner was closed",
        }));
    }
    fn complete(&self, outcome: Outcome) {
        if let Ok(mut slot) = self.outcome.lock() {
            if slot.is_none() {
                *slot = Some(outcome);
            }
        }
        self.ready.notify_all();
    }
    fn wait(&self) -> PyResult<Value> {
        let mut slot = self
            .outcome
            .lock()
            .map_err(|_| binding_error("state_failed", "Dialog result unavailable"))?;
        while slot.is_none() {
            slot = self
                .ready
                .wait(slot)
                .map_err(|_| binding_error("state_failed", "Dialog result unavailable"))?;
        }
        match slot.take() {
            Some(Ok(value)) => Ok(value),
            Some(Err(error)) => Err(error.error()),
            None => Err(binding_error("state_failed", "Dialog result unavailable")),
        }
    }
}

#[derive(Default, Deserialize)]
#[serde(deny_unknown_fields)]
struct FileOptions {
    add_filter: Option<(String, Vec<String>)>,
    set_directory: Option<PathBuf>,
    set_file_name: Option<String>,
    set_title: Option<String>,
    set_can_create_directories: Option<bool>,
}
#[derive(Default, Deserialize)]
#[serde(deny_unknown_fields)]
struct MessageOptions {
    title: Option<String>,
    kind: Option<String>,
    buttons: Option<MessageDialogButtons>,
}
enum Request {
    File {
        mode: String,
        options: FileOptions,
    },
    Message {
        message: String,
        options: MessageOptions,
    },
}

#[pyclass(frozen, module = "pytaurix.plugins.dialog.ffi")]
pub struct Dialog {
    handle: AppHandle,
    owner: Option<Owner>,
    message: Option<String>,
}
#[pyfunction]
#[pyo3(signature=(handle, window=None, message=None))]
pub fn dialog_factory(
    handle: &AppHandle,
    window: Option<&crate::window::WebviewWindow>,
    message: Option<String>,
) -> PyResult<Dialog> {
    handle.runtime.ensure_active()?;
    if !handle.runtime.plugins.contains("dialog") {
        return Err(binding_error(
            "plugin_missing",
            "Register dialog with Builder.build(plugins=...)",
        ));
    }
    if message
        .as_ref()
        .is_some_and(|message| message.contains('\0'))
    {
        return Err(binding_error(
            "invalid_dialog_option",
            "Message must not contain NUL",
        ));
    }
    Ok(Dialog {
        handle: handle.clone(),
        owner: window
            .map(|window| Owner::from_window(window, handle))
            .transpose()?,
        message,
    })
}

fn is_main_thread(py: Python<'_>) -> PyResult<bool> {
    let threading = py.import("threading")?;
    Ok(threading
        .call_method0("current_thread")?
        .is(&threading.call_method0("main_thread")?))
}
fn file_path(path: FilePath) -> Result<PathBuf, Failure> {
    match path {
        FilePath::Path(path) => Ok(path),
        _ => Err(Failure {
            code: "unsupported_capability",
            message: "Mobile URI results are not supported",
        }),
    }
}
fn finish(
    runtime: &crate::runtime::RuntimeState,
    handle: &tauri::AppHandle,
    id: u64,
    outcome: Outcome,
) {
    let Some(operation) = runtime.resources.take_operation(id) else {
        return;
    };
    if runtime.ensure_active().is_err() || runtime.failed() {
        operation.cancel("app_closed");
        return;
    }
    if operation.check_owner().is_err() {
        operation.cancel("window_closed");
        return;
    }
    operation.complete(outcome.clone());
    if let Some(slot) = &operation.callback {
        Python::attach(|py| {
            // 等待 GIL 期间可能已销毁所有者；登记取走后仍须在进入 Python 前复核。
            if runtime.ensure_active().is_err()
                || runtime.failed()
                || operation.check_owner().is_err()
            {
                slot.clear();
                return;
            }
            let _scope = Scope::callback();
            let result = (|| match outcome {
                Ok(value) => {
                    if let Some(callback) = slot.callback(py, true)? {
                        check_sync(py, callback.call1(py, (value.python(py)?,))?)?;
                    }
                    Ok(())
                }
                Err(error) => {
                    slot.clear();
                    Err(error.error())
                }
            })();
            if let Err(error) = result {
                runtime.fail(handle, error);
            }
        });
    }
}

impl Dialog {
    fn start(
        &self,
        py: Python<'_>,
        request: Request,
        parent: Option<&crate::window::WebviewWindow>,
        callback: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        self.handle.runtime.ensure_active()?;
        if !self.handle.runtime.running.load(Ordering::SeqCst) {
            return Err(binding_error(
                "app_not_running",
                "Dialog requires a running application",
            ));
        }
        let blocking = callback.is_none();
        if blocking && (is_main_thread(py)? || Scope::in_callback()) {
            return Err(binding_error(
                "would_block",
                "Use blocking dialogs from a command worker thread",
            ));
        }
        if callback
            .as_ref()
            .is_some_and(|callback| !callback.bind(py).is_callable())
        {
            return Err(binding_error(
                "invalid_callback",
                "Dialog callback must be callable",
            ));
        }
        let parent = parent
            .map(|window| Owner::from_window(window, &self.handle))
            .transpose()?;
        let mut owners = self.owner.clone().into_iter().collect::<Vec<_>>();
        owners.extend(parent.clone());
        let operation = Arc::new(Operation {
            owners,
            callback: callback.map(|callback| CallbackSlot::new(None, callback)),
            outcome: Mutex::new(None),
            ready: Condvar::new(),
        });
        let id = self
            .handle
            .runtime
            .resources
            .add_operation(&self.handle.runtime, &operation)?;
        let weak_runtime = Arc::downgrade(&self.handle.runtime);
        let native_handle = self.handle.inner.clone();
        // 在 GUI 线程构建父窗口句柄并启动；上游再次调度时就在同一 GUI 线程立即执行。
        let result = py.detach(|| {
            self.handle.inner.run_on_main_thread(move || {
                let Some(runtime) = weak_runtime.upgrade() else {
                    return;
                };
                let Some(operation) = runtime.resources.operation(id) else {
                    return;
                };
                if runtime.ensure_active().is_err()
                    || runtime.failed()
                    || operation.check_owner().is_err()
                    || operation
                        .owners
                        .iter()
                        .any(|owner| owner.window.is_visible().is_err())
                {
                    if let Some(operation) = runtime.resources.take_operation(id) {
                        operation.cancel(if runtime.ensure_active().is_err() || runtime.failed() {
                            "app_closed"
                        } else {
                            "window_closed"
                        });
                    }
                    return;
                }
                let Some(dialog) = native_handle
                    .try_state::<tauri_plugin_dialog::Dialog<tauri::Wry>>()
                    .map(|state| state.inner().clone())
                else {
                    finish(
                        &runtime,
                        &native_handle,
                        id,
                        Err(Failure {
                            code: "plugin_missing",
                            message: "Dialog plugin state unavailable",
                        }),
                    );
                    return;
                };
                let weak_runtime = Arc::downgrade(&runtime);
                let receive = move |value| {
                    if let Some(runtime) = weak_runtime.upgrade() {
                        finish(&runtime, &native_handle, id, value);
                    }
                };
                match request {
                    Request::Message { message, options } => {
                        let mut builder = dialog.message(message);
                        if let Some(title) = options.title {
                            builder = builder.title(title);
                        }
                        if let Some(buttons) = options.buttons {
                            builder = builder.buttons(buttons);
                        }
                        if let Some(kind) = options.kind {
                            builder = builder.kind(match kind.as_str() {
                                "Info" => MessageDialogKind::Info,
                                "Warning" => MessageDialogKind::Warning,
                                "Error" => MessageDialogKind::Error,
                                _ => {
                                    receive(Err(Failure {
                                        code: "invalid_dialog_option",
                                        message: "Invalid message kind",
                                    }));
                                    return;
                                }
                            });
                        }
                        if let Some(parent) = parent {
                            builder = builder.parent(&parent.window);
                        }
                        builder.show(move |value| receive(Ok(Value::Message(value))));
                    }
                    Request::File { mode, options } => {
                        let mut builder = dialog.file();
                        if let Some((name, extensions)) = options.add_filter {
                            builder = builder.add_filter(
                                name,
                                &extensions.iter().map(String::as_str).collect::<Vec<_>>(),
                            );
                        }
                        if let Some(directory) = options.set_directory {
                            builder = builder.set_directory(directory);
                        }
                        if let Some(name) = options.set_file_name {
                            builder = builder.set_file_name(name);
                        }
                        if let Some(title) = options.set_title {
                            builder = builder.set_title(title);
                        }
                        if let Some(can) = options.set_can_create_directories {
                            builder = builder.set_can_create_directories(can);
                        }
                        if let Some(parent) = parent {
                            builder = builder.set_parent(&parent.window);
                        }
                        match mode.as_str() {
                            "pick_file" => builder.pick_file(move |value| {
                                receive(value.map(file_path).transpose().map(Value::File))
                            }),
                            "pick_folder" => builder.pick_folder(move |value| {
                                receive(value.map(file_path).transpose().map(Value::File))
                            }),
                            "save_file" => builder.save_file(move |value| {
                                receive(value.map(file_path).transpose().map(Value::File))
                            }),
                            "pick_files" => builder.pick_files(move |value| {
                                receive(
                                    value
                                        .map(|paths| paths.into_iter().map(file_path).collect())
                                        .transpose()
                                        .map(Value::Files),
                                )
                            }),
                            "pick_folders" => builder.pick_folders(move |value| {
                                receive(
                                    value
                                        .map(|paths| paths.into_iter().map(file_path).collect())
                                        .transpose()
                                        .map(Value::Files),
                                )
                            }),
                            _ => receive(Err(Failure {
                                code: "invalid_dialog_option",
                                message: "Invalid file mode",
                            })),
                        }
                    }
                }
            })
        });
        if result.is_err() {
            if let Some(operation) = self.handle.runtime.resources.take_operation(id) {
                operation.cancel("dispatch_failed");
            }
            return Err(binding_error("dispatch_failed", "Dialog submission failed"));
        }
        if blocking {
            let value = py.detach(|| operation.wait())?;
            self.handle.runtime.ensure_active()?;
            operation.check_owner()?;
            value.python(py)
        } else {
            Ok(py.None())
        }
    }
}

#[pymethods]
impl Dialog {
    #[pyo3(signature=(mode, options_json, parent=None, callback=None))]
    fn file(
        &self,
        py: Python<'_>,
        mode: String,
        options_json: &str,
        parent: Option<&crate::window::WebviewWindow>,
        callback: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        if self.message.is_some()
            || !matches!(
                mode.as_str(),
                "pick_file" | "pick_files" | "pick_folder" | "pick_folders" | "save_file"
            )
        {
            return Err(binding_error(
                "invalid_dialog_option",
                "Unknown file dialog operation",
            ));
        }
        let options: FileOptions = serde_json::from_str(options_json)
            .map_err(|_| binding_error("invalid_dialog_option", "Invalid file dialog options"))?;
        let mut texts = Vec::new();
        texts.extend(options.set_file_name.as_deref());
        texts.extend(options.set_title.as_deref());
        if let Some(directory) = &options.set_directory {
            texts.push(directory.to_str().ok_or_else(|| {
                binding_error("invalid_dialog_option", "Invalid directory encoding")
            })?);
        }
        if let Some((name, extensions)) = &options.add_filter {
            texts.push(name);
            texts.extend(extensions.iter().map(String::as_str));
        }
        if texts.iter().any(|text| text.contains('\0')) {
            return Err(binding_error(
                "invalid_dialog_option",
                "Dialog text must not contain NUL",
            ));
        }
        self.start(py, Request::File { mode, options }, parent, callback)
    }
    #[pyo3(signature=(options_json, parent=None, callback=None))]
    fn show(
        &self,
        py: Python<'_>,
        options_json: &str,
        parent: Option<&crate::window::WebviewWindow>,
        callback: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let message = self
            .message
            .clone()
            .ok_or_else(|| binding_error("invalid_dialog_option", "Not a message dialog"))?;
        let options: MessageOptions = serde_json::from_str(options_json).map_err(|_| {
            binding_error("invalid_dialog_option", "Invalid message dialog options")
        })?;
        if options
            .kind
            .as_deref()
            .is_some_and(|kind| !matches!(kind, "Info" | "Warning" | "Error"))
        {
            return Err(binding_error(
                "invalid_dialog_option",
                "Invalid message kind",
            ));
        }
        let null_buttons = match options.buttons.as_ref() {
            Some(MessageDialogButtons::OkCustom(ok)) => ok.contains('\0'),
            Some(MessageDialogButtons::OkCancelCustom(ok, cancel)) => {
                ok.contains('\0') || cancel.contains('\0')
            }
            Some(MessageDialogButtons::YesNoCancelCustom(yes, no, cancel)) => {
                yes.contains('\0') || no.contains('\0') || cancel.contains('\0')
            }
            _ => false,
        };
        if options
            .title
            .as_ref()
            .is_some_and(|text| text.contains('\0'))
            || null_buttons
        {
            return Err(binding_error(
                "invalid_dialog_option",
                "Dialog text must not contain NUL",
            ));
        }
        self.start(py, Request::Message { message, options }, parent, callback)
    }
}
