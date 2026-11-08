//! 可跨线程句柄、类型状态与具有明确清理路径的事件监听。
use crate::{binding_error, runtime::RuntimeState, window_state::WindowState};
use pyo3::{prelude::*, types::PyType};
use std::sync::Arc;
use tauri::Manager;

#[pyclass(frozen, skip_from_py_object, module = "pytaruix.ffi")]
#[derive(Clone)]
pub struct AppHandle {
    pub inner: tauri::AppHandle,
    pub runtime: Arc<RuntimeState>,
}

impl AppHandle {
    pub fn new(inner: tauri::AppHandle, runtime: Arc<RuntimeState>) -> Self {
        Self { inner, runtime }
    }
}

#[pymethods]
impl AppHandle {
    /// 查询应用持有的托盘；返回共享代次句柄，仅启用 tray-icon 时可用。
    #[cfg(all(desktop, feature = "tray-icon"))]
    #[pyo3(signature = (id, /))]
    pub fn tray_by_id(&self, py: Python<'_>, id: String) -> PyResult<Py<PyAny>> {
        crate::tray::lookup(py, self, id, false)
    }
    /// 移除应用持有引用并返回托盘；现存句柄继续有效，不等同于 close。
    #[cfg(all(desktop, feature = "tray-icon"))]
    #[pyo3(signature = (id, /))]
    pub fn remove_tray_by_id(&self, py: Python<'_>, id: String) -> PyResult<Py<PyAny>> {
        crate::tray::lookup(py, self, id, true)
    }
    /// 累加应用级托盘回调；同步异常归还 run_return，回调内禁止注册。
    #[cfg(all(desktop, feature = "tray-icon"))]
    #[pyo3(signature = (handler, /))]
    pub fn on_tray_icon_event(&self, py: Python<'_>, handler: Py<PyAny>) -> PyResult<()> {
        crate::tray::listen_global(py, self, handler)
    }
    /// 清空应用级托盘回调，释放 Python 引用；可在同步回调内调用。
    #[cfg(all(desktop, feature = "tray-icon"))]
    pub fn clear_tray_icon_event_handlers(&self) -> PyResult<()> {
        crate::tray::clear_global(self)
    }
    pub fn exit(&self, py: Python<'_>, exit_code: i32) -> PyResult<()> {
        self.runtime.ensure_active()?;
        py.detach(|| self.inner.exit(exit_code));
        Ok(())
    }
    /// 返回当前应用菜单，未挂载时返回 None。
    ///
    /// 桌面 setup 或运行期间使用，释放 GIL，禁止同步回调重入。
    #[cfg(desktop)]
    pub fn menu(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        crate::menu::attachment(py, self, None, "get", None)
    }
    /// 设置同应用 Menu 并返回先前菜单。
    ///
    /// 系统应用菜单规则沿用 Tauri，工作线程释放 GIL，退出后拒绝。
    #[cfg(desktop)]
    #[pyo3(signature = (menu, /))]
    pub fn set_menu(&self, py: Python<'_>, menu: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        crate::menu::attachment(py, self, None, "set", Some(menu))
    }
    /// 移除应用菜单并返回先前菜单。
    ///
    /// 显式窗口菜单沿用 Tauri 行为；释放 GIL，退出后拒绝。
    #[cfg(desktop)]
    pub fn remove_menu(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        crate::menu::attachment(py, self, None, "remove", None)
    }
    /// 累加同步菜单回调，参数为应用句柄及字符串菜单 ID。
    ///
    /// 菜单事件全局广播；异常归还 run_return，禁止回调内注册。
    #[cfg(desktop)]
    #[pyo3(signature = (handler, /))]
    pub fn on_menu_event(&self, py: Python<'_>, handler: Py<PyAny>) -> PyResult<()> {
        crate::menu::listen(py, self, None, handler)
    }
    /// 清空本应用入口注册的 Python 菜单回调。
    ///
    /// 不移除上游原生弱引用监听闭包；可在回调内停止后续派发。
    #[cfg(desktop)]
    pub fn clear_menu_event_handlers(&self) -> PyResult<()> {
        crate::menu::clear(self, None)
    }
    pub fn get_webview_window(&self, label: &str) -> PyResult<Option<WebviewWindow>> {
        self.runtime.ensure_active()?;
        self.inner
            .get_webview_window(label)
            .map(|inner| WebviewWindow::new(inner, self.clone()))
            .transpose()
            .map(|window| window.filter(|window| window.state.ensure_active().is_ok()))
    }
    pub fn webview_windows(&self) -> PyResult<std::collections::HashMap<String, WebviewWindow>> {
        self.runtime.ensure_active()?;
        let mut windows = std::collections::HashMap::new();
        for (label, inner) in self.inner.webview_windows() {
            let window = WebviewWindow::new(inner, self.clone())?;
            if window.state.ensure_active().is_ok() {
                windows.insert(label, window);
            }
        }
        Ok(windows)
    }
    pub fn manage(&self, py: Python<'_>, value: Py<PyAny>) -> PyResult<bool> {
        self.runtime.ensure_active()?;
        if value.is_none(py) {
            return Err(binding_error(
                "invalid_state",
                "None cannot be registered as managed state",
            ));
        }
        let states = self.runtime.states.bind(py);
        let key = value.bind(py).get_type();
        if states.contains(&key)? {
            return Ok(false);
        }
        states.set_item(key, value)?;
        Ok(true)
    }
    pub fn try_state(
        &self,
        py: Python<'_>,
        state_type: &Bound<'_, PyType>,
    ) -> PyResult<Option<Py<PyAny>>> {
        self.runtime.ensure_active()?;
        Ok(self
            .runtime
            .states
            .bind(py)
            .get_item(state_type)?
            .map(Bound::unbind))
    }
    /// 提交主线程同步回调，不等待任务完成；退出清理尚未执行的回调。
    pub fn run_on_main_thread(&self, py: Python<'_>, callback: Py<PyAny>) -> PyResult<()> {
        crate::dispatch::submit(py, self, None, callback)
    }
    pub fn emit_json(&self, py: Python<'_>, event: &str, payload_json: &str) -> PyResult<()> {
        crate::events::emit(py, self, None, event, payload_json)
    }
    pub fn emit_to_json(
        &self,
        py: Python<'_>,
        target: &str,
        event: &str,
        payload_json: &str,
    ) -> PyResult<()> {
        crate::events::emit(
            py,
            self,
            Some(tauri::EventTarget::labeled(target)),
            event,
            payload_json,
        )
    }
    pub fn emit_target_json(
        &self,
        py: Python<'_>,
        target_json: &str,
        event: &str,
        payload_json: &str,
    ) -> PyResult<()> {
        crate::events::emit_target(py, self, target_json, event, payload_json)
    }
    #[pyo3(signature = (event, callback, *, once=false, any_target=false))]
    pub fn listen(
        &self,
        py: Python<'_>,
        event: &str,
        callback: Py<PyAny>,
        once: bool,
        any_target: bool,
    ) -> PyResult<u32> {
        crate::events::listen(py, self, None, event, callback, once, any_target)
    }
    pub fn unlisten(&self, py: Python<'_>, id: u32) -> PyResult<()> {
        crate::events::unlisten(py, self, None, id)
    }
}

#[pyclass(frozen, module = "pytaruix.webview")]
pub struct WebviewWindow {
    pub inner: tauri::WebviewWindow,
    pub handle: AppHandle,
    pub state: Arc<WindowState>,
}

impl WebviewWindow {
    pub fn new(inner: tauri::WebviewWindow, handle: AppHandle) -> PyResult<Self> {
        let state = handle.runtime.window_state(inner.label())?;
        Ok(Self {
            inner,
            handle,
            state,
        })
    }
    pub(crate) fn ensure_active(&self) -> PyResult<()> {
        self.handle.runtime.ensure_active()?;
        self.state.ensure_active()
    }
}

#[pymethods]
impl WebviewWindow {
    /// 异步请求打开开发者工具，释放 GIL，不等待面板出现。
    ///
    /// 需要运行中的窗口及 debug 构建或 devtools feature；同步 GUI 回调内拒绝。
    pub fn open_devtools(&self, py: Python<'_>) -> PyResult<()> {
        crate::devtools::operate(py, self, "open").map(|_| ())
    }

    /// 异步请求关闭开发者工具，释放 GIL，不等待面板消失。
    ///
    /// 生命周期、构建 feature 和线程要求同 open_devtools；Windows 上游未实现，返回 platform_unavailable。
    pub fn close_devtools(&self, py: Python<'_>) -> PyResult<()> {
        crate::devtools::operate(py, self, "close").map(|_| ())
    }

    /// 查询开发者工具状态，释放 GIL并等待原生查询完成。
    ///
    /// 工作线程使用；同步 GUI 回调内拒绝，关闭原窗口后返回 window_closed。
    /// Windows 上游未实现，返回 platform_unavailable，不把固定 false 当作真实状态。
    pub fn is_devtools_open(&self, py: Python<'_>) -> PyResult<bool> {
        crate::devtools::operate(py, self, "state")
    }

    /// 返回当前窗口菜单，未挂载时返回 None。
    ///
    /// 检查原窗口代次，释放 GIL，禁止同步回调重入。
    #[cfg(desktop)]
    pub fn menu(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        crate::menu::attachment(py, &self.handle, Some(self), "get", None)
    }
    /// 设置同应用 Menu 并返回先前菜单。
    ///
    /// 原窗口关闭后拒绝操作；桌面规则沿用 Tauri，释放 GIL。
    #[cfg(desktop)]
    #[pyo3(signature = (menu, /))]
    pub fn set_menu(&self, py: Python<'_>, menu: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        crate::menu::attachment(py, &self.handle, Some(self), "set", Some(menu))
    }
    /// 移除窗口菜单并返回先前菜单。
    ///
    /// 原窗口关闭后拒绝操作；释放 GIL，禁止同步回调重入。
    #[cfg(desktop)]
    pub fn remove_menu(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        crate::menu::attachment(py, &self.handle, Some(self), "remove", None)
    }
    /// 弹出 Menu 或 Submenu，位置由平台默认决定。
    ///
    /// 弹出可能等待用户选择；工作线程释放 GIL，同步回调内拒绝。
    #[cfg(desktop)]
    #[pyo3(signature = (menu, /))]
    pub fn popup_menu(&self, py: Python<'_>, menu: &Bound<'_, PyAny>) -> PyResult<()> {
        crate::menu::popup(py, self, menu, None)
    }
    /// 在窗口坐标中的逻辑或物理位置弹出 Menu 或 Submenu。
    ///
    /// 接受已绑定的位置类型；检查原代次，释放 GIL，禁止回调重入。
    #[cfg(desktop)]
    #[pyo3(signature = (menu, position, /))]
    pub fn popup_menu_at(
        &self,
        py: Python<'_>,
        menu: &Bound<'_, PyAny>,
        position: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        crate::menu::popup(py, self, menu, Some(position))
    }
    /// 替换原窗口的同步菜单回调，参数为订阅窗口及字符串 ID。
    ///
    /// 上游事件全局广播，窗口参数不代表点击来源；关闭原代次清理引用。
    #[cfg(desktop)]
    #[pyo3(signature = (handler, /))]
    pub fn on_menu_event(&self, py: Python<'_>, handler: Py<PyAny>) -> PyResult<()> {
        crate::menu::listen(py, &self.handle, Some(self), handler)
    }
    /// 清空原窗口代次的 Python 菜单回调。
    ///
    /// 可在回调内清空；不移除上游弱引用闭包，旧句柄不能操作重建窗口。
    #[cfg(desktop)]
    pub fn clear_menu_event_handlers(&self) -> PyResult<()> {
        crate::menu::clear(&self.handle, Some(&self.state))
    }
    /// 查询当前窗口所在显示器，原生无匹配时返回 None。
    ///
    /// 返回不可变 Monitor 快照；释放 GIL，支持运行中的工作线程。
    /// 应用/窗口失效返回 app_closed/window_closed；未运行返回 app_not_running，
    /// GUI 同步回调返回 blocking_callback，原生错误返回 monitor_failed。
    pub fn current_monitor(&self, py: Python<'_>) -> PyResult<Option<crate::monitor::Monitor>> {
        crate::monitor::query(py, self, || self.inner.current_monitor())
            .map(|value| value.map(|inner| crate::monitor::Monitor { inner }))
    }

    /// 查询系统主显示器，原生未提供时返回 None。
    ///
    /// 返回不可变快照；释放 GIL，支持工作线程，平台语义沿用 Tauri。
    /// 状态与线程错误同 current_monitor，不在同步 GUI 回调内阻塞等待。
    pub fn primary_monitor(&self, py: Python<'_>) -> PyResult<Option<crate::monitor::Monitor>> {
        crate::monitor::query(py, self, || self.inner.primary_monitor())
            .map(|value| value.map(|inner| crate::monitor::Monitor { inner }))
    }

    /// 枚举当前系统显示器，返回独立 Monitor 快照列表。
    ///
    /// 原生顺序不保证稳定；释放 GIL，支持工作线程，不订阅热插拔。
    /// 状态与线程错误同 current_monitor，原生失败返回 monitor_failed。
    pub fn available_monitors(&self, py: Python<'_>) -> PyResult<Vec<crate::monitor::Monitor>> {
        crate::monitor::query(py, self, || self.inner.available_monitors()).map(|values| {
            values
                .into_iter()
                .map(|inner| crate::monitor::Monitor { inner })
                .collect()
        })
    }

    /// 查询包含物理像素坐标的显示器，原生无匹配时返回 None。
    ///
    /// x/y 必须为有限数值，允许负坐标；非法值返回 invalid_position。
    /// 释放 GIL，返回独立快照；状态与线程错误同 current_monitor。
    #[pyo3(signature = (x, y, /))]
    pub fn monitor_from_point(
        &self,
        py: Python<'_>,
        x: f64,
        y: f64,
    ) -> PyResult<Option<crate::monitor::Monitor>> {
        self.ensure_active()?;
        if !x.is_finite() || !y.is_finite() {
            return Err(binding_error(
                "invalid_position",
                "Coordinates must be finite",
            ));
        }
        crate::monitor::query(py, self, || self.inner.monitor_from_point(x, y))
            .map(|value| value.map(|inner| crate::monitor::Monitor { inner }))
    }

    /// 返回现有窗口所属代次的 Webview 引用，不创建新原生资源。
    ///
    /// 可在工作线程调用；应用/窗口销毁后分别返回 app_closed/window_closed。
    /// 此引用仅提供 label/app_handle 与 channel_on 所需的视图，不代表完整 Webview API。
    pub fn as_ref_webview(&self) -> PyResult<crate::channel::Webview> {
        self.ensure_active()?;
        Ok(crate::channel::Webview::from_window(self))
    }
    /// 提交属于本窗口代次的主线程同步回调；销毁取消尚未执行的任务。
    pub fn run_on_main_thread(&self, py: Python<'_>, callback: Py<PyAny>) -> PyResult<()> {
        self.ensure_active()?;
        crate::dispatch::submit(py, &self.handle, Some(self), callback)
    }
    pub fn emit_json(&self, py: Python<'_>, event: &str, payload_json: &str) -> PyResult<()> {
        self.ensure_active()?;
        crate::events::emit(py, &self.handle, None, event, payload_json)
    }
    pub fn emit_target_json(
        &self,
        py: Python<'_>,
        target_json: &str,
        event: &str,
        payload_json: &str,
    ) -> PyResult<()> {
        self.ensure_active()?;
        crate::events::emit_target(py, &self.handle, target_json, event, payload_json)
    }
    #[pyo3(signature = (event, callback, *, once=false, any_target=false))]
    pub fn listen(
        &self,
        py: Python<'_>,
        event: &str,
        callback: Py<PyAny>,
        once: bool,
        any_target: bool,
    ) -> PyResult<u32> {
        self.ensure_active()?;
        crate::events::listen(
            py,
            &self.handle,
            Some(self),
            event,
            callback,
            once,
            any_target,
        )
    }
    pub fn unlisten(&self, py: Python<'_>, id: u32) -> PyResult<()> {
        self.ensure_active()?;
        crate::events::unlisten(py, &self.handle, Some(&self.state), id)
    }
    /// 显示窗口，释放 GIL；已销毁窗口返回 window_closed。
    pub fn show(&self, py: Python<'_>) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.show())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 隐藏窗口，释放 GIL；已销毁窗口返回 window_closed。
    pub fn hide(&self, py: Python<'_>) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.hide())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 将窗口居中，释放 GIL；已销毁窗口返回 window_closed。
    pub fn center(&self, py: Python<'_>) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.center())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 最小化窗口，释放 GIL；已销毁窗口返回 window_closed。
    pub fn minimize(&self, py: Python<'_>) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.minimize())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 恢复最小化窗口，释放 GIL；已销毁窗口返回 window_closed。
    pub fn unminimize(&self, py: Python<'_>) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.unminimize())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 最大化窗口，释放 GIL；已销毁窗口返回 window_closed。
    pub fn maximize(&self, py: Python<'_>) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.maximize())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 恢复最大化窗口，释放 GIL；已销毁窗口返回 window_closed。
    pub fn unmaximize(&self, py: Python<'_>) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.unmaximize())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 查询 is_visible 原生状态，受平台窗口管理器行为约束。
    pub fn is_visible(&self, py: Python<'_>) -> PyResult<bool> {
        self.ensure_active()?;
        py.detach(|| self.inner.is_visible())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 查询键盘焦点；Windows 包含所属 WebView 子窗口，失效句柄仍拒绝。
    pub fn is_focused(&self, py: Python<'_>) -> PyResult<bool> {
        self.ensure_active()?;
        #[cfg(target_os = "windows")]
        return py.detach(|| {
            use windows_sys::Win32::UI::WindowsAndMessaging::{
                GetGUIThreadInfo, IsChild, GUITHREADINFO,
            };
            let hwnd = self
                .inner
                .hwnd()
                .map_err(|error| binding_error("window_failed", error))?;
            let mut info = GUITHREADINFO {
                cbSize: std::mem::size_of::<GUITHREADINFO>() as u32,
                ..Default::default()
            };
            // SAFETY: Win32 写入已初始化、大小正确的本地结构；HWND 仅作为值查询，
            // 不解引用跨线程指针。查询前台队列避免 GetFocus 的调用线程限制。
            // 参考 https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-getguithreadinfo
            let focused = unsafe {
                if GetGUIThreadInfo(0, &mut info) == 0 {
                    return Err(binding_error(
                        "window_failed",
                        std::io::Error::last_os_error(),
                    ));
                }
                !info.hwndFocus.is_null()
                    && (info.hwndFocus == hwnd.0 || IsChild(hwnd.0, info.hwndFocus) != 0)
            };
            // 销毁与本次系统快照竞争时，不能以复用的 HWND 恢复旧句柄。
            self.ensure_active()?;
            Ok(focused)
        });
        #[cfg(not(target_os = "windows"))]
        py.detach(|| self.inner.is_focused())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 查询 is_minimized 原生状态，受平台窗口管理器行为约束。
    pub fn is_minimized(&self, py: Python<'_>) -> PyResult<bool> {
        self.ensure_active()?;
        py.detach(|| self.inner.is_minimized())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 查询 is_maximized 原生状态，受平台窗口管理器行为约束。
    pub fn is_maximized(&self, py: Python<'_>) -> PyResult<bool> {
        self.ensure_active()?;
        py.detach(|| self.inner.is_maximized())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 查询 is_fullscreen 原生状态，受平台窗口管理器行为约束。
    pub fn is_fullscreen(&self, py: Python<'_>) -> PyResult<bool> {
        self.ensure_active()?;
        py.detach(|| self.inner.is_fullscreen())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 查询 is_decorated 原生状态，受平台窗口管理器行为约束。
    pub fn is_decorated(&self, py: Python<'_>) -> PyResult<bool> {
        self.ensure_active()?;
        py.detach(|| self.inner.is_decorated())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 查询 is_always_on_top 原生状态，受平台窗口管理器行为约束。
    pub fn is_always_on_top(&self, py: Python<'_>) -> PyResult<bool> {
        self.ensure_active()?;
        py.detach(|| self.inner.is_always_on_top())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 查询 is_resizable 原生状态，受平台窗口管理器行为约束。
    pub fn is_resizable(&self, py: Python<'_>) -> PyResult<bool> {
        self.ensure_active()?;
        py.detach(|| self.inner.is_resizable())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 查询 is_maximizable 原生状态，受平台窗口管理器行为约束。
    pub fn is_maximizable(&self, py: Python<'_>) -> PyResult<bool> {
        self.ensure_active()?;
        py.detach(|| self.inner.is_maximizable())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 查询 is_minimizable 原生状态，受平台窗口管理器行为约束。
    pub fn is_minimizable(&self, py: Python<'_>) -> PyResult<bool> {
        self.ensure_active()?;
        py.detach(|| self.inner.is_minimizable())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 查询 is_closable 原生状态，受平台窗口管理器行为约束。
    pub fn is_closable(&self, py: Python<'_>) -> PyResult<bool> {
        self.ensure_active()?;
        py.detach(|| self.inner.is_closable())
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 设置 set_fullscreen 原生属性，平台限制沿用上游。
    pub fn set_fullscreen(&self, py: Python<'_>, value: bool) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.set_fullscreen(value))
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 设置 set_decorations 原生属性，平台限制沿用上游。
    pub fn set_decorations(&self, py: Python<'_>, value: bool) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.set_decorations(value))
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 设置 set_shadow 原生属性，平台限制沿用上游。
    pub fn set_shadow(&self, py: Python<'_>, value: bool) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.set_shadow(value))
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 设置 set_always_on_top 原生属性，平台限制沿用上游。
    pub fn set_always_on_top(&self, py: Python<'_>, value: bool) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.set_always_on_top(value))
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 设置窗口主题；None 恢复跟随系统，效果与限制沿用上游。
    pub fn set_theme(&self, py: Python<'_>, theme: Option<&str>) -> PyResult<()> {
        self.ensure_active()?;
        let value = match theme {
            None => None,
            Some("light") => Some(tauri::Theme::Light),
            Some("dark") => Some(tauri::Theme::Dark),
            Some(_) => {
                return Err(binding_error(
                    "invalid_theme",
                    "theme must be None, 'light' or 'dark'",
                ));
            }
        };
        py.detach(|| self.inner.set_theme(value))
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 返回当前窗口主题；不根据系统主题变化推断。
    pub fn theme(&self, py: Python<'_>) -> PyResult<String> {
        self.ensure_active()?;
        let theme = py
            .detach(|| self.inner.theme())
            .map_err(|error| binding_error("window_failed", error))?;
        Ok(format!("{theme:?}").to_lowercase())
    }

    /// 设置窗口置底；平台效果沿用上游。
    pub fn set_always_on_bottom(&self, py: Python<'_>, value: bool) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.set_always_on_bottom(value))
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 设置内容保护；平台效果沿用上游。
    pub fn set_content_protected(&self, py: Python<'_>, value: bool) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.set_content_protected(value))
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 设置是否在所有工作区可见；平台效果沿用上游。
    pub fn set_visible_on_all_workspaces(&self, py: Python<'_>, value: bool) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.set_visible_on_all_workspaces(value))
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 设置 set_resizable 原生属性，平台限制沿用上游。
    pub fn set_resizable(&self, py: Python<'_>, value: bool) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.set_resizable(value))
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 设置 set_maximizable 原生属性，平台限制沿用上游。
    pub fn set_maximizable(&self, py: Python<'_>, value: bool) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.set_maximizable(value))
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 设置 set_minimizable 原生属性，平台限制沿用上游。
    pub fn set_minimizable(&self, py: Python<'_>, value: bool) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.set_minimizable(value))
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 设置 set_closable 原生属性，平台限制沿用上游。
    pub fn set_closable(&self, py: Python<'_>, value: bool) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.set_closable(value))
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 设置 set_focusable 原生属性，平台限制沿用上游。
    pub fn set_focusable(&self, py: Python<'_>, value: bool) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.set_focusable(value))
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 设置 set_skip_taskbar 原生属性，平台限制沿用上游。
    pub fn set_skip_taskbar(&self, py: Python<'_>, value: bool) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.set_skip_taskbar(value))
            .map_err(|error| binding_error("window_failed", error))
    }

    /// 查询原生窗口标题。
    pub fn title(&self, py: Python<'_>) -> PyResult<String> {
        self.ensure_active()?;
        py.detach(|| self.inner.title())
            .map_err(|error| binding_error("window_failed", error))
    }
    /// 查询 DPI 缩放系数。
    pub fn scale_factor(&self, py: Python<'_>) -> PyResult<f64> {
        self.ensure_active()?;
        py.detach(|| self.inner.scale_factor())
            .map_err(|error| binding_error("window_failed", error))
    }
    /// 查询物理像素客户区尺寸，最小化时平台可能返回零。
    pub fn inner_size(&self, py: Python<'_>) -> PyResult<crate::dpi::PhysicalSize> {
        self.ensure_active()?;
        let size = py
            .detach(|| self.inner.inner_size())
            .map_err(|error| binding_error("window_failed", error))?;
        Ok(crate::dpi::PhysicalSize {
            width: size.width,
            height: size.height,
        })
    }
    /// 查询物理像素窗口外框位置。
    pub fn outer_position(&self, py: Python<'_>) -> PyResult<crate::dpi::PhysicalPosition> {
        self.ensure_active()?;
        let position = py
            .detach(|| self.inner.outer_position())
            .map_err(|error| binding_error("window_failed", error))?;
        Ok(crate::dpi::PhysicalPosition {
            x: position.x,
            y: position.y,
        })
    }
    /// 设置客户区尺寸，必须显式声明逻辑或物理单位。
    pub fn set_size(&self, py: Python<'_>, size: &Bound<'_, PyAny>) -> PyResult<()> {
        self.ensure_active()?;
        let size = crate::dpi::size(size)?;
        py.detach(|| self.inner.set_size(size))
            .map_err(|error| binding_error("window_failed", error))
    }
    /// 设置窗口位置，必须显式声明逻辑或物理单位。
    pub fn set_position(&self, py: Python<'_>, position: &Bound<'_, PyAny>) -> PyResult<()> {
        self.ensure_active()?;
        let position = crate::dpi::position(position)?;
        py.detach(|| self.inner.set_position(position))
            .map_err(|error| binding_error("window_failed", error))
    }
    /// 设置或清除客户区最小尺寸。
    pub fn set_min_size(&self, py: Python<'_>, size: Option<&Bound<'_, PyAny>>) -> PyResult<()> {
        self.ensure_active()?;
        let size = size.map(crate::dpi::size).transpose()?;
        py.detach(|| self.inner.set_min_size(size))
            .map_err(|error| binding_error("window_failed", error))
    }
    /// 设置或清除客户区最大尺寸。
    pub fn set_max_size(&self, py: Python<'_>, size: Option<&Bound<'_, PyAny>>) -> PyResult<()> {
        self.ensure_active()?;
        let size = size.map(crate::dpi::size).transpose()?;
        py.detach(|| self.inner.set_max_size(size))
            .map_err(|error| binding_error("window_failed", error))
    }
    /// 设置自有 RGBA 窗口图标。
    pub fn set_icon(&self, py: Python<'_>, image: PyRef<'_, crate::image::Image>) -> PyResult<()> {
        self.ensure_active()?;
        let image = image.inner.clone();
        py.detach(|| self.inner.set_icon(image))
            .map_err(|error| binding_error("window_failed", error))
    }
    /// 设置一个同步窗口事件处理器，替换并释放先前的处理器。
    pub fn on_window_event(&self, py: Python<'_>, callback: Py<PyAny>) -> PyResult<()> {
        self.ensure_active()?;
        if !callback.bind(py).is_callable() {
            return Err(binding_error(
                "invalid_callback",
                "Window event callback must be callable",
            ));
        }
        let removed = self
            .state
            .callbacks
            .lock()
            .map_err(|_| binding_error("state_failed", "Window callbacks unavailable"))?
            .window_event
            .replace(callback);
        drop(removed);
        Ok(())
    }

    pub fn label(&self) -> &str {
        self.inner.label()
    }
    pub fn app_handle(&self) -> PyResult<AppHandle> {
        self.ensure_active()?;
        Ok(self.handle.clone())
    }
    pub fn set_title(&self, py: Python<'_>, title: &str) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.set_title(title))
            .map_err(|error| binding_error("window_failed", error))
    }
    pub fn set_focus(&self, py: Python<'_>) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.set_focus())
            .map_err(|error| binding_error("window_failed", error))
    }
    pub fn close(&self, py: Python<'_>) -> PyResult<()> {
        self.ensure_active()?;
        py.detach(|| self.inner.close())
            .map_err(|error| binding_error("window_failed", error))
    }
}
