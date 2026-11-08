# PytaruiX
# 文件作用：保存 ECL 当前工作区快照，在独立目录生成显式导入迁移和可审核补丁。
# 公开接口：无；仅复制指定来源，不修改来源仓库或运行时数据。
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def snapshot(source: Path, destination: Path) -> dict[str, object]:
    files: dict[str, str] = {}
    commits: dict[str, str] = {}

    def copy_repository(root: Path, relative: Path) -> None:
        commits[relative.as_posix()] = git(root, "rev-parse", "HEAD").decode().strip()
        for raw in git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0"):
            if not raw:
                continue
            name = Path(raw.decode("utf-8"))
            current = root / name
            if current.is_dir() and (current / ".git").exists():
                copy_repository(current, relative / name)
            elif current.is_file():
                target = destination / relative / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(current, target)
                files[(relative / name).as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()

    copy_repository(source, Path("."))
    built_frontend = source / "frontend" / "dist"
    if built_frontend.is_dir():
        shutil.copytree(built_frontend, destination / "frontend" / "dist", dirs_exist_ok=True)
    return {
        "source": str(source),
        "commits": commits,
        "status": git(source, "status", "--short").decode("utf-8"),
        "files_sha256": files,
    }


def migrate(destination: Path) -> list[str]:
    changes: list[str] = []

    def edit(name: str, transform: object) -> None:
        # transform 仅为本脚本的纯文本函数，不接受外部脚本或表达式。
        if not callable(transform):
            raise TypeError("Expected text transformation")
        path = destination / name
        previous = path.read_text(encoding="utf-8")
        following = transform(previous)
        if previous == following:
            return
        path.write_text(following, encoding="utf-8")
        changes.extend(
            difflib.unified_diff(
                previous.splitlines(keepends=True),
                following.splitlines(keepends=True),
                fromfile=f"a/{name}",
                tofile=f"b/{name}",
            )
        )

    for name in [
        "adapters/tauri.py",
        "api/registry.py",
        "api/bridge.py",
        "api/windows.py",
        "api/files.py",
        "api/accounts.py",
    ]:
        edit(
            "ECL/" + name,
            lambda s: (
                s.replace("from pytauri_plugins.dialog", "from pytaruix.plugins.dialog")
                .replace("from pytauri_wheel.lib", "from pytaruix")
                .replace("from pytauri.", "from pytaruix.")
                .replace("from pytauri import", "from pytaruix import")
                .replace(
                    "from pytaruix import AppHandle, Commands, Manager, RunEvent, RunEventType\n"
                    "from pytaruix.plugins.dialog import init as dialog_init\n"
                    "from pytaruix import builder_factory, context_factory",
                    "from pytaruix import AppHandle, Commands, Manager, RunEvent, RunEventType, "
                    "builder_factory, context_factory\n"
                    "from pytaruix.plugins.dialog import init as dialog_init",
                )
            ),
        )
    edit(
        "pyproject.toml",
        lambda s: s.replace('    "pytauri-wheel>=0.8.0",\n    "pytauri>=0.8.0",', '    "pytaruix==0.1.0a1",'),
    )
    edit(
        "ECL/plugins/host_dependencies.py",
        lambda s: s.replace(
            '                        "ECL",', '                        "ECL",\n                        "pytaruix",'
        ),
    )
    edit(
        "ECL/api/windows.py",
        lambda s: s.replace(
            "suffix = request.instance_key or uuid4().hex[:10]",
            'suffix = (request.instance_key or uuid4().hex[:10]).replace(".", ":")',
        ).replace(
            'label = request.descriptor_id if descriptor["singleton"] else f"{request.descriptor_id}:{suffix}"',
            'label_base = request.descriptor_id.replace(".", ":")\n'
            '        label = label_base if descriptor["singleton"] else f"{label_base}:{suffix}"',
        ),
    )
    edit("capabilities/default.toml", lambda s: s.replace("plugin.*", "plugin:*"))
    for name in ["packaging/build-nuitka.ps1", ".github/workflows/build.yml"]:

        def packaging(s: str) -> str:
            for old in ["pytauri_plugins", "pytauri_utils", "pytauri_wheel"]:
                s = "".join(line for line in s.splitlines(keepends=True) if f"--include-package={old}" not in line)
            return (
                s.replace("--include-package=pytauri ", "--include-package=pytaruix ")
                .replace(
                    "--include-package=ECL `",
                    "--include-package=ECL `\n        --nofollow-import-to=ECL.game.tests `\n"
                    "        --disable-cache=ccache `\n        --noinclude-custom-mode=pygments:bytecode `",
                )
                .replace(
                    "--include-package=ECL \\",
                    "--include-package=ECL \\\n            --nofollow-import-to=ECL.game.tests \\\n"
                    "            --noinclude-custom-mode=pygments:bytecode \\",
                )
                .replace(
                    'ARGS+=(--windows-console-mode="$CONSOLE_MODE")',
                    'ARGS+=(--windows-console-mode="$CONSOLE_MODE" --disable-cache=ccache)',
                )
                .replace("--include-module=pytauri_wheel.ext_mod", "--include-module=pytaruix._native")
                .replace("--include-distribution-metadata=pytauri-wheel", "--include-distribution-metadata=pytaruix")
            )

        edit(name, packaging)

    def pyinstaller(s: str) -> str:
        s = s.replace('_collect_all_safe("pytauri_wheel")', '_collect_all_safe("pytaruix")')
        s = s.replace('_collect_all_safe("pytauri_plugins")', '_collect_all_safe("pytaruix.plugins")')
        s = s.replace('copy_metadata("pytauri-wheel")', 'copy_metadata("pytaruix")')
        s = s.replace('    "pytauri",', '    "pytaruix",')
        s = s.replace('    "pytauri.ffi",', '    "pytaruix.ffi",')
        s = s.replace('    "pytauri.ffi._ext_mod",', '    "pytaruix._native",')
        s = "".join(
            line
            for line in s.splitlines(keepends=True)
            if line.strip() not in {'"pytauri_wheel",', '"pytauri_wheel.ext_mod",'}
        )
        return s

    edit("EuoraCraft-Launcher.spec", pyinstaller)
    for path in (destination / "tests").glob("*.py"):
        if "pytauri" in path.read_text(encoding="utf-8"):
            edit(
                path.relative_to(destination).as_posix(),
                lambda s: s.replace("pytauri", "pytaruix").replace(
                    "pytaruix_plugins.dialog", "pytaruix.plugins.dialog"
                ),
            )
    edit(
        "tests/test_windows.py",
        lambda s: (
            s.replace('"plugin.*"', '"plugin:*"')
            .replace("icon.width()", "icon.width")
            .replace("icon.height()", "icon.height")
        ),
    )
    edit(
        "tests/test_frontend_api_config.py",
        lambda s: s.replace(
            "    def show(self) -> None:\n",
            "    def emit_target_json(self, target_json, event, payload) -> None:\n"
            "        # 原生发送在其他桌面测试验收；业务窗口替身仅记录调度。\n"
            "        self.last_event = (target_json, event, payload)\n\n"
            "    def show(self) -> None:\n",
            1,
        ),
    )
    return changes


def main() -> None:
    """
    将当前 ECL 与子模块的工作区内容复制到新的 artifacts 子目录并记录原始摘要。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", default="phase9-ecl")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = (root / "artifacts" / args.destination).resolve()
    if not destination.is_relative_to(root / "artifacts") or destination == root / "artifacts":
        parser.error("Destination must be a new directory inside artifacts")
    destination.mkdir(parents=True, exist_ok=False)
    baseline = snapshot(args.source.resolve(), destination)
    (destination.parent / f"{destination.name}-baseline.json").write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    patch = destination.parent / f"{destination.name}-migration.patch"
    patch.write_text("".join(migrate(destination)), encoding="utf-8")
    print(
        json.dumps(
            {"snapshot": str(destination), "patch": str(patch), "files": len(baseline["files_sha256"])},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
