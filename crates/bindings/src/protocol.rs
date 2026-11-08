//! Python 自定义 URI scheme 协议。
//!
//! 只暴露异步响应版本：Python 回调在阻塞工作线程执行，GUI 线程不等待。
//! 上游同步版本会在调用线程直接执行回调；由 Python 承担该风险没有安全收益，故不提供。

use crate::{binding_error, runtime::RuntimeState};
use pyo3::{prelude::*, types::PyBytes};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use tauri::{
    http::{
        header::{HeaderName, HeaderValue},
        Response, StatusCode,
    },
    Manager,
};

/// scheme 名长度上限；与上游要求的 ASCII 小写标识保持一致。
const SCHEME_LIMIT: usize = 32;

/// 上游已占用或与传输语义冲突的 scheme，注册即拒绝。
const RESERVED: [&str; 6] = ["tauri", "asset", "http", "https", "ipc", "channel"];

/// 处理器归还的状态码、头字段与正文。
type ResponseParts = (u16, Vec<(String, String)>, Vec<u8>);

pub fn valid_scheme(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= SCHEME_LIMIT
        && !RESERVED.contains(&name)
        && name.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'-' | b'+' | b'.')
        })
        && name.as_bytes()[0].is_ascii_lowercase()
}

/// 一次性消费的协议描述符；构建应用时交给原生构建器。
#[pyclass(frozen, module = "pytaurix.protocol")]
pub struct Protocol {
    name: String,
    handler: Py<PyAny>,
    consumed: AtomicBool,
}

impl Protocol {
    /// 取出处理器；重复消费返回 protocol_consumed。
    pub fn take(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        if self.consumed.swap(true, Ordering::SeqCst) {
            return Err(binding_error(
                "protocol_consumed",
                "Protocol was already consumed",
            ));
        }
        Ok(self.handler.clone_ref(py))
    }
}

#[pymethods]
impl Protocol {
    #[getter]
    pub fn name(&self) -> &str {
        &self.name
    }
    #[getter]
    fn consumed(&self) -> bool {
        self.consumed.load(Ordering::SeqCst)
    }
}

#[pyfunction]
/// 创建协议描述符；名称非法、保留或处理器不可调用时拒绝。
///
/// 参数 name 为 ASCII 小写 scheme，handler 为同步可调用对象。
/// 返回一次性描述符，导入与创建都不初始化 GUI。
pub fn protocol_create(py: Python<'_>, name: &str, handler: Py<PyAny>) -> PyResult<Protocol> {
    if !valid_scheme(name) {
        return Err(binding_error(
            "invalid_protocol_name",
            "Scheme must be lowercase ASCII letters, digits, '-', '+' or '.', and not reserved",
        ));
    }
    if !handler.bind(py).is_callable() {
        return Err(binding_error(
            "invalid_callback",
            "protocol handler must be callable",
        ));
    }
    Ok(Protocol {
        name: name.to_owned(),
        handler,
        consumed: AtomicBool::new(false),
    })
}

/// 在构建期登记异步协议；每次请求在阻塞工作线程调用 Python。
pub fn register(
    builder: tauri::Builder<tauri::Wry>,
    name: String,
    handler: Py<PyAny>,
) -> tauri::Builder<tauri::Wry> {
    builder.register_asynchronous_uri_scheme_protocol(name, move |context, request, responder| {
        let runtime = Arc::clone(context.app_handle().state::<Arc<RuntimeState>>().inner());
        let label = context.webview_label().to_owned();
        let handler = Python::attach(|py| handler.clone_ref(py));
        let (parts, body) = request.into_parts();
        let uri = parts.uri.to_string();
        let method = parts.method.as_str().to_owned();
        let headers = parts
            .headers
            .iter()
            .map(|(name, value)| {
                (
                    name.as_str().to_owned(),
                    String::from_utf8_lossy(value.as_bytes()).into_owned(),
                )
            })
            .collect::<Vec<_>>();
        tauri::async_runtime::spawn_blocking(move || {
            responder.respond(serve(&runtime, handler, uri, method, headers, body, label));
        });
    })
}

/// 调用 Python 处理一次请求；任何失败都归还空 500，不把异常带到前端。
fn serve(
    runtime: &RuntimeState,
    handler: Py<PyAny>,
    uri: String,
    method: String,
    headers: Vec<(String, String)>,
    body: Vec<u8>,
    label: String,
) -> Response<Vec<u8>> {
    // 配置窗口在 setup 之前就可能有资源请求；等待初始化而不是读取半初始化状态。
    if !runtime.wait_for_setup() {
        return failure(StatusCode::SERVICE_UNAVAILABLE);
    }
    let result = Python::attach(|py| -> PyResult<ResponseParts> {
        runtime.ensure_active()?;
        let value = handler.call1(py, (uri, method, headers, PyBytes::new(py, &body), label))?;
        let value = value.bind(py);
        let status = value.get_item(0)?.extract::<u16>()?;
        let headers = value.get_item(1)?.extract::<Vec<(String, String)>>()?;
        let body = value.get_item(2)?.extract::<Vec<u8>>()?;
        Ok((status, headers, body))
    });
    let Ok((status, headers, body)) = result else {
        return failure(StatusCode::INTERNAL_SERVER_ERROR);
    };
    let Ok(status) = StatusCode::from_u16(status) else {
        return failure(StatusCode::INTERNAL_SERVER_ERROR);
    };
    let mut response = Response::new(body);
    *response.status_mut() = status;
    for (name, value) in headers {
        let (Ok(name), Ok(value)) = (
            HeaderName::try_from(name.as_str()),
            HeaderValue::try_from(value.as_str()),
        ) else {
            return failure(StatusCode::INTERNAL_SERVER_ERROR);
        };
        response.headers_mut().append(name, value);
    }
    response
}

fn failure(status: StatusCode) -> Response<Vec<u8>> {
    let mut response = Response::new(Vec::new());
    *response.status_mut() = status;
    response
}
