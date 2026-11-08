//! 原生 Channel、窗口引用视图与弱登记的流生命周期。
//!
//! `capacity > 0` 时通道使用窗口流控：配额由前端 `pytaruix_channel_ack` 归还，
//! 没有 ack 的前端不得启用，否则发送会一直等到通道关闭。

use crate::{
    binding_error,
    runtime::RuntimeState,
    window::{AppHandle, WebviewWindow},
    window_state::WindowState,
};
use pyo3::{prelude::*, types::PyBytes};
use std::{
    str::FromStr,
    sync::{Arc, Condvar, Mutex},
    time::{Duration, Instant},
};
use tauri::ipc::InvokeResponseBody;

/// 流控等待的轮询间隔；每次唤醒都重新检查通道与应用状态。
const FLOW_POLL: Duration = Duration::from_millis(50);

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
    #[pyo3(signature = (webview, /, *, capacity=0))]
    /// 在指定活跃 Webview 代次绑定原生通道，允许工作线程调用。
    ///
    /// 参数 webview 为现有窗口引用；capacity 为 0 表示不限制，大于 0 时启用窗口流控，
    /// 需要前端用 `pytaruix.createChannel` 归还配额。返回 Channel；应用/窗口失效分别报对应关闭错误。
    /// 原生操作释放 GIL；一个前端编号应只绑定一个发送句柄，再共享该句柄。
    fn channel_on(&self, py: Python<'_>, webview: &Webview, capacity: usize) -> PyResult<Channel> {
        py.detach(|| {
            webview.ensure_active()?;
            let native = self.inner.channel_on(webview.inner.clone());
            let id = native.id();
            let state = Arc::new(ChannelState {
                id,
                owner: Arc::clone(&webview.owner),
                native: Mutex::new(Some(native)),
                flow: (capacity > 0).then(|| Flow::new(capacity)),
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

/// 窗口流控配额；容量由 Python 指定，归还只来自前端 ack 或发送失败回滚。
struct Flow {
    capacity: usize,
    inflight: Mutex<usize>,
    available: Condvar,
}

impl Flow {
    fn new(capacity: usize) -> Self {
        Self {
            capacity,
            inflight: Mutex::new(0),
            available: Condvar::new(),
        }
    }
    fn pending(&self) -> usize {
        self.inflight.lock().map(|value| *value).unwrap_or(0)
    }
    fn try_acquire(&self) -> Result<bool, ()> {
        let mut inflight = self.inflight.lock().map_err(|_| ())?;
        if *inflight < self.capacity {
            *inflight += 1;
            return Ok(true);
        }
        Ok(false)
    }
    fn release(&self) {
        if let Ok(mut inflight) = self.inflight.lock() {
            *inflight = inflight.saturating_sub(1);
        }
        self.available.notify_one();
    }
    fn wake_all(&self) {
        self.available.notify_all();
    }
}

pub struct ChannelState {
    pub owner: Arc<WindowState>,
    pub id: u32,
    native: Mutex<Option<tauri::ipc::Channel>>,
    flow: Option<Flow>,
}
impl ChannelState {
    pub fn belongs_to(&self, owner: &Arc<WindowState>) -> bool {
        Arc::ptr_eq(&self.owner, owner)
    }
    fn is_open(&self, runtime: &RuntimeState) -> bool {
        runtime.active.load(std::sync::atomic::Ordering::SeqCst)
            && self.owner.active.load(std::sync::atomic::Ordering::SeqCst)
            && self.native.lock().is_ok_and(|slot| slot.is_some())
    }
    /// 等待流控配额；关闭的通道立即失败，超时返回 false。
    fn acquire(
        &self,
        runtime: &RuntimeState,
        timeout: Option<Duration>,
    ) -> Result<(), &'static str> {
        let Some(flow) = &self.flow else {
            return Ok(());
        };
        let start = Instant::now();
        loop {
            if !self.is_open(runtime) {
                return Err("closed");
            }
            match flow.try_acquire() {
                Ok(true) => return Ok(()),
                Ok(false) => {}
                Err(()) => return Err("closed"),
            }
            if timeout.is_some_and(|limit| start.elapsed() >= limit) {
                return Err("timeout");
            }
            // 等待在释放 GIL 的路径中执行，唤醒后重新检查关闭状态与配额。
            if let Ok(inflight) = flow.inflight.lock() {
                let _ = flow.available.wait_timeout(inflight, FLOW_POLL);
            }
        }
    }
    /// 归还一次配额；没有启用流控时返回 false。
    pub fn release(&self) -> bool {
        match &self.flow {
            Some(flow) => {
                flow.release();
                true
            }
            None => false,
        }
    }
    pub fn clear(&self) {
        let native = self.native.lock().ok().and_then(|mut slot| slot.take());
        if let Some(flow) = &self.flow {
            flow.wake_all();
        }
        // 最后一个原生句柄 drop 发送终止帧；不持资源登记锁执行 Webview 操作。
        drop(native);
    }
}

/// 原生发送句柄，由 channel_on 创建，归属应用及原始窗口代次。
///
/// 支持 JSON/字节、工作线程、显式关闭和最后引用释放；capacity > 0 时按配额发送。
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
        !self.state.is_open(&self.runtime)
    }
    #[getter]
    /// 查询尚未归还的流控配额；未启用流控时恒为 0。
    fn pending(&self) -> usize {
        self.state.flow.as_ref().map_or(0, |flow| flow.pending())
    }
    /// 幂等释放原生句柄，提交终止帧，不等待前端确认。
    ///
    /// 返回 None；工作线程可用，释放 GIL。所有包装共享关闭状态，不取消业务任务。
    fn close(&self, py: Python<'_>) {
        py.detach(|| self.state.clear());
    }
    #[pyo3(signature = (data, /, *, timeout=None))]
    /// 发送原始 JSON 文本或 ArrayBuffer 字节，原生操作释放 GIL。
    ///
    /// 参数 data 只接受 str/bytes；timeout 仅在启用流控时生效，单位秒。
    /// 无效 JSON 为 invalid_json，其他类型为 TypeError。
    /// 关闭/失效报 channel_closed/window_closed/app_closed；配额超时为 channel_backpressure。
    /// 返回 None 只表示提交成功，可在工作线程调用，不确认前端已经处理。
    fn send(&self, py: Python<'_>, data: &Bound<'_, PyAny>, timeout: Option<f64>) -> PyResult<()> {
        // 状态错误优先，载荷在拿到原生锁之前复制，避免 GIL/资源锁反向等待。
        self.runtime.ensure_active()?;
        self.state.owner.ensure_active()?;
        if timeout.is_some_and(|value| !(value.is_finite() && value >= 0.0)) {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "timeout must be a non-negative finite number",
            ));
        }
        // 失效对象优先于载荷格式校验，避免关闭后仍返回 invalid_json 这类细节。
        let open = self
            .state
            .native
            .lock()
            .map_err(|_| binding_error("state_failed", "Channel unavailable"))?
            .is_some();
        if !open {
            return Err(binding_error("channel_closed", "Channel has been closed"));
        }
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
        let deadline = timeout.map(Duration::from_secs_f64);
        py.detach(move || {
            self.state
                .acquire(&self.runtime, deadline)
                .map_err(|reason| match reason {
                    "timeout" => binding_error(
                        "channel_backpressure",
                        "Channel send window is still full after the timeout",
                    ),
                    _ => binding_error("channel_closed", "Channel has been closed"),
                })?;
            let sent = self
                .state
                .native
                .lock()
                .map_err(|_| binding_error("state_failed", "Channel unavailable"))
                .and_then(|slot| {
                    self.runtime.ensure_active()?;
                    self.state.owner.ensure_active()?;
                    let native = slot.as_ref().ok_or_else(|| {
                        binding_error("channel_closed", "Channel has been closed")
                    })?;
                    native
                        .send(body)
                        .map_err(|error| binding_error("channel_failed", error))
                });
            if sent.is_err() {
                // 提交失败必须回滚配额，避免容量泄漏到前端永远 ack 不到的一条消息上。
                self.state.release();
            }
            sent
        })
    }
}
