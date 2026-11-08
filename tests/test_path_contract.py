from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from pytaruix import BaseDirectory, BindingError, PathResolver, process
from pytaruix.ffi import AppHandle
from pytaruix.manager import ManagerType


class StubHandle:
    """记录路径请求并返回预设结果，用于验证 Python 侧的转换与错误语义。"""

    def __init__(self, directories: dict[str, str] | None = None, parsed: dict[str, str] | None = None) -> None:
        self.directories = directories or {}
        self.parsed = parsed or {}
        self.calls: list[tuple[str, str]] = []

    def resolve_path(self, base: str, path: str, /) -> str | None:
        self.calls.append((base, path))
        return self.directories.get(f"{base}|{path}")

    def parse_path(self, path: str, /) -> str | None:
        return self.parsed.get(path)

    def current_binary(self) -> str:
        return r"C:\Program Files\PytaruiX\pytaruix.exe"


def resolver(handle: StubHandle) -> PathResolver:
    return PathResolver(cast(AppHandle, handle))


def test_resolve_returns_path_and_forwards_canonical_name() -> None:
    handle = StubHandle({"appData|logs/app.log": r"C:\Users\me\AppData\logs\app.log"})
    assert resolver(handle).resolve("logs/app.log", BaseDirectory.APP_DATA) == Path(r"C:\Users\me\AppData\logs\app.log")
    assert handle.calls == [("appData", "logs/app.log")]


def test_resolve_accepts_string_names_without_rewriting() -> None:
    handle = StubHandle({"$APPDATA|": r"C:\Users\me\AppData"})
    assert resolver(handle).resolve("", "$APPDATA") == Path(r"C:\Users\me\AppData")
    assert handle.calls == [("$APPDATA", "")]


def test_unavailable_directory_raises_binding_error() -> None:
    with pytest.raises(BindingError, match="path_unresolved"):
        resolver(StubHandle()).resolve("logs", BaseDirectory.APP_LOG)


def test_parse_maps_variable_and_rejects_unknown() -> None:
    handle = StubHandle(parsed={"$HOME/a.txt": r"C:\Users\me\a.txt"})
    assert resolver(handle).parse("$HOME/a.txt") == Path(r"C:\Users\me\a.txt")
    with pytest.raises(BindingError, match="path_unresolved"):
        resolver(handle).parse("$UNKNOWN/a.txt")


def test_directory_properties_distinguish_missing_from_present() -> None:
    present = resolver(StubHandle({"appData|": r"C:\data"}))
    assert present.app_data_dir == Path(r"C:\data")
    assert present.app_log_dir is None
    assert resolver(StubHandle()).app_config_dir is None


def test_base_directory_names_are_canonical_and_complete() -> None:
    assert BaseDirectory("appData") is BaseDirectory.APP_DATA
    assert BaseDirectory("appLocalData") is BaseDirectory.APP_LOCAL_DATA
    assert len(BaseDirectory) == 23


def test_current_pid_needs_no_application() -> None:
    assert process.current_pid() > 0


def test_current_binary_uses_handle() -> None:
    assert process.current_binary(cast(ManagerType, StubHandle())) == Path(r"C:\Program Files\PytaruiX\pytaruix.exe")
