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
//!
//! 本文件只保留模块声明与 Builder 装配；各关注点的实现在同名模块里。

mod backend;
mod lifecycle;
mod logging;
mod platform;
mod quick;
mod shortcuts;
mod shot;
mod state;
mod tray;

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU16, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::{Manager, RunEvent};
use url::Url;

use crate::backend::{cleanup_backend, monitor_backend, start_backend};
use crate::lifecycle::{mark_stopping, navigate, show_error_on_main};
#[cfg(unix)]
use crate::lifecycle::{block_exit_signals, spawn_signal_handler};
use crate::logging::log_wins;
use crate::state::AppState;
use crate::tray::{toggle_window, MENU_HIDE, MENU_QUIT, MENU_SHOW};

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
            quick::quick_get_pending,
            quick::quick_hide,
            quick::open_main_query,
            shortcuts::get_global_shortcuts,
            shortcuts::set_global_shortcut,
            shortcuts::reset_global_shortcuts,
            shot::open_screen_recording_settings,
            shot::finish_region_shot,
            shot::cancel_region_shot,
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
            tray::setup_tray(app.handle())?;
            shortcuts::setup_shortcuts(app.handle())?;

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
