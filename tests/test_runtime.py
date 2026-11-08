from __future__ import annotations

from pytaurix import get_runtime_info


def test_runtime_reports_compiled_capabilities_without_claiming_registration() -> None:
    info = get_runtime_info()
    assert info.tauri_version == "2.12.1"
    assert info.pyo3_version == "0.29.3"
    assert "ipc.async_portal" in info.capabilities
    assert "plugin.register" in info.capabilities
    assert ("plugin.dialog" in info.capabilities) == (info.dialog_version == "2.8.1")
