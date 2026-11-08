from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from pytaruix import BindingError, Commands, builder_factory, context_factory
from pytaruix.application import _merge_config


def make_project(tmp_path: Path) -> Path:
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text("<!doctype html><p>Test</p>", encoding="utf-8")
    config = {"identifier": "top.eclteam.test", "build": {"frontendDist": "web"}, "app": {"windows": []}}
    (tmp_path / "tauri.conf.json").write_text(json.dumps(config), encoding="utf-8")
    return tmp_path


def test_merge_is_recursive_without_mutation() -> None:
    original: dict[str, object] = {"app": {"windows": [1], "security": {"csp": "old"}}}
    override: dict[str, object] = {"app": {"windows": [2], "security": {"csp": None}}}
    assert _merge_config(original, override) == {"app": {"windows": [2], "security": {}}}
    assert original == {"app": {"windows": [1], "security": {"csp": "old"}}}


def test_context_reads_real_assets_and_native_config(tmp_path: Path) -> None:
    context_factory(make_project(tmp_path))


@pytest.mark.parametrize(
    "override",
    [
        {"build": {"frontendDist": "file:///private/index.html"}},
        {"app": {"security": {"csp": "default-src 'self'"}}},
        {"app": {"security": {"pattern": {"use": "isolation"}}}},
        {"app": {"security": {"capabilities": ["custom"]}}},
    ],
)
def test_unsupported_configuration_is_rejected(tmp_path: Path, override: dict[str, object]) -> None:
    with pytest.raises(BindingError):
        context_factory(make_project(tmp_path), tauri_config=override)


def test_wrong_thread_build_is_rejected_before_native_access(tmp_path: Path) -> None:
    context = context_factory(make_project(tmp_path))
    failures: list[Exception] = []

    def build() -> None:
        try:
            builder_factory().build(context=context, invoke_handler=Commands().generate_handler())
        except Exception as error:
            failures.append(error)

    worker = threading.Thread(target=build)
    worker.start()
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], BindingError)
    assert "wrong_thread" in str(failures[0])


def test_asset_link_escape_is_rejected(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    project = make_project(project_root)
    secret = tmp_path / "private.txt"
    secret.write_text("must not be served", encoding="utf-8")
    try:
        (project / "web" / "link.txt").symlink_to(secret)
    except OSError:
        pytest.skip("OS does not permit creating test symlinks")
    with pytest.raises(BindingError, match="resource_failed"):
        context_factory(project)
