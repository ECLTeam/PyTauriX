//! 新 JSON 协议与旧 PyTauri 字节协议共用一个 Python 工作线程分发器。
use crate::{
    runtime::RuntimeState,
    window::{AppHandle, WebviewWindow},
};
use pyo3::{prelude::*, types::PyBytes};
use serde_json::{json, Value};
use std::sync::Arc;
use tauri::{
    ipc::{Invoke, InvokeBody, InvokeError, InvokeResponseBody},
    Manager,
};

pub struct PythonCommands(pub Py<PyAny>);

pub fn invoke_handler(invoke: Invoke) -> bool {
    if invoke.message.command() != "python_command" {
        return false;
    }
    dispatch(invoke, false);
    true
}
pub fn legacy_handler(invoke: Invoke) -> bool {
    if invoke.message.command() != "pyfunc" {
        return false;
    }
    dispatch(invoke, true);
    true
}

fn dispatch(invoke: Invoke, legacy: bool) {
    let result = prepare(&invoke, legacy);
    let (command, body) = match result {
        Ok(request) => request,
        Err(error) => {
            invoke.resolver.reject(if legacy {
                Value::String(error.to_string())
            } else {
                error
            });
            return;
        }
    };
    let webview = invoke.message.webview();
    let app = webview.app_handle();
    let Some(window) = app.get_webview_window(webview.label()) else {
        invoke.resolver.reject(if legacy {
            json!("invalid_window")
        } else {
            json!({"code":"invalid_window", "message":"Origin is not a WebviewWindow"})
        });
        return;
    };
    let runtime = Arc::clone(app.state::<Arc<RuntimeState>>().inner());
    // 在排队前捕获来源窗口代次；工作线程不能按同名新窗口重新取得所有权。
    let window_state = match runtime.window_state(webview.label()) {
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
    let app = app.clone();
    invoke.resolver.respond_async_serialized(async move {
        let result = tauri::async_runtime::spawn_blocking(move || {
            // 配置窗口在 setup 之前加载页面；等待初始化完成，避免早到 IPC 读取半初始化状态。
            // 这里没有 GIL，也没有占用 GUI 线程。
            if !runtime.wait_for_setup() {
                return Err(json!({"code":"app_closed", "message":"Application initialization failed or exited"}));
            }
            Python::attach(|py| {
                if runtime.ensure_active().is_err() { return Err(json!({"code":"app_closed", "message":"Application has exited"})); }
                let handle = AppHandle::new(app, runtime);
                window_state.ensure_active().map_err(|_| json!({"code":"window_closed", "message":"Originating window has been destroyed"}))?;
                let window = WebviewWindow { inner: window, handle: handle.clone(), state: window_state };
                let py_headers: Vec<(Py<PyBytes>, Py<PyBytes>)> = headers.iter().map(|(name,value)|
                    (PyBytes::new(py, name).unbind(), PyBytes::new(py, value).unbind())).collect();
                let response = handler.call1(py, (command, PyBytes::new(py, &body), handle, window, py_headers, legacy));
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
        result.map_err(|error| InvokeError::from(if legacy { Value::String(format!("{}: {}", error["code"].as_str().unwrap_or("command_failed"), error["message"].as_str().unwrap_or("Python command failed"))) } else { error }))
    });
}

fn prepare(invoke: &Invoke, legacy: bool) -> Result<(String, Vec<u8>), Value> {
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
        Ok((command.to_owned(), body))
    } else {
        let InvokeBody::Json(payload) = invoke.message.payload() else {
            return Err(invalid());
        };
        let command = payload
            .get("command")
            .and_then(Value::as_str)
            .filter(|name| !name.is_empty())
            .ok_or_else(invalid)?;
        Ok((
            command.to_owned(),
            payload
                .get("payload")
                .unwrap_or(&Value::Null)
                .to_string()
                .into_bytes(),
        ))
    }
}
