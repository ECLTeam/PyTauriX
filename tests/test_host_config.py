from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pytaruix import BindingError, context_factory
from pytaruix.configuration import _prepare_context
from test_context import make_project


def write_capability(root: Path, value: object) -> None:
    directory = root / "capabilities"
    directory.mkdir(exist_ok=True)
    (directory / "host.json").write_text(json.dumps(value), encoding="utf-8")


def test_toml_platform_and_explicit_override(tmp_path: Path) -> None:
    make_project(tmp_path)
    (tmp_path / "tauri.conf.json").unlink()
    (tmp_path / "Tauri.toml").write_text(
        'identifier = "top.eclteam.host"\nproductName = "Base"\n[build]\nfrontendDist = "web"\n[app]\nwindows = []\n',
        encoding="utf-8",
    )
    platform = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    (tmp_path / f"Tauri.{platform}.toml").write_text('productName = "Platform"\n', encoding="utf-8")
    assert _prepare_context(tmp_path, None, False).config["productName"] == "Platform"
    override: dict[str, object] = {"productName": "Override", "app": {"windows": []}}
    assert _prepare_context(tmp_path, override, False).config["productName"] == "Override"
    assert override == {"productName": "Override", "app": {"windows": []}}
    context_factory(tmp_path, tauri_config=override)


def test_json_has_priority_over_toml(tmp_path: Path) -> None:
    make_project(tmp_path)
    (tmp_path / "Tauri.toml").write_text("deliberately invalid TOML", encoding="utf-8")
    context_factory(tmp_path)


def test_development_source_requires_explicit_selection(tmp_path: Path) -> None:
    make_project(tmp_path)
    override: dict[str, object] = {"build": {"devUrl": "http://127.0.0.1:5173"}}
    production = _prepare_context(tmp_path, override, False)
    development = _prepare_context(tmp_path, override, True)
    assert production.asset_root == tmp_path / "web"
    assert development.asset_root is None
    assert development.config["build"] == {"frontendDist": "http://127.0.0.1:5173", "devUrl": "http://127.0.0.1:5173"}
    context_factory(tmp_path, tauri_config=override, dev=True)
    assert override == {"build": {"devUrl": "http://127.0.0.1:5173"}}


def test_explicit_frontend_url_and_empty_host_policy(tmp_path: Path) -> None:
    make_project(tmp_path)
    (tmp_path / "capabilities").mkdir()
    prepared = _prepare_context(tmp_path, {"build": {"frontendDist": "https://example.com/app/"}}, False)
    assert prepared.asset_root is None
    assert prepared.host_capabilities
    assert prepared.capabilities == []
    context_factory(tmp_path, tauri_config={"build": {"frontendDist": "https://example.com/app/"}})


@pytest.mark.parametrize("url", ["file:///secret", "https://user:pass@example.com", "http://", "http://a:wrong"])
def test_invalid_frontend_origin(tmp_path: Path, url: str) -> None:
    with pytest.raises(BindingError, match="invalid_context"):
        context_factory(make_project(tmp_path), tauri_config={"build": {"frontendDist": url}})


def test_development_source_is_required(tmp_path: Path) -> None:
    with pytest.raises(BindingError, match="invalid_context"):
        context_factory(make_project(tmp_path), dev=True)


def test_host_capabilities_select_references_and_inline_objects(tmp_path: Path) -> None:
    make_project(tmp_path)
    write_capability(
        tmp_path,
        [
            {"identifier": "selected", "windows": ["main", "plugin.*"], "permissions": ["core:window:default"]},
            {"identifier": "excluded", "windows": ["rogue"], "permissions": ["core:default"]},
        ],
    )
    inline = {"identifier": "inline", "windows": ["theme-studio"], "permissions": ["core:default"]}
    override: dict[str, object] = {"app": {"security": {"capabilities": ["selected", inline]}}}
    prepared = _prepare_context(tmp_path, override, False)
    assert [item["identifier"] for item in prepared.capabilities] == ["selected", "inline"]
    assert prepared.host_capabilities
    context_factory(tmp_path, tauri_config=override)


def test_capabilities_toml(tmp_path: Path) -> None:
    make_project(tmp_path)
    (tmp_path / "capabilities").mkdir()
    (tmp_path / "capabilities" / "default.toml").write_text(
        'identifier = "ecl"\nwindows = ["main", "theme-studio", "plugin.*"]\n'
        'permissions = ["core:default", "core:window:default", "dialog:default"]\n',
        encoding="utf-8",
    )
    prepared = _prepare_context(tmp_path, None, False)
    assert prepared.capabilities[0]["identifier"] == "ecl"
    context_factory(tmp_path)


@pytest.mark.parametrize(
    "capabilities",
    [
        [{"identifier": "bad", "permissions": ["nonexistent:permission"]}],
        [{"identifier": "bad", "windows": ["["], "permissions": ["core:default"]}],
        [{"identifier": "bad", "remote": {"urls": ["http://["]}, "permissions": ["core:default"]}],
        [{"identifier": "duplicate"}, {"identifier": "duplicate"}],
        [{"identifier": ""}],
    ],
)
def test_invalid_host_policy_is_an_ordinary_error(tmp_path: Path, capabilities: object) -> None:
    make_project(tmp_path)
    write_capability(tmp_path, capabilities)
    with pytest.raises(BindingError, match="invalid_capability"):
        context_factory(tmp_path)


def test_missing_capability_reference(tmp_path: Path) -> None:
    with pytest.raises(BindingError, match="invalid_capability"):
        context_factory(make_project(tmp_path), tauri_config={"app": {"security": {"capabilities": ["missing"]}}})


def test_host_icon_is_loaded_as_owned_pixels(tmp_path: Path) -> None:
    make_project(tmp_path)
    image = Path(__file__).parents[1] / "examples" / "display_image" / "icons" / "alpha.png"
    prepared = _prepare_context(tmp_path, {"bundle": {"icon": [str(image)]}}, False)
    assert prepared.icon is not None
    assert prepared.icon.width > 0
    assert len(prepared.icon.rgba) == prepared.icon.width * prepared.icon.height * 4
    context_factory(tmp_path, tauri_config={"bundle": {"icon": [str(image)]}})


def test_native_config_window_failure_returns_to_python() -> None:
    code = """
from pathlib import Path
from pytaruix import BindingError, Commands, builder_factory, context_factory
context = context_factory(Path("examples/minimal"), tauri_config={
    "app": {"windows": [{"label": "invalid.dot"}]}
})
app = builder_factory().build(context=context, invoke_handler=Commands().generate_handler())
try:
    app.run_return()
except BindingError as error:
    assert "window_create_failed" in str(error), str(error)
else:
    raise AssertionError("Invalid native label was accepted")
try:
    app.handle()
except BindingError as error:
    assert "app_closed" in str(error), str(error)
print("CONFIG_WINDOW_ERROR_RECOVERED")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CONFIG_WINDOW_ERROR_RECOVERED" in result.stdout
    assert "panicked" not in result.stderr


def test_unregistered_host_plugin_policy_does_not_consume_runtime() -> None:
    code = """
from pathlib import Path
from pytaruix import BindingError, Commands, builder_factory, context_factory
from pytaruix.plugins.dialog import init
context = context_factory(Path("examples/minimal"), tauri_config={
    "app": {"windows": [], "security": {"capabilities": [{
        "identifier": "host-dialog", "windows": ["main"], "permissions": ["dialog:default"]
    }]}}
})
plugin = init()
handler = Commands().generate_handler()
try:
    builder_factory().build(context=context, invoke_handler=handler)
except BindingError as error:
    assert "invalid_capability" in str(error)
else:
    raise AssertionError("Unregistered dialog permissions were accepted")
assert not plugin.consumed
app = builder_factory().build(context=context, invoke_handler=handler, plugins=[plugin])
assert plugin.consumed
del app
print("HOST_PLUGIN_POLICY_RECOVERED")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "HOST_PLUGIN_POLICY_RECOVERED" in result.stdout
