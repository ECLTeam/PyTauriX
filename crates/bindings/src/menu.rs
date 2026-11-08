//! 桌面菜单资源：原生主线程事务、严格快捷键边界与可清空菜单事件。
use crate::{
    binding_error,
    image::Image,
    resources::CallbackSlot,
    window::{AppHandle, WebviewWindow},
    window_state::{check_sync, Scope, WindowState},
};
use pyo3::prelude::*;
use std::sync::{atomic::Ordering, mpsc, Arc};
use tauri::{
    menu::{self, IsMenuItem},
    Manager,
};

#[derive(Clone)]
enum Node {
    Menu(menu::Menu<tauri::Wry>),
    Submenu(menu::Submenu<tauri::Wry>),
    Item(menu::MenuItem<tauri::Wry>),
    Check(menu::CheckMenuItem<tauri::Wry>),
    Icon(menu::IconMenuItem<tauri::Wry>),
    Predefined(menu::PredefinedMenuItem<tauri::Wry>),
}
impl Node {
    fn from_item(item: menu::MenuItemKind<tauri::Wry>) -> Self {
        match item {
            menu::MenuItemKind::MenuItem(item) => Self::Item(item),
            menu::MenuItemKind::Submenu(item) => Self::Submenu(item),
            menu::MenuItemKind::Check(item) => Self::Check(item),
            menu::MenuItemKind::Icon(item) => Self::Icon(item),
            menu::MenuItemKind::Predefined(item) => Self::Predefined(item),
        }
    }
    fn item(&self) -> PyResult<&dyn IsMenuItem<tauri::Wry>> {
        match self {
            Self::Submenu(item) => Ok(item),
            Self::Item(item) => Ok(item),
            Self::Check(item) => Ok(item),
            Self::Icon(item) => Ok(item),
            Self::Predefined(item) => Ok(item),
            Self::Menu(_) => Err(invalid()),
        }
    }
    fn items(&self) -> PyResult<Vec<menu::MenuItemKind<tauri::Wry>>> {
        match self {
            Self::Menu(menu) => native(menu.items()),
            Self::Submenu(menu) => native(menu.items()),
            _ => Err(invalid()),
        }
    }
}
fn invalid() -> PyErr {
    binding_error("invalid_menu", "Unsupported menu resource or operation")
}
fn native<T>(result: tauri::Result<T>) -> PyResult<T> {
    result.map_err(|error| binding_error("menu_failed", error))
}
fn string(value: &str) -> PyResult<()> {
    if value.contains('\0') {
        Err(binding_error(
            "invalid_menu",
            "Menu strings cannot contain NUL",
        ))
    } else {
        Ok(())
    }
}
fn accelerator(value: Option<&str>) -> PyResult<()> {
    if let Some(value) = value {
        value
            .parse::<muda::accelerator::Accelerator>()
            .map_err(|_| binding_error("invalid_accelerator", "Invalid menu accelerator"))?;
    }
    Ok(())
}

/// 预定义项的显示文本覆盖：空字符串表示使用平台默认文案。
fn label(text: &str) -> Option<&str> {
    if text.is_empty() {
        None
    } else {
        Some(text)
    }
}

/// 从 JSON 对象构造 About 元数据；图标仍由独立 Image 入口提供。
fn about_metadata(raw: &str) -> PyResult<menu::AboutMetadata<'static>> {
    let value: serde_json::Value = serde_json::from_str(raw)
        .map_err(|_| binding_error("invalid_menu", "About metadata must be valid JSON"))?;
    let object = value
        .as_object()
        .ok_or_else(|| binding_error("invalid_menu", "About metadata must be a JSON object"))?;
    let field = |name: &str| {
        object
            .get(name)
            .and_then(|item| item.as_str())
            .map(str::to_owned)
    };
    let authors = object
        .get("authors")
        .and_then(|item| item.as_array())
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.as_str().map(str::to_owned))
                .collect::<Vec<_>>()
        });
    Ok(menu::AboutMetadata {
        name: field("name"),
        version: field("version"),
        short_version: field("short_version"),
        authors,
        comments: field("comments"),
        copyright: field("copyright"),
        license: field("license"),
        website: field("website"),
        website_label: field("website_label"),
        credits: field("credits"),
        icon: None,
    })
}

/// 内部菜单句柄；公开 Python 类型按菜单种类限制操作。
///
/// 资源归属应用，关闭构造它的窗口不会销毁资源；退出后拒绝操作。
#[pyclass(frozen, skip_from_py_object, module = "pytaruix._native")]
#[derive(Clone)]
pub struct MenuResource {
    node: Node,
    handle: AppHandle,
}

// 每项复合操作在一次 GUI 任务内完成；索引校验和插入之间不能被其他任务打断。
pub(crate) fn execute<T: Send + 'static>(
    py: Python<'_>,
    handle: &AppHandle,
    owner: Option<&Arc<WindowState>>,
    operation: impl FnOnce() -> PyResult<T> + Send + 'static,
) -> PyResult<T> {
    handle.runtime.ensure_active()?;
    if let Some(owner) = owner {
        owner.ensure_active()?;
    }
    if Scope::in_callback() {
        return Err(binding_error(
            "blocking_callback",
            "Native resource operations cannot run in synchronous GUI callbacks",
        ));
    }
    if !handle.runtime.running.load(Ordering::SeqCst) && !Scope::can_build_on_main() {
        return Err(binding_error(
            "app_not_running",
            "Native resources require setup or a running event loop",
        ));
    }
    let runtime = Arc::clone(&handle.runtime);
    let task_owner = owner.cloned();
    let waiting_runtime = Arc::clone(&runtime);
    let waiting_owner = task_owner.clone();
    let (tx, rx) = mpsc::channel();
    let result = py.detach(move || {
        handle
            .inner
            .run_on_main_thread(move || {
                let result = (|| {
                    runtime.ensure_active()?;
                    if Scope::in_callback() {
                        return Err(binding_error(
                            "blocking_callback",
                            "Native resource task cannot reenter a GUI callback or modal menu",
                        ));
                    }
                    if let Some(owner) = task_owner {
                        owner.ensure_active()?;
                    }
                    operation()
                })();
                let _ = tx.send(result);
            })
            .map_err(|error| binding_error("dispatch_failed", error))?;
        loop {
            match rx.recv_timeout(std::time::Duration::from_millis(50)) {
                Ok(result) => break result,
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    break Err(binding_error(
                        "dispatch_failed",
                        "Native resource task was cancelled",
                    ))
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {
                    waiting_runtime.ensure_active()?;
                    if let Some(owner) = &waiting_owner {
                        owner.ensure_active()?;
                    }
                }
            }
        }
    });
    handle.runtime.ensure_active()?;
    if let Some(owner) = owner {
        owner.ensure_active()?;
    }
    result
}

impl MenuResource {
    #[cfg(feature = "tray-icon")]
    pub(crate) fn tray_menu(&self, handle: &AppHandle) -> PyResult<TrayMenu> {
        same_app(handle, &self.handle)?;
        match &self.node {
            Node::Menu(menu) => Ok(TrayMenu::Menu(menu.clone())),
            Node::Submenu(menu) => Ok(TrayMenu::Submenu(menu.clone())),
            _ => Err(invalid()),
        }
    }
}

#[cfg(feature = "tray-icon")]
#[derive(Clone)]
pub(crate) enum TrayMenu {
    Menu(menu::Menu<tauri::Wry>),
    Submenu(menu::Submenu<tauri::Wry>),
}

#[pymethods]
impl MenuResource {
    /// 创建指定种类的应用菜单资源。
    ///
    /// 参数由公开 Python 工厂收敛；桌面 setup 或运行期间执行，释放 GIL。
    #[staticmethod]
    // 按公开 Python 构造字段传递；共享一处线程/所有权校验而不复制六种绑定。
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (handle, kind, id=None, text="", enabled=true, checked=false, accelerator=None, icon=None, metadata=None))]
    fn create(
        py: Python<'_>,
        handle: &AppHandle,
        kind: &str,
        id: Option<String>,
        text: &str,
        enabled: bool,
        checked: bool,
        accelerator: Option<String>,
        icon: Option<&Image>,
        metadata: Option<String>,
    ) -> PyResult<Self> {
        string(text)?;
        if let Some(id) = &id {
            string(id)?;
        }
        self::accelerator(accelerator.as_deref())?;
        let kind = kind.to_owned();
        let text = text.to_owned();
        let icon = icon.map(|icon| icon.inner.clone());
        let about = metadata.as_deref().map(about_metadata).transpose()?;
        let app = handle.clone();
        execute(py, handle, None, move || {
            let manager = &app.inner;
            let node = match (kind.as_str(), id) {
                ("menu", Some(id)) => Node::Menu(native(menu::Menu::with_id(manager, id))?),
                ("menu", None) => Node::Menu(native(menu::Menu::new(manager))?),
                ("submenu", Some(id)) => {
                    Node::Submenu(native(menu::Submenu::with_id(manager, id, text, enabled))?)
                }
                ("submenu", None) => {
                    Node::Submenu(native(menu::Submenu::new(manager, text, enabled))?)
                }
                ("item", Some(id)) => Node::Item(native(menu::MenuItem::with_id(
                    manager,
                    id,
                    text,
                    enabled,
                    accelerator,
                ))?),
                ("item", None) => Node::Item(native(menu::MenuItem::new(
                    manager,
                    text,
                    enabled,
                    accelerator,
                ))?),
                ("check", Some(id)) => Node::Check(native(menu::CheckMenuItem::with_id(
                    manager,
                    id,
                    text,
                    enabled,
                    checked,
                    accelerator,
                ))?),
                ("check", None) => Node::Check(native(menu::CheckMenuItem::new(
                    manager,
                    text,
                    enabled,
                    checked,
                    accelerator,
                ))?),
                ("icon", Some(id)) => Node::Icon(native(menu::IconMenuItem::with_id(
                    manager,
                    id,
                    text,
                    enabled,
                    icon,
                    accelerator,
                ))?),
                ("icon", None) => Node::Icon(native(menu::IconMenuItem::new(
                    manager,
                    text,
                    enabled,
                    icon,
                    accelerator,
                ))?),
                ("separator", None) => {
                    Node::Predefined(native(menu::PredefinedMenuItem::separator(manager))?)
                }
                ("copy", None) => Node::Predefined(native(menu::PredefinedMenuItem::copy(
                    manager,
                    label(&text),
                ))?),
                ("cut", None) => Node::Predefined(native(menu::PredefinedMenuItem::cut(
                    manager,
                    label(&text),
                ))?),
                ("paste", None) => Node::Predefined(native(menu::PredefinedMenuItem::paste(
                    manager,
                    label(&text),
                ))?),
                ("select_all", None) => Node::Predefined(native(
                    menu::PredefinedMenuItem::select_all(manager, label(&text)),
                )?),
                ("undo", None) => Node::Predefined(native(menu::PredefinedMenuItem::undo(
                    manager,
                    label(&text),
                ))?),
                ("redo", None) => Node::Predefined(native(menu::PredefinedMenuItem::redo(
                    manager,
                    label(&text),
                ))?),
                ("minimize", None) => Node::Predefined(native(
                    menu::PredefinedMenuItem::minimize(manager, label(&text)),
                )?),
                ("maximize", None) => Node::Predefined(native(
                    menu::PredefinedMenuItem::maximize(manager, label(&text)),
                )?),
                ("fullscreen", None) => Node::Predefined(native(
                    menu::PredefinedMenuItem::fullscreen(manager, label(&text)),
                )?),
                ("hide", None) => Node::Predefined(native(menu::PredefinedMenuItem::hide(
                    manager,
                    label(&text),
                ))?),
                ("hide_others", None) => Node::Predefined(native(
                    menu::PredefinedMenuItem::hide_others(manager, label(&text)),
                )?),
                ("show_all", None) => Node::Predefined(native(
                    menu::PredefinedMenuItem::show_all(manager, label(&text)),
                )?),
                ("close_window", None) => Node::Predefined(native(
                    menu::PredefinedMenuItem::close_window(manager, label(&text)),
                )?),
                ("quit", None) => Node::Predefined(native(menu::PredefinedMenuItem::quit(
                    manager,
                    label(&text),
                ))?),
                ("services", None) => Node::Predefined(native(
                    menu::PredefinedMenuItem::services(manager, label(&text)),
                )?),
                ("bring_all_to_front", None) => Node::Predefined(native(
                    menu::PredefinedMenuItem::bring_all_to_front(manager, label(&text)),
                )?),
                ("about", None) => Node::Predefined(native(menu::PredefinedMenuItem::about(
                    manager,
                    label(&text),
                    about,
                ))?),
                _ => return Err(invalid()),
            };
            Ok(Self { node, handle: app })
        })
    }
    /// 返回菜单种类；读取内部元数据，不调用 GUI。
    ///
    /// 应用退出后拒绝读取资源。
    fn kind(&self) -> PyResult<&str> {
        self.handle.runtime.ensure_active()?;
        Ok(match self.node {
            Node::Menu(_) => "menu",
            Node::Submenu(_) => "submenu",
            Node::Item(_) => "item",
            Node::Check(_) => "check",
            Node::Icon(_) => "icon",
            Node::Predefined(_) => "predefined",
        })
    }
    /// 返回菜单字符串 ID，允许重复 ID，沿用原生检索和移除语义。
    ///
    /// 元数据读取可在回调内执行；应用退出后报错。
    fn id(&self) -> PyResult<String> {
        self.handle.runtime.ensure_active()?;
        Ok(match &self.node {
            Node::Menu(menu) => menu.id(),
            _ => self.node.item()?.id(),
        }
        .0
        .clone())
    }
    /// 返回所属应用句柄，不拥有构造时窗口的寿命。
    ///
    /// 可跨线程读取；应用退出后报错。
    fn app_handle(&self) -> PyResult<AppHandle> {
        self.handle.runtime.ensure_active()?;
        Ok(self.handle.clone())
    }
    /// 读取有序子项快照；返回的句柄保持原生共享身份。
    ///
    /// GUI 操作释放 GIL，禁止同步回调重入。
    fn items(&self, py: Python<'_>) -> PyResult<Vec<Self>> {
        let resource = self.clone();
        execute(py, &self.handle, None, move || {
            Ok(resource
                .node
                .items()?
                .into_iter()
                .map(|item| Self {
                    node: Node::from_item(item),
                    handle: resource.handle.clone(),
                })
                .collect())
        })
    }
    /// 追加或按位置插入同应用菜单项，原生负责循环与平台限制。
    ///
    /// 越界在原生修改前拒绝；重复与共享项目沿用上游语义。
    #[pyo3(signature = (item, position=None))]
    fn insert(&self, py: Python<'_>, item: &Self, position: Option<usize>) -> PyResult<()> {
        same_app(&self.handle, &item.handle)?;
        item.node.item()?;
        let resource = self.clone();
        let item = item.clone();
        execute(py, &self.handle, None, move || {
            if let Some(position) = position {
                if position > resource.node.items()?.len() {
                    return Err(binding_error(
                        "invalid_index",
                        "Menu position exceeds item count",
                    ));
                }
            }
            let item = item.node.item()?;
            match (&resource.node, position) {
                (Node::Menu(menu), Some(position)) => native(menu.insert(item, position)),
                (Node::Menu(menu), None) => native(menu.append(item)),
                (Node::Submenu(menu), Some(position)) => native(menu.insert(item, position)),
                (Node::Submenu(menu), None) => native(menu.append(item)),
                _ => Err(invalid()),
            }
        })
    }
    /// 按 ID 移除全部原生匹配项；被移除对象仍可使用。
    ///
    /// 非子项返回 menu_failed；原生操作释放 GIL。
    fn remove(&self, py: Python<'_>, item: &Self) -> PyResult<()> {
        same_app(&self.handle, &item.handle)?;
        let resource = self.clone();
        let item = item.clone();
        execute(py, &self.handle, None, move || match &resource.node {
            Node::Menu(menu) => native(menu.remove(item.node.item()?)),
            Node::Submenu(menu) => native(menu.remove(item.node.item()?)),
            _ => Err(invalid()),
        })
    }
    /// 移除指定位置并返回项目；非负越界返回 None。
    ///
    /// 所有修改在 GUI 单次任务内执行，应用关闭后拒绝。
    fn remove_at(&self, py: Python<'_>, position: usize) -> PyResult<Option<Self>> {
        let resource = self.clone();
        execute(py, &self.handle, None, move || {
            let item = match &resource.node {
                Node::Menu(menu) => native(menu.remove_at(position))?,
                Node::Submenu(menu) => native(menu.remove_at(position))?,
                _ => return Err(invalid()),
            };
            Ok(item.map(|item| Self {
                node: Node::from_item(item),
                handle: resource.handle,
            }))
        })
    }
    /// 读取原生文本；保留助记符和快捷键显示的上游语义。
    ///
    /// 同步回调禁止查询，工作线程释放 GIL。
    fn text(&self, py: Python<'_>) -> PyResult<String> {
        let node = self.node.clone();
        execute(py, &self.handle, None, move || match node {
            Node::Submenu(item) => native(item.text()),
            Node::Item(item) => native(item.text()),
            Node::Check(item) => native(item.text()),
            Node::Icon(item) => native(item.text()),
            Node::Predefined(item) => native(item.text()),
            _ => Err(invalid()),
        })
    }
    /// 更新原生文本；NUL 字符在修改前拒绝。
    ///
    /// 操作更新共享项目及其所有原生父菜单，释放 GIL。
    fn set_text(&self, py: Python<'_>, text: &str) -> PyResult<()> {
        string(text)?;
        let text = text.to_owned();
        let node = self.node.clone();
        execute(py, &self.handle, None, move || match node {
            Node::Submenu(item) => native(item.set_text(text)),
            Node::Item(item) => native(item.set_text(text)),
            Node::Check(item) => native(item.set_text(text)),
            Node::Icon(item) => native(item.set_text(text)),
            Node::Predefined(item) => native(item.set_text(text)),
            _ => Err(invalid()),
        })
    }
    /// 查询启用或勾选状态，仅对适用项目开放。
    ///
    /// 释放 GIL；同步 GUI 回调禁止重入。
    fn flag(&self, py: Python<'_>, checked: bool) -> PyResult<bool> {
        let node = self.node.clone();
        execute(py, &self.handle, None, move || match (node, checked) {
            (Node::Check(item), true) => native(item.is_checked()),
            (Node::Check(item), false) => native(item.is_enabled()),
            (Node::Item(item), false) => native(item.is_enabled()),
            (Node::Icon(item), false) => native(item.is_enabled()),
            (Node::Submenu(item), false) => native(item.is_enabled()),
            _ => Err(invalid()),
        })
    }
    /// 更新启用或勾选状态，保持同一项目共享更新。
    ///
    /// 原生操作释放 GIL，退出或同步回调内报错。
    fn set_flag(&self, py: Python<'_>, checked: bool, value: bool) -> PyResult<()> {
        let node = self.node.clone();
        execute(py, &self.handle, None, move || match (node, checked) {
            (Node::Check(item), true) => native(item.set_checked(value)),
            (Node::Check(item), false) => native(item.set_enabled(value)),
            (Node::Item(item), false) => native(item.set_enabled(value)),
            (Node::Icon(item), false) => native(item.set_enabled(value)),
            (Node::Submenu(item), false) => native(item.set_enabled(value)),
            _ => Err(invalid()),
        })
    }
    /// 设置或清除快捷键；使用上游解析器校验，无效输入不修改项目。
    ///
    /// 仅普通、勾选和图像项支持，工作线程释放 GIL。
    fn set_accelerator(&self, py: Python<'_>, value: Option<String>) -> PyResult<()> {
        accelerator(value.as_deref())?;
        let node = self.node.clone();
        execute(py, &self.handle, None, move || match node {
            Node::Item(item) => native(item.set_accelerator(value)),
            Node::Check(item) => native(item.set_accelerator(value)),
            Node::Icon(item) => native(item.set_accelerator(value)),
            _ => Err(invalid()),
        })
    }
    /// 设置或清除自有 RGBA 图像；不保留借用的 Python 缓冲区。
    ///
    /// 仅图像项支持；释放 GIL，平台显示尺寸沿用原生行为。
    fn set_icon(&self, py: Python<'_>, icon: Option<&Image>) -> PyResult<()> {
        let icon = icon.map(|icon| icon.inner.clone());
        let node = self.node.clone();
        execute(py, &self.handle, None, move || match node {
            Node::Icon(item) => native(item.set_icon(icon)),
            _ => Err(invalid()),
        })
    }
}
fn same_app(handle: &AppHandle, other: &AppHandle) -> PyResult<()> {
    handle.runtime.ensure_active()?;
    other.runtime.ensure_active()?;
    if Arc::ptr_eq(&handle.runtime, &other.runtime) {
        Ok(())
    } else {
        Err(binding_error(
            "menu_owner",
            "Menu resources belong to different applications",
        ))
    }
}
#[cfg(target_os = "windows")]
pub fn cache_window(window: &tauri::WebviewWindow, handle: &AppHandle) -> PyResult<()> {
    let state = handle.runtime.window_state(window.label())?;
    state.ensure_active()?;
    let hwnd = native(window.hwnd())?;
    state.menu_hwnd.store(hwnd.0 as isize, Ordering::SeqCst);
    Ok(())
}

#[cfg(target_os = "windows")]
pub fn detach_closing_window(state: &WindowState) {
    let hwnd = state.menu_hwnd.swap(0, Ordering::SeqCst);
    if hwnd == 0 {
        return;
    }
    // SAFETY: 仅从原始窗口的 GUI CloseRequested 通知调用；HWND 在通知返回前仍属于该窗口。
    // Windows 会自动销毁仍挂载的 HMENU。这里只解除关联，Muda 的 NCDESTROY 负责自身登记清理。
    // 不能通过 Window.hwnd/remove_menu 重入 Wry 已持有的窗口表锁。
    unsafe {
        windows_sys::Win32::UI::WindowsAndMessaging::SetMenu(hwnd as _, std::ptr::null_mut());
    }
}

fn extract(value: &Bound<'_, PyAny>) -> PyResult<MenuResource> {
    value
        .getattr("_native_menu")
        .map_err(|_| invalid())?
        .extract::<PyRef<MenuResource>>()
        .map(|value| value.clone())
        .map_err(|_| invalid())
}
fn public(py: Python<'_>, resource: Option<MenuResource>) -> PyResult<Py<PyAny>> {
    match resource {
        Some(resource) => Ok(py
            .import("pytaruix.ffi.menu")?
            .getattr("_from_native")?
            .call1((resource,))?
            .unbind()),
        None => Ok(py.None()),
    }
}
pub fn attachment(
    py: Python<'_>,
    handle: &AppHandle,
    window: Option<&WebviewWindow>,
    action: &str,
    value: Option<&Bound<'_, PyAny>>,
) -> PyResult<Py<PyAny>> {
    let resource = value.map(extract).transpose()?;
    let menu = resource
        .map(|resource| {
            same_app(handle, &resource.handle)?;
            match resource.node {
                Node::Menu(menu) => Ok(menu),
                _ => Err(invalid()),
            }
        })
        .transpose()?;
    let app = handle.inner.clone();
    let target = window.map(|window| window.inner.clone());
    let action = action.to_owned();
    #[cfg(target_os = "windows")]
    let lifecycle_handle = handle.clone();
    let previous = execute(py, handle, window.map(|window| &window.state), move || {
        #[cfg(target_os = "windows")]
        if action == "set" {
            if let Some(window) = &target {
                cache_window(window, &lifecycle_handle)?;
            } else {
                for window in app.webview_windows().values() {
                    cache_window(window, &lifecycle_handle)?;
                }
            }
        }
        match (target, action.as_str()) {
            (Some(window), "get") => Ok(window.menu()),
            (None, "get") => Ok(app.menu()),
            (Some(window), "set") => native(window.set_menu(menu.ok_or_else(invalid)?)),
            (None, "set") => native(app.set_menu(menu.ok_or_else(invalid)?)),
            (Some(window), "remove") => native(window.remove_menu()),
            (None, "remove") => native(app.remove_menu()),
            _ => Err(invalid()),
        }
    })?;
    public(
        py,
        previous.map(|menu| MenuResource {
            node: Node::Menu(menu),
            handle: handle.clone(),
        }),
    )
}
pub fn popup(
    py: Python<'_>,
    window: &WebviewWindow,
    value: &Bound<'_, PyAny>,
    position: Option<&Bound<'_, PyAny>>,
) -> PyResult<()> {
    let resource = extract(value)?;
    same_app(&window.handle, &resource.handle)?;
    let target = window.inner.clone();
    let position = position.map(crate::dpi::position).transpose()?;
    execute(py, &window.handle, Some(&window.state), move || {
        // 模态原生消息循环可能重入 GUI 任务；保持与 Python 同步回调相同的禁止重入边界。
        let _scope = Scope::callback();
        match (resource.node, position) {
            (Node::Menu(menu), Some(position)) => native(target.popup_menu_at(&menu, position)),
            (Node::Menu(menu), None) => native(target.popup_menu(&menu)),
            (Node::Submenu(menu), Some(position)) => native(target.popup_menu_at(&menu, position)),
            (Node::Submenu(menu), None) => native(target.popup_menu(&menu)),
            _ => Err(invalid()),
        }
    })
}
pub fn clear(handle: &AppHandle, owner: Option<&Arc<WindowState>>) -> PyResult<()> {
    handle.runtime.ensure_active()?;
    if let Some(owner) = owner {
        owner.ensure_active()?;
    }
    handle.runtime.resources.clear_menu(owner)
}
pub fn listen(
    py: Python<'_>,
    handle: &AppHandle,
    window: Option<&WebviewWindow>,
    callback: Py<PyAny>,
) -> PyResult<()> {
    if !callback.bind(py).is_callable() {
        return Err(binding_error(
            "invalid_callback",
            "Menu handler must be callable",
        ));
    }
    // Tauri 派发时持有监听表锁；回调中注册会死锁，必须在进入 native 前拒绝。
    if Scope::in_callback() {
        return Err(binding_error(
            "blocking_callback",
            "Cannot register menu handlers in a GUI callback",
        ));
    }
    let slot = CallbackSlot::new(window.map(|window| Arc::clone(&window.state)), callback);
    let weak_slot = Arc::downgrade(&slot);
    let weak_runtime = Arc::downgrade(&handle.runtime);
    let label = window.map(|window| window.inner.label().to_owned());
    // 原生 Manager 永久保留菜单闭包；只捕获弱引用，不捕获指回 Manager 的 AppHandle。
    let receive = move |native_handle: &tauri::AppHandle, event: menu::MenuEvent| {
        let (Some(slot), Some(runtime)) = (weak_slot.upgrade(), weak_runtime.upgrade()) else {
            return;
        };
        Python::attach(|py| {
            let _scope = Scope::callback();
            let result = (|| {
                if runtime.ensure_active().is_err()
                    || runtime.failed()
                    || slot.check_owner().is_err()
                {
                    return Ok(());
                }
                let Some(callback) = slot.callback(py, false)? else {
                    return Ok(());
                };
                let app = AppHandle::new(native_handle.clone(), Arc::clone(&runtime));
                let source = if let Some(label) = &label {
                    let Some(inner) = native_handle.get_webview_window(label) else {
                        return Ok(());
                    };
                    let state = runtime.window_state(label)?;
                    if !slot
                        .owner
                        .as_ref()
                        .is_some_and(|owner| Arc::ptr_eq(owner, &state))
                    {
                        return Ok(());
                    }
                    Py::new(
                        py,
                        WebviewWindow {
                            inner,
                            handle: app,
                            state,
                        },
                    )?
                    .into_any()
                } else {
                    Py::new(py, app)?.into_any()
                };
                check_sync(py, callback.call1(py, (source, event.id.0))?)?;
                Ok::<_, PyErr>(())
            })();
            if let Err(error) = result {
                runtime.fail(native_handle, error);
            }
        });
    };
    let app = handle.clone();
    let target = window.map(|window| window.inner.clone());
    execute(py, handle, window.map(|window| &window.state), move || {
        app.runtime.resources.add_menu(&app.runtime, &slot)?;
        if let Some(window) = target {
            window.on_menu_event(move |window, event| receive(window.app_handle(), event));
        } else {
            app.inner.on_menu_event(receive);
        }
        Ok(())
    })
}
