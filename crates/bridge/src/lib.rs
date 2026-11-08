//! 前端全局桥注册；脚本由 build.rs 纳入 Tauri 官方加载顺序。

pub fn init() -> tauri::plugin::TauriPlugin<tauri::Wry> {
    tauri::plugin::Builder::new("pytaruix").build()
}
