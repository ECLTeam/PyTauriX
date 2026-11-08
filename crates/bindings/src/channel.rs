//! 原生 Channel、窗口引用视图与弱登记的流生命周期。
use crate::{
    binding_error,
    runtime::RuntimeState,
    window::{AppHandle, WebviewWindow},
    window_state::WindowState,
};
use pyo3::{prelude::*, types::PyBytes};
use std::{
    str::FromStr,
    sync::{Arc, Mutex},
};
use tauri::ipc::InvokeResponseBody;

/// 现有 WebviewWindow 的原始代次引用；不拥有新窗口，不提供独立 Webview 构造器。
///
/// 支持工作线程查询和绑定 Channel，窗口/应用销毁后拒绝资源操作。
#[pyclass(frozen, module = "pytaruix.webview")]
pub struct Webview {
    inner: tauri::Webview,
    handle: AppHandle,
    owner: Arc<WindowState>,
}
impl Webview {
    pub fn from_window(window: &WebviewWindow) -> Self {
        Self {
            inner: window.inner.as_ref().clone(),
            handle: window.handle.clone(),
            owner: Arc::clone(&window.state),
        }
    }
    pub(crate) fn from_native(
        inner: tauri::Webview,
        handle: AppHandle,
        owner: Arc<WindowState>,
    ) -> Self {
        Self {
            inner,
            handle,
            owner,
        }
    }
    fn ensure_active(&self) -> PyResult<()> {
        self.handle.runtime.ensure_active()?;
        self.owner.ensure_active()
    }
}
#[pymethods]
impl Webview {
    /// 取得原始窗口代次的标签；应用/窗口销毁后拒绝。
    ///
    /// 返回字符串，可在工作线程调用，不修改窗口；仅当前桌面运行时已验收。
    fn label(&self) -> PyResult<&str> {
        self.ensure_active()?;
        Ok(self.inner.label())
    }
    /// 取得可跨线程的应用句柄，不拥有新窗口。
    ///
    /// 应用/窗口销毁后拒绝，不改变资源所有权；返回 AppHandle。
    fn app_handle(&self) -> PyResult<AppHandle> {
        self.ensure_active()?;
        Ok(self.handle.clone())
    }
}

/// 原生前端 Channel 标识，通过 from_str 创建，不提供任意回调构造器。
///
/// 标识仅校验格式，不证明回调存在或调用方已获授权。
#[pyclass(frozen, module = "pytaruix.ffi.ipc")]
pub struct JavaScriptChannelId {
    inner: tauri::ipc::JavaScriptChannelId,
    text: String,
}
#[pymethods]
impl JavaScriptChannelId {
    #[classmethod]
    #[pyo3(signature = (value, /))]
    /// 解析前端 Channel 文本，校验前缀及 u32 编号；不检查回调是否存在。
    ///
    /// 参数 value 为字符串；返回原生标识，无效文本为 invalid_channel_id。
    /// 可在工作线程调用，不初始化 GUI，也不修改前端状态。
    fn from_str(_class: &Bound<'_, pyo3::types::PyType>, value: &str) -> PyResult<Self> {
        let inner = tauri::ipc::JavaScriptChannelId::from_str(value)
            .map_err(|error| binding_error("invalid_channel_id", error))?;
        Ok(Self {
            inner,
            text: value.to_owned(),
        })
    }
    fn __str__(&self) -> &str {
        &self.text
    }
    #[pyo3(signature = (webview, /))]
    /// 在指定活跃 Webview 代次绑定原生通道，允许工作线程调用。
    ///
    /// 参数 webview 为现有窗口引用，返回 Channel；应用/窗口失效分别报对应关闭错误。
    /// 原生操作释放 GIL；一个前端编号应只绑定一个发送句柄，再共享该句柄。
    fn channel_on(&self, py: Python<'_>, webview: &Webview) -> PyResult<Channel> {
        py.detach(|| {
            webview.ensure_active()?;
            let native = self.inner.channel_on(webview.inner.clone());
            let id = native.id();
            let state = Arc::new(ChannelState {
                owner: Arc::clone(&webview.owner),
                native: Mutex::new(Some(native)),
            });
            webview
                .handle
                .runtime
                .resources
                .add_channel(&webview.handle.runtime, &state)?;
            Ok(Channel {
                id,
                state,
                runtime: Arc::clone(&webview.handle.runtime),
            })
        })
    }
}

pub struct ChannelState {
    pub owner: Arc<WindowState>,
    native: Mutex<Option<tauri::ipc::Channel>>,
}
impl ChannelState {
    pub fn belongs_to(&self, owner: &Arc<WindowState>) -> bool {
        Arc::ptr_eq(&self.owner, owner)
    }
    pub fn clear(&self) {
        let native = self.native.lock().ok().and_then(|mut slot| slot.take());
        // 最后一个原生句柄 drop 发送终止帧；不持资源登记锁执行 Webview 操作。
        drop(native);
    }
}

/// 原生发送句柄，由 channel_on 创建，归属应用及原始窗口代次。
///
/// 支持 JSON/字节、工作线程、显式关闭和最后引用释放；没有接收确认或自动背压。
#[pyclass(frozen, module = "pytaruix.ffi.ipc")]
pub struct Channel {
    id: u32,
    state: Arc<ChannelState>,
    runtime: Arc<RuntimeState>,
}
#[pymethods]
impl Channel {
    /// 取得前端回调编号；关闭后仍可读取。
    ///
    /// 返回 u32 对应 Python 整数，不修改资源，不检查 JS 回调是否存在。
    fn id(&self) -> u32 {
        self.id
    }
    #[getter]
    /// 查询显式关闭、窗口销毁或应用退出状态。
    ///
    /// 返回 bool；支持工作线程，只查询本地绑定状态，不请求前端确认。
    fn closed(&self) -> bool {
        !self
            .runtime
            .active
            .load(std::sync::atomic::Ordering::SeqCst)
            || !self
                .state
                .owner
                .active
                .load(std::sync::atomic::Ordering::SeqCst)
            || self.state.native.lock().map_or(true, |slot| slot.is_none())
    }
    /// 幂等释放原生句柄，提交终止帧，不等待前端确认。
    ///
    /// 返回 None；工作线程可用，释放 GIL。所有包装共享关闭状态，不取消业务任务。
    fn close(&self, py: Python<'_>) {
        py.detach(|| self.state.clear());
    }
    #[pyo3(signature = (data, /))]
    /// 发送原始 JSON 文本或 ArrayBuffer 字节，原生操作释放 GIL。
    ///
    /// 参数 data 只接受 str/bytes；无效 JSON 为 invalid_json，其他类型为 TypeError。
    /// 关闭/失效报 channel_closed/window_closed/app_closed；原生提交失败为 channel_failed。
    /// 返回 None 只表示提交成功，可在工作线程调用，不确认前端已经处理。
    fn send(&self, py: Python<'_>, data: &Bound<'_, PyAny>) -> PyResult<()> {
        // 状态错误优先，载荷在拿到原生锁之前复制，避免 GIL/资源锁反向等待。
        self.runtime.ensure_active()?;
        self.state.owner.ensure_active()?;
        py.detach(|| {
            let slot = self
                .state
                .native
                .lock()
                .map_err(|_| binding_error("state_failed", "Channel unavailable"))?;
            self.runtime.ensure_active()?;
            self.state.owner.ensure_active()?;
            if slot.is_none() {
                return Err(binding_error("channel_closed", "Channel has been closed"));
            }
            Ok(())
        })?;
        let body = if let Ok(bytes) = data.cast::<PyBytes>() {
            InvokeResponseBody::Raw(bytes.as_bytes().to_vec())
        } else if let Ok(text) = data.extract::<String>() {
            serde_json::from_str::<serde_json::Value>(&text)
                .map_err(|_| binding_error("invalid_json", "Channel text must be valid JSON"))?;
            InvokeResponseBody::Json(text)
        } else {
            return Err(pyo3::exceptions::PyTypeError::new_err(
                "Channel.send requires str or bytes",
            ));
        };
        py.detach(|| {
            let slot = self
                .state
                .native
                .lock()
                .map_err(|_| binding_error("state_failed", "Channel unavailable"))?;
            self.runtime.ensure_active()?;
            self.state.owner.ensure_active()?;
            let native = slot
                .as_ref()
                .ok_or_else(|| binding_error("channel_closed", "Channel has been closed"))?;
            native
                .send(body)
                .map_err(|error| binding_error("channel_failed", error))
        })
    }
}
