//! 桌面托盘：应用引用与显式关闭分离，回调以弱引用隔离资源代次。
use crate::{
    binding_error,
    image::Image,
    menu::{execute, MenuResource, TrayMenu},
    resources::CallbackSlot,
    window::AppHandle,
    window_state::{check_sync, Scope},
};
use pyo3::prelude::*;
use serde::Deserialize;
use std::{
    collections::HashMap,
    path::PathBuf,
    sync::{Arc, Mutex, Weak},
};
use tauri::tray::{TrayIcon, TrayIconBuilder, TrayIconEvent};

type NativeTray = TrayIcon<tauri::Wry>;

#[derive(Default)]
pub struct Registry {
    entries: Mutex<HashMap<String, Weak<TrayState>>>,
    attached: Mutex<HashMap<String, Arc<TrayState>>>,
    global: Mutex<Vec<Arc<CallbackSlot>>>,
}

struct TrayState {
    id: String,
    native: Mutex<Option<NativeTray>>,
    mouse: Mutex<Option<Arc<CallbackSlot>>>,
    menus: Mutex<Vec<Arc<CallbackSlot>>>,
}
impl TrayState {
    fn native(&self) -> PyResult<NativeTray> {
        self.native
            .lock()
            .map_err(|_| unavailable())?
            .clone()
            .ok_or_else(|| binding_error("tray_closed", "This tray icon has been closed"))
    }
    fn clear_callbacks(&self) {
        let mouse = self.mouse.lock().ok().and_then(|mut slot| slot.take());
        let menus = self
            .menus
            .lock()
            .map(|mut slots| std::mem::take(&mut *slots))
            .unwrap_or_default();
        if let Some(slot) = mouse {
            slot.clear();
        }
        for slot in menus {
            slot.clear();
        }
    }
}
impl Drop for TrayState {
    fn drop(&mut self) {
        self.clear_callbacks();
    }
}
fn unavailable() -> PyErr {
    binding_error("state_failed", "Tray registry unavailable")
}
fn native<T>(result: tauri::Result<T>) -> PyResult<T> {
    result.map_err(|error| binding_error("tray_failed", error))
}
fn text(value: &str) -> PyResult<()> {
    if value.contains('\0') {
        Err(binding_error(
            "invalid_tray",
            "Tray strings cannot contain NUL",
        ))
    } else {
        Ok(())
    }
}
fn callback(py: Python<'_>, value: &Py<PyAny>) -> PyResult<()> {
    if !value.bind(py).is_callable()
        || py
            .import("inspect")?
            .call_method1("iscoroutinefunction", (value,))?
            .is_truthy()?
    {
        Err(binding_error(
            "invalid_callback",
            "Expected a synchronous callable",
        ))
    } else {
        Ok(())
    }
}
impl Registry {
    pub fn cleanup(&self, handle: &tauri::AppHandle) {
        let states = self
            .entries
            .lock()
            .map(|mut entries| {
                entries
                    .drain()
                    .filter_map(|(_, weak)| weak.upgrade())
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        for state in states {
            state.clear_callbacks();
            let _ = handle.remove_tray_by_id(&state.id);
            let icon = state.native.lock().ok().and_then(|mut icon| icon.take());
            drop(icon);
        }
        if let Ok(mut attached) = self.attached.lock() {
            attached.clear();
        }
        self.clear_global();
    }
    fn clear_global(&self) {
        let slots = self
            .global
            .lock()
            .map(|mut slots| std::mem::take(&mut *slots))
            .unwrap_or_default();
        for slot in slots {
            slot.clear();
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Options {
    id: String,
    tooltip: Option<String>,
    title: Option<String>,
    temp_dir_path: Option<PathBuf>,
    #[serde(default)]
    icon_as_template: bool,
    #[serde(default = "default_left")]
    show_menu_on_left_click: bool,
}
fn default_left() -> bool {
    true
}

#[pyclass(frozen, skip_from_py_object, module = "pytaruix._native")]
#[derive(Clone)]
pub struct TrayResource {
    handle: AppHandle,
    state: Arc<TrayState>,
}
impl TrayResource {
    fn run<T: Send + 'static>(
        &self,
        py: Python<'_>,
        operation: impl FnOnce(NativeTray) -> PyResult<T> + Send + 'static,
    ) -> PyResult<T> {
        self.handle.runtime.ensure_active()?;
        self.state.native()?;
        let state = Arc::clone(&self.state);
        execute(py, &self.handle, None, move || operation(state.native()?))
    }
}
#[pymethods]
impl TrayResource {
    /// 创建应用拥有的原生托盘；仅 setup 或运行期间可用，工作线程释放 GIL。
    #[staticmethod]
    #[pyo3(signature = (handle, options_json, menu=None, icon=None, menu_handler=None, mouse_handler=None))]
    #[allow(clippy::too_many_arguments)]
    fn create(
        py: Python<'_>,
        handle: &AppHandle,
        options_json: &str,
        menu: Option<&MenuResource>,
        icon: Option<&Image>,
        menu_handler: Option<Py<PyAny>>,
        mouse_handler: Option<Py<PyAny>>,
    ) -> PyResult<Self> {
        let options: Options = serde_json::from_str(options_json)
            .map_err(|error| binding_error("invalid_tray", error))?;
        text(&options.id)?;
        for value in [&options.tooltip, &options.title].into_iter().flatten() {
            text(value)?;
        }
        let menu = menu.map(|menu| menu.tray_menu(handle)).transpose()?;
        let icon = icon.map(|icon| icon.inner.clone());
        for handler in [&menu_handler, &mouse_handler].into_iter().flatten() {
            callback(py, handler)?;
        }
        let app = handle.clone();
        execute(py, handle, None, move || {
            let registry = &app.runtime.trays;
            let mut entries = registry.entries.lock().map_err(|_| unavailable())?;
            entries.retain(|_, state| state.strong_count() > 0);
            if entries
                .get(&options.id)
                .and_then(Weak::upgrade)
                .is_some_and(|state| state.native().is_ok())
                || app.inner.tray_by_id(&options.id).is_some()
            {
                return Err(binding_error("duplicate_tray", "Tray ID is already alive"));
            }
            let mut builder = TrayIconBuilder::with_id(&options.id)
                .icon_as_template(options.icon_as_template)
                .show_menu_on_left_click(options.show_menu_on_left_click);
            if let Some(menu) = menu {
                builder = match menu {
                    TrayMenu::Menu(menu) => builder.menu(&menu),
                    TrayMenu::Submenu(menu) => builder.menu(&menu),
                };
            }
            if let Some(icon) = icon {
                builder = builder.icon(icon);
            }
            if let Some(value) = options.tooltip {
                builder = builder.tooltip(value);
            }
            if let Some(value) = options.title {
                builder = builder.title(value);
            }
            if let Some(value) = options.temp_dir_path {
                builder = builder.temp_dir_path(value);
            }
            let icon = native(builder.build(&app.inner))?;
            let state = Arc::new(TrayState {
                id: options.id.clone(),
                native: Mutex::new(Some(icon.clone())),
                mouse: Mutex::new(mouse_handler.map(|handler| CallbackSlot::new(None, handler))),
                menus: Mutex::new(Vec::new()),
            });
            let weak_state = Arc::downgrade(&state);
            if let Some(handler) = menu_handler {
                install_menu(&state, &app, &icon, CallbackSlot::new(None, handler))?;
            }
            let weak_runtime = Arc::downgrade(&app.runtime);
            icon.on_tray_icon_event(move |icon, event| {
                let (Some(state), Some(runtime)) = (weak_state.upgrade(), weak_runtime.upgrade())
                else {
                    return;
                };
                if runtime.ensure_active().is_err() || runtime.failed() || state.native().is_err() {
                    return;
                }
                let slot = state.mouse.lock().ok().and_then(|slot| slot.clone());
                let Some(slot) = slot else {
                    return;
                };
                receive(icon.app_handle(), &runtime, &slot, |py| {
                    Ok((
                        Py::new(
                            py,
                            Self {
                                handle: AppHandle::new(
                                    icon.app_handle().clone(),
                                    Arc::clone(&runtime),
                                ),
                                state: Arc::clone(&state),
                            },
                        )?
                        .into_any(),
                        event_json(&event)?,
                    ))
                });
            });
            entries.insert(options.id.clone(), Arc::downgrade(&state));
            registry
                .attached
                .lock()
                .map_err(|_| unavailable())?
                .insert(options.id, Arc::clone(&state));
            Ok(Self {
                handle: app.clone(),
                state,
            })
        })
    }
    /// 返回稳定标识；关闭后仍可读取，不访问 GUI。
    fn id(&self) -> String {
        self.state.id.clone()
    }
    /// 返回所属应用句柄；应用退出后拒绝。
    fn app_handle(&self) -> PyResult<AppHandle> {
        self.handle.runtime.ensure_active()?;
        Ok(self.handle.clone())
    }
    /// 返回资源是否已关闭，不初始化 GUI。
    #[getter]
    fn closed(&self) -> bool {
        self.state.native().is_err()
    }
    /// 显式关闭并使所有别名失效；幂等，禁止同步 GUI 回调内等待。
    fn close(&self, py: Python<'_>) -> PyResult<()> {
        if self.closed() {
            return Ok(());
        }
        let state = Arc::clone(&self.state);
        let app = self.handle.clone();
        execute(py, &self.handle, None, move || {
            state.clear_callbacks();
            if app
                .runtime
                .trays
                .attached
                .lock()
                .map_err(|_| unavailable())?
                .remove(&state.id)
                .is_some()
            {
                drop(app.inner.remove_tray_by_id(&state.id));
            }
            let icon = state.native.lock().map_err(|_| unavailable())?.take();
            drop(icon);
            Ok(())
        })
    }
    /// 设置或移除 RGBA 图像；释放 GIL，关闭后拒绝。
    fn set_icon(&self, py: Python<'_>, icon: Option<&Image>) -> PyResult<()> {
        let icon = icon.map(|image| image.inner.clone());
        self.run(py, move |tray| native(tray.set_icon(icon)))
    }
    /// 原子更新图像与模板状态；模板仅 macOS 有效，其他桌面平台更新图像。
    fn set_icon_with_as_template(
        &self,
        py: Python<'_>,
        icon: Option<&Image>,
        is_template: bool,
    ) -> PyResult<()> {
        let icon = icon.map(|image| image.inner.clone());
        self.run(py, move |tray| {
            native(tray.set_icon_with_as_template(icon, is_template))
        })
    }
    /// 更新上下文菜单；验证应用所有权，Linux 移除限制沿用上游。
    fn set_menu(&self, py: Python<'_>, menu: Option<&MenuResource>) -> PyResult<()> {
        let menu = menu.map(|menu| menu.tray_menu(&self.handle)).transpose()?;
        self.run(py, move |tray| {
            native(match menu {
                Some(TrayMenu::Menu(menu)) => tray.set_menu(Some(menu)),
                Some(TrayMenu::Submenu(menu)) => tray.set_menu(Some(menu)),
                None => tray.set_menu(None::<tauri::menu::Menu<tauri::Wry>>),
            })
        })
    }
    /// 更新或清除提示；Linux 上游无效果，不计为效果验收。
    fn set_tooltip(&self, py: Python<'_>, value: Option<String>) -> PyResult<()> {
        if let Some(value) = &value {
            text(value)?;
        }
        self.run(py, move |tray| native(tray.set_tooltip(value)))
    }
    /// 更新标题；Windows 上游无效果。
    fn set_title(&self, py: Python<'_>, value: Option<String>) -> PyResult<()> {
        if let Some(value) = &value {
            text(value)?;
        }
        self.run(py, move |tray| native(tray.set_title(value)))
    }
    /// 显示或隐藏通知区域图标；释放 GIL，需运行中的应用。
    fn set_visible(&self, py: Python<'_>, visible: bool) -> PyResult<()> {
        self.run(py, move |tray| native(tray.set_visible(visible)))
    }
    /// 设置临时图像目录；仅 Linux 有效果，接受 pathlib.Path。
    fn set_temp_dir_path(&self, py: Python<'_>, path: Option<PathBuf>) -> PyResult<()> {
        self.run(py, move |tray| native(tray.set_temp_dir_path(path)))
    }
    /// 设置模板图像状态；仅 macOS 有效果。
    fn set_icon_as_template(&self, py: Python<'_>, value: bool) -> PyResult<()> {
        self.run(py, move |tray| native(tray.set_icon_as_template(value)))
    }
    /// 控制左击弹出菜单；Linux 上游不支持。
    fn set_show_menu_on_left_click(&self, py: Python<'_>, value: bool) -> PyResult<()> {
        self.run(py, move |tray| {
            native(tray.set_show_menu_on_left_click(value))
        })
    }
    /// 查询原生矩形的 JSON 快照；Linux 返回 None，Python 入口转换为 Rect。
    fn rect_json(&self, py: Python<'_>) -> PyResult<Option<String>> {
        self.run(py, |tray| {
            native(tray.rect())?
                .map(|rect| {
                    serde_json::to_string(&rect)
                        .map_err(|error| binding_error("tray_failed", error))
                })
                .transpose()
        })
    }
    /// 替换该托盘鼠标回调；不在回调内重新获取原生监听表锁。
    fn on_tray_icon_event(&self, py: Python<'_>, handler: Py<PyAny>) -> PyResult<()> {
        callback(py, &handler)?;
        let state = Arc::clone(&self.state);
        self.run(py, move |_| {
            let old = state
                .mouse
                .lock()
                .map_err(|_| unavailable())?
                .replace(CallbackSlot::new(None, handler));
            if let Some(old) = old {
                old.clear();
            }
            Ok(())
        })
    }
    /// 累加全应用菜单广播回调；资源关闭时清空 Python 引用。
    fn on_menu_event(&self, py: Python<'_>, handler: Py<PyAny>) -> PyResult<()> {
        callback(py, &handler)?;
        let slot = CallbackSlot::new(None, handler);
        let state = Arc::clone(&self.state);
        let app = self.handle.clone();
        self.run(py, move |tray| install_menu(&state, &app, &tray, slot))
    }
    /// 清空本托盘回调；不注销上游弱引用闭包，可在同步回调内使用。
    fn clear_event_handlers(&self) -> PyResult<()> {
        self.handle.runtime.ensure_active()?;
        self.state.native()?;
        self.state.clear_callbacks();
        Ok(())
    }
}
fn install_menu(
    state: &TrayState,
    handle: &AppHandle,
    tray: &NativeTray,
    slot: Arc<CallbackSlot>,
) -> PyResult<()> {
    let weak = Arc::downgrade(&slot);
    let runtime = Arc::downgrade(&handle.runtime);
    state.menus.lock().map_err(|_| unavailable())?.push(slot);
    tray.on_menu_event(move |app, event| {
        let (Some(slot), Some(runtime)) = (weak.upgrade(), runtime.upgrade()) else {
            return;
        };
        receive(app, &runtime, &slot, |py| {
            Ok((
                Py::new(py, AppHandle::new(app.clone(), Arc::clone(&runtime)))?.into_any(),
                event.id.0,
            ))
        });
    });
    Ok(())
}
fn event_json(event: &TrayIconEvent) -> PyResult<String> {
    serde_json::to_string(event).map_err(|error| binding_error("tray_failed", error))
}
fn receive(
    app: &tauri::AppHandle,
    runtime: &Arc<crate::runtime::RuntimeState>,
    slot: &CallbackSlot,
    arguments: impl FnOnce(Python<'_>) -> PyResult<(Py<PyAny>, String)>,
) {
    if runtime.ensure_active().is_err() || runtime.failed() {
        return;
    }
    Python::attach(|py| {
        let _scope = Scope::callback();
        let result = (|| {
            let Some(callback) = slot.callback(py, false)? else {
                return Ok(());
            };
            let (source, event) = arguments(py)?;
            check_sync(py, callback.call1(py, (source, event))?)
        })();
        if let Err(error) = result {
            runtime.fail(app, error);
        }
    });
}
pub fn lookup(py: Python<'_>, handle: &AppHandle, id: String, remove: bool) -> PyResult<Py<PyAny>> {
    text(&id)?;
    let app = handle.clone();
    let resource = execute(py, handle, None, move || {
        let registry = &app.runtime.trays;
        let mut attached = registry.attached.lock().map_err(|_| unavailable())?;
        let state = if remove {
            attached.remove(&id)
        } else {
            attached.get(&id).cloned()
        };
        if remove {
            drop(app.inner.remove_tray_by_id(&id));
        }
        Ok(state.map(|state| TrayResource {
            handle: app.clone(),
            state,
        }))
    })?;
    match resource {
        Some(resource) => Ok(py
            .import("pytaruix.ffi.tray")?
            .getattr("_from_native")?
            .call1((resource,))?
            .unbind()),
        None => Ok(py.None()),
    }
}
pub fn listen_global(py: Python<'_>, handle: &AppHandle, handler: Py<PyAny>) -> PyResult<()> {
    callback(py, &handler)?;
    let adapter = py
        .import("pytaruix.ffi.tray")?
        .getattr("_adapt_global")?
        .call1((handler,))?
        .unbind();
    let slot = CallbackSlot::new(None, adapter);
    let weak = Arc::downgrade(&slot);
    let runtime = Arc::downgrade(&handle.runtime);
    let app = handle.clone();
    execute(py, handle, None, move || {
        app.runtime
            .trays
            .global
            .lock()
            .map_err(|_| unavailable())?
            .push(slot);
        app.inner.on_tray_icon_event(move |app, event| {
            let (Some(slot), Some(runtime)) = (weak.upgrade(), runtime.upgrade()) else {
                return;
            };
            receive(app, &runtime, &slot, |py| {
                Ok((
                    Py::new(py, AppHandle::new(app.clone(), Arc::clone(&runtime)))?.into_any(),
                    event_json(&event)?,
                ))
            });
        });
        Ok(())
    })
}
pub fn clear_global(handle: &AppHandle) -> PyResult<()> {
    handle.runtime.ensure_active()?;
    handle.runtime.trays.clear_global();
    Ok(())
}
