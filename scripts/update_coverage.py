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
from pathlib import Path


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
        ["cargo", "metadata", "--locked", "--format-version", "1"],
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
    declaration_pattern = re.compile(
        r"^\s*pub\s+(?:(?:async|unsafe|const)\s+)*(fn|struct|enum|trait|type|const|static|mod)\s+(\w+)"
    )
    crate_root = manifest_path.parent
    for source_path in sorted((crate_root / "src").rglob("*.rs")):
        relative = source_path.relative_to(crate_root).as_posix()
        source_bytes = source_path.read_bytes()
        sources.append({"path": relative, "sha256": hashlib.sha256(source_bytes).hexdigest()})
        for number, line in enumerate(source_bytes.decode("utf-8").splitlines(), 1):
            match = declaration_pattern.match(line)
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
    _dialog_coverage(root, packages, binding_manifest, arguments.check)
    print(
        f"Tauri {package['version']}: {len(upstream_features)} feature mappings, "
        f"{len(declarations)} declaration candidates"
    )


def _validate_ledger(root: Path, package: dict[str, object], ledger_path: Path) -> None:
    crate_root = Path(str(package["manifest_path"])).parent
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if ledger["version"] != package["version"]:
        raise SystemExit("Reviewed ledger version does not match locked Tauri")
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
    print(f"Reviewed API subset: {len(ids)} entries, {dict(Counter(entry['status'] for entry in ledger['entries']))}")


def _dialog_coverage(root: Path, packages: list[dict[str, object]], manifest: dict[str, object], check: bool) -> None:
    """
    单独核验 dialog 版本、源码、feature 和审核账本，不并入核心覆盖统计。
    """
    package = next(package for package in packages if package["name"] == "tauri-plugin-dialog")
    crate_root = Path(str(package["manifest_path"])).parent
    features = package["features"]
    assert isinstance(features, dict)
    binding_features = manifest["features"]
    assert isinstance(binding_features, dict)
    for name in features:
        if name == "default":
            assert "plugin-dialog" in binding_features["default"]
            assert all("dialog-" + feature in binding_features["default"] for feature in features[name])
        elif "tauri-plugin-dialog/" + name not in binding_features.get("dialog-" + name, []):
            raise SystemExit(f"Missing dialog feature mapping: {name}")
    sources = []
    declarations = []
    pattern = re.compile(
        r"^\s*pub\s+(?:(?:async|unsafe|const)\s+)*(fn|struct|enum|trait|type|const|static|mod)\s+(\w+)"
    )
    for path in sorted((crate_root / "src").rglob("*.rs")):
        relative = path.relative_to(crate_root).as_posix()
        content = path.read_bytes()
        sources.append({"path": relative, "sha256": hashlib.sha256(content).hexdigest()})
        for number, line in enumerate(content.decode("utf-8").splitlines(), 1):
            match = pattern.match(line)
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
    destination = root / "docs/upstream" / f"dialog-{package['version']}.json"
    content = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    if check:
        if not destination.is_file() or destination.read_text(encoding="utf-8") != content:
            raise SystemExit("Dialog source snapshot changed; regenerate and review")
    else:
        destination.write_text(content, encoding="utf-8", newline="\n")
    _validate_ledger(root, package, root / "docs/upstream" / f"bindings-dialog-{package['version']}.json")
    print(f"Dialog {package['version']}: {len(features)} feature mappings, {len(declarations)} declaration candidates")


if __name__ == "__main__":
    main()
