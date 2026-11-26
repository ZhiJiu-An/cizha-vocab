//! 快查浮窗：按需创建、载荷投递与相关 IPC 命令。

use tauri::{
    AppHandle, Emitter, Manager, Runtime, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
};
use url::Url;

use crate::lifecycle::navigate;
use crate::logging::log_wins;
use crate::state::{current_port, AppState, QuickPayload};

// 快查浮窗标签
pub(crate) const QUICK_LABEL: &str = "quick";

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
pub(crate) fn show_quick<R: Runtime>(app: &AppHandle<R>, payload: QuickPayload) {
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

pub(crate) fn next_payload_id() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0)
}

pub(crate) fn open_quick_text<R: Runtime>(app: &AppHandle<R>) {
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

/// 前端挂载后主动取一次（新建窗口时事件可能比页面加载更早）
#[tauri::command]
pub(crate) fn quick_get_pending(state: tauri::State<'_, AppState>) -> Option<QuickPayload> {
    state.quick_pending.lock().ok().and_then(|mut pending| pending.take())
}

#[tauri::command]
pub(crate) fn quick_hide(app: tauri::AppHandle) {
    if let Some(window) = app.get_webview_window(QUICK_LABEL) {
        let _ = window.hide();
    }
    log_wins(&app, "quick_hide 后");
}

/// 把词交给主窗口的词典页（/?q=xxx），复用完整的双栏结果
#[tauri::command]
pub(crate) fn open_main_query(app: tauri::AppHandle, word: String) -> Result<(), String> {
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
