//! 新 JSON 协议与旧 PyTauri 字节协议共用一个 Python 工作线程分发器。
//!
//! 新协议按 `(窗口标签, request_id)` 登记待应答项：取消与完成竞争同一份 resolver，
//! 先取走者应答。上游 `return_result` 对已消费的 resolver 直接 panic，因此这里不重复应答。

use crate::{
    runtime::RuntimeState,
    window::{AppHandle, WebviewWindow},
};
use pyo3::{prelude::*, types::PyBytes};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
};
use tauri::{
    ipc::{Invoke, InvokeBody, InvokeError, InvokeResolver, InvokeResponseBody},
    Manager,
};

pub struct PythonCommands(pub Py<PyAny>);

/// 前端请求编号上限；只接受可打印 ASCII，避免超长键与不可见分隔符。
const REQUEST_ID_LIMIT: usize = 96;

fn valid_request_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= REQUEST_ID_LIMIT
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b':' | b'.'))
}

/// 单次请求的应答所有权；取消与完成先取走 resolver 者应答，另一方丢弃结果。
pub struct PendingInvocation {
    resolver: Mutex<Option<InvokeResolver>>,
    cancelled: AtomicBool,
}

impl PendingInvocation {
    fn new(resolver: InvokeResolver) -> Arc<Self> {
        Arc::new(Self {
            resolver: Mutex::new(Some(resolver)),
            cancelled: AtomicBool::new(false),
        })
    }
    fn take(&self) -> Option<InvokeResolver> {
        self.resolver.lock().ok().and_then(|mut slot| slot.take())
    }
    pub fn cancelled(&self) -> bool {
        self.cancelled.load(Ordering::SeqCst)
    }
    /// 标记取消并应答；已取消或已应答时返回 false，不重复回复。
    pub fn cancel(&self) -> bool {
        self.cancel_with("cancelled", "Request was cancelled")
    }
    fn cancel_with(&self, code: &str, message: &str) -> bool {
        if self.cancelled.swap(true, Ordering::SeqCst) {
            return false;
        }
        match self.take() {
            Some(resolver) => {
                resolver.reject(json!({"code":code,"message":message}));
                true
            }
            None => false,
        }
    }
    /// 完成后应答；已被取消时静默丢弃结果。
    fn complete(&self, result: Result<InvokeResponseBody, InvokeError>) {
        let Some(resolver) = self.take() else {
            return;
        };
        match result {
            Ok(body) => resolver.resolve(body),
            Err(error) => resolver.invoke_error(error),
        }
    }
}

/// 待应答请求登记表；键包含窗口标签，取消只作用于来源窗口。
#[derive(Default)]
pub struct Requests {
    pending: Mutex<HashMap<(String, String), Arc<PendingInvocation>>>,
}

impl Requests {
    fn register(&self, label: &str, id: &str, pending: &Arc<PendingInvocation>) -> bool {
        let Ok(mut slots) = self.pending.lock() else {
            return false;
        };
        let key = (label.to_owned(), id.to_owned());
        if slots.contains_key(&key) {
            return false;
        }
        slots.insert(key, Arc::clone(pending));
        true
    }
    fn remove(&self, label: &str, id: &str) {
        if let Ok(mut slots) = self.pending.lock() {
            slots.remove(&(label.to_owned(), id.to_owned()));
        }
    }
    /// 取消指定窗口的请求，返回是否本次真正应答。
    pub fn cancel(&self, label: &str, id: &str) -> bool {
        let pending = self
            .pending
            .lock()
            .ok()
            .and_then(|slots| slots.get(&(label.to_owned(), id.to_owned())).cloned());
        pending.is_some_and(|pending| pending.cancel())
    }
    fn drain(&self, label: Option<&str>, code: &str, message: &str) {
        let drained = self
            .pending
            .lock()
            .map(|mut slots| {
                let keys = slots
                    .keys()
                    .filter(|(owner, _)| label.is_none_or(|label| owner == label))
                    .cloned()
                    .collect::<Vec<_>>();
                keys.into_iter()
                    .filter_map(|key| slots.remove(&key))
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        for pending in drained {
            pending.cancel_with(code, message);
        }
    }
    /// 窗口销毁时归还其全部待应答项。
    pub fn cancel_window(&self, label: &str) {
        self.drain(
            Some(label),
            "window_closed",
            "Originating window has been destroyed",
        );
    }
    /// 应用退出时归还全部待应答项。
    pub fn cancel_all(&self) {
        self.drain(None, "app_closed", "Application has exited");
    }
}

/// 命令可注入的请求句柄；只表示本地登记状态，不是授权凭证。
#[pyclass(frozen, module = "pytaruix.ffi.ipc")]
pub struct Request {
    id: String,
    pending: Arc<PendingInvocation>,
}

#[pymethods]
impl Request {
    /// 取得前端提交的请求编号；取消后仍可读取。
    #[getter]
    fn id(&self) -> &str {
        &self.id
    }
    /// 查询是否已取消；同步命令需自行检查并提前返回。
    #[getter]
    fn cancelled(&self) -> bool {
        self.pending.cancelled()
    }
    /// 主动取消并立即拒绝前端 Promise；已应答时返回 false。
    ///
    /// 可在工作线程调用；不中断正在执行的同步 Python 代码。
    fn cancel(&self) -> bool {
        self.pending.cancel()
    }
    fn __repr__(&self) -> String {
        format!("Request(id={:?}, cancelled={})", self.id, self.cancelled())
    }
}

pub fn invoke_handler(invoke: Invoke) -> bool {
    match invoke.message.command() {
        "python_command" => dispatch(invoke, false),
        "pytaruix_cancel" => cancel(invoke),
        "pytaruix_channel_ack" => acknowledge(invoke),
        _ => return false,
    }
    true
}

pub fn legacy_handler(invoke: Invoke) -> bool {
    if invoke.message.command() != "pyfunc" {
        return false;
    }
    dispatch(invoke, true);
    true
}

fn json_payload(invoke: &Invoke) -> Option<Value> {
    match invoke.message.payload() {
        InvokeBody::Json(payload) => Some(payload.clone()),
        _ => None,
    }
}

/// 取消入口：只应答本地登记的请求，不执行任何 Python 代码。
fn cancel(invoke: Invoke) {
    let Some(id) = json_payload(&invoke)
        .and_then(|payload| {
            payload
                .get("request_id")
                .and_then(Value::as_str)
                .map(str::to_owned)
        })
        .filter(|id| valid_request_id(id))
    else {
        invoke.resolver.reject(json!({
            "code": "invalid_request",
            "message": "Invalid request identifier"
        }));
        return;
    };
    let webview = invoke.message.webview();
    let app = webview.app_handle();
    let runtime = Arc::clone(app.state::<Arc<RuntimeState>>().inner());
    let cancelled = runtime.requests.cancel(webview.label(), &id);
    invoke.resolver.resolve(cancelled);
}

/// 配额归还入口：只归还来源窗口自己的通道。
fn acknowledge(invoke: Invoke) {
    let Some(id) = json_payload(&invoke)
        .and_then(|payload| payload.get("channel_id").and_then(Value::as_u64))
        .and_then(|id| u32::try_from(id).ok())
    else {
        invoke.resolver.reject(json!({
            "code": "invalid_request",
            "message": "Invalid channel identifier"
        }));
        return;
    };
    let webview = invoke.message.webview();
    let app = webview.app_handle();
    let runtime = Arc::clone(app.state::<Arc<RuntimeState>>().inner());
    let released = runtime
        .window_state(webview.label())
        .ok()
        .and_then(|owner| runtime.resources.channel(id, &owner))
        .is_some_and(|channel| channel.release());
    invoke.resolver.resolve(released);
}

fn dispatch(invoke: Invoke, legacy: bool) {
    let (command, body, request_id) = match prepare(&invoke, legacy) {
        Ok(prepared) => prepared,
        Err(error) => {
            invoke.resolver.reject(if legacy {
                Value::String(
                    error["code"]
                        .as_str()
                        .unwrap_or("invalid_request")
                        .to_owned(),
                )
            } else {
                error
            });
            return;
        }
    };
    let webview = invoke.message.webview();
    let label = webview.label().to_owned();
    let app = webview.app_handle();
    let Some(window) = app.get_webview_window(&label) else {
        invoke.resolver.reject(if legacy {
            json!("invalid_window")
        } else {
            json!({"code":"invalid_window", "message":"Origin is not a WebviewWindow"})
        });
        return;
    };
    let runtime = Arc::clone(app.state::<Arc<RuntimeState>>().inner());
    // 在排队前捕获来源窗口代次；工作线程不能按同名新窗口重新取得所有权。
    let window_state = match runtime.window_state(&label) {
        Ok(state) => state,
        Err(_) => {
            invoke.resolver.reject(if legacy {
                json!("window_closed")
            } else {
                json!({"code":"window_closed", "message":"Originating window unavailable"})
            });
            return;
        }
    };
    let handler = Python::attach(|py| app.state::<PythonCommands>().0.clone_ref(py));
    let headers: Vec<(Vec<u8>, Vec<u8>)> = invoke
        .message
        .headers()
        .iter()
        .map(|(name, value)| (name.as_str().as_bytes().to_vec(), value.as_bytes().to_vec()))
        .collect();
    let request = match request_id {
        Some(id) => {
            let pending = PendingInvocation::new(invoke.resolver.clone());
            if !runtime.requests.register(&label, &id, &pending) {
                invoke.resolver.reject(json!({
                    "code": "duplicate_request_id",
                    "message": "Request identifier is already pending"
                }));
                return;
            }
            Some((id, pending))
        }
        None => None,
    };
    let request_handle = request
        .as_ref()
        .map(|(id, pending)| (id.clone(), Arc::clone(pending)));
    let task = execute(
        Arc::clone(&runtime),
        app.clone(),
        window,
        window_state,
        handler,
        command,
        body,
        headers,
        legacy,
        request_handle,
    );
    match request {
        Some((id, pending)) => {
            // 取消只影响应答；工作线程仍会跑完，结果在 resolver 已被取走时丢弃。
            let registry = Arc::clone(&runtime);
            tauri::async_runtime::spawn(async move {
                let result = task.await;
                registry.requests.remove(&label, &id);
                pending.complete(result);
            });
        }
        None => invoke.resolver.respond_async_serialized(task),
    }
}

#[allow(clippy::too_many_arguments)]
async fn execute(
    runtime: Arc<RuntimeState>,
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    window_state: Arc<crate::window_state::WindowState>,
    handler: Py<PyAny>,
    command: String,
    body: Vec<u8>,
    headers: Vec<(Vec<u8>, Vec<u8>)>,
    legacy: bool,
    request: Option<(String, Arc<PendingInvocation>)>,
) -> Result<InvokeResponseBody, InvokeError> {
    let result = tauri::async_runtime::spawn_blocking(move || {
        // 配置窗口在 setup 之前加载页面；等待初始化完成，避免早到 IPC 读取半初始化状态。
        // 这里没有 GIL，也没有占用 GUI 线程。
        if !runtime.wait_for_setup() {
            return Err(json!({"code":"app_closed", "message":"Application initialization failed or exited"}));
        }
        Python::attach(|py| {
            if runtime.ensure_active().is_err() {
                return Err(json!({"code":"app_closed", "message":"Application has exited"}));
            }
            let handle = AppHandle::new(app, Arc::clone(&runtime));
            window_state.ensure_active().map_err(|_| json!({"code":"window_closed", "message":"Originating window has been destroyed"}))?;
            let window = WebviewWindow {
                inner: window,
                handle: handle.clone(),
                state: window_state,
            };
            let request = match request {
                Some((id, pending)) => Some(Py::new(py, Request { id, pending }).map_err(|_| json!({"code":"worker_failed", "message":"Request handle unavailable"}))?),
                None => None,
            };
            let py_headers: Vec<(Py<PyBytes>, Py<PyBytes>)> = headers.iter().map(|(name,value)|
                (PyBytes::new(py, name).unbind(), PyBytes::new(py, value).unbind())).collect();
            let response = handler.call1(py, (command, PyBytes::new(py, &body), handle, window, py_headers, legacy, request));
            match response {
                Ok(response) => {
                    if let Ok(bytes) = response.bind(py).cast::<PyBytes>() {
                        Ok(InvokeResponseBody::Raw(bytes.as_bytes().to_vec()))
                    } else {
                        let response = response.extract::<String>(py).map_err(|_| json!({"code":"invalid_response", "message":"Handler must return JSON text or bytes"}))?;
                        serde_json::from_str::<Value>(&response).map_err(|_| json!({"code":"invalid_response", "message":"Handler returned invalid JSON"}))?;
                        Ok(InvokeResponseBody::Json(response))
                    }
                }
                Err(error) => {
                    let value = error.value(py);
                    let code = value.getattr("code").and_then(|value| value.extract::<String>()).unwrap_or_else(|_| "command_failed".to_owned());
                    let message = value.getattr("message").and_then(|value| value.extract::<String>()).unwrap_or_else(|_| "Python command failed".to_owned());
                    Err(json!({"code":code,"message":message}))
                }
            }
        })
    }).await.unwrap_or_else(|_| Err(json!({"code":"worker_failed","message":"Command worker failed"})));
    result.map_err(|error| {
        let value = if legacy {
            Value::String(format!(
                "{}: {}",
                error["code"].as_str().unwrap_or("command_failed"),
                error["message"].as_str().unwrap_or("Python command failed")
            ))
        } else {
            error
        };
        InvokeError::from(value)
    })
}

fn prepare(invoke: &Invoke, legacy: bool) -> Result<(String, Vec<u8>, Option<String>), Value> {
    let invalid = || json!({"code":"invalid_request", "message":"Invalid Python command request"});
    if legacy {
        let command = invoke
            .message
            .headers()
            .get("pyfunc")
            .and_then(|value| value.to_str().ok())
            .filter(|name| !name.is_empty())
            .ok_or_else(invalid)?;
        let body = match invoke.message.payload() {
            InvokeBody::Raw(body) => body.clone(),
            InvokeBody::Json(Value::Null) => Vec::new(),
            // @tauri-apps/api/core 的默认参数将 undefined 正文转换成空对象。
            InvokeBody::Json(Value::Object(value)) if value.is_empty() => Vec::new(),
            _ => return Err(invalid()),
        };
        Ok((command.to_owned(), body, None))
    } else {
        let InvokeBody::Json(payload) = invoke.message.payload() else {
            return Err(invalid());
        };
        let command = payload
            .get("command")
            .and_then(Value::as_str)
            .filter(|name| !name.is_empty())
            .ok_or_else(invalid)?;
        let request_id = match payload.get("request_id") {
            None | Some(Value::Null) => None,
            Some(Value::String(id)) if valid_request_id(id) => Some(id.clone()),
            Some(_) => {
                return Err(json!({
                    "code": "invalid_request_id",
                    "message": "Request identifier must be printable ASCII up to 96 characters"
                }))
            }
        };
        Ok((
            command.to_owned(),
            payload
                .get("payload")
                .unwrap_or(&Value::Null)
                .to_string()
                .into_bytes(),
            request_id,
        ))
    }
}
