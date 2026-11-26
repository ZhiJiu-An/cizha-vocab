//! 截图取词：选区层、Esc / 超时兜底、屏幕录制权限与原生取图。

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::thread;
use std::time::Duration;

use tauri::{AppHandle, Manager, Runtime, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};
use url::Url;

use crate::logging::{log_screen_event, log_wins};
use crate::platform::{
    capture_rect_points, frontmost_pid, remember_frontmost_app, restore_frontmost_app,
    set_native_cursor_arrow, set_native_cursor_crosshair,
};
use crate::quick::{next_payload_id, show_quick, QUICK_LABEL};
use crate::state::{current_port, QuickPayload};

// 截图选区浮层标签
const SHOT_LABEL: &str = "shot";

/// 选区层无操作后由壳层兜底关闭的时限。
/// 防止页面脚本失效时全屏置顶窗口无限期遮挡桌面。
const SHOT_TIMEOUT: Duration = Duration::from_secs(60);

/// 选区层代次：每次显示递增，旧的超时看护据此判断自己是否已过期。
static SHOT_EPOCH: AtomicU64 = AtomicU64::new(0);

/// 截图是阻塞操作（用户在框选），不能卡住快捷键回调线程
pub(crate) fn open_quick_shot<R: Runtime>(app: &AppHandle<R>) {
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
pub(crate) fn finish_region_shot(
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
pub(crate) fn cancel_region_shot(app: tauri::AppHandle) {
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
pub(crate) fn open_screen_recording_settings() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        let status = std::process::Command::new("/usr/bin/open")
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
