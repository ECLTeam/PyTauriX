//! 系统通知插件。
//!
//! 桌面端的权限状态恒为已授予；Windows 未打包应用缺少应用标识时，
//! 通知可能需要系统层面的注册才会显示，这里只如实归还上游结果。

use crate::{binding_error, window::AppHandle};
use pyo3::prelude::*;
use tauri_plugin_notification::NotificationExt;

/// 通知发送入口，归属应用运行期。
#[pyclass(frozen, module = "pytaurix.plugins.notification")]
pub struct NotificationApi {
    handle: AppHandle,
}

impl NotificationApi {
    fn ready(&self) -> PyResult<()> {
        self.handle.runtime.ensure_active()?;
        if !self.handle.runtime.plugins.contains("notification") {
            return Err(binding_error(
                "plugin_missing",
                "Register the notification plugin before using Notification",
            ));
        }
        Ok(())
    }
}

#[pymethods]
impl NotificationApi {
    #[new]
    fn new(handle: &AppHandle) -> Self {
        Self {
            handle: handle.clone(),
        }
    }

    /// 查询当前权限状态，返回上游的名称文本（如 granted、denied、prompt）。
    fn permission_state(&self, py: Python<'_>) -> PyResult<String> {
        self.ready()?;
        py.detach(|| {
            self.handle
                .inner
                .notification()
                .permission_state()
                .map(|state| state.to_string())
                .map_err(|error| binding_error("notification_failed", error))
        })
    }

    /// 请求权限并返回请求后的状态；桌面端通常直接返回已授予。
    fn request_permission(&self, py: Python<'_>) -> PyResult<String> {
        self.ready()?;
        py.detach(|| {
            self.handle
                .inner
                .notification()
                .request_permission()
                .map(|state| state.to_string())
                .map_err(|error| binding_error("notification_failed", error))
        })
    }

    #[pyo3(signature = (title, body, *, silent=false, id=None))]
    /// 发送一条通知；show 成功不代表系统已经展示。
    ///
    /// 参数 title/body 为文本，silent 关闭声音，id 用于替换同一标识的通知。
    fn send(
        &self,
        py: Python<'_>,
        title: &str,
        body: &str,
        silent: bool,
        id: Option<i32>,
    ) -> PyResult<()> {
        self.ready()?;
        py.detach(move || {
            let mut builder = self
                .handle
                .inner
                .notification()
                .builder()
                .title(title)
                .body(body);
            if silent {
                builder = builder.silent();
            }
            if let Some(id) = id {
                builder = builder.id(id);
            }
            builder
                .show()
                .map_err(|error| binding_error("notification_failed", error))
        })
    }
}
