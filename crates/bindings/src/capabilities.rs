//! 宿主权限快照；使用锁定 Tauri 的解析器，在构建前验证并整体替换示例 ACL。
use crate::binding_error;
use pyo3::prelude::*;
use std::collections::{BTreeMap, HashSet};
use tauri::utils::acl::{
    capability::Capability, manifest::Manifest, resolved::Resolved, RemoteUrlPattern, APP_ACL_KEY,
};

fn manifests() -> PyResult<BTreeMap<String, Manifest>> {
    serde_json::from_str(include_str!(concat!(
        env!("OUT_DIR"),
        "/acl-manifests.json"
    )))
    .map_err(|error| binding_error("capability_failed", error))
}

pub fn parse(json: &str) -> PyResult<Vec<Capability>> {
    let capabilities: Vec<Capability> =
        serde_json::from_str(json).map_err(|error| binding_error("invalid_capability", error))?;
    let mut ids = HashSet::new();
    for capability in &capabilities {
        if capability.identifier.is_empty() || !ids.insert(&capability.identifier) {
            return Err(binding_error(
                "invalid_capability",
                "Capability identifiers must be nonempty and unique",
            ));
        }
        if let Some(remote) = &capability.remote {
            for url in &remote.urls {
                // 上游 resolve_command 会 unwrap 远程模式；先调用同一解析器归还普通错误。
                url.parse::<RemoteUrlPattern>()
                    .map_err(|error| binding_error("invalid_capability", error))?;
            }
        }
    }
    resolve(&manifests()?, &capabilities)?;
    Ok(capabilities)
}

fn resolve(acl: &BTreeMap<String, Manifest>, capabilities: &[Capability]) -> PyResult<Resolved> {
    Resolved::resolve(
        acl,
        capabilities
            .iter()
            .map(|capability| (capability.identifier.clone(), capability.clone()))
            .collect(),
        tauri::utils::platform::Target::current(),
    )
    .map_err(|error| binding_error("invalid_capability", error))
}

pub fn authority(
    capabilities: &[Capability],
    plugins: &HashSet<String>,
) -> PyResult<tauri::ipc::RuntimeAuthority> {
    let mut acl = manifests()?;
    // 发行包编译进某插件不等于宿主注册了它；未注册插件的权限不能静默接受。
    acl.retain(|name, _| {
        name == APP_ACL_KEY
            || name == "core"
            || name.starts_with("core:")
            || name == "pytauri"
            || plugins.contains(name)
    });
    let resolved = resolve(&acl, capabilities)?;
    // RuntimeAuthority 构造及 Context.runtime_authority_mut 是版本相关集成边界。
    // 只使用精确锁定的 Tauri 2.12.1；升级时须连同真实允许/拒绝场景一起审核。
    Ok(tauri::runtime_authority!(acl, resolved))
}
