# ============================================================
# PytaruiX
# 文件作用：区分应用资源页面与外部网页，避免隐式 URL 推断。
# 公开接口：WebviewUrl、WebviewUrlType。
# ============================================================
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TypeAlias
from urllib.parse import unquote, urlsplit

from .errors import BindingError


class WebviewUrl:
    """
    按来源显式声明页面 URL，外部页面不自动获得本地 IPC 权限。
    """

    @dataclass(frozen=True, slots=True)
    class App:
        """
        声明应用资源目录内页面，可含查询与片段。

        路径必须为相对路径，不能包含父目录、磁盘前缀或网络来源。
        """

        path: str | Path

        def __post_init__(self) -> None:
            value = str(self.path).replace("\\", "/")
            parsed = urlsplit(value)
            path = unquote(parsed.path)
            if (
                not path
                or parsed.scheme
                or parsed.netloc
                or PurePosixPath(path).is_absolute()
                or any(part == ".." for part in path.split("/"))
                or "\\" in path
                or "\x00" in value
            ):
                raise BindingError("invalid_url: App URL must stay within application assets")
            object.__setattr__(self, "path", value)

    @dataclass(frozen=True, slots=True)
    class External:
        """
        声明外部 HTTP(S) 页面，不自动授予该来源 Python 调用权限。

        :param url: 具有主机名的绝对 HTTP(S) URL
        """

        url: str

        def __post_init__(self) -> None:
            parsed = urlsplit(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or "\x00" in self.url:
                raise BindingError("invalid_url: External URL requires an absolute HTTP(S) address")


WebviewUrlType: TypeAlias = WebviewUrl.App | WebviewUrl.External
