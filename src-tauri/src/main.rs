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

use std::collections::HashMap;
use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicI32, AtomicU16, AtomicU64, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager, RunEvent, Runtime, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};
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
    /// 全局快捷键：id -> 当前绑定（accelerator 为空表示禁用）
    shortcuts: Mutex<HashMap<String, ShortcutBinding>>,
}

/// 全局快捷键定义：id / 展示名 / 默认 accelerator（Tauri 语法，见 shortcuts.json）
const GLOBAL_SHORTCUTS: [(&str, &str, &str); 3] = [
    ("toggle_window", "唤起 / 隐藏主窗口", "CmdOrCtrl+Shift+KeyC"),
    ("quick_text", "输入翻译", "Alt+KeyA"),
    ("quick_shot", "截图取词", "Alt+KeyS"),
];

#[derive(Clone)]
struct ShortcutBinding {
    accelerator: String,
    registered: bool,
    error: String,
}

#[derive(Clone, serde::Serialize)]
struct GlobalShortcutInfo {
    id: String,
    label: String,
    accelerator: String,
    registered: bool,
    error: String,
}

/// shortcuts.json 的结构。只存 accelerator，动作 id 与标签固定在这里
#[derive(serde::Serialize, serde::Deserialize, Default)]
struct ShortcutFile {
    #[serde(default)]
    shortcuts: HashMap<String, String>,
}

/// 快查浮窗载荷。`id` 用于前端去重（同一次打开可能既收到事件又取到 pending）
#[derive(Clone, serde::Serialize)]
struct QuickPayload {
    id: u64,
    /// "text" 输入翻译 / "image" 截图取词
    mode: String,
    /// data URL（image/png;base64）
    image: Option<String>,
    /// 原生 OCR 识别出的文字（有值时前端直接填入输入框，不再上传图片）
    text: Option<String>,
    error: Option<String>,
    /// 缺少「屏幕录制」权限：前端据此展示「打开系统设置」按钮
    needs_permission: bool,
}

// 菜单项 ID（托盘菜单）
const MENU_SHOW: &str = "show";
const MENU_HIDE: &str = "hide";
const MENU_QUIT: &str = "quit";

// 快查浮窗标签
const QUICK_LABEL: &str = "quick";
// 截图选区浮层标签
const SHOT_LABEL: &str = "shot";

/// 选区层无操作后由壳层兜底关闭的时限。
/// 防止页面脚本失效时全屏置顶窗口无限期遮挡桌面。
const SHOT_TIMEOUT: Duration = Duration::from_secs(60);

/// 选区层代次：每次显示递增，旧的超时看护据此判断自己是否已过期。
static SHOT_EPOCH: AtomicU64 = AtomicU64::new(0);

/// 唤起截图前的前台应用 PID；取消选区后把焦点还回去，
/// 避免词札被激活后把主窗口顶到最前面。
static PREV_FRONTMOST_PID: AtomicI32 = AtomicI32::new(0);

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
            get_global_shortcuts,
            set_global_shortcut,
            reset_global_shortcuts,
            open_screen_recording_settings,
            finish_region_shot,
            cancel_region_shot,
        ])
        // macOS: show 窗口时强制激活（抢回焦点到最前，不管其他 App 是否在最前）
        .activate_ignoring_other_apps(true)
        .setup(|app| {
            app.manage(AppState {
                backend: Mutex::new(None),
                stopping: AtomicBool::new(false),
                port: AtomicU16::new(0),
                quick_pending: Mutex::new(None),
                shortcuts: Mutex::new(HashMap::new()),
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
            RunEvent::Reopen { .. } => {
                log_wins(app, "Reopen");
                toggle_window(app, true);
            }
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

/// 启动时读取 shortcuts.json 并注册全局快捷键。
/// 单个组合被其他应用占用不拖垮启动：状态与错误记进 AppState，设置页会展示。
fn setup_shortcuts<R: Runtime>(app: &AppHandle<R>) -> Result<(), Box<dyn std::error::Error>> {
    let config = load_shortcut_config(app);
    let mut bindings = HashMap::new();
    for (id, label, _) in GLOBAL_SHORTCUTS {
        let accelerator = config.get(id).cloned().unwrap_or_default();
        let (registered, error) = match register_binding(app, id, &accelerator) {
            Ok(()) => (!accelerator.is_empty(), String::new()),
            Err(e) => {
                eprintln!("⚠️  注册全局快捷键「{label}」失败: {e}");
                (false, e)
            }
        };
        if registered {
            println!("⌨️  已注册全局快捷键「{label}」 {accelerator}");
        }
        bindings.insert(
            id.to_string(),
            ShortcutBinding { accelerator, registered, error },
        );
    }
    if let Some(state) = app.try_state::<AppState>() {
        if let Ok(mut guard) = state.shortcuts.lock() {
            *guard = bindings;
        }
    }
    Ok(())
}

fn shortcut_file_path<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    app.path()
        .app_config_dir()
        .ok()
        .map(|dir| dir.join("shortcuts.json"))
}

/// 默认值打底，再用 shortcuts.json 覆盖；文件损坏时退回默认，不影响启动
fn load_shortcut_config<R: Runtime>(app: &AppHandle<R>) -> HashMap<String, String> {
    let mut config: HashMap<String, String> = GLOBAL_SHORTCUTS
        .iter()
        .map(|(id, _, accelerator)| ((*id).to_string(), (*accelerator).to_string()))
        .collect();
    let Some(path) = shortcut_file_path(app) else {
        return config;
    };
    let Ok(text) = std::fs::read_to_string(&path) else {
        return config;
    };
    let Ok(file) = serde_json::from_str::<ShortcutFile>(&text) else {
        eprintln!("⚠️  shortcuts.json 解析失败，使用默认快捷键");
        return config;
    };
    for (id, accelerator) in file.shortcuts {
        if config.contains_key(&id) {
            config.insert(id, accelerator);
        }
    }
    config
}

fn save_shortcut_config<R: Runtime>(
    app: &AppHandle<R>,
    config: &HashMap<String, String>,
) -> Result<(), String> {
    let path = shortcut_file_path(app).ok_or("找不到应用配置目录")?;
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| format!("创建配置目录失败：{e}"))?;
    }
    let file = ShortcutFile { shortcuts: config.clone() };
    let text = serde_json::to_string_pretty(&file).map_err(|e| format!("序列化快捷键失败：{e}"))?;
    std::fs::write(&path, text).map_err(|e| format!("写入 shortcuts.json 失败：{e}"))
}

fn shortcut_label(id: &str) -> String {
    GLOBAL_SHORTCUTS
        .iter()
        .find(|(key, _, _)| *key == id)
        .map(|(_, label, _)| (*label).to_string())
        .unwrap_or_else(|| id.to_string())
}

/// 注册单个全局快捷键；空 accelerator 表示禁用，不注册
fn register_binding<R: Runtime>(
    app: &AppHandle<R>,
    id: &str,
    accelerator: &str,
) -> Result<(), String> {
    let accelerator = accelerator.trim();
    if accelerator.is_empty() {
        return Ok(());
    }
    let shortcut: Shortcut = accelerator
        .parse()
        .map_err(|_| format!("无法识别的快捷键：{accelerator}"))?;
    let action = id.to_string();
    app.global_shortcut()
        .on_shortcut(shortcut, move |app, _shortcut, event| {
            if event.state != ShortcutState::Pressed {
                return;
            }
            match action.as_str() {
                "toggle_window" => toggle_window(app, !is_window_visible(app)),
                "quick_text" => open_quick_text(app),
                "quick_shot" => open_quick_shot(app),
                _ => {}
            }
        })
        .map_err(|e| format!("注册失败（组合可能已被其他应用占用）：{e}"))
}

fn unregister_binding<R: Runtime>(app: &AppHandle<R>, accelerator: &str) -> Result<(), String> {
    let accelerator = accelerator.trim();
    if accelerator.is_empty() {
        return Ok(());
    }
    let shortcut: Shortcut = accelerator
        .parse()
        .map_err(|_| format!("无法识别的快捷键：{accelerator}"))?;
    app.global_shortcut()
        .unregister(shortcut)
        .map_err(|e| format!("解除注册失败：{e}"))
}

fn collect_shortcut_infos(bindings: &HashMap<String, ShortcutBinding>) -> Vec<GlobalShortcutInfo> {
    GLOBAL_SHORTCUTS
        .iter()
        .map(|(id, label, _)| {
            let binding = bindings.get(*id);
            GlobalShortcutInfo {
                id: (*id).to_string(),
                label: (*label).to_string(),
                accelerator: binding.map(|b| b.accelerator.clone()).unwrap_or_default(),
                registered: binding.map(|b| b.registered).unwrap_or(false),
                error: binding.map(|b| b.error.clone()).unwrap_or_default(),
            }
        })
        .collect()
}

#[tauri::command]
fn get_global_shortcuts(state: tauri::State<'_, AppState>) -> Vec<GlobalShortcutInfo> {
    match state.shortcuts.lock() {
        Ok(guard) => collect_shortcut_infos(&guard),
        Err(_) => Vec::new(),
    }
}

/// 改绑：先解旧键 → 注册新键（失败则恢复旧键）→ 落盘。
/// 空 accelerator 表示禁用该动作。
#[tauri::command]
fn set_global_shortcut(
    app: AppHandle,
    state: tauri::State<'_, AppState>,
    id: String,
    accelerator: String,
) -> Result<GlobalShortcutInfo, String> {
    let Some((_, label, _)) = GLOBAL_SHORTCUTS.iter().find(|(key, _, _)| *key == id) else {
        return Err("未知的快捷键".to_string());
    };
    let accelerator = accelerator.trim().to_string();

    let (old_accelerator, old_registered) = {
        let guard = state.shortcuts.lock().map_err(|_| "快捷键状态被占用")?;
        let binding = guard.get(&id);
        (
            binding.map(|b| b.accelerator.clone()).unwrap_or_default(),
            binding.map(|b| b.registered).unwrap_or(false),
        )
    };

    if !accelerator.is_empty() {
        let _: Shortcut = accelerator
            .parse()
            .map_err(|_| "快捷键格式不正确".to_string())?;
        let guard = state.shortcuts.lock().map_err(|_| "快捷键状态被占用")?;
        for (other_id, binding) in guard.iter() {
            if other_id != &id && binding.accelerator == accelerator {
                return Err(format!("与「{}」冲突", shortcut_label(other_id)));
            }
        }
    }

    if old_registered && !old_accelerator.is_empty() {
        let _ = unregister_binding(&app, &old_accelerator);
    }

    if let Err(e) = register_binding(&app, &id, &accelerator) {
        // 新键注册失败：把旧键装回去，避免用户既没新键也没旧键
        if old_registered && !old_accelerator.is_empty() {
            let _ = register_binding(&app, &id, &old_accelerator);
        }
        return Err(e);
    }

    let mut config = load_shortcut_config(&app);
    config.insert(id.clone(), accelerator.clone());
    if let Err(e) = save_shortcut_config(&app, &config) {
        let _ = unregister_binding(&app, &accelerator);
        if old_registered && !old_accelerator.is_empty() {
            let _ = register_binding(&app, &id, &old_accelerator);
        }
        return Err(e);
    }

    let registered = !accelerator.is_empty();
    if let Ok(mut guard) = state.shortcuts.lock() {
        guard.insert(
            id.clone(),
            ShortcutBinding { accelerator: accelerator.clone(), registered, error: String::new() },
        );
    }
    Ok(GlobalShortcutInfo {
        id,
        label: (*label).to_string(),
        accelerator,
        registered,
        error: String::new(),
    })
}

/// 恢复默认：逐个解绑后重新注册；单个失败只记录在该项上，不整体失败
#[tauri::command]
fn reset_global_shortcuts(
    app: AppHandle,
    state: tauri::State<'_, AppState>,
) -> Result<Vec<GlobalShortcutInfo>, String> {
    let current = {
        let guard = state.shortcuts.lock().map_err(|_| "快捷键状态被占用")?;
        guard.clone()
    };
    for binding in current.values() {
        if binding.registered {
            let _ = unregister_binding(&app, &binding.accelerator);
        }
    }

    let defaults: HashMap<String, String> = GLOBAL_SHORTCUTS
        .iter()
        .map(|(id, _, accelerator)| ((*id).to_string(), (*accelerator).to_string()))
        .collect();
    let mut bindings = HashMap::new();
    for (id, label, _) in GLOBAL_SHORTCUTS {
        let accelerator = defaults.get(id).cloned().unwrap_or_default();
        let (registered, error) = match register_binding(&app, id, &accelerator) {
            Ok(()) => (true, String::new()),
            Err(e) => {
                eprintln!("⚠️  恢复默认快捷键「{label}」失败: {e}");
                (false, e)
            }
        };
        bindings.insert(
            id.to_string(),
            ShortcutBinding { accelerator, registered, error },
        );
    }
    save_shortcut_config(&app, &defaults)?;

    let infos = collect_shortcut_infos(&bindings);
    if let Ok(mut guard) = state.shortcuts.lock() {
        *guard = bindings;
    }
    Ok(infos)
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

/// 快查浮窗尺寸（逻辑像素）。固定大小，内容超出时在窗口内滚动
const QUICK_WIDTH: f64 = 520.0;
const QUICK_HEIGHT: f64 = 620.0;
/// 浮窗距屏幕边缘的留白
const QUICK_MARGIN: f64 = 24.0;

/// 计算浮窗初始位置：主显示器右上角。取不到显示器信息时退回固定位置。
fn quick_window_position<R: Runtime>(app: &AppHandle<R>) -> (f64, f64) {
    let Some(monitor) = app.primary_monitor().ok().flatten() else {
        return (900.0, QUICK_MARGIN);
    };
    let scale = monitor.scale_factor();
    let size = monitor.size();
    let logical_w = size.width as f64 / scale;
    let x = (logical_w - QUICK_WIDTH - QUICK_MARGIN).max(QUICK_MARGIN);
    // 顶部对齐；屏幕比窗口还矮时也保持贴顶，保证输入框可见
    (x, QUICK_MARGIN)
}

/// 按需创建快查浮窗（隐藏状态）。后端未就绪时返回 None，浮窗打不开是预期行为
fn ensure_quick_window<R: Runtime>(app: &AppHandle<R>) -> Option<WebviewWindow<R>> {
    if let Some(window) = app.get_webview_window(QUICK_LABEL) {
        return Some(window);
    }
    let port = current_port(app)?;
    let url = Url::parse(&format!("http://127.0.0.1:{port}/quick")).ok()?;
    let (x, y) = quick_window_position(app);
    match WebviewWindowBuilder::new(app, QUICK_LABEL, WebviewUrl::External(url))
        .title("词札 · 快查")
        .inner_size(QUICK_WIDTH, QUICK_HEIGHT)
        .position(x, y)
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
    log_wins(app, &format!("quick 显示前 existed={existed} mode={}", payload.mode));
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
        log_wins(&handle, "quick show 前");
        let _ = window.show();
        log_wins(&handle, "quick show 后");
        let _ = window.set_focus();
        log_wins(&handle, "quick set_focus 后");
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
            text: None,
            error: None,
            needs_permission: false,
        },
    );
}

/// 截图是阻塞操作（用户在框选），不能卡住快捷键回调线程
fn open_quick_shot<R: Runtime>(app: &AppHandle<R>) {
    let app = app.clone();
    thread::spawn(move || {
        log_wins(&app, "open_quick_shot");
        // 选区层已显示时，⌥S 视为关闭而不是重新截图。
        // 页面脚本失效时，这是用户退出全屏置顶窗口的最后一条路径。
        if close_visible_shot_overlay(&app, "再次按键关闭") {
            return;
        }

        // 权限必须在截图前确认：没有「屏幕录制」权限时截屏只会得到桌面壁纸。
        let access = ensure_screen_recording();
        log_screen_event(&format!(
            "按 ⌥S：access={}",
            match access {
                ScreenAccess::Granted => "granted",
                ScreenAccess::PendingRestart => "pending_restart",
                ScreenAccess::Denied => "denied",
            }
        ));
        if !matches!(access, ScreenAccess::Granted) {
            show_quick(&app, permission_payload(matches!(access, ScreenAccess::Denied)));
            return;
        }

        // 浮窗若已在屏幕上，先藏起来，避免把浮窗截进去
        if let Some(window) = app.get_webview_window(QUICK_LABEL) {
            let _ = window.hide();
        }

        // 全屏透明选区窗口必须在主线程创建
        let handle = app.clone();
        let _ = app.run_on_main_thread(move || {
            if let Err(e) = show_shot_overlay(&handle) {
                eprintln!("⚠️  截图选区不可用: {e}");
                show_quick(
                    &handle,
                    QuickPayload {
                        id: next_payload_id(),
                        mode: "text".into(),
                        image: None,
                        text: None,
                        error: Some(format!("截图失败：{e}")),
                        needs_permission: false,
                    },
                );
            }
        });
    });
}

// 选区层显示/隐藏时同步切换系统光标：只用 CSS 的话，指针不动时不会立刻变
#[cfg(target_os = "macos")]
#[link(name = "AppKit", kind = "framework")]
extern "C" {}

#[cfg(target_os = "macos")]
fn set_native_cursor_crosshair() {
    use objc2::msg_send;
    use objc2::rc::Retained;
    use objc2::runtime::AnyObject;
    unsafe {
        let cursor: Retained<AnyObject> = msg_send![objc2::class!(NSCursor), crosshairCursor];
        let _: () = msg_send![&cursor, set];
    }
}

#[cfg(target_os = "macos")]
fn set_native_cursor_arrow() {
    use objc2::msg_send;
    use objc2::rc::Retained;
    use objc2::runtime::AnyObject;
    unsafe {
        let cursor: Retained<AnyObject> = msg_send![objc2::class!(NSCursor), arrowCursor];
        let _: () = msg_send![&cursor, set];
    }
}

#[cfg(not(target_os = "macos"))]
fn set_native_cursor_crosshair() {}

#[cfg(not(target_os = "macos"))]
fn set_native_cursor_arrow() {}

/// 当前前台应用 PID（诊断与焦点还原共用）。
#[cfg(target_os = "macos")]
fn frontmost_pid() -> i32 {
    use objc2::msg_send;
    use objc2::runtime::AnyObject;
    unsafe {
        let workspace: *mut AnyObject = msg_send![objc2::class!(NSWorkspace), sharedWorkspace];
        if workspace.is_null() {
            return 0;
        }
        let app: *mut AnyObject = msg_send![workspace, frontmostApplication];
        if app.is_null() {
            return 0;
        }
        msg_send![app, processIdentifier]
    }
}

#[cfg(not(target_os = "macos"))]
fn frontmost_pid() -> i32 {
    0
}

/// 记录唤起截图前的前台应用，供取消后还原焦点。
#[cfg(target_os = "macos")]
fn remember_frontmost_app() {
    let pid = frontmost_pid();
    if pid > 0 {
        PREV_FRONTMOST_PID.store(pid, Ordering::SeqCst);
    }
}

#[cfg(not(target_os = "macos"))]
fn remember_frontmost_app() {}

/// 取消选区后激活唤起截图前的应用，避免主窗口被顶到前台。
#[cfg(target_os = "macos")]
fn restore_frontmost_app() {
    use objc2::msg_send;
    use objc2::runtime::AnyObject;
    let pid = PREV_FRONTMOST_PID.swap(0, Ordering::SeqCst);
    if pid <= 0 || pid == std::process::id() as i32 {
        return;
    }
    unsafe {
        let app: *mut AnyObject = msg_send![
            objc2::class!(NSRunningApplication),
            runningApplicationWithProcessIdentifier: pid
        ];
        if app.is_null() {
            return;
        }
        // NSApplicationActivateIgnoringOtherApps = 1 << 1
        let _: bool = msg_send![app, activateWithOptions: 2usize];
    }
}

#[cfg(not(target_os = "macos"))]
fn restore_frontmost_app() {}

/// 截图会话开始前，若主窗口在后台仍可见，先隐藏它。
/// 点击透明选区层会让它取得焦点，macOS 随即激活词札，
/// 并把该应用所有可见窗口一起抬到前台 —— 阅读场景下主窗口会盖住正在读的文档。
/// 词札已经在前台时不隐藏：此时主窗口是用户正在看的窗口。
fn hide_background_main_window<R: Runtime>(app: &AppHandle<R>) {
    if frontmost_pid() == std::process::id() as i32 {
        return;
    }
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(false) {
            let _ = window.hide();
            log_wins(app, "截图前隐藏后台主窗");
        }
    }
}

/// 诊断：记录前台应用 PID 与 main / quick / shot 的可见、聚焦状态。
/// 仅在设置 `CIZHA_DEBUG_WINDOWS=1` 时输出，避免生产日志噪音。
fn log_wins<R: Runtime>(app: &AppHandle<R>, tag: &str) {
    if std::env::var("CIZHA_DEBUG_WINDOWS").ok().as_deref() != Some("1") {
        return;
    }
    let state = |label: &str| match app.get_webview_window(label) {
        Some(w) => format!(
            "{label}[v{} f{}]",
            u8::from(w.is_visible().unwrap_or(false)),
            u8::from(w.is_focused().unwrap_or(false))
        ),
        None => format!("{label}[-]"),
    };
    log_screen_event(&format!(
        "[窗] {tag} front={} {} {} {}",
        frontmost_pid(),
        state("main"),
        state("quick"),
        state("shot")
    ));
}

/// 隐藏可见的选区层并恢复箭头光标；返回是否确实关闭了一个可见窗口。
/// 提交选区或取消后窗口已隐藏，到期的超时看护据此静默退出，不重复操作。
fn close_visible_shot_overlay<R: Runtime>(app: &AppHandle<R>, reason: &str) -> bool {
    let Some(window) = app.get_webview_window(SHOT_LABEL) else {
        disarm_shot_esc(app);
        return false;
    };
    if !window.is_visible().unwrap_or(false) {
        disarm_shot_esc(app);
        return false;
    }
    // 先把焦点还给原应用，再隐藏选区层：
    // 否则 macOS 会先把词札主窗口顶到前台，造成闪现。
    log_wins(app, &format!("close 前 {reason}"));
    let _ = app.run_on_main_thread(restore_frontmost_app);
    let _ = window.hide();
    log_wins(app, &format!("close 后 {reason}"));
    let _ = app.run_on_main_thread(set_native_cursor_arrow);
    disarm_shot_esc(app);
    log_screen_event(&format!("选区层关闭：{reason}"));
    true
}

/// 武装选区层的超时看护：到期时代次未变且窗口仍可见，就由壳层自动关闭。
fn arm_shot_watchdog<R: Runtime>(app: &AppHandle<R>) {
    let epoch = SHOT_EPOCH.fetch_add(1, Ordering::SeqCst) + 1;
    let handle = app.clone();
    thread::spawn(move || {
        thread::sleep(SHOT_TIMEOUT);
        if SHOT_EPOCH.load(Ordering::SeqCst) != epoch {
            return; // 已有更新的选区层，旧任务作废
        }
        close_visible_shot_overlay(&handle, "超时关闭");
    });
}

/// 选区层显示期间临时注册 Esc 为全局取消键。
/// 选区层不抢焦点，页面收不到键盘事件，Esc 只能由壳层接住。
static SHOT_ESC_REGISTERED: AtomicBool = AtomicBool::new(false);

fn arm_shot_esc<R: Runtime>(app: &AppHandle<R>) {
    if SHOT_ESC_REGISTERED.swap(true, Ordering::SeqCst) {
        return;
    }
    let Ok(shortcut) = "Escape".parse::<Shortcut>() else {
        SHOT_ESC_REGISTERED.store(false, Ordering::SeqCst);
        log_screen_event("注册 Esc 取消失败：无法解析快捷键");
        return;
    };
    let result = app.global_shortcut().on_shortcut(shortcut, |app, _shortcut, event| {
        if event.state != ShortcutState::Pressed {
            return;
        }
        let handle = app.clone();
        // 不在快捷键回调里注销自身，避免重入
        thread::spawn(move || {
            if close_visible_shot_overlay(&handle, "Esc 关闭") {
                disarm_shot_esc(&handle);
            }
        });
    });
    if let Err(e) = result {
        SHOT_ESC_REGISTERED.store(false, Ordering::SeqCst);
        log_screen_event(&format!("注册 Esc 取消失败：{e}"));
    }
}

fn disarm_shot_esc<R: Runtime>(app: &AppHandle<R>) {
    if !SHOT_ESC_REGISTERED.swap(false, Ordering::SeqCst) {
        return;
    }
    if let Ok(shortcut) = "Escape".parse::<Shortcut>() {
        let _ = app.global_shortcut().unregister(shortcut);
    }
}

/// 在鼠标所在显示器上铺一层透明选区窗口（页面 `/shot`）。
/// 不再调用 `screencapture` 子进程：它会以独立进程身份触发屏幕录制授权，
/// 导致系统设置里已勾选词札、每次截图仍弹窗。
fn show_shot_overlay<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    log_wins(app, "show_shot_overlay");
    remember_frontmost_app();
    hide_background_main_window(app);
    let port = current_port(app).ok_or("后端尚未就绪")?;
    let cursor = app.cursor_position().map_err(|e| e.to_string())?;
    let monitor = app
        .monitor_from_point(cursor.x, cursor.y)
        .ok()
        .flatten()
        .or_else(|| app.primary_monitor().ok().flatten())
        .ok_or("找不到可用显示器")?;
    let scale = monitor.scale_factor();
    let pos = monitor.position();
    let size = monitor.size();
    let x = pos.x as f64 / scale;
    let y = pos.y as f64 / scale;
    let width = size.width as f64 / scale;
    let height = size.height as f64 / scale;

    let url = Url::parse(&format!("http://127.0.0.1:{port}/shot")).map_err(|e| e.to_string())?;

    // 选区窗口只创建一次，之后复用：重载页面清掉上次选区，再显示。
    // 不能用 close() 后立刻 build()：Tauri 的销毁是异步的，同 label 会冲突。
    if let Some(win) = app.get_webview_window(SHOT_LABEL) {
        let _ = win.hide();
        let _ = win.navigate(url);
        arm_shot_watchdog(app);
        arm_shot_esc(app);
        let handle = win.clone();
        let app_handle = app.clone();
        thread::spawn(move || {
            thread::sleep(Duration::from_millis(200));
            // 只显示不抢焦点：保留当前阅读应用的焦点与外观
            let _ = handle.show();
            log_wins(&app_handle, "shot show 后(复用)");
            let _ = app_handle.run_on_main_thread(set_native_cursor_crosshair);
        });
        return Ok(());
    }

    let window = WebviewWindowBuilder::new(app, SHOT_LABEL, WebviewUrl::External(url))
        .title("词札 · 截图")
        .position(x, y)
        .inner_size(width, height)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(false)
        .shadow(false)
        .transparent(true)
        // 第一次点击就交给页面（否则只是激活窗口，用户要点两下才能开始框选）
        .accept_first_mouse(true)
        // 不主动抢焦点：避免创建窗口时把词札主窗口顶到前台
        .focused(false)
        .visible(false)
        .build()
        .map_err(|e| format!("无法创建选区窗口：{e}"))?;
    arm_shot_watchdog(app);
    arm_shot_esc(app);
    // 等页面首帧（含路由解析、透明样式）完成再显示，避免闪一下主界面
    let win = window.clone();
    let app_handle = app.clone();
    thread::spawn(move || {
        thread::sleep(Duration::from_millis(250));
        // 只显示不抢焦点：保留当前阅读应用的焦点与外观
        let _ = win.show();
        log_wins(&app_handle, "shot show 后(新建)");
        let _ = app_handle.run_on_main_thread(set_native_cursor_crosshair);
    });
    Ok(())
}

/// 前端选区完成：x / y / width / height 都是窗口内 CSS 像素（macOS 上等于 point）
#[tauri::command]
fn finish_region_shot(
    app: tauri::AppHandle,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Result<(), String> {
    log_wins(&app, "finish 入口");
    if width < 4.0 || height < 4.0 {
        return Err("选区太小".into());
    }
    let Some(window) = app.get_webview_window(SHOT_LABEL) else {
        return Err("选区窗口不存在".into());
    };
    // 选区层已被兜底关闭或取消：忽略拖拽结束后迟到的提交
    if !window.is_visible().unwrap_or(false) {
        return Ok(());
    }
    let scale = window.scale_factor().map_err(|e| e.to_string())?;
    let pos = window.outer_position().map_err(|e| e.to_string())?;
    // 全局逻辑坐标：窗口物理位置 / scale，再加上页面内偏移
    let gx = pos.x as f64 / scale + x;
    let gy = pos.y as f64 / scale + y;

    let _ = window.hide();
    log_wins(&app, "finish hide 后");
    disarm_shot_esc(&app);
    let _ = app.run_on_main_thread(set_native_cursor_arrow);
    let handle = app.clone();
    thread::spawn(move || {
        // 等遮罩真正从屏幕上消失，避免把自己截进去
        thread::sleep(Duration::from_millis(140));
        let captured = capture_rect_points(gx, gy, width, height);
        log_screen_event(&format!(
            "取图 ({gx:.0},{gy:.0}) {width:.0}x{height:.0}: {}",
            match &captured {
                Ok(_) => "ok".to_string(),
                Err(e) => format!("err: {e}"),
            }
        ));
        let payload = match captured {
            // 端上 OCR 有结果：只把文字发给前端，秒出；图片不必再传
            Ok((_, text)) if !text.trim().is_empty() => QuickPayload {
                id: next_payload_id(),
                mode: "text".into(),
                image: None,
                text: Some(text),
                error: None,
                needs_permission: false,
            },
            // OCR 没认出字：保留图片，走原有视觉模型兜底
            Ok((image, _)) => QuickPayload {
                id: next_payload_id(),
                mode: "image".into(),
                image: Some(image),
                text: None,
                error: None,
                needs_permission: false,
            },
            Err(e) => QuickPayload {
                id: next_payload_id(),
                mode: "text".into(),
                image: None,
                text: None,
                error: Some(format!("截图失败：{e}")),
                needs_permission: false,
            },
        };
        show_quick(&handle, payload);
    });
    Ok(())
}

/// Esc 或点击取消：藏起选区层，不开快查浮窗
#[tauri::command]
fn cancel_region_shot(app: tauri::AppHandle) {
    log_wins(&app, "cancel 入口");
    let _ = app.run_on_main_thread(restore_frontmost_app);
    if let Some(window) = app.get_webview_window(SHOT_LABEL) {
        let _ = window.hide();
    }
    log_wins(&app, "cancel hide 后");
    disarm_shot_esc(&app);
    let _ = app.run_on_main_thread(set_native_cursor_arrow);
}

/// 未授权时的提示载荷。macOS 授权后需要重启 App 才对当前进程生效，必须写明。
/// `needs_settings` 为 true 表示还没授权，附上「打开设置」按钮；
/// 为 false 表示已授权但当前进程未生效，只需提示重启。
fn permission_payload(needs_settings: bool) -> QuickPayload {
    let error = if needs_settings {
        "未获得「屏幕录制」权限，截图只会得到桌面壁纸。\
         请在 系统设置 → 隐私与安全性 → 屏幕录制 中勾选「词札」，\
         然后退出并重新打开词札再试。"
    } else {
        "已获得「屏幕录制」权限，但需要重启词札后才生效。请退出并重新打开词札。"
    };
    QuickPayload {
        id: next_payload_id(),
        mode: "text".into(),
        image: None,
        text: None,
        error: Some(error.into()),
        needs_permission: needs_settings,
    }
}

/// 屏幕录制权限的三态：已生效 / 已申请但当前进程未生效 / 未授权
enum ScreenAccess {
    Granted,
    PendingRestart,
    Denied,
}

#[cfg(target_os = "macos")]
#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    /// 只查询授权状态，不弹窗
    fn CGPreflightScreenCaptureAccess() -> bool;
    /// 首次调用会弹出系统授权框，并把 App 加进「屏幕录制」列表
    fn CGRequestScreenCaptureAccess() -> bool;
}

/// 每次启动最多主动申请一次授权，避免每次按 ⌥S 都被系统弹窗打断
#[cfg(target_os = "macos")]
static SCREEN_RECORD_REQUESTED: AtomicBool = AtomicBool::new(false);

/// 截图链路诊断日志：~/Library/Logs/com.cizha.vocab/screen.log
/// 权限问题在不同 macOS 版本上表现不一，留一份时间线便于排查。
fn log_screen_event(message: &str) {
    let Some(home) = std::env::var_os("HOME") else {
        return;
    };
    let dir = PathBuf::from(home).join("Library/Logs/com.cizha.vocab");
    let _ = std::fs::create_dir_all(&dir);
    let path = dir.join("screen.log");
    // 超过 5MB 轮转为 screen.log.1，只保留一份，避免长期使用无限增长。
    if let Ok(meta) = std::fs::metadata(&path) {
        if meta.len() > 5 * 1024 * 1024 {
            let _ = std::fs::rename(&path, dir.join("screen.log.1"));
        }
    }
    if let Ok(mut file) = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
    {
        let secs = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let _ = writeln!(file, "[{secs}] {message}");
    }
}

/// 当前进程是否可以使用屏幕录制。
/// 注意：preflight 为 false 时即使 CGRequest 返回 true，也必须重启 App 才真正生效，
/// 所以这里不直接放行截图，避免又截到一张桌面壁纸。
#[cfg(target_os = "macos")]
fn ensure_screen_recording() -> ScreenAccess {
    if unsafe { CGPreflightScreenCaptureAccess() } {
        return ScreenAccess::Granted;
    }
    if !SCREEN_RECORD_REQUESTED.swap(true, Ordering::SeqCst)
        && unsafe { CGRequestScreenCaptureAccess() }
    {
        return ScreenAccess::PendingRestart;
    }
    ScreenAccess::Denied
}

#[cfg(not(target_os = "macos"))]
fn ensure_screen_recording() -> ScreenAccess {
    // 非 macOS 没有 TCC；交给 capture_region 返回「仅支持 macOS」
    ScreenAccess::Granted
}

/// 打开「隐私与安全性 → 屏幕录制」设置页，供权限提示里的按钮调用
#[tauri::command]
fn open_screen_recording_settings() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        let status = Command::new("/usr/bin/open")
            .arg("x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")
            .status()
            .map_err(|e| format!("无法打开系统设置：{e}"))?;
        if status.success() {
            return Ok(());
        }
        return Err("无法打开系统设置".into());
    }
    #[cfg(not(target_os = "macos"))]
    {
        Err("系统级截图仅支持 macOS".into())
    }
}

/// macOS 原生区域截图：CGWindowListCreateImage 在应用进程内取图，
/// 权限归属词札本身；返回 data URL。
#[cfg(target_os = "macos")]
#[repr(C)]
#[derive(Clone, Copy)]
struct CGPoint {
    x: f64,
    y: f64,
}

#[cfg(target_os = "macos")]
#[repr(C)]
#[derive(Clone, Copy)]
struct CGSize {
    width: f64,
    height: f64,
}

#[cfg(target_os = "macos")]
#[repr(C)]
#[derive(Clone, Copy)]
struct CGRect {
    origin: CGPoint,
    size: CGSize,
}

#[cfg(target_os = "macos")]
#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGWindowListCreateImage(
        screen_bounds: CGRect,
        list_option: u32,
        window_id: u32,
        image_option: u32,
    ) -> *mut std::ffi::c_void;
    fn CGImageRelease(image: *mut std::ffi::c_void);
}

#[cfg(target_os = "macos")]
#[link(name = "CoreFoundation", kind = "framework")]
extern "C" {
    fn CFDataCreateMutable(
        allocator: *const std::ffi::c_void,
        capacity: isize,
    ) -> *mut std::ffi::c_void;
    fn CFDataGetBytePtr(data: *const std::ffi::c_void) -> *const u8;
    fn CFDataGetLength(data: *const std::ffi::c_void) -> isize;
    fn CFStringCreateWithCString(
        allocator: *const std::ffi::c_void,
        c_str: *const std::os::raw::c_char,
        encoding: u32,
    ) -> *const std::ffi::c_void;
    fn CFRelease(cf: *const std::ffi::c_void);
}

#[cfg(target_os = "macos")]
#[link(name = "ImageIO", kind = "framework")]
extern "C" {
    fn CGImageDestinationCreateWithData(
        data: *mut std::ffi::c_void,
        type_identifier: *const std::ffi::c_void,
        count: usize,
        options: *const std::ffi::c_void,
    ) -> *mut std::ffi::c_void;
    fn CGImageDestinationAddImage(
        destination: *mut std::ffi::c_void,
        image: *mut std::ffi::c_void,
        properties: *const std::ffi::c_void,
    );
    fn CGImageDestinationFinalize(destination: *mut std::ffi::c_void) -> bool;
}

#[cfg(target_os = "macos")]
fn capture_rect_points(x: f64, y: f64, width: f64, height: f64) -> Result<(String, String), String> {
    use base64::Engine;
    use std::ffi::c_void;
    use std::ptr;

    const K_ON_SCREEN_ONLY: u32 = 1;
    const K_NULL_WINDOW_ID: u32 = 0;
    const K_IMAGE_DEFAULT: u32 = 0;
    const K_CF_STRING_ENCODING_UTF8: u32 = 0x0800_0100;

    let rect = CGRect {
        origin: CGPoint { x, y },
        size: CGSize { width, height },
    };
    let image = unsafe {
        CGWindowListCreateImage(rect, K_ON_SCREEN_ONLY, K_NULL_WINDOW_ID, K_IMAGE_DEFAULT)
    };
    if image.is_null() {
        return Err("无法获取屏幕图像（屏幕录制权限可能未生效）".into());
    }

    // 先在原图上做系统级 OCR（Apple Vision，毫秒级），再编码 PNG
    let ocr_text = ocr_cg_image(image);

    let encoded = unsafe {
        let data = CFDataCreateMutable(ptr::null(), 0);
        let uti = CFStringCreateWithCString(
            ptr::null(),
            b"public.png\0".as_ptr() as *const std::os::raw::c_char,
            K_CF_STRING_ENCODING_UTF8,
        );
        if data.is_null() || uti.is_null() {
            if !data.is_null() {
                CFRelease(data as *const c_void);
            }
            if !uti.is_null() {
                CFRelease(uti);
            }
            CGImageRelease(image);
            return Err("截图编码初始化失败".into());
        }

        let dest = CGImageDestinationCreateWithData(data, uti, 1, ptr::null());
        let bytes = if dest.is_null() {
            None
        } else {
            CGImageDestinationAddImage(dest, image, ptr::null());
            let ok = CGImageDestinationFinalize(dest);
            let result = if ok {
                let len = CFDataGetLength(data as *const c_void);
                let raw_ptr = CFDataGetBytePtr(data as *const c_void);
                if raw_ptr.is_null() || len <= 0 {
                    None
                } else {
                    Some(std::slice::from_raw_parts(raw_ptr, len as usize).to_vec())
                }
            } else {
                None
            };
            CFRelease(dest as *const c_void);
            result
        };

        CFRelease(data as *const c_void);
        CFRelease(uti);
        CGImageRelease(image);
        bytes
    };

    let bytes = encoded.ok_or("截图编码失败")?;
    Ok((
        format!(
            "data:image/png;base64,{}",
            base64::engine::general_purpose::STANDARD.encode(bytes)
        ),
        ocr_text,
    ))
}

#[cfg(not(target_os = "macos"))]
fn capture_rect_points(_x: f64, _y: f64, _width: f64, _height: f64) -> Result<(String, String), String> {
    Err("截图取词目前仅支持 macOS".into())
}

// 用 Apple Vision 做端上 OCR，和 EasyDict 同一套系统能力。
// 失败返回空串，由调用方回退到上传图片走视觉模型。
#[cfg(target_os = "macos")]
#[link(name = "Vision", kind = "framework")]
extern "C" {}
#[cfg(target_os = "macos")]
fn ocr_cg_image(image: *mut std::ffi::c_void) -> String {
    use objc2::msg_send;
    use objc2::rc::{Allocated, Retained};
    use objc2::runtime::AnyObject;
    use objc2_foundation::{NSArray, NSString};

    if image.is_null() {
        return String::new();
    }

    unsafe {
        let request: Retained<AnyObject> = msg_send![objc2::class!(VNRecognizeTextRequest), new];
        // VNRequestTextRecognitionLevelAccurate = 1
        let _: () = msg_send![&request, setRecognitionLevel: 1isize];
        let languages = NSArray::from_retained_slice(&[
            NSString::from_str("zh-Hans"),
            NSString::from_str("en-US"),
        ]);
        let _: () = msg_send![&request, setRecognitionLanguages: &*languages];
        let _: () = msg_send![&request, setUsesLanguageCorrection: true];

        let alloc: Allocated<AnyObject> =
            msg_send![objc2::class!(VNImageRequestHandler), alloc];
        let handler: Option<Retained<AnyObject>> = msg_send![
            alloc,
            initWithCGImage: image,
            options: std::ptr::null::<AnyObject>()
        ];
        let Some(handler) = handler else {
            return String::new();
        };

        let requests = NSArray::from_retained_slice(&[request.clone()]);
        let mut error: *mut AnyObject = std::ptr::null_mut();
        let ok: bool = msg_send![&*handler, performRequests: &*requests, error: &mut error];
        if !ok {
            return String::new();
        }

        let results: Option<Retained<NSArray<AnyObject>>> = msg_send![&request, results];
        let Some(results) = results else {
            return String::new();
        };

        let mut lines: Vec<String> = Vec::new();
        for observation in results.iter() {
            let candidates: Option<Retained<NSArray<AnyObject>>> =
                msg_send![&*observation, topCandidates: 1usize];
            let Some(candidates) = candidates else { continue };
            let Some(candidate) = candidates.firstObject() else {
                continue;
            };
            let text: Retained<NSString> = msg_send![&*candidate, string];
            let line = text.to_string();
            if !line.trim().is_empty() {
                lines.push(line);
            }
        }
        lines.join("\n")
    }
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
    log_wins(&app, "quick_hide 后");
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

/// 开发模式（cargo tauri dev）优先跑源码后端：
/// 这样改 Python 只需重启壳层，前端 dist 也由源码路径直接托管，无需 PyInstaller。
fn dev_backend_command() -> Option<Command> {
    if !cfg!(debug_assertions) {
        return None;
    }
    let backend = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()?
        .join("backend");
    let run_py = backend.join("run.py");
    let python = if cfg!(windows) {
        backend.join("venv").join("Scripts").join("python.exe")
    } else {
        backend.join("venv").join("bin").join("python")
    };
    if !run_py.is_file() || !python.is_file() {
        return None;
    }
    let mut cmd = Command::new(python);
    cmd.arg(run_py);
    // 与打包版共用同一份数据（词库 / 模型配置 / 偏好），避免开发版看到空库
    #[cfg(target_os = "macos")]
    if let Some(home) = std::env::var_os("HOME") {
        cmd.env(
            "CIZHA_DATA_DIR",
            PathBuf::from(home).join("Library/Application Support/cizha"),
        );
    }
    Some(cmd)
}

/// spawn 后端进程：端口交给系统分配，启动完成后写入 ready 文件
fn spawn_backend<R: Runtime>(app: &AppHandle<R>, ready_file: &Path) -> Option<Child> {
    let mut cmd = match dev_backend_command() {
        Some(cmd) => cmd,
        None => {
            let path = match backend_executable(app) {
                Some(path) => path,
                None => {
                    eprintln!("❌ 找不到后端可执行文件（resource_dir / dist / _pybuild 都没有）");
                    return None;
                }
            };
            Command::new(&path)
        }
    };
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

    let label = cmd.get_program().to_string_lossy().to_string();
    match cmd.spawn() {
        Ok(child) => {
            println!("🚀 后端已启动: {label}");
            Some(child)
        }
        Err(e) => {
            eprintln!("❌ 后端启动失败 {label}: {e}");
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

