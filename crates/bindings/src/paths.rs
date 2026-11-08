//! 路径解析：把上游 `BaseDirectory` 暴露为稳定字符串入口。
//!
//! 公开边界只接受名称字符串与相对路径，返回 UTF-8 绝对路径；
//! 目录不可用时返回 `None`，不把平台差异折叠成空字符串。
use crate::binding_error;
use pyo3::prelude::*;
use std::path::PathBuf;
use tauri::path::BaseDirectory;
use tauri::Manager;

/// 把公开目录名解析为上游 `BaseDirectory`。
///
/// 接受 camelCase、snake_case 与 `$VARIABLE` 形式，比较前忽略大小写、下划线与美元符号。
pub fn base_directory(name: &str) -> PyResult<BaseDirectory> {
    let normalized = name
        .chars()
        .filter(char::is_ascii_alphanumeric)
        .map(|value| value.to_ascii_lowercase())
        .collect::<String>();
    let directory = match normalized.as_str() {
        "audio" => BaseDirectory::Audio,
        "cache" => BaseDirectory::Cache,
        "config" => BaseDirectory::Config,
        "data" => BaseDirectory::Data,
        "localdata" => BaseDirectory::LocalData,
        "document" | "documents" => BaseDirectory::Document,
        "download" | "downloads" => BaseDirectory::Download,
        "picture" | "pictures" => BaseDirectory::Picture,
        "public" => BaseDirectory::Public,
        "video" | "videos" => BaseDirectory::Video,
        "resource" | "resources" => BaseDirectory::Resource,
        "temp" => BaseDirectory::Temp,
        "appconfig" => BaseDirectory::AppConfig,
        "appdata" => BaseDirectory::AppData,
        "applocaldata" => BaseDirectory::AppLocalData,
        "appcache" => BaseDirectory::AppCache,
        "applog" => BaseDirectory::AppLog,
        "home" => BaseDirectory::Home,
        #[cfg(not(target_os = "android"))]
        "desktop" => BaseDirectory::Desktop,
        #[cfg(not(target_os = "android"))]
        "exe" | "executable" => BaseDirectory::Executable,
        #[cfg(not(target_os = "android"))]
        "font" | "fonts" => BaseDirectory::Font,
        #[cfg(not(target_os = "android"))]
        "runtime" => BaseDirectory::Runtime,
        #[cfg(not(target_os = "android"))]
        "template" => BaseDirectory::Template,
        _ => {
            return Err(binding_error(
                "invalid_base_directory",
                format!("Unknown base directory: {name}"),
            ))
        }
    };
    Ok(directory)
}

/// 解析宿主目录下的相对路径；目录在当前平台不可用时返回 `None`。
pub fn resolve(handle: &tauri::AppHandle, base: &str, path: &str) -> PyResult<Option<String>> {
    let directory = base_directory(base)?;
    match handle.path().resolve(path, directory) {
        Ok(resolved) => path_string(resolved).map(Some),
        Err(_) => Ok(None),
    }
}

/// 解析以 `$VARIABLE` 开头的路径；未知变量或不可用目录返回 `None`。
pub fn parse(handle: &tauri::AppHandle, path: &str) -> PyResult<Option<String>> {
    match handle.path().parse(path) {
        Ok(parsed) => path_string(parsed).map(Some),
        Err(_) => Ok(None),
    }
}

/// 把原生路径转换为 Python 可接收的字符串。
///
/// 非 UTF-8 路径明确失败，不使用有损转换隐藏真实文件名。
/// Windows 上去掉 `\\?\` 扩展前缀，避免调用方拿到 Python 不便处理的写法。
pub fn path_string(path: PathBuf) -> PyResult<String> {
    normalize(path)
        .into_os_string()
        .into_string()
        .map_err(|_| binding_error("path_not_utf8", "Path is not valid UTF-8"))
}

/// 去掉 Windows 扩展长度前缀；其他平台保持原样。
#[cfg(windows)]
fn normalize(path: PathBuf) -> PathBuf {
    use std::path::{Component, Prefix};

    let mut components = path.components();
    let Some(Component::Prefix(prefix)) = components.next() else {
        return path;
    };
    let rebuilt = match prefix.kind() {
        Prefix::VerbatimDisk(letter) => Some(PathBuf::from(format!("{}:\\", letter as char))),
        Prefix::VerbatimUNC(server, share) => Some(PathBuf::from(format!(
            r"\\{}\{}",
            server.to_string_lossy(),
            share.to_string_lossy()
        ))),
        _ => None,
    };
    match rebuilt {
        Some(mut result) => {
            result.extend(components);
            result
        }
        None => path,
    }
}

/// 非 Windows 平台没有扩展长度前缀，直接返回原路径。
#[cfg(not(windows))]
fn normalize(path: PathBuf) -> PathBuf {
    path
}
