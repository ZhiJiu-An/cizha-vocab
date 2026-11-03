//! 词札桌面壳层 —— Tauri + PyInstaller 后端
//!
//! 职责：
//!   1. spawn PyInstaller 打包的后端（onedir 产物，随 App 资源一起分发）
//!   2. 用 `--port 0` 让系统分配端口，后端把实际端口写进 ready 文件回传
//!   3. 立即显示 loading 页面，后台探测 /api/health，就绪后再加载前端
//!      —— 启动等待不阻塞 UI；失败时在 loading 页给出提示，而不是白等
//!   4. 托盘图标（右键菜单：打开 / 隐藏 / 退出）
//!   5. 全局快捷键（⌘⇧C 唤起/隐藏窗口，⌥A 输入翻译，⌥S 区域截图取词）
//!   6. 应用退出时终止后端子进程（避免退出后残留后台服务）
//!   7. 启动成功后看护后端：进程崩溃会自动回到启动页并重启

use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU16, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager, RunEvent, Runtime, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use url::Url;

/// 后端可执行文件名（Windows 带 .exe）
const BACKEND_BIN: &str = if cfg!(windows) {
    "cizha-backend.exe"
} else {
    "cizha-backend"
};

/// 等待后端就绪的最长时间。
/// 正常 onedir 启动 1~2 秒足够；留足余量覆盖首次启动的系统磁盘校验。
const READY_TIMEOUT: Duration = Duration::from_secs(30);

/// 启动失败时的自动重试次数（上一次进程未退干净等偶发问题）
const START_ATTEMPTS: u8 = 2;

/// 全局状态：后端子进程 handle + 退出标记 + 后端端口
struct AppState {
    backend: Mutex<Option<Child>>,
    /// 置位后看护线程立即停止，避免退出过程中又把后端拉起来
    stopping: AtomicBool,
    /// 后端实际端口（系统分配），0 表示尚未就绪。快查浮窗的 URL 依赖它
    port: AtomicU16,
    /// 快查浮窗的待处理载荷：新建窗口首帧还没加载完时事件会丢，前端挂载后主动取一次
    quick_pending: Mutex<Option<QuickPayload>>,
}

/// 快查浮窗载荷。`id` 用于前端去重（同一次打开可能既收到事件又取到 pending）
#[derive(Clone, serde::Serialize)]
struct QuickPayload {
    id: u64,
    /// "text" 输入翻译 / "image" 截图取词
    mode: String,
    /// data URL（image/png;base64）
    image: Option<String>,
    error: Option<String>,
}

// 菜单项 ID（托盘菜单）
const MENU_SHOW: &str = "show";
const MENU_HIDE: &str = "hide";
const MENU_QUIT: &str = "quit";

// 快查浮窗标签
const QUICK_LABEL: &str = "quick";

fn main() {
    // 先屏蔽退出信号，再创建任何线程：这样后续线程都继承屏蔽字，
    // 信号只交给 spawn_signal_handler 里的 sigwait 线程处理。
    #[cfg(unix)]
    block_exit_signals();

    tauri::Builder::default()
        // 单实例必须最先注册：第二次启动会把参数转给已有实例后自己退出，
        // 避免出现两个托盘图标、两个后端同时读写同一个 SQLite。
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            toggle_window(app, true);
        }))
        // macOS 会自动提供默认菜单栏（词札 / 文件 / 编辑 / 视图 / 窗口 / 帮助）
        // 已包含 Cmd+Q 退出、Cmd+W 关闭、Cmd+M 最小化 等原生行为
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        // 快查浮窗用的 IPC：取待处理载荷 / 隐藏浮窗 / 把词交给主窗口
        .invoke_handler(tauri::generate_handler![
            quick_get_pending,
            quick_hide,
            open_main_query,
        ])
        // macOS: show 窗口时强制激活（抢回焦点到最前，不管其他 App 是否在最前）
        .activate_ignoring_other_apps(true)
        .setup(|app| {
            app.manage(AppState {
                backend: Mutex::new(None),
                stopping: AtomicBool::new(false),
                port: AtomicU16::new(0),
                quick_pending: Mutex::new(None),
            });

            // 注销 / kill / Ctrl+C 不会触发 RunEvent::Exit，必须自己接管信号，
            // 否则后端会变成孤儿进程继续占着端口。
            #[cfg(unix)]
            spawn_signal_handler(app.handle().clone());

            // 1. 显示窗口。loading 页是 frontend/public/loading.html（窗口初始 URL），
            //    由 WebView 正常加载，不依赖 eval 注入，不会再出现白屏或覆盖竞态。
            let main_window = app
                .get_webview_window("main")
                .ok_or("找不到 main 窗口")?;
            // 窗口在配置里是 visible:false：等 loading 页画出首帧再显示，
            // 否则 WebView 创建瞬间会闪一下白底（启动页是深蓝底）。
            let show_window = main_window.clone();
            thread::spawn(move || {
                thread::sleep(Duration::from_millis(200));
                let _ = show_window.show();
                let _ = show_window.set_focus();
            });

            // 2. 后台启动后端并等待就绪 → 加载前端。
            //    setup 立即返回，loading 动画不被卡住；启动失败会重试一次，
            //    两次都失败才在 loading 页给出可见的错误提示。
            let app_handle = app.handle().clone();
            let window = main_window.clone();
            // 记住启动页地址：后端中途崩溃时用它回到「加载中」，再跳新端口
            let loading_url = main_window.url().ok();
            thread::spawn(move || {
                match start_backend(&app_handle) {
                    Ok(port) => {
                        println!("✅ 后端就绪，监听 http://127.0.0.1:{port}");
                        // 端口要留给快查浮窗拼 URL（浮窗可能在启动后才按需创建）
                        if let Some(state) = app_handle.try_state::<AppState>() {
                            state.port.store(port as u16, Ordering::SeqCst);
                        }
                        match Url::parse(&format!("http://127.0.0.1:{port}/")) {
                            Ok(url) => navigate(&app_handle, &window, url),
                            Err(e) => show_error_on_main(&app_handle, &window, &format!("地址解析失败：{e}")),
                        }
                        // 启动成功后开始看护：后端中途崩溃会自动重启
                        if let Some(url) = loading_url {
                            monitor_backend(app_handle.clone(), window.clone(), url);
                        }
                    }
                    Err(message) => {
                        eprintln!("❌ 后端启动失败: {message}");
                        cleanup_backend(&app_handle);
                        show_error_on_main(&app_handle, &window, &message);
                    }
                }
            });

            // 3. 托盘 + 快捷键马上可用
            setup_tray(app.handle())?;
            setup_shortcuts(app.handle())?;

            Ok(())
        })
        // 托盘菜单事件
        .on_menu_event(|app, event| match event.id().as_ref() {
            MENU_SHOW => toggle_window(app, true),
            MENU_HIDE => toggle_window(app, false),
            MENU_QUIT => {
                mark_stopping(app);
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
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        // Cmd+Q / 托盘退出 / 系统注销都会走到这里：统一 kill 后端
        .run(|app, event| match event {
            RunEvent::Exit => {
                mark_stopping(app);
                cleanup_backend(app);
            }
            // macOS：窗口被关掉（隐藏到托盘）后再点 Dock 图标，要能重新显示
            #[cfg(target_os = "macos")]
            RunEvent::Reopen { .. } => toggle_window(app, true),
            _ => {}
        });
}

/// 在 loading 页展示错误信息。
/// 启动失败可能发生在页面还没加载完时，eval 会被丢弃，所以间隔重试几次。
fn show_error_on_main<R: Runtime>(
    app: &AppHandle<R>,
    window: &tauri::WebviewWindow<R>,
    message: &str,
) {
    let Ok(message_json) = serde_json::to_string(message) else {
        return;
    };
    let script = format!("window.showStartupError && window.showStartupError({message_json});");

    for attempt in 0..10 {
        let window = window.clone();
        let script = script.clone();
        let _ = app.run_on_main_thread(move || {
            let _ = window.eval(script);
        });
        if attempt < 9 {
            thread::sleep(Duration::from_millis(200));
        }
    }
}

/// 启动后端并等待就绪，失败自动重试一次，返回最终可用的端口。
/// 端口由系统分配（`--port 0`），后端启动后把实际端口写进 ready 文件，
/// 彻底避免「先探测空端口再交给后端 bind」的竞态。
fn start_backend<R: Runtime>(app: &AppHandle<R>) -> Result<u16, String> {
    let mut last_error = String::from("未知错误");

    for attempt in 1..=START_ATTEMPTS {
        let ready_file = ready_file_path(attempt);
        let _ = std::fs::remove_file(&ready_file);
        println!("🔌 第 {attempt} 次启动（端口由系统分配）");

        let Some(child) = spawn_backend(app, &ready_file) else {
            return Err("找不到或无法启动本地服务程序（cizha-backend），请重新安装词札。".into());
        };
        if let Some(state) = app.try_state::<AppState>() {
            *state.backend.lock().unwrap() = Some(child);
        }

        println!("⏳ 等待后端启动...");
        match wait_for_backend(app, &ready_file) {
            Ok(port) => {
                let _ = std::fs::remove_file(&ready_file);
                return Ok(port);
            }
            Err(message) => {
                eprintln!("⚠️  第 {attempt} 次启动失败: {message}");
                // 先杀掉失败进程，避免它继续占着端口影响重试
                cleanup_backend(app);
                last_error = message;
            }
        }
    }

    Err(last_error)
}

/// watchdog：启动成功后每 2 秒确认后端还活着，崩了就回启动页并自动重启
fn monitor_backend<R: Runtime>(
    app: AppHandle<R>,
    window: tauri::WebviewWindow<R>,
    loading_url: Url,
) {
    thread::spawn(move || loop {
        thread::sleep(Duration::from_secs(2));
        if is_stopping(&app) {
            break;
        }
        if !backend_exited(&app) {
            continue;
        }

        eprintln!("⚠️  后端进程已退出，正在自动重启");
        navigate(&app, &window, loading_url.clone());
        match start_backend(&app) {
            Ok(port) => {
                println!("✅ 后端已重启，监听 http://127.0.0.1:{port}");
                if let Some(state) = app.try_state::<AppState>() {
                    state.port.store(port as u16, Ordering::SeqCst);
                }
                match Url::parse(&format!("http://127.0.0.1:{port}/")) {
                    Ok(url) => navigate(&app, &window, url),
                    Err(e) => show_error_on_main(&app, &window, &format!("地址解析失败：{e}")),
                }
                // 快查浮窗若已创建，也要跟到新端口，否则它下次打开会白屏
                if let Some(quick) = app.get_webview_window(QUICK_LABEL) {
                    if let Ok(url) = Url::parse(&format!("http://127.0.0.1:{port}/quick")) {
                        navigate_with(&app, &quick, url, false);
                    }
                }
            }
            Err(message) => {
                eprintln!("❌ 后端重启失败: {message}");
                cleanup_backend(&app);
                show_error_on_main(&app, &window, &message);
                // 失败后放慢节奏，避免每 2 秒刷一次错误提示
                thread::sleep(Duration::from_secs(20));
            }
        }
    });
}

/// 在主线程导航；导航失败时把原因写回启动页，而不是静默停在 loading
fn navigate<R: Runtime>(app: &AppHandle<R>, window: &tauri::WebviewWindow<R>, url: Url) {
    navigate_with(app, window, url, true);
}

/// `focus=false` 用于隐藏的快查浮窗：只换地址，不抢用户焦点
fn navigate_with<R: Runtime>(
    app: &AppHandle<R>,
    window: &tauri::WebviewWindow<R>,
    url: Url,
    focus: bool,
) {
    let window = window.clone();
    let _ = app.run_on_main_thread(move || {
        if let Err(e) = window.navigate(url) {
            let message = serde_json::to_string(&format!("页面加载失败：{e}")).unwrap_or_default();
            let _ = window.eval(format!(
                "window.showStartupError && window.showStartupError({message});"
            ));
        } else if focus {
            let _ = window.set_focus();
        }
    });
}

/// 退出流程开始后置位，看护线程看到就停
fn mark_stopping<R: Runtime>(app: &AppHandle<R>) {
    if let Some(state) = app.try_state::<AppState>() {
        state.stopping.store(true, Ordering::Relaxed);
    }
}

fn is_stopping<R: Runtime>(app: &AppHandle<R>) -> bool {
    app.try_state::<AppState>()
        .map(|state| state.stopping.load(Ordering::Relaxed))
        .unwrap_or(true)
}

/// 每次启动用一个独立的 ready 文件，避免读到上一次的残留端口
fn ready_file_path(attempt: u8) -> PathBuf {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    std::env::temp_dir().join(format!(
        "cizha-backend-{}-{attempt}-{nanos}.port",
        std::process::id()
    ))
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

/// 注册全局快捷键：
///   ⌘⇧C 唤起/隐藏主窗口
///   ⌥A   输入翻译（弹出快查浮窗）
///   ⌥S   区域截图取词（调 macOS 自带 screencapture）
fn setup_shortcuts<R: Runtime>(app: &AppHandle<R>) -> Result<(), Box<dyn std::error::Error>> {
    // Modifiers::SUPER = Cmd on macOS，ALT = Option
    register_shortcut(app, Modifiers::SUPER | Modifiers::SHIFT, Code::KeyC, "⌘⇧C 唤起主窗口", |app, _| {
        toggle_window(app, !is_window_visible(app));
    });
    register_shortcut(app, Modifiers::ALT, Code::KeyA, "⌥A 输入翻译", |app, _| {
        open_quick_text(app);
    });
    register_shortcut(app, Modifiers::ALT, Code::KeyS, "⌥S 截图取词", |app, _| {
        open_quick_shot(app);
    });
    Ok(())
}

/// 单个快捷键注册失败（组合被其他应用占用）不应拖垮启动，只记日志
fn register_shortcut<R, F>(app: &AppHandle<R>, modifiers: Modifiers, code: Code, label: &str, handler: F)
where
    R: Runtime,
    F: Fn(&AppHandle<R>, &Shortcut) + Send + Sync + 'static,
{
    let shortcut = Shortcut::new(Some(modifiers), code);
    match app.global_shortcut().on_shortcut(shortcut, move |app, shortcut, event| {
        if event.state == ShortcutState::Pressed {
            handler(app, shortcut);
        }
    }) {
        Ok(()) => println!("⌨️  已注册全局快捷键 {label}"),
        Err(e) => eprintln!("⚠️  注册全局快捷键 {label} 失败（组合可能已被其他应用占用）: {e}"),
    }
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

/// 后端实际端口；0 表示启动流程还没跑完
fn current_port<R: Runtime>(app: &AppHandle<R>) -> Option<u16> {
    app.try_state::<AppState>()
        .map(|state| state.port.load(Ordering::SeqCst))
        .filter(|port| *port > 0)
}

/// 按需创建快查浮窗（隐藏状态）。后端未就绪时返回 None，浮窗打不开是预期行为
fn ensure_quick_window<R: Runtime>(app: &AppHandle<R>) -> Option<WebviewWindow<R>> {
    if let Some(window) = app.get_webview_window(QUICK_LABEL) {
        return Some(window);
    }
    let port = current_port(app)?;
    let url = Url::parse(&format!("http://127.0.0.1:{port}/quick")).ok()?;
    match WebviewWindowBuilder::new(app, QUICK_LABEL, WebviewUrl::External(url))
        .title("词札 · 快查")
        .inner_size(460.0, 360.0)
        .resizable(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .visible(false)
        .build()
    {
        Ok(window) => Some(window),
        Err(e) => {
            eprintln!("⚠️  快查浮窗创建失败: {e}");
            None
        }
    }
}

/// 显示浮窗并投递载荷。
/// 新建窗口时首帧还没加载完，事件可能丢失 —— 先存进 pending，前端挂载后自己取。
/// 窗口创建统一回主线程：从快捷键/截图线程直接建窗在 macOS 上会卡死。
fn show_quick<R: Runtime>(app: &AppHandle<R>, payload: QuickPayload) {
    let existed = app.get_webview_window(QUICK_LABEL).is_some();
    if let Some(state) = app.try_state::<AppState>() {
        if let Ok(mut pending) = state.quick_pending.lock() {
            *pending = if existed { None } else { Some(payload.clone()) };
        }
    }
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        let Some(window) = ensure_quick_window(&handle) else {
            eprintln!("⚠️  快查浮窗不可用（后端可能还没就绪）");
            return;
        };
        let _ = window.show();
        let _ = window.set_focus();
        let _ = handle.emit_to(QUICK_LABEL, "quick-open", payload);
    });
}

fn next_payload_id() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0)
}

fn open_quick_text<R: Runtime>(app: &AppHandle<R>) {
    show_quick(
        app,
        QuickPayload {
            id: next_payload_id(),
            mode: "text".into(),
            image: None,
            error: None,
        },
    );
}

/// 截图是阻塞操作（用户在框选），不能卡住快捷键回调线程
fn open_quick_shot<R: Runtime>(app: &AppHandle<R>) {
    let app = app.clone();
    thread::spawn(move || {
        // 浮窗若已在屏幕上，先藏起来，避免把自己截进去
        if let Some(window) = app.get_webview_window(QUICK_LABEL) {
            let _ = window.hide();
        }
        thread::sleep(Duration::from_millis(120));

        let payload = match capture_region() {
            Ok(Some(image)) => QuickPayload {
                id: next_payload_id(),
                mode: "image".into(),
                image: Some(image),
                error: None,
            },
            // 用户按 Esc 取消，安静收场
            Ok(None) => return,
            Err(message) => QuickPayload {
                id: next_payload_id(),
                mode: "text".into(),
                image: None,
                error: Some(format!("截图失败：{message}")),
            },
        };
        show_quick(&app, payload);
    });
}

/// 调系统自带 screencapture 做区域截图，返回 data URL；Ok(None) = 用户取消。
/// 首次使用会要求「屏幕录制」权限，被拒时 stderr 有内容，原样带回前端提示。
#[cfg(target_os = "macos")]
fn capture_region() -> Result<Option<String>, String> {
    use base64::Engine;

    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let path = std::env::temp_dir().join(format!("cizha-shot-{nanos}.png"));

    let output = Command::new("/usr/sbin/screencapture")
        .args(["-i", "-x", "-o", "-t", "png"])
        .arg(&path)
        .output()
        .map_err(|e| format!("无法启动系统截图：{e}"))?;

    if !output.status.success() {
        let _ = std::fs::remove_file(&path);
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return if stderr.is_empty() { Ok(None) } else { Err(stderr) };
    }

    let bytes = std::fs::read(&path).map_err(|e| format!("读取截图失败：{e}"));
    let _ = std::fs::remove_file(&path);
    let bytes = bytes?;
    if bytes.is_empty() {
        return Ok(None);
    }
    Ok(Some(format!(
        "data:image/png;base64,{}",
        base64::engine::general_purpose::STANDARD.encode(bytes)
    )))
}

#[cfg(not(target_os = "macos"))]
fn capture_region() -> Result<Option<String>, String> {
    Err("截图取词目前仅支持 macOS".into())
}

/// 前端挂载后主动取一次（新建窗口时事件可能比页面加载更早）
#[tauri::command]
fn quick_get_pending(state: tauri::State<'_, AppState>) -> Option<QuickPayload> {
    state.quick_pending.lock().ok().and_then(|mut pending| pending.take())
}

#[tauri::command]
fn quick_hide(app: tauri::AppHandle) {
    if let Some(window) = app.get_webview_window(QUICK_LABEL) {
        let _ = window.hide();
    }
}

/// 把词交给主窗口的词典页（/?q=xxx），复用完整的双栏结果
#[tauri::command]
fn open_main_query(app: tauri::AppHandle, word: String) -> Result<(), String> {
    let word = word.trim().to_string();
    if word.is_empty() {
        return Err("单词不能为空".into());
    }
    let port = current_port(&app).ok_or("后端尚未就绪")?;
    let main = app.get_webview_window("main").ok_or("找不到主窗口")?;
    let mut url =
        Url::parse(&format!("http://127.0.0.1:{port}/")).map_err(|e| e.to_string())?;
    url.query_pairs_mut().append_pair("q", &word);
    let _ = main.show();
    navigate(&app, &main, url);
    if let Some(window) = app.get_webview_window(QUICK_LABEL) {
        let _ = window.hide();
    }
    Ok(())
}

fn cleanup_backend<R: Runtime>(app: &AppHandle<R>) {
    if let Some(state) = app.try_state::<AppState>() {
        if let Ok(mut backend) = state.backend.lock() {
            if let Some(mut child) = backend.take() {
                terminate_child(&mut child);
                println!("🧹 后端进程已清理");
            }
        }
    }
}

/// 先 SIGTERM 让 uvicorn / SQLite 正常收尾，3 秒内没退出再 SIGKILL。
/// 直接 kill 会跳过关闭流程，极端情况下可能丢最后一次写入。
fn terminate_child(child: &mut Child) {
    // 进程可能已被 try_wait 回收：此时 pid 可能被系统复用，绝不能再发信号
    if matches!(child.try_wait(), Ok(Some(_))) {
        return;
    }

    #[cfg(unix)]
    unsafe {
        libc::kill(child.id() as libc::pid_t, libc::SIGTERM);
    }
    #[cfg(not(unix))]
    {
        let _ = child.kill();
    }

    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        match child.try_wait() {
            Ok(Some(_)) => return,
            Ok(None) => {}
            Err(_) => break,
        }
        if Instant::now() >= deadline {
            break;
        }
        thread::sleep(Duration::from_millis(50));
    }

    let _ = child.kill();
    let _ = child.wait();
}

/// 提前屏蔽退出信号（必须在任何线程创建之前调用）。
/// 后续创建的线程都会继承该屏蔽字，信号只会被 sigwait 线程取走。
#[cfg(unix)]
fn block_exit_signals() {
    unsafe {
        let mut set: libc::sigset_t = std::mem::zeroed();
        libc::sigemptyset(&mut set);
        libc::sigaddset(&mut set, libc::SIGTERM);
        libc::sigaddset(&mut set, libc::SIGINT);
        libc::sigaddset(&mut set, libc::SIGHUP);
        libc::pthread_sigmask(libc::SIG_BLOCK, &set, std::ptr::null_mut());
    }
}

/// 专用线程等待退出信号：注销 / kill / Ctrl+C 时先清理后端再退出。
/// 用 sigwait 而不是信号回调，是为了能安全地拿 Mutex 和调用 Tauri API。
#[cfg(unix)]
fn spawn_signal_handler<R: Runtime>(app: AppHandle<R>) {
    thread::spawn(move || {
        let mut set: libc::sigset_t = unsafe { std::mem::zeroed() };
        unsafe {
            libc::sigemptyset(&mut set);
            libc::sigaddset(&mut set, libc::SIGTERM);
            libc::sigaddset(&mut set, libc::SIGINT);
            libc::sigaddset(&mut set, libc::SIGHUP);
        }

        loop {
            let mut sig: libc::c_int = 0;
            if unsafe { libc::sigwait(&set, &mut sig) } != 0 {
                break;
            }
            eprintln!("⚠️  收到退出信号 {sig}，清理后端进程后退出");
            mark_stopping(&app);
            cleanup_backend(&app);
            app.exit(0);
            break;
        }
    });
}

/// 后端日志路径：macOS = ~/Library/Logs/<bundle id>/backend.log
fn backend_log_path<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    let dir = app.path().app_log_dir().ok()?;
    std::fs::create_dir_all(&dir).ok()?;
    Some(dir.join("backend.log"))
}

/// 打开后端日志（追加写，超过 5MB 轮转一份 .1）
fn open_backend_log<R: Runtime>(app: &AppHandle<R>) -> Option<File> {
    let path = backend_log_path(app)?;
    if let Ok(meta) = std::fs::metadata(&path) {
        if meta.len() > 5 * 1024 * 1024 {
            let _ = std::fs::rename(&path, path.with_extension("log.1"));
        }
    }
    OpenOptions::new().create(true).append(true).open(&path).ok()
}

/// 解析后端可执行文件路径。
///
/// 打包后：Contents/Resources/backend/cizha-backend（onedir 目录，避免每次启动解压）
/// 开发时：依次尝试 resources/ 副本和 PyInstaller 输出目录
fn backend_executable<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    let mut candidates = Vec::new();

    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join("backend").join(BACKEND_BIN));
    }

    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    candidates.push(manifest.join("resources").join("backend").join(BACKEND_BIN));
    candidates.push(
        manifest
            .join("..")
            .join("dist")
            .join("cizha-backend")
            .join(BACKEND_BIN),
    );
    candidates.push(
        manifest
            .join("..")
            .join("_pybuild")
            .join("dist")
            .join("cizha-backend")
            .join(BACKEND_BIN),
    );

    candidates.into_iter().find(|path| path.is_file())
}

/// spawn 后端进程：端口交给系统分配，启动完成后写入 ready 文件
fn spawn_backend<R: Runtime>(app: &AppHandle<R>, ready_file: &Path) -> Option<Child> {
    let path = match backend_executable(app) {
        Some(path) => path,
        None => {
            eprintln!("❌ 找不到后端可执行文件（resource_dir / dist / _pybuild 都没有）");
            return None;
        }
    };

    let mut cmd = Command::new(&path);
    cmd.args(["--host", "127.0.0.1", "--port", "0"])
        .arg("--ready-file")
        .arg(ready_file)
        .stdin(Stdio::null());

    // 输出落到日志文件：接 pipe 会因缓冲区写满把后端卡死，直接丢弃又没法排查。
    match open_backend_log(app) {
        Some(mut log) => {
            let _ = writeln!(log, "\n===== 启动后端（端口由系统分配）=====");
            match log.try_clone() {
                Ok(err_log) => {
                    cmd.stdout(Stdio::from(log));
                    cmd.stderr(Stdio::from(err_log));
                }
                Err(_) => {
                    cmd.stdout(Stdio::from(log));
                    cmd.stderr(Stdio::null());
                }
            }
        }
        None => {
            cmd.stdout(Stdio::null());
            cmd.stderr(Stdio::null());
        }
    }

    // 子进程会继承父进程的信号屏蔽字。main 里屏蔽了 SIGTERM 等信号，
    // 若不清空，后端就收不到 SIGTERM、永远无法优雅退出。
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        unsafe {
            cmd.pre_exec(|| {
                let mut empty: libc::sigset_t = std::mem::zeroed();
                libc::sigemptyset(&mut empty);
                libc::sigprocmask(libc::SIG_SETMASK, &empty, std::ptr::null_mut());
                Ok(())
            });
        }
    }

    match cmd.spawn() {
        Ok(child) => {
            println!("🚀 后端已启动: {}", path.display());
            Some(child)
        }
        Err(e) => {
            eprintln!("❌ 后端启动失败 {}: {}", path.display(), e);
            None
        }
    }
}

/// 等待后端真正可用：先从 ready 文件拿实际端口，再轮询 /api/health
fn wait_for_backend<R: Runtime>(app: &AppHandle<R>, ready_file: &Path) -> Result<u16, String> {
    let deadline = Instant::now() + READY_TIMEOUT;
    let log_hint = backend_log_path(app)
        .map(|path| format!("日志：{}", path.display()))
        .unwrap_or_else(|| "日志文件创建失败".to_string());

    loop {
        if let Some(port) = read_ready_port(ready_file) {
            if backend_health_ok(port) {
                return Ok(port);
            }
        }
        if backend_exited(app) {
            return Err(format!("本地服务进程已退出，具体原因见日志。{log_hint}"));
        }
        if Instant::now() >= deadline {
            return Err(format!(
                "本地服务在 {} 秒内没有启动。{log_hint}",
                READY_TIMEOUT.as_secs()
            ));
        }
        thread::sleep(Duration::from_millis(150));
    }
}

/// 读取后端回传的实际监听端口
fn read_ready_port(path: &Path) -> Option<u16> {
    std::fs::read_to_string(path).ok()?.trim().parse().ok()
}

/// 后端子进程是否已经退出
fn backend_exited<R: Runtime>(app: &AppHandle<R>) -> bool {
    let Some(state) = app.try_state::<AppState>() else {
        return true;
    };
    let Ok(mut backend) = state.backend.lock() else {
        return false;
    };
    match backend.as_mut() {
        Some(child) => matches!(child.try_wait(), Ok(Some(_))),
        None => true,
    }
}

/// 通过 HTTP GET /api/health 判断服务是否已就绪
fn backend_health_ok(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(400)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(800)));
    let request =
        format!("GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut buf = [0u8; 64];
    match stream.read(&mut buf) {
        Ok(n) if n > 8 => buf[..n].starts_with(b"HTTP/1.1 200"),
        _ => false,
    }
}

