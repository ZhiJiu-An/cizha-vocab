//! 后端 sidecar 的启动、就绪判定、日志与看护。

use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::Ordering;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, Runtime};
use url::Url;

use crate::lifecycle::{is_stopping, navigate, navigate_with, show_error_on_main};
use crate::quick::QUICK_LABEL;
use crate::state::AppState;

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

/// 启动后端并等待就绪，失败自动重试一次，返回最终可用的端口。
/// 端口由系统分配（`--port 0`），后端启动后把实际端口写进 ready 文件，
/// 彻底避免「先探测空端口再交给后端 bind」的竞态。
pub(crate) fn start_backend<R: Runtime>(app: &AppHandle<R>) -> Result<u16, String> {
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
pub(crate) fn monitor_backend<R: Runtime>(
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

/// 清理后端子进程（幂等）
pub(crate) fn cleanup_backend<R: Runtime>(app: &AppHandle<R>) {
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
