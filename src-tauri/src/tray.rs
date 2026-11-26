//! 系统托盘：菜单与主窗口显隐。

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager, Runtime,
};

// 菜单项 ID（托盘菜单）
pub(crate) const MENU_SHOW: &str = "show";
pub(crate) const MENU_HIDE: &str = "hide";
pub(crate) const MENU_QUIT: &str = "quit";

/// 创建系统托盘（菜单 + 左键切换）
pub(crate) fn setup_tray<R: Runtime>(
    app: &AppHandle<R>,
) -> Result<(), Box<dyn std::error::Error>> {
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

pub(crate) fn is_window_visible<R: Runtime>(app: &AppHandle<R>) -> bool {
    app.get_webview_window("main")
        .and_then(|w| w.is_visible().ok())
        .unwrap_or(false)
}

pub(crate) fn toggle_window<R: Runtime>(app: &AppHandle<R>, show: bool) {
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
