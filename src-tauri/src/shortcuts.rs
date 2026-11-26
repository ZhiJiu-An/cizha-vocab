//! 全局快捷键：注册、改绑、重置与本机持久化。

use std::collections::HashMap;
use std::path::PathBuf;

use tauri::{AppHandle, Manager, Runtime};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

use crate::quick::open_quick_text;
use crate::shot::open_quick_shot;
use crate::state::{AppState, ShortcutBinding};
use crate::tray::{is_window_visible, toggle_window};

/// 全局快捷键定义：id / 展示名 / 默认 accelerator（Tauri 语法，见 shortcuts.json）
const GLOBAL_SHORTCUTS: [(&str, &str, &str); 3] = [
    ("toggle_window", "唤起 / 隐藏主窗口", "CmdOrCtrl+Shift+KeyC"),
    ("quick_text", "输入翻译", "Alt+KeyA"),
    ("quick_shot", "截图取词", "Alt+KeyS"),
];

#[derive(Clone, serde::Serialize)]
pub(crate) struct GlobalShortcutInfo {
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

/// 启动时读取 shortcuts.json 并注册全局快捷键。
/// 单个组合被其他应用占用不拖垮启动：状态与错误记进 AppState，设置页会展示。
pub(crate) fn setup_shortcuts<R: Runtime>(
    app: &AppHandle<R>,
) -> Result<(), Box<dyn std::error::Error>> {
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
pub(crate) fn get_global_shortcuts(state: tauri::State<'_, AppState>) -> Vec<GlobalShortcutInfo> {
    match state.shortcuts.lock() {
        Ok(guard) => collect_shortcut_infos(&guard),
        Err(_) => Vec::new(),
    }
}

/// 改绑：先解旧键 → 注册新键（失败则恢复旧键）→ 落盘。
/// 空 accelerator 表示禁用该动作。
#[tauri::command]
pub(crate) fn set_global_shortcut(
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
pub(crate) fn reset_global_shortcuts(
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
