# ============================================================
# PytaruiX
# 文件作用：按宿主目录解析路径，屏蔽平台差异并返回 pathlib.Path。
# 公开接口：BaseDirectory、PathResolver。
# ============================================================
from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import BindingError

if TYPE_CHECKING:
    from .ffi import AppHandle


class BaseDirectory(StrEnum):
    """
    宿主目录的公开名称，取值由原生入口归一化后映射到上游 `BaseDirectory`。

    平台不支持的目录在解析时返回 None，不折叠成空路径。
    """

    AUDIO = "audio"
    CACHE = "cache"
    CONFIG = "config"
    DATA = "data"
    LOCAL_DATA = "localData"
    DOCUMENT = "document"
    DOWNLOAD = "download"
    PICTURE = "picture"
    PUBLIC = "public"
    VIDEO = "video"
    RESOURCE = "resource"
    TEMP = "temp"
    APP_CONFIG = "appConfig"
    APP_DATA = "appData"
    APP_LOCAL_DATA = "appLocalData"
    APP_CACHE = "appCache"
    APP_LOG = "appLog"
    HOME = "home"
    DESKTOP = "desktop"
    EXECUTABLE = "executable"
    FONT = "font"
    RUNTIME = "runtime"
    TEMPLATE = "template"


def _base_name(base: BaseDirectory | str) -> str:
    return base.value if isinstance(base, BaseDirectory) else str(base)


class PathResolver:
    """
    把相对路径解析到宿主目录，所有返回值都是绝对路径。

    解析只读取当前应用身份，不创建目录、不校验路径是否存在；
    目录归属与读写权限由调用方决定。
    """

    def __init__(self, handle: AppHandle) -> None:
        self._handle = handle

    def resolve(self, path: str | Path, base: BaseDirectory | str) -> Path:
        """
        把相对路径解析到指定宿主目录下。

        :param path: 相对路径，空字符串表示目录本身
        :param base: 目录名称或 BaseDirectory 成员，忽略大小写与分隔符
        :return: 绝对路径
        :raises BindingError: 名称非法、目录在当前平台不可用或应用已关闭
        """
        resolved = self._handle.resolve_path(_base_name(base), str(path))
        if resolved is None:
            raise BindingError(f"path_unresolved: {base} is not available on this platform")
        return Path(resolved)

    def parse(self, path: str | Path) -> Path:
        """
        解析以 `$VARIABLE` 开头的路径，其余部分按原样保留。

        :param path: 可能含 `$VARIABLE` 前缀的路径
        :return: 绝对路径
        :raises BindingError: 变量无法解析、路径非 UTF-8 或应用已关闭
        """
        parsed = self._handle.parse_path(str(path))
        if parsed is None:
            raise BindingError(f"path_unresolved: {path} cannot be resolved")
        return Path(parsed)

    def _optional(self, base: BaseDirectory) -> Path | None:
        resolved = self._handle.resolve_path(base.value, "")
        return None if resolved is None else Path(resolved)

    @property
    def audio_dir(self) -> Path | None:
        """音频目录，平台不提供时为 None。"""
        return self._optional(BaseDirectory.AUDIO)

    @property
    def cache_dir(self) -> Path | None:
        """缓存目录，平台不提供时为 None。"""
        return self._optional(BaseDirectory.CACHE)

    @property
    def config_dir(self) -> Path | None:
        """用户配置目录，平台不提供时为 None。"""
        return self._optional(BaseDirectory.CONFIG)

    @property
    def data_dir(self) -> Path | None:
        """用户数据目录，平台不提供时为 None。"""
        return self._optional(BaseDirectory.DATA)

    @property
    def local_data_dir(self) -> Path | None:
        """用户本地数据目录，平台不提供时为 None。"""
        return self._optional(BaseDirectory.LOCAL_DATA)

    @property
    def document_dir(self) -> Path | None:
        """文档目录，平台不提供时为 None。"""
        return self._optional(BaseDirectory.DOCUMENT)

    @property
    def download_dir(self) -> Path | None:
        """下载目录，平台不提供时为 None。"""
        return self._optional(BaseDirectory.DOWNLOAD)

    @property
    def picture_dir(self) -> Path | None:
        """图片目录，平台不提供时为 None。"""
        return self._optional(BaseDirectory.PICTURE)

    @property
    def public_dir(self) -> Path | None:
        """公共目录，平台不提供时为 None。"""
        return self._optional(BaseDirectory.PUBLIC)

    @property
    def video_dir(self) -> Path | None:
        """视频目录，平台不提供时为 None。"""
        return self._optional(BaseDirectory.VIDEO)

    @property
    def desktop_dir(self) -> Path | None:
        """桌面目录，平台不提供时为 None。"""
        return self._optional(BaseDirectory.DESKTOP)

    @property
    def font_dir(self) -> Path | None:
        """字体目录，平台不提供时为 None。"""
        return self._optional(BaseDirectory.FONT)

    @property
    def runtime_dir(self) -> Path | None:
        """运行时目录，平台不提供时为 None。"""
        return self._optional(BaseDirectory.RUNTIME)

    @property
    def template_dir(self) -> Path | None:
        """模板目录，平台不提供时为 None。"""
        return self._optional(BaseDirectory.TEMPLATE)

    @property
    def home_dir(self) -> Path | None:
        """用户主目录，平台不提供时为 None。"""
        return self._optional(BaseDirectory.HOME)

    @property
    def resource_dir(self) -> Path | None:
        """应用资源目录，打包方式决定其位置。"""
        return self._optional(BaseDirectory.RESOURCE)

    @property
    def app_config_dir(self) -> Path | None:
        """应用配置目录，受宿主 appDirectoriesOverride 影响。"""
        return self._optional(BaseDirectory.APP_CONFIG)

    @property
    def app_data_dir(self) -> Path | None:
        """应用数据目录，受宿主 appDirectoriesOverride 影响。"""
        return self._optional(BaseDirectory.APP_DATA)

    @property
    def app_local_data_dir(self) -> Path | None:
        """应用本地数据目录，受宿主 appDirectoriesOverride 影响。"""
        return self._optional(BaseDirectory.APP_LOCAL_DATA)

    @property
    def app_cache_dir(self) -> Path | None:
        """应用缓存目录，受宿主 appDirectoriesOverride 影响。"""
        return self._optional(BaseDirectory.APP_CACHE)

    @property
    def app_log_dir(self) -> Path | None:
        """应用日志目录，受宿主 appDirectoriesOverride 影响。"""
        return self._optional(BaseDirectory.APP_LOG)


__all__ = ["BaseDirectory", "PathResolver"]
