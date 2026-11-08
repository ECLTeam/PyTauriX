# ============================================================
# PytaruiX
# 文件作用：从锁定 Cargo 源码发现公开声明并核验 feature 转发。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PluginSpec:
    """单个插件的核验口径：crate 名、快照前缀、本项目 feature 与转发要求。"""

    crate: str
    key: str
    feature: str
    in_default: bool
    required: tuple[str, ...]


# 上游 feature 转发要求：dialog 需要显式选择 Linux 后端，其余插件只用最小绑定。
PLUGIN_SPECS = (
    PluginSpec(
        crate="tauri-plugin-dialog",
        key="dialog",
        feature="plugin-dialog",
        in_default=True,
        required=("gtk3", "xdg-portal"),
    ),
    PluginSpec(
        crate="tauri-plugin-fs",
        key="fs",
        feature="plugin-fs",
        in_default=False,
        required=(),
    ),
    PluginSpec(
        crate="tauri-plugin-global-shortcut",
        key="global-shortcut",
        feature="plugin-global-shortcut",
        in_default=False,
        required=(),
    ),
    PluginSpec(
        crate="tauri-plugin-notification",
        key="notification",
        feature="plugin-notification",
        in_default=False,
        required=(),
    ),
    PluginSpec(
        crate="tauri-plugin-opener",
        key="opener",
        feature="plugin-opener",
        in_default=False,
        required=(),
    ),
    PluginSpec(
        crate="tauri-plugin-single-instance",
        key="single-instance",
        feature="plugin-single-instance",
        in_default=False,
        required=(),
    ),
)

DECLARATION_PATTERN = re.compile(
    r"^\s*pub\s+(?:(?:async|unsafe|const)\s+)*(fn|struct|enum|trait|type|const|static|mod)\s+(\w+)"
)


def main() -> None:
    """
    生成确定性的上游发现快照；检查模式发现差异时退出失败。

    仅扫描可见声明，不能替代 Rust 语义解析、cfg 或宏展开与人工审核。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        # 可选插件依赖默认不在解析图中，需启用全部 feature 才能列出其源码与版本。
        ["cargo", "metadata", "--locked", "--format-version", "1", "--all-features"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    packages = json.loads(result.stdout)["packages"]
    package = next(package for package in packages if package["name"] == "tauri")
    manifest_path = Path(package["manifest_path"])
    with (root / "crates" / "bindings" / "Cargo.toml").open("rb") as source:
        binding_manifest = tomllib.load(source)
    upstream_features = package["features"]
    for name in upstream_features:
        # default 是上游聚合开关。本项目禁用该聚合并显式选择能力，不逐项转发。
        if name == "default":
            continue
        if f"tauri/{name}" not in binding_manifest["features"].get(name, []):
            raise SystemExit(f"Missing Tauri feature forwarding: {name}")
    declarations = []
    sources = []
    crate_root = manifest_path.parent
    for source_path in sorted((crate_root / "src").rglob("*.rs")):
        relative = source_path.relative_to(crate_root).as_posix()
        source_bytes = source_path.read_bytes()
        sources.append({"path": relative, "sha256": hashlib.sha256(source_bytes).hexdigest()})
        for number, line in enumerate(source_bytes.decode("utf-8").splitlines(), 1):
            match = DECLARATION_PATTERN.match(line)
            if match:
                declarations.append(
                    {
                        "id": f"{relative}:{number}:{match[1]}:{match[2]}",
                        "source": relative,
                        "line": number,
                        "kind": match[1],
                        "name": match[2],
                        "declaration": line.strip(),
                        "status": "unreviewed",
                    }
                )
    snapshot = {
        "schema_version": 1,
        "crate": "tauri",
        "version": package["version"],
        "rust_version": package["rust_version"],
        "scope": "Public declaration candidates; excludes semantic cfg, macro expansion and trait member analysis",
        "features": {
            name: {"dependencies": dependencies, "status": "forwarded_only"}
            for name, dependencies in sorted(upstream_features.items())
        },
        "sources": sources,
        "declarations": declarations,
    }
    destination = root / "docs" / "upstream" / f"tauri-{package['version']}.json"
    content = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    if arguments.check:
        if not destination.is_file() or destination.read_text(encoding="utf-8") != content:
            raise SystemExit("Upstream snapshot changed; regenerate and review the difference")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8", newline="\n")
    _validate_ledger(root, package, root / "docs" / "upstream" / f"bindings-{package['version']}.json")
    for spec in PLUGIN_SPECS:
        _plugin_coverage(root, packages, binding_manifest, arguments.check, spec)
    for spec in PLUGIN_SPECS:
        _plugin_ledger(root, packages, spec)
    print(
        f"Tauri {package['version']}: {len(upstream_features)} feature mappings, "
        f"{len(declarations)} declaration candidates"
    )


def _validate_ledger(root: Path, package: dict[str, object], ledger_path: Path) -> None:
    crate_root = Path(str(package["manifest_path"])).parent
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if ledger["version"] != package["version"]:
        raise SystemExit("Reviewed ledger version does not match locked upstream crate")
    ids: set[str] = set()
    statuses = {"bound_tested", "partial_tested", "bound_unverified", "unimplemented", "platform_unavailable"}
    for entry in ledger["entries"]:
        if entry["id"] in ids or entry["status"] not in statuses:
            raise SystemExit(f"Invalid reviewed entry: {entry['id']}")
        ids.add(entry["id"])
        upstream = entry["upstream"]
        source_path = (crate_root / upstream["source"]).resolve()
        if not source_path.is_relative_to(crate_root.resolve()):
            raise SystemExit("Reviewed source escaped crate root")
        lines = source_path.read_text(encoding="utf-8").splitlines()
        if lines[upstream["line"] - 1].strip() != upstream["declaration"]:
            raise SystemExit(f"Reviewed declaration changed: {entry['id']}")
        if not entry["python"]["entry"] or not entry["python"]["signature"] or not entry["conditions"]:
            raise SystemExit(f"Reviewed mapping incomplete: {entry['id']}")
        if entry["status"] in {"bound_tested", "partial_tested"}:
            if not entry["evidence"] or not entry["tested_platforms"]:
                raise SystemExit(f"Reviewed test evidence missing: {entry['id']}")
        for evidence in entry["evidence"]:
            path = (root / evidence).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise SystemExit(f"Reviewed evidence missing: {evidence}")
    counts = dict(Counter(entry["status"] for entry in ledger["entries"]))
    print(f"Reviewed {package['name']} {package['version']}: {len(ids)} entries, {counts}")


def _plugin_coverage(
    root: Path,
    packages: list[dict[str, object]],
    manifest: dict[str, object],
    check: bool,
    spec: PluginSpec,
) -> None:
    """
    核验单个插件的版本、源码、feature 与审核账本，不并入核心覆盖统计。
    """
    package = next(package for package in packages if package["name"] == spec.crate)
    crate_root = Path(str(package["manifest_path"])).parent
    features = package["features"]
    assert isinstance(features, dict)
    binding_features = manifest["features"]
    assert isinstance(binding_features, dict)
    for name in features:
        if name == "default":
            if spec.in_default:
                assert spec.feature in binding_features["default"]
                assert all(f"{spec.key}-{feature}" in binding_features["default"] for feature in features[name])
            else:
                assert spec.feature not in binding_features["default"]
        elif name in spec.required:
            if f"{spec.crate}/{name}" not in binding_features.get(f"{spec.key}-{name}", []):
                raise SystemExit(f"Missing {spec.key} feature mapping: {name}")
    sources = []
    declarations = []
    for path in sorted((crate_root / "src").rglob("*.rs")):
        relative = path.relative_to(crate_root).as_posix()
        content = path.read_bytes()
        sources.append({"path": relative, "sha256": hashlib.sha256(content).hexdigest()})
        for number, line in enumerate(content.decode("utf-8").splitlines(), 1):
            match = DECLARATION_PATTERN.match(line)
            if match:
                declarations.append(
                    {
                        "id": f"{relative}:{number}:{match[1]}:{match[2]}",
                        "source": relative,
                        "line": number,
                        "kind": match[1],
                        "name": match[2],
                        "declaration": line.strip(),
                        "status": "unreviewed",
                    }
                )
    snapshot = {
        "schema_version": 1,
        "crate": package["name"],
        "version": package["version"],
        "rust_version": package["rust_version"],
        "scope": "Declaration candidates only; excludes cfg, macro expansion, trait methods and enum variants",
        "features": {name: {"dependencies": deps, "status": "build_mapped"} for name, deps in sorted(features.items())},
        "sources": sources,
        "declarations": declarations,
    }
    destination = root / "docs/upstream" / f"{spec.key}-{package['version']}.json"
    content = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    if check:
        if not destination.is_file() or destination.read_text(encoding="utf-8") != content:
            raise SystemExit(f"{spec.crate} source snapshot changed; regenerate and review")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8", newline="\n")
    print(
        f"{policy_label(spec)} {package['version']}: {len(features)} feature mappings, "
        f"{len(declarations)} declaration candidates"
    )


def _plugin_ledger(root: Path, packages: list[dict[str, object]], spec: PluginSpec) -> None:
    package = next(package for package in packages if package["name"] == spec.crate)
    _validate_ledger(root, package, root / "docs" / "upstream" / f"bindings-{spec.key}-{package['version']}.json")


def policy_label(spec: PluginSpec) -> str:
    return spec.crate.removeprefix("tauri-plugin-").replace("-", " ").title()


if __name__ == "__main__":
    main()
