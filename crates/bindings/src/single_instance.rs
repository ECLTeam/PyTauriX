//! 单实例插件：第二个进程启动时把命令行参数交给已有实例。
//!
//! 上游要求该插件尽早登记，因此应用构建顺序把用户插件放在内置插件之前。
//! 回调异常沿用其他同步回调的处理方式：记录并退出应用，不静默吞掉。

use crate::{binding_error, runtime::RuntimeState, window::AppHandle};
use pyo3::prelude::*;
use std::sync::Arc;
use tauri::Manager;

pub fn init(py: Python<'_>, handler: Py<PyAny>) -> PyResult<crate::plugin::Plugin> {
    if !handler.bind(py).is_callable() {
        return Err(binding_error(
            "invalid_callback",
            "single-instance handler must be callable",
        ));
    }
    Ok(crate::plugin::Plugin::new(
        "single-instance",
        Box::new(move |builder| {
            builder.plugin(tauri_plugin_single_instance::init(move |app, args, cwd| {
                let runtime = Arc::clone(app.state::<Arc<RuntimeState>>().inner());
                Python::attach(|py| {
                    let handle = AppHandle::new(app.clone(), Arc::clone(&runtime));
                    let result = handler
                        .call1(py, (handle, args, cwd))
                        .and_then(|value| crate::window_state::check_sync(py, value));
                    if let Err(error) = result {
                        runtime.fail(app, error);
                    }
                });
            }))
        }),
    ))
}
