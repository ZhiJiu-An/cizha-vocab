//! 生命周期与退出：退出标记、Unix 信号接管、窗口导航与启动页错误。

use std::sync::atomic::Ordering;
use std::thread;
use std::time::Duration;

use tauri::{AppHandle, Manager, Runtime};
use url::Url;

use crate::backend::cleanup_backend;
use crate::state::AppState;

/// 退出流程开始后置位，看护线程看到就停
pub(crate) fn mark_stopping<R: Runtime>(app: &AppHandle<R>) {
    if let Some(state) = app.try_state::<AppState>() {
        state.stopping.store(true, Ordering::Relaxed);
    }
}

pub(crate) fn is_stopping<R: Runtime>(app: &AppHandle<R>) -> bool {
    app.try_state::<AppState>()
        .map(|state| state.stopping.load(Ordering::Relaxed))
        .unwrap_or(true)
}

/// 在主线程导航；导航失败时把原因写回启动页，而不是静默停在 loading
pub(crate) fn navigate<R: Runtime>(
    app: &AppHandle<R>,
    window: &tauri::WebviewWindow<R>,
    url: Url,
) {
    navigate_with(app, window, url, true);
}

/// `focus=false` 用于隐藏的快查浮窗：只换地址，不抢用户焦点
pub(crate) fn navigate_with<R: Runtime>(
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

/// 在 loading 页展示错误信息。
/// 启动失败可能发生在页面还没加载完时，eval 会被丢弃，所以间隔重试几次。
pub(crate) fn show_error_on_main<R: Runtime>(
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

/// 提前屏蔽退出信号（必须在任何线程创建之前调用）。
/// 后续创建的线程都会继承该屏蔽字，信号只会被 sigwait 线程取走。
#[cfg(unix)]
pub(crate) fn block_exit_signals() {
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
pub(crate) fn spawn_signal_handler<R: Runtime>(app: AppHandle<R>) {
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
