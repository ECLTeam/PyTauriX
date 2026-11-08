fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "python_command",
            "pytaurix_cancel",
            "pytaurix_channel_ack",
        ]),
    ))
    .expect("Tauri build configuration failed");
}
