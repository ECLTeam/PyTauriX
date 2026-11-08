fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(&[
                "python_command",
                "pytaruix_cancel",
                "pytaruix_channel_ack",
            ]))
            .plugin(
                "pytauri",
                tauri_build::InlinedPlugin::new()
                    .commands(&["pyfunc"])
                    .default_permission(tauri_build::DefaultPermissionRule::AllowAllCommands),
            ),
    )
    .expect("Tauri build configuration failed");
}
