use std::collections::HashMap;
use std::process::Child;
use std::sync::atomic::{AtomicBool, AtomicU16, Ordering};
use std::sync::Mutex;

use tauri::{AppHandle, Manager, Runtime};

/// 全局状态：后端子进程 handle + 退出标记 + 后端端口
pub(crate) struct AppState {
    pub(crate) backend: Mutex<Option<Child>>,
    /// 置位后看护线程立即停止，避免退出过程中又把后端拉起来
    pub(crate) stopping: AtomicBool,
    /// 后端实际端口（系统分配），0 表示尚未就绪。快查浮窗的 URL 依赖它
    pub(crate) port: AtomicU16,
    /// 快查浮窗的待处理载荷：新建窗口首帧还没加载完时事件会丢，前端挂载后主动取一次
    pub(crate) quick_pending: Mutex<Option<QuickPayload>>,
    /// 全局快捷键：id -> 当前绑定（accelerator 为空表示禁用）
    pub(crate) shortcuts: Mutex<HashMap<String, ShortcutBinding>>,
}

/// 快查浮窗载荷。`id` 用于前端去重（同一次打开可能既收到事件又取到 pending）
#[derive(Clone, serde::Serialize)]
pub(crate) struct QuickPayload {
    pub(crate) id: u64,
    /// "text" 输入翻译 / "image" 截图取词
    pub(crate) mode: String,
    /// data URL（image/png;base64）
    pub(crate) image: Option<String>,
    /// 原生 OCR 识别出的文字（有值时前端直接填入输入框，不再上传图片）
    pub(crate) text: Option<String>,
    pub(crate) error: Option<String>,
    /// 缺少「屏幕录制」权限：前端据此展示「打开系统设置」按钮
    pub(crate) needs_permission: bool,
}

/// 单个全局快捷键的当前状态
#[derive(Clone)]
pub(crate) struct ShortcutBinding {
    pub(crate) accelerator: String,
    pub(crate) registered: bool,
    pub(crate) error: String,
}

/// 后端实际端口；0 表示启动流程还没跑完
pub(crate) fn current_port<R: Runtime>(app: &AppHandle<R>) -> Option<u16> {
    app.try_state::<AppState>()
        .map(|state| state.port.load(Ordering::SeqCst))
        .filter(|port| *port > 0)
}
