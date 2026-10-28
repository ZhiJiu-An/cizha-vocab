//! 词札桌面壳层 —— Tauri + PyInstaller sidecar
//!
//! 职责：
//!   1. spawn PyInstaller 打包的后端二进制做 sidecar 子进程
//!   2. 探测可用端口 → 传 --port 给后端
//!   3. 等待后端就绪 → 创建 WebView 窗口加载 http://127.0.0.1:{port}/
//!   4. 托盘图标（右键菜单：打开 / 隐藏 / 退出）
//!   5. 全局快捷键（Cmd+Shift+C 唤起/隐藏窗口）
//!   6. 应用退出时 kill sidecar 子进程

use std::net::TcpListener;
use std::process::{Child, Command as StdCommand, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager, Runtime,
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use tauri_plugin_shell::ShellExt;
use url::Url;

/// 全局状态：保存 sidecar 子进程 handle
#[allow(dead_code)]
struct AppState {
    port: Mutex<u16>,
    backend: Mutex<Option<Child>>,
}

// 菜单项 ID
const MENU_SHOW: &str = "show";
const MENU_HIDE: &str = "hide";
const MENU_QUIT: &str = "quit";

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .setup(|app| {
            // 1. 探测可用端口（从 18765 开始，避免常见端口）
            let port = find_free_port(18765).expect("找不到可用端口");
            println!("🔌 分配端口: {}", port);

            // 存入全局状态
            app.manage(AppState {
                port: Mutex::new(port),
                backend: Mutex::new(None),
            });

            // 2. spawn sidecar
            let backend_child = spawn_backend_sidecar(app.handle(), port);

            // 3. 等待后端就绪
            println!("⏳ 等待后端启动...");
            if let Err(e) = wait_for_port(port, 15, Duration::from_millis(500)) {
                eprintln!("❌ 后端启动失败: {}", e);
                return Err(Box::new(e));
            }
            thread::sleep(Duration::from_millis(1500));
            println!("✅ 后端就绪，监听 http://127.0.0.1:{}", port);

            // 4. 保存 child handle 到状态
            if let Some(state) = app.try_state::<AppState>() {
                *state.backend.lock().unwrap() = backend_child;
            }

            // 5. 创建主窗口（初始 hidden，等后端 ready 再显示）
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

            // 6. 创建托盘图标
            setup_tray(app.handle())?;

            // 7. 注册全局快捷键 Cmd+Shift+C
            setup_shortcuts(app.handle())?;

            Ok(())
        })
        // 托盘菜单事件
        .on_menu_event(|app, event| match event.id().as_ref() {
            MENU_SHOW => toggle_window(app, true),
            MENU_HIDE => toggle_window(app, false),
            MENU_QUIT => {
                cleanup_backend(app);
                app.exit(0);
            }
            _ => {}
        })
        // 关闭窗口 = 隐藏到托盘（不退出）
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
                println!("📥 窗口已隐藏到托盘");
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// 创建系统托盘（菜单 + 左键切换）
fn setup_tray<R: Runtime>(app: &AppHandle<R>) -> Result<(), Box<dyn std::error::Error>> {
    let show_item = MenuItem::with_id(app, MENU_SHOW, "打开词札", true, None::<&str>)?;
    let hide_item = MenuItem::with_id(app, MENU_HIDE, "隐藏窗口", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, MENU_QUIT, "退出", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show_item, &hide_item, &quit_item])?;

    let _tray = TrayIconBuilder::with_id("main-tray")
        .tooltip("词札 - Cizha Vocab")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle();
                if let Some(window) = app.get_webview_window("main") {
                    let _ = if window.is_visible().unwrap_or(false) {
                        window.hide()
                    } else {
                        window.show().and_then(|_| window.set_focus())
                    };
                }
            }
        })
        .build(app)?;

    println!("🔔 托盘图标已创建");
    Ok(())
}

/// 注册全局快捷键 Cmd+Shift+C（唤起/隐藏窗口）
fn setup_shortcuts<R: Runtime>(app: &AppHandle<R>) -> Result<(), Box<dyn std::error::Error>> {
    // Cmd+Shift+C: Modifiers::SUPER = Cmd on macOS
    let shortcut = Shortcut::new(
        Some(Modifiers::SUPER | Modifiers::SHIFT),
        Code::KeyC,
    );

    app.global_shortcut().on_shortcut(
        shortcut,
        |app, _shortcut, event| {
            if event.state == ShortcutState::Pressed {
                toggle_window(app, !is_window_visible(app));
            }
        },
    )?;

    println!("⌨️  全局快捷键 Cmd+Shift+C 已注册");
    Ok(())
}

fn is_window_visible<R: Runtime>(app: &AppHandle<R>) -> bool {
    app.get_webview_window("main")
        .and_then(|w| w.is_visible().ok())
        .unwrap_or(false)
}

fn toggle_window<R: Runtime>(app: &AppHandle<R>, show: bool) {
    if let Some(window) = app.get_webview_window("main") {
        if show {
            let _ = window.show().and_then(|_| window.set_focus());
            println!("📤 窗口已显示");
        } else {
            let _ = window.hide();
            println!("📥 窗口已隐藏");
        }
    }
}

fn cleanup_backend<R: Runtime>(app: &AppHandle<R>) {
    if let Some(state) = app.try_state::<AppState>() {
        if let Ok(mut backend) = state.backend.lock() {
            if let Some(mut child) = backend.take() {
                let _ = child.kill();
                let _ = child.wait();
                println!("🧹 sidecar 已清理");
            }
        }
    }
}

// ========== 以下为原有辅助函数，未改 ==========

/// spawn sidecar 二进制
fn spawn_backend_sidecar(app_handle: &tauri::AppHandle, port: u16) -> Option<Child> {
    let args = ["--host", "127.0.0.1", "--port", &port.to_string()];

    // 方式 1：Tauri shell 插件
    match app_handle.shell().sidecar("cizha-backend") {
        Ok(sidecar) => match sidecar.args(args).spawn() {
            Ok((_rx, _child)) => {
                println!("🚀 sidecar 已启动（Tauri shell 方式）");
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
    let candidate_paths = [
        "../_pybuild/dist/cizha-backend",
        "_pybuild/dist/cizha-backend",
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
                drop(_listener);
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::AddrInUse => {
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
