fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "python_command",
            "pytaruix_cancel",
            "pytaruix_channel_ack",
        ]),
    ))
    .expect("Tauri build configuration failed");
}
