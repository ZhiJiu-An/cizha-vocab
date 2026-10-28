// Tauri build script —— 打包时生成必要的资源，检查 sidecar 就位
fn main() {
    tauri_build::build();

    // 可选：检查 src-tauri/binaries/ 下是否有对应平台的 sidecar
    // dev 模式下 PyInstaller 产物可能还没生成，只做警告不阻断
    let manifest_dir = std::env::var("CARGO_MANIFEST_DIR").unwrap();
    let binaries_dir = format!("{}/binaries", manifest_dir);
    let profile = std::env::var("PROFILE").unwrap_or_default();

    // 在 release build 时如果 binaries 目录不存在就警告
    if profile == "release" {
        if !std::path::Path::new(&binaries_dir).exists() {
            eprintln!(
                "⚠️  WARNING: src-tauri/binaries/ 目录不存在。\n\
                打包前请先运行 `python3 scripts/prepare-sidecar.py` 将 PyInstaller 产物重命名并放入该目录。"
            );
        }
    }

    // 告诉 Cargo 在 binaries/ 变化时重新运行 build.rs
    println!("cargo:rerun-if-changed=binaries/");
}
