//! macOS 原生能力：光标切换、前台应用记录与还原、区域取图与端上 OCR。
//! 非 macOS 分支保留与拆分前一致的桩函数。

use std::sync::atomic::{AtomicI32, Ordering};

/// 唤起截图前的前台应用 PID；取消选区后把焦点还回去，
/// 避免词札被激活后把主窗口顶到最前面。
static PREV_FRONTMOST_PID: AtomicI32 = AtomicI32::new(0);

// 选区层显示/隐藏时同步切换系统光标：只用 CSS 的话，指针不动时不会立刻变
#[cfg(target_os = "macos")]
#[link(name = "AppKit", kind = "framework")]
extern "C" {}

#[cfg(target_os = "macos")]
pub(crate) fn set_native_cursor_crosshair() {
    use objc2::msg_send;
    use objc2::rc::Retained;
    use objc2::runtime::AnyObject;
    unsafe {
        let cursor: Retained<AnyObject> = msg_send![objc2::class!(NSCursor), crosshairCursor];
        let _: () = msg_send![&cursor, set];
    }
}

#[cfg(target_os = "macos")]
pub(crate) fn set_native_cursor_arrow() {
    use objc2::msg_send;
    use objc2::rc::Retained;
    use objc2::runtime::AnyObject;
    unsafe {
        let cursor: Retained<AnyObject> = msg_send![objc2::class!(NSCursor), arrowCursor];
        let _: () = msg_send![&cursor, set];
    }
}

#[cfg(not(target_os = "macos"))]
pub(crate) fn set_native_cursor_crosshair() {}

#[cfg(not(target_os = "macos"))]
pub(crate) fn set_native_cursor_arrow() {}

/// 当前前台应用 PID（诊断与焦点还原共用）。
#[cfg(target_os = "macos")]
pub(crate) fn frontmost_pid() -> i32 {
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
pub(crate) fn frontmost_pid() -> i32 {
    0
}

/// 记录唤起截图前的前台应用，供取消后还原焦点。
#[cfg(target_os = "macos")]
pub(crate) fn remember_frontmost_app() {
    let pid = frontmost_pid();
    if pid > 0 {
        PREV_FRONTMOST_PID.store(pid, Ordering::SeqCst);
    }
}

#[cfg(not(target_os = "macos"))]
pub(crate) fn remember_frontmost_app() {}

/// 取消选区后激活唤起截图前的应用，避免主窗口被顶到前台。
#[cfg(target_os = "macos")]
pub(crate) fn restore_frontmost_app() {
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
pub(crate) fn restore_frontmost_app() {}

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
pub(crate) fn capture_rect_points(
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Result<(String, String), String> {
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
pub(crate) fn capture_rect_points(
    _x: f64,
    _y: f64,
    _width: f64,
    _height: f64,
) -> Result<(String, String), String> {
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
