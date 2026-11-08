use std::path::Path;

fn main() {
    let bridge = Path::new("../../frontend/bridge.js");
    println!("cargo:rerun-if-changed={}", bridge.display());
    // 通过官方构建集成注册，使桥接脚本在 Tauri 全局 API 初始化之后执行。
    tauri_utils::plugin::define_global_api_script_path(bridge);
}
