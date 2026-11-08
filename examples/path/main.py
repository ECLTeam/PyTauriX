# PyTauriX
# 文件作用：真实桌面核验宿主目录解析、进程查询与错误契约。
# 公开接口：无。
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from pytaurix import (
    AppHandle,
    BaseDirectory,
    BindingError,
    Commands,
    Manager,
    RunEvent,
    RunEventType,
    builder_factory,
    context_factory,
    process,
)


def same_path(left: Path, right: Path) -> bool:
    """
    按平台大小写规则比较两个已存在路径，避免短名与长名差异造成误判。
    """
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def main() -> int:
    """
    构建真实窗口，在 Ready 回调内核对解析结果并立即退出。
    """
    root = Path(__file__).resolve().parent
    commands = Commands()
    checks: dict[str, bool] = {}

    def on_event(app_handle: AppHandle, event: RunEventType) -> None:
        if not isinstance(event, RunEvent.Ready):
            return
        resolver = Manager.path(app_handle)
        app_data = resolver.app_data_dir
        expected_log = None if app_data is None else app_data / "logs" / "app.log"
        checks["app_data_present"] = app_data is not None and app_data.is_absolute()
        checks["resolve_under_app_data"] = resolver.resolve("logs/app.log", BaseDirectory.APP_DATA) == expected_log
        checks["parse_variable"] = resolver.parse("$APPDATA/logs/app.log") == expected_log
        checks["string_base_name"] = resolver.resolve("", "appData") == app_data
        checks["temp_matches_environment"] = same_path(
            resolver.resolve("", BaseDirectory.TEMP), Path(tempfile.gettempdir())
        )
        resource = resolver.resource_dir
        checks["resource_dir_present"] = resource is not None and resource.exists()
        checks["home_present"] = resolver.home_dir is not None
        directories = [
            resolver.audio_dir,
            resolver.cache_dir,
            resolver.config_dir,
            resolver.data_dir,
            resolver.local_data_dir,
            resolver.document_dir,
            resolver.download_dir,
            resolver.picture_dir,
            resolver.public_dir,
            resolver.video_dir,
            resolver.desktop_dir,
            resolver.font_dir,
            resolver.runtime_dir,
            resolver.template_dir,
            resolver.resource_dir,
            resolver.app_config_dir,
            resolver.app_data_dir,
            resolver.app_local_data_dir,
            resolver.app_cache_dir,
            resolver.app_log_dir,
            resolver.home_dir,
        ]
        checks["directories_well_formed"] = all(item is None or item.is_absolute() for item in directories)
        checks["app_directories_present"] = all(
            item is not None
            for item in (
                resolver.app_config_dir,
                resolver.app_data_dir,
                resolver.app_local_data_dir,
                resolver.app_cache_dir,
                resolver.app_log_dir,
            )
        )
        try:
            resolver.resolve("", "unknown-directory")
        except BindingError as error:
            checks["invalid_base_rejected"] = str(error).startswith("invalid_base_directory:")
        else:
            checks["invalid_base_rejected"] = False
        checks["current_pid_matches"] = process.current_pid() == os.getpid()
        binary = process.current_binary(app_handle)
        checks["current_binary_matches"] = (
            binary.is_absolute() and binary.exists() and binary.name.lower() == Path(sys.executable).name.lower()
        )
        print("PATH_RESULT " + json.dumps(checks, sort_keys=True), flush=True)
        app_handle.exit(0 if all(checks.values()) else 1)

    context = context_factory(root)
    app = builder_factory().build(context=context, invoke_handler=commands.generate_handler())
    return app.run_return(on_event)


if __name__ == "__main__":
    raise SystemExit(main())
