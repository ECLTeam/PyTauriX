//! 启动时读取资源快照，校验路径，避免请求期间阻塞磁盘访问。

use std::{borrow::Cow, collections::BTreeMap, fs, path::Path};

use tauri::utils::assets::{AssetKey, AssetsIter, CspHash};

#[derive(Clone, Default)]
pub struct DirectoryAssets(BTreeMap<String, Vec<u8>>);

impl DirectoryAssets {
    pub fn load(root: &Path) -> std::io::Result<Self> {
        let root = root.canonicalize()?;
        let mut entries = BTreeMap::new();
        Self::visit(&root, &root, &mut entries)?;
        Ok(Self(entries))
    }

    fn visit(
        root: &Path,
        directory: &Path,
        entries: &mut BTreeMap<String, Vec<u8>>,
    ) -> std::io::Result<()> {
        for entry in fs::read_dir(directory)? {
            let entry = entry?;
            let path = entry.path();
            // 拒绝链接与 junction，避免将资源根目录之外的文件加入快照。
            if entry.file_type()?.is_symlink() || !path.canonicalize()?.starts_with(root) {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::InvalidInput,
                    "asset link escapes resource root",
                ));
            }
            if path.is_dir() {
                Self::visit(root, &path, entries)?;
            } else if path.is_file() {
                let relative = path.strip_prefix(root).map_err(std::io::Error::other)?;
                let key = format!("/{}", relative.to_string_lossy().replace('\\', "/"));
                entries.insert(key, fs::read(path)?);
            }
        }
        Ok(())
    }
}

impl tauri::Assets<tauri::Wry> for DirectoryAssets {
    fn get(&self, key: &AssetKey) -> Option<Cow<'_, [u8]>> {
        self.0
            .get(key.as_ref())
            .map(|bytes| Cow::Borrowed(bytes.as_slice()))
    }

    fn iter(&self) -> Box<AssetsIter<'_>> {
        Box::new(
            self.0
                .iter()
                .map(|(key, bytes)| (Cow::Borrowed(key.as_str()), Cow::Borrowed(bytes.as_slice()))),
        )
    }

    fn csp_hashes(&self, _html_path: &AssetKey) -> Box<dyn Iterator<Item = CspHash<'_>> + '_> {
        Box::new(std::iter::empty())
    }
}
