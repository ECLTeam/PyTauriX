# ============================================================
# PyTauriX
# 文件作用：记录源码与工具链身份、wheel 体积分解及独立环境安装占用。
# 公开接口：main。
# ============================================================
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

SOURCE_DIRS = ("python", "crates", "frontend", "docs", "scripts", "tests", "examples", ".github")
SOURCE_FILES = ("AGENTS.md", "Cargo.lock", "Cargo.toml", "README.md", "pyproject.toml", "uv.lock")
SKIPPED_PARTS = frozenset({"__pycache__", "gen", "target", "artifacts", ".venv", "dist"})
SKIPPED_SUFFIXES = frozenset({".pyd", ".pdb", ".pyc"})
NATIVE_SUFFIXES = frozenset({".pyd", ".so", ".dylib"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _skipped(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return any(part in SKIPPED_PARTS for part in relative.parts) or path.suffix in SKIPPED_SUFFIXES


def _source_manifest(root: Path) -> dict[str, object]:
    paths = [root / name for name in SOURCE_FILES]
    for name in SOURCE_DIRS:
        base = root / name
        if base.is_dir():
            paths.extend(path for path in base.rglob("*") if path.is_file() and not _skipped(path, root))
    entries = sorted(
        ((path.relative_to(root).as_posix(), _sha256(path)) for path in paths if path.is_file()),
        key=lambda item: item[0],
    )
    digest = hashlib.sha256("".join(f"{name}:{value}\n" for name, value in entries).encode()).hexdigest()
    return {"file_count": len(entries), "manifest_sha256": digest, "files": dict(entries)}


def _executable(name: str) -> str | None:
    candidate = Path(name)
    if candidate.is_absolute() or candidate.parent != Path("."):
        return str(candidate) if candidate.is_file() else None
    sibling = Path(sys.executable).with_name(name + (".exe" if sys.platform == "win32" else ""))
    if sibling.is_file():
        return str(sibling)
    return shutil.which(name)


def _version_of(executable: str | None) -> str | None:
    if executable is None:
        return None
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=60, check=False)
    except OSError:
        return None
    return result.stdout.strip() or result.stderr.strip() or None


def _toolchain(uv: str) -> dict[str, str | None]:
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "rustc": _version_of(_executable("rustc")),
        "cargo": _version_of(_executable("cargo")),
        "maturin": _version_of(_executable("maturin")),
        "uv": _version_of(_executable(uv)),
    }


def _git_identity(root: Path) -> dict[str, object]:
    def run(arguments: list[str]) -> str | None:
        try:
            result = subprocess.run(arguments, cwd=root, capture_output=True, text=True, timeout=60, check=False)
        except OSError:
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    status = run(["git", "status", "--porcelain"])
    return {
        "commit": run(["git", "rev-parse", "HEAD"]),
        "branch": run(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or run(["git", "branch", "--show-current"]),
        "dirty_files": 0 if status is None else len([line for line in status.splitlines() if line.strip()]),
    }


def _wheel_report(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        entries = [
            {"name": info.filename, "compressed": info.compress_size, "uncompressed": info.file_size}
            for info in archive.infolist()
        ]
    native = sum(entry["uncompressed"] for entry in entries if Path(entry["name"]).suffix in NATIVE_SUFFIXES)
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "compressed_bytes": sum(entry["compressed"] for entry in entries),
        "uncompressed_bytes": sum(entry["uncompressed"] for entry in entries),
        "native_uncompressed_bytes": native,
        "entries": entries,
    }


def _tree_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _install_report(uv: str, wheel: Path, venv: Path) -> dict[str, object]:
    if venv.exists():
        shutil.rmtree(venv)
    subprocess.run([uv, "venv", str(venv), "--python", sys.executable], check=True, timeout=300)
    if sys.platform == "win32":
        python = venv / "Scripts" / "python.exe"
        site_packages = venv / "Lib" / "site-packages"
    else:
        python = venv / "bin" / "python"
        site_packages = venv / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    subprocess.run([uv, "pip", "install", "--python", str(python), str(wheel)], check=True, timeout=600)
    script = (
        "import importlib.metadata as m, json, pytaurix\n"
        "print(json.dumps({'module': pytaurix.__file__, 'distributions': "
        "[{'name': d.metadata['Name'], 'version': d.version} for d in m.distributions()]}))"
    )
    probe = subprocess.run([str(python), "-I", "-c", script], capture_output=True, text=True, timeout=120, check=True)
    data = json.loads(probe.stdout)
    return {
        "venv": str(venv),
        "python": str(python),
        "module": data["module"],
        "package_dir_bytes": _tree_bytes(site_packages / "pytaurix"),
        "site_packages_bytes": _tree_bytes(site_packages),
        "distributions": data["distributions"],
    }


def main() -> None:
    """
    生成构建身份与 wheel/安装测量报告。

    :param sys.argv: --label 必填；--wheel 可重复；--out 为 JSON 路径
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--wheel", action="append", default=[])
    parser.add_argument("--out", required=True)
    parser.add_argument("--uv", default="uv")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    arguments = parser.parse_args()

    root = Path(arguments.root)
    wheels: list[dict[str, object]] = []
    installs: list[dict[str, object]] = []
    for raw in arguments.wheel:
        wheel = Path(raw).resolve()
        wheels.append(_wheel_report(wheel))
        venv = root / "artifacts" / "phase11" / "baseline" / "venvs" / f"{arguments.label}-{wheel.stem[-12:]}"
        installs.append(_install_report(arguments.uv, wheel, venv))

    report: dict[str, object] = {
        "label": arguments.label,
        "generated_at": datetime.now(UTC).isoformat(),
        "git": _git_identity(root),
        "toolchain": _toolchain(arguments.uv),
        "source": _source_manifest(root),
        "wheels": wheels,
        "installs": installs,
    }
    output = Path(arguments.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"MEASURED {arguments.label} -> {output}")


if __name__ == "__main__":
    main()
