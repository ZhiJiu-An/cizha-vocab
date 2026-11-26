//! 诊断日志：截图链路（screen.log）与窗口状态。仅在需要排查时输出，避免生产噪音。

use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;

use tauri::{AppHandle, Manager, Runtime};

use crate::platform::frontmost_pid;

/// 截图链路诊断日志：~/Library/Logs/com.cizha.vocab/screen.log
/// 权限问题在不同 macOS 版本上表现不一，留一份时间线便于排查。
pub(crate) fn log_screen_event(message: &str) {
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

/// 诊断：记录前台应用 PID 与 main / quick / shot 的可见、聚焦状态。
/// 仅在设置 `CIZHA_DEBUG_WINDOWS=1` 时输出，避免生产日志噪音。
pub(crate) fn log_wins<R: Runtime>(app: &AppHandle<R>, tag: &str) {
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
