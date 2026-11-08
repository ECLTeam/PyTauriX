//! WebView 策略回调：不可变快照、失败拒绝与窗口代次隔离。
use crate::{
    binding_error,
    window::AppHandle,
    window_state::{check_sync, Scope, WindowState},
};
use pyo3::{prelude::*, types::PyBytes, types::PyTuple};
use std::{borrow::Cow, sync::Arc};
use tauri::http::{HeaderMap, HeaderName, HeaderValue, Response, StatusCode};

type ResponseParts = (u16, Vec<(String, Vec<u8>)>, Vec<u8>);

fn headers<'py>(py: Python<'py>, values: &HeaderMap) -> PyResult<Bound<'py, PyTuple>> {
    PyTuple::new(
        py,
        values
            .iter()
            .map(|(name, value)| (name.as_str(), PyBytes::new(py, value.as_bytes())))
            .collect::<Vec<_>>(),
    )
}

fn response(py: Python<'_>, value: Py<PyAny>) -> PyResult<Response<Cow<'static, [u8]>>> {
    // 即使调用方绕过 frozen dataclass，也在 Python/HTTP 边界重新完整校验。
    let parts = py
        .import("pytaurix.webview_requests")?
        .getattr("_response_parts")?
        .call1((value,))?;
    let (status, fields, body): ResponseParts = parts.extract()?;
    let mut result = Response::new(Cow::Owned(body));
    *result.status_mut() =
        StatusCode::from_u16(status).map_err(|error| binding_error("invalid_response", error))?;
    for (name, value) in fields {
        let name = HeaderName::from_bytes(name.as_bytes())
            .map_err(|error| binding_error("invalid_response", error))?;
        let value = HeaderValue::from_bytes(&value)
            .map_err(|error| binding_error("invalid_response", error))?;
        result.headers_mut().append(name, value);
    }
    Ok(result)
}

fn reject_response(target: &mut Response<Cow<'static, [u8]>>) {
    // 不泄露原页面/正文或异常细节，也不保留旧 Content-Length/CSP 等头部。
    *target = Response::new(Cow::Borrowed(b""));
    *target.status_mut() = StatusCode::INTERNAL_SERVER_ERROR;
}

/// 在创建窗口时安装策略钩子；只持有运行态及所属窗口代次的弱引用。
pub fn register<'a>(
    mut builder: tauri::WebviewWindowBuilder<'a, tauri::Wry, tauri::AppHandle>,
    handle: &AppHandle,
    state: &Arc<WindowState>,
    new_window: bool,
    permission: bool,
    resource: bool,
) -> tauri::WebviewWindowBuilder<'a, tauri::Wry, tauri::AppHandle> {
    if new_window {
        let runtime = Arc::downgrade(&handle.runtime);
        let state = Arc::downgrade(state);
        let native = handle.inner.clone();
        builder = builder.on_new_window(move |url, features| {
            let (Some(runtime), Some(state)) = (runtime.upgrade(), state.upgrade()) else {
                return tauri::webview::NewWindowResponse::Deny;
            };
            if runtime.failed()
                || runtime.ensure_active().is_err()
                || state.ensure_active().is_err()
            {
                return tauri::webview::NewWindowResponse::Deny;
            }
            let decision = Python::attach(|py| -> PyResult<String> {
                let _scope = Scope::callback();
                let callback = state.callback(py, "new_window")?.ok_or_else(|| {
                    binding_error("window_closed", "New window handler has been cleared")
                })?;
                let module = py.import("pytaurix.webview_requests")?;
                let size = features.size().map(|value| (value.width, value.height));
                let position = features.position().map(|value| (value.x, value.y));
                let features = module
                    .getattr("NewWindowFeatures")?
                    .call1((size, position))?;
                let result = callback.call1(py, (url.as_str(), features))?;
                check_sync(py, result.clone_ref(py))?;
                module
                    .getattr("_decision")?
                    .call1((result, "new_window"))?
                    .extract()
            });
            match decision {
                Ok(value) if value == "allow" => tauri::webview::NewWindowResponse::Allow,
                Ok(_) => tauri::webview::NewWindowResponse::Deny,
                Err(error) => {
                    runtime.fail(&native, error);
                    tauri::webview::NewWindowResponse::Deny
                }
            }
        });
    }
    if permission {
        let runtime = Arc::downgrade(&handle.runtime);
        let state = Arc::downgrade(state);
        let native = handle.inner.clone();
        builder = builder.on_permission_request(move |view, kind| {
            let (Some(runtime), Some(state)) = (runtime.upgrade(), state.upgrade()) else {
                return tauri::webview::PermissionResponse::Deny;
            };
            if runtime.failed()
                || runtime.ensure_active().is_err()
                || state.ensure_active().is_err()
            {
                return tauri::webview::PermissionResponse::Deny;
            }
            let decision = Python::attach(|py| -> PyResult<String> {
                let _scope = Scope::callback();
                let callback = state.callback(py, "permission")?.ok_or_else(|| {
                    binding_error("window_closed", "Permission handler has been cleared")
                })?;
                let module = py.import("pytaurix.webview_requests")?;
                let kind = module
                    .getattr("PermissionKind")?
                    .call1((kind.to_string(),))?;
                let handle = AppHandle::new(native.clone(), Arc::clone(&runtime));
                let view = crate::channel::Webview::from_native(view, handle, Arc::clone(&state));
                let result = callback.call1(py, (view, kind))?;
                check_sync(py, result.clone_ref(py))?;
                module
                    .getattr("_decision")?
                    .call1((result, "permission"))?
                    .extract()
            });
            match decision {
                Ok(value) if value == "allow" => tauri::webview::PermissionResponse::Allow,
                Ok(value) if value == "default" => tauri::webview::PermissionResponse::Default,
                Ok(_) => tauri::webview::PermissionResponse::Deny,
                Err(error) => {
                    runtime.fail(&native, error);
                    tauri::webview::PermissionResponse::Deny
                }
            }
        });
    }
    if resource {
        let runtime = Arc::downgrade(&handle.runtime);
        let state = Arc::downgrade(state);
        let native = handle.inner.clone();
        builder = builder.on_web_resource_request(move |request, target| {
            let (Some(runtime), Some(state)) = (runtime.upgrade(), state.upgrade()) else {
                reject_response(target);
                return;
            };
            if runtime.failed()
                || runtime.ensure_active().is_err()
                || state.ensure_active().is_err()
            {
                reject_response(target);
                return;
            }
            let result = Python::attach(|py| -> PyResult<Option<Response<Cow<'static, [u8]>>>> {
                let _scope = Scope::callback();
                let callback = state.callback(py, "resource")?.ok_or_else(|| {
                    binding_error("window_closed", "Resource handler has been cleared")
                })?;
                let module = py.import("pytaurix.webview_requests")?;
                let request = module.getattr("WebResourceRequest")?.call1((
                    request.uri().to_string(),
                    request.method().as_str(),
                    headers(py, request.headers())?,
                    PyBytes::new(py, request.body()),
                ))?;
                let original = module.getattr("WebResourceResponse")?.call1((
                    target.status().as_u16(),
                    headers(py, target.headers())?,
                    PyBytes::new(py, target.body().as_ref()),
                ))?;
                let result = callback.call1(py, (request, original))?;
                check_sync(py, result.clone_ref(py))?;
                if result.is_none(py) {
                    Ok(None)
                } else {
                    response(py, result).map(Some)
                }
            });
            match result {
                Ok(Some(value)) => *target = value,
                Ok(None) => (),
                Err(error) => {
                    reject_response(target);
                    runtime.fail(&native, error);
                }
            }
        });
    }
    builder
}
