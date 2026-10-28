// Tauri build script —— 打包时校验后端资源是否就位且与最近一次打包一致
use std::fs;
use std::path::{Path, PathBuf};

fn main() {
    tauri_build::build();

    // 后端是 PyInstaller onedir 产物，打包前由 scripts/prepare-sidecar.py
    // 复制到 src-tauri/resources/backend/，随 bundle.resources 进入 App。
    // dev 模式下可能还没生成，只做警告不阻断；release 必须校验通过。
    let manifest_dir = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap());
    let resources = manifest_dir.join("resources");
    let backend_dir = resources.join("backend");
    let manifest_path = resources.join("backend-manifest.json");
    let profile = std::env::var("PROFILE").unwrap_or_default();

    println!("cargo:rerun-if-changed=resources/backend");
    println!("cargo:rerun-if-changed=resources/backend-manifest.json");

    if profile != "release" {
        if !backend_dir.exists() {
            eprintln!(
                "⚠️  WARNING: src-tauri/resources/backend/ 目录不存在。\n\
                 dev 模式下会回退到 dist/_pybuild 里的后端，打包前请运行 `python3 scripts/prepare-sidecar.py`。"
            );
        }
        return;
    }

    if !backend_dir.is_dir() {
        panic!(
            "打包失败：src-tauri/resources/backend/ 不存在。\n\
             请先运行 `python3 scripts/prepare-sidecar.py` 准备后端资源。"
        );
    }

    let manifest = fs::read_to_string(&manifest_path).unwrap_or_else(|_| {
        panic!(
            "打包失败：缺少 resources/backend-manifest.json。\n\
             后端资源不是由 prepare-sidecar.py 准备的，请重新运行该脚本。"
        )
    });

    let value = |key: &str| -> Option<String> {
        manifest.lines().find_map(|line| {
            let line = line.trim();
            if line.starts_with('#') {
                return None;
            }
            let (k, v) = line.split_once('=')?;
            (k.trim() == key).then(|| v.trim().to_string())
        })
    };

    let exe_name = value("exe").unwrap_or_else(|| "cizha-backend".to_string());
    let expected_exe_size: u64 = value("exe_size")
        .and_then(|v| v.parse().ok())
        .unwrap_or_else(|| {
            panic!("打包失败：backend-manifest.json 里的 exe_size 无效，请重新运行 prepare-sidecar.py。")
        });
    let expected_count: u64 = value("file_count")
        .and_then(|v| v.parse().ok())
        .unwrap_or_else(|| {
            panic!("打包失败：backend-manifest.json 里的 file_count 无效，请重新运行 prepare-sidecar.py。")
        });

    let actual_exe_size = fs::metadata(backend_dir.join(&exe_name))
        .map(|m| m.len())
        .unwrap_or(0);
    if actual_exe_size != expected_exe_size {
        panic!(
            "打包失败：后端可执行文件与 manifest 不一致（{} != {}）。\n\
             后端可能被替换过，请重新运行 `python3 scripts/prepare-sidecar.py`。",
            actual_exe_size, expected_exe_size
        );
    }

    let actual_count = count_files(&backend_dir);
    if actual_count != expected_count {
        panic!(
            "打包失败：后端资源文件数与 manifest 不一致（{} != {}）。\n\
             请重新运行 `python3 scripts/prepare-sidecar.py`。",
            actual_count, expected_count
        );
    }

    // 本地 dist 还在时，确认打包源与复制件一致：
    // 防止复制后又重新打了 PyInstaller，导致 App 里仍是旧后端。
    if let Some(src) = value("source") {
        if let Ok(meta) = fs::metadata(Path::new(&src).join(&exe_name)) {
            if meta.len() != expected_exe_size {
                panic!(
                    "打包失败：dist 里的后端已重新打包，但 src-tauri/resources/backend 还是旧版本。\n\
                     请重新运行 `python3 scripts/prepare-sidecar.py`。"
                );
            }
        }
    }
}

fn count_files(dir: &Path) -> u64 {
    let mut count = 0;
    if let Ok(entries) = fs::read_dir(dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                count += count_files(&path);
            } else {
                count += 1;
            }
        }
    }
    count
}
