//! 词札桌面壳层 —— Tauri + PyInstaller sidecar
//!
//! 职责：
//!   1. spawn PyInstaller 打包的后端二进制做 sidecar 子进程
//!   2. 探测可用端口 → 传 --port 给后端
//!   3. 等待后端就绪 → 创建 WebView 窗口加载 http://127.0.0.1:{port}/
//!   4. 应用退出时 kill sidecar 子进程

use std::net::TcpListener;
use std::process::{Child, Command as StdCommand, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::Manager;
use tauri_plugin_shell::ShellExt;
use url::Url;

/// 全局状态：保存当前后端使用的端口和 sidecar 子进程 handle
#[allow(dead_code)]
struct AppState {
    port: Mutex<u16>,
    backend: Mutex<Option<Child>>,
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // 1. 探测可用端口（从 18765 开始，避免常见端口）
            let port = find_free_port(18765).expect("找不到可用端口");
            println!("🔌 分配端口: {}", port);

            // 存入全局状态
            app.manage(AppState {
                port: Mutex::new(port),
                backend: Mutex::new(None),
            });

            // 2. spawn sidecar —— 优先用 Tauri shell 插件（release 模式）
            //    dev 模式下二进制可能还没按 triple 重命名，fallback 到 std::process::Command
            let backend_child = spawn_backend_sidecar(app.handle(), port);

            // 3. 等待后端就绪
            println!("⏳ 等待后端启动...");
            if let Err(e) = wait_for_port(port, 15, Duration::from_millis(500)) {
                eprintln!("❌ 后端启动失败: {}", e);
                return Err(Box::new(e));
            }
            // 端口 listen 后给 FastAPI 一个额外的 startup event 完成时间
            thread::sleep(Duration::from_millis(1500));
            println!("✅ 后端就绪，监听 http://127.0.0.1:{}", port);

            // 4. 保存 child handle 到状态
            if let Some(state) = app.try_state::<AppState>() {
                *state.backend.lock().unwrap() = backend_child;
            }

            // 5. 创建主窗口（初始 hidden，等后端 ready 再显示，避免白屏闪烁）
            let main_window = app
                .get_webview_window("main")
                .ok_or("找不到 main 窗口")?;

            let url = format!("http://127.0.0.1:{}/", port);
            let parsed_url = Url::parse(&url)
                .map_err(|e| Box::new(e) as Box<dyn std::error::Error>)?;
            main_window
                .navigate(parsed_url)
                .map_err(|e| Box::new(e) as Box<dyn std::error::Error>)?;
            main_window.show().map_err(|e| Box::new(e) as Box<dyn std::error::Error>)?;
            main_window.set_focus().map_err(|e| Box::new(e) as Box<dyn std::error::Error>)?;

            println!("🖥️  窗口已显示，加载 {}", url);

            Ok(())
        })
        // 退出时清理 sidecar
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                // 优雅退出 sidecar
                if let Some(state) = window.try_state::<AppState>() {
                    if let Ok(mut backend) = state.backend.lock() {
                        if let Some(mut child) = backend.take() {
                            let _ = child.kill();
                            let _ = child.wait();
                            println!("🧹 sidecar 已清理");
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// spawn sidecar 二进制
///
/// 优先级：
///   1. 尝试 Tauri shell 插件（会自动按 target triple 找 src-tauri/binaries/cizha-backend-{triple}）
///   2. fallback：用 std::process::Command 直接运行 _pybuild/dist/cizha-backend（dev 模式）
fn spawn_backend_sidecar(app_handle: &tauri::AppHandle, port: u16) -> Option<Child> {
    let args = ["--host", "127.0.0.1", "--port", &port.to_string()];

    // 方式 1：Tauri shell 插件
    match app_handle.shell().sidecar("cizha-backend") {
        Ok(sidecar) => match sidecar.args(args).spawn() {
            Ok((_rx, _child)) => {
                println!("🚀 sidecar 已启动（Tauri shell 方式）");
                // 返回一个 stub Child——真正的 child handle 在 Tauri 内部
                // 我们用 fallback 方式拿可 kill 的 handle
                return None;
            }
            Err(e) => {
                eprintln!("⚠️  Tauri shell sidecar 失败: {}，尝试 fallback", e);
            }
        },
        Err(e) => {
            eprintln!("⚠️  sidecar() 失败: {}，尝试 fallback", e);
        }
    }

    // 方式 2：fallback —— 用 std::process::Command
    // 依次尝试几个可能的路径
    let candidate_paths = [
        // 项目根相对路径（dev 模式，从 src-tauri/ 起）
        "../_pybuild/dist/cizha-backend",
        "_pybuild/dist/cizha-backend",
        // 绝对路径 fallback（如果用户已手动 prepare-sidecar）
        "binaries/cizha-backend",
    ];

    for path in &candidate_paths {
        let mut cmd = StdCommand::new(path);
        cmd.args(["--host", "127.0.0.1", "--port", &port.to_string()])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        match cmd.spawn() {
            Ok(child) => {
                println!("🚀 后端已启动（fallback 方式: {}）", path);

                // stdout/stderr 让子进程自己处理（不转发到 Tauri），
                // 避免 clone stdio 的平台相关 API 问题

                return Some(child);
            }
            Err(e) => {
                eprintln!("  ❌ 路径 {} 启动失败: {}", path, e);
                continue;
            }
        }
    }

    eprintln!("❌ 所有 sidecar 候选路径都尝试失败");
    None
}

/// 探测可用端口：从 start_port 开始逐个 bind，返回第一个成功的
fn find_free_port(start_port: u16) -> Result<u16, std::io::Error> {
    for port in start_port..(start_port + 100) {
        if TcpListener::bind(("127.0.0.1", port)).is_ok() {
            return Ok(port);
        }
    }
    Err(std::io::Error::new(
        std::io::ErrorKind::AddrInUse,
        "找不到可用端口",
    ))
}

/// 等待指定端口变得可连接
fn wait_for_port(
    port: u16,
    max_attempts: u32,
    interval: Duration,
) -> Result<(), std::io::Error> {
    for attempt in 0..max_attempts {
        match TcpListener::bind(("127.0.0.1", port)) {
            Ok(_listener) => {
                // 还没 listen
                drop(_listener);
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::AddrInUse => {
                // 端口已被 listen
                return Ok(());
            }
            Err(e) => return Err(e),
        }
        if attempt < max_attempts - 1 {
            thread::sleep(interval);
        }
    }
    Err(std::io::Error::new(
        std::io::ErrorKind::TimedOut,
        format!("端口 {} 在 {} 次尝试内未就绪", port, max_attempts),
    ))
}
