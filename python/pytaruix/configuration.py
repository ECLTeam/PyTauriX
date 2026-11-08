# PytaruiX
# 文件作用：读取宿主配置和能力快照，区分生产资源与显式开发来源。
# 公开接口：无；context_factory 使用本模块准备原生上下文。
from __future__ import annotations

import json
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .errors import BindingError
from .ffi.image import Image


@dataclass(frozen=True, slots=True)
class _PreparedContext:
    asset_root: Path | None
    config: dict[str, object]
    capabilities: list[dict[str, object]]
    host_capabilities: bool
    icon: Image | None


def _document(path: Path) -> dict[str, object]:
    data: object = (
        tomllib.loads(path.read_text(encoding="utf-8"))
        if path.suffix == ".toml"
        else json.loads(path.read_text(encoding="utf-8-sig"))
    )
    if not isinstance(data, dict):
        raise ValueError(f"Expected a configuration object: {path.name}")
    return data


def _merge_config(original: Mapping[str, object], override: Mapping[str, object]) -> dict[str, object]:
    """
    递归合并配置，不修改输入；数组整体替换，null 删除字段。
    """
    merged = dict(original)
    for key, value in override.items():
        if value is None:
            merged.pop(key, None)
        elif isinstance(value, dict):
            previous = merged.get(key)
            merged[key] = _merge_config(previous if isinstance(previous, dict) else {}, value)
        else:
            merged[key] = value
    return merged


def _config(root: Path, override: Mapping[str, object] | None) -> dict[str, object]:
    path = root / "tauri.conf.json"
    if not path.is_file():
        path = root / "Tauri.toml"
    config = _document(path)
    target = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    platform_path = root / (f"Tauri.{target}.toml" if path.suffix == ".toml" else f"tauri.{target}.conf.json")
    if platform_path.is_file():
        config = _merge_config(config, _document(platform_path))
    return config if override is None else _merge_config(config, override)


def _http_url(value: object) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError("Frontend URL must be HTTP(S) text")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Frontend URL requires an HTTP(S) origin without credentials")
    _ = parsed.port
    return value


def _frontend(root: Path, build: dict[str, object], dev: bool) -> Path | None:
    frontend = build.get("frontendDist")
    if dev:
        frontend = build.get("devUrl") or frontend
        if not isinstance(frontend, str) or "://" not in frontend:
            raise ValueError("dev=True requires devUrl or a URL frontendDist")
    if not isinstance(frontend, str) or not frontend:
        raise ValueError("frontendDist must be a directory or an HTTP(S) URL")
    if "://" in frontend:
        url = _http_url(frontend)
        # 本绑定启用 custom-protocol，Tauri 不会仅凭调试 profile 选择 devUrl。
        # 显式把所选开发来源作为 app URL；生产目录模式仍保持打包资源来源。
        build["frontendDist"] = url
        build["devUrl"] = url
        return None
    asset_root = (root / frontend).resolve()
    if not (asset_root / "index.html").is_file():
        raise ValueError("frontendDist must contain index.html")
    return asset_root


def _capability_objects(value: object) -> list[dict[str, object]]:
    if isinstance(value, dict) and "capabilities" in value:
        value = value["capabilities"]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("Capabilities must contain capability objects")
    return value


def _capabilities(root: Path, security: dict[str, object]) -> tuple[list[dict[str, object]], bool]:
    directory = root / "capabilities"
    available: dict[str, dict[str, object]] = {}

    def insert(item: dict[str, object]) -> None:
        identifier = item.get("identifier")
        if not isinstance(identifier, str) or not identifier or identifier in available:
            raise ValueError("Capability identifiers must be nonempty and unique")
        available[identifier] = item

    if directory.is_dir():
        for path in sorted(directory.rglob("*")):
            if path.suffix not in {".json", ".toml"} or not path.is_file():
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError("Capability file escapes the host root")
            value: object = (
                _document(path) if path.suffix == ".toml" else json.loads(path.read_text(encoding="utf-8-sig"))
            )
            for item in _capability_objects(value):
                insert(item)
    host = directory.is_dir() or "capabilities" in security
    selected = security.get("capabilities")
    if selected is not None and not isinstance(selected, list):
        raise ValueError("security.capabilities must be a list")
    if selected:
        result: list[dict[str, object]] = []
        ids: set[str] = set()
        for item in selected:
            if isinstance(item, str):
                if item not in available:
                    raise ValueError(f"Unknown capability reference: {item}")
                item = available[item]
            if not isinstance(item, dict):
                raise ValueError("Expected a capability reference or object")
            identifier = item.get("identifier")
            if not isinstance(identifier, str) or not identifier or identifier in ids:
                raise ValueError("Selected capability identifiers must be nonempty and unique")
            ids.add(identifier)
            result.append(item)
        return result, host
    if host:
        # 与上游一致：空选择列表采用目录能力；空宿主目录不退回示例默认权限。
        return list(available.values()), True
    return [
        {
            "identifier": "pytaruix-prototype",
            "windows": ["main", "secondary"],
            "permissions": ["core:default", "pytauri:allow-pyfunc", "allow-python-command"],
        }
    ], False


def _icon(root: Path, config: dict[str, object]) -> Image | None:
    bundle = config.get("bundle", {})
    if not isinstance(bundle, dict):
        raise ValueError("bundle must be an object")
    icons = bundle.get("icon", [])
    if not isinstance(icons, list) or any(not isinstance(item, str) for item in icons):
        raise ValueError("bundle.icon must be a list of paths")
    if not icons:
        return None
    preferred = (".ico", ".png") if sys.platform == "win32" else (".png", ".ico")
    for extension in preferred:
        for value in icons:
            path = root / value
            if path.suffix.lower() == extension:
                return Image.from_path(path)
    raise ValueError("Default window icon requires a PNG or ICO entry")


def _prepare_context(root: Path, override: Mapping[str, object] | None, dev: bool) -> _PreparedContext:
    """
    读取宿主配置和能力，不创建 GUI；CSP/隔离仍明确拒绝。
    """
    try:
        if type(dev) is not bool:
            raise TypeError("dev must be bool")
        config = _config(root, override)
        build = config.setdefault("build", {})
        app = config.setdefault("app", {})
        if not isinstance(build, dict) or not isinstance(app, dict):
            raise ValueError("build/app must be objects")
        security = app.get("security", {})
        if not isinstance(security, dict):
            raise ValueError("app.security must be an object")
        if security.get("csp") is not None:
            raise ValueError("Runtime CSP assets are not implemented")
        pattern = security.get("pattern", {"use": "brownfield"})
        if not isinstance(pattern, dict) or pattern.get("use") != "brownfield":
            raise ValueError("Only the brownfield pattern is implemented")
        app["withGlobalTauri"] = True
        asset_root = _frontend(root, build, dev)
        try:
            capabilities, host_capabilities = _capabilities(root, security)
        except (OSError, ValueError, TypeError) as error:
            raise BindingError(f"invalid_capability: {error}") from error
        return _PreparedContext(asset_root, config, capabilities, host_capabilities, _icon(root, config))
    except (OSError, ValueError, TypeError) as error:
        raise BindingError(f"invalid_context: {error}") from error
