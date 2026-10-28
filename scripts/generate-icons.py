#!/usr/bin/env python3
"""生成 Tauri 桌面 App 图标集。

产出：
  src-tauri/icons/32x32.png
  src-tauri/icons/128x128.png
  src-tauri/icons/128x128@2x.png  (256x256)
  src-tauri/icons/icon.png       (512x512, 源图)
  src-tauri/icons/icon.ico       (多尺寸 Windows 图标)
  src-tauri/icons/icon.icns      (macOS 图标)
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent / "src-tauri" / "icons"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SIZE = 512

# ---------- 画图标 ----------
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# 圆角矩形背景 —— 深蓝渐变
# 先画两层叠加模拟渐变
r = SIZE // 5
for y in range(SIZE):
    t = y / SIZE
    # 从 #2563EB (blue-600) 渐变到 #1D4ED8 (blue-700)
    r1, g1, b1 = 0x25, 0x63, 0xEB
    r2, g2, b2 = 0x1D, 0x4E, 0xD8
    cr = int(r1 + (r2 - r1) * t)
    cg = int(g1 + (g2 - g1) * t)
    cb = int(b1 + (b2 - b1) * t)
    draw.line([(0, y), (SIZE, y)], fill=(cr, cg, cb, 255))

# 圆角 mask
mask = Image.new("L", (SIZE, SIZE), 0)
mask_draw = ImageDraw.Draw(mask)
mask_draw.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=r, fill=255)
output = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
output.paste(img, (0, 0), mask)
img = output
draw = ImageDraw.Draw(img)

# 白色 "C" 字（词札 Logo —— 取 Cizha 首字母）
try:
    # macOS 系统字体
    font = ImageFont.truetype(
        "/System/Library/Fonts/PingFang.ttc", size=320
    )
except Exception:
    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Helvetica.ttc", size=320
        )
    except Exception:
        font = ImageFont.load_default()

text = "C"
# 计算居中位置
bbox = draw.textbbox((0, 0), text, font=font)
tw = bbox[2] - bbox[0]
th = bbox[3] - bbox[1]
tx = (SIZE - tw) // 2 - bbox[0]
ty = (SIZE - th) // 2 - bbox[1]

# 文字阴影
shadow_offset = 8
draw.text((tx + shadow_offset, ty + shadow_offset), text, fill=(0, 0, 0, 60), font=font)
# 白色文字
draw.text((tx, ty), text, fill=(255, 255, 255, 255), font=font)

# ---------- 输出各尺寸 ----------
def save_png(src: Image.Image, size: int, name: str):
    resized = src.resize((size, size), Image.LANCZOS)
    path = OUT_DIR / name
    resized.save(path, "PNG")
    print(f"  ✅ {path.name:30s} {size}x{size}")


# 源图
img.save(OUT_DIR / "icon.png", "PNG")
print(f"  ✅ {'icon.png':30s} {SIZE}x{SIZE}")

# 标准尺寸
for name, size in [
    ("32x32.png", 32),
    ("128x128.png", 128),
    ("128x128@2x.png", 256),
]:
    save_png(img, size, name)

# ---------- ICO（Windows） ----------
ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
ico_images = [img.resize(s, Image.LANCZOS) for s in ico_sizes]
ico_images[0].save(
    OUT_DIR / "icon.ico",
    format="ICO",
    sizes=[(s[0], s[1]) for s in ico_sizes],
)
print(f"  ✅ {'icon.ico':30s} {len(ico_sizes)} sizes embedded")

# ---------- ICNS（macOS） ----------
# PIL 不能直接写 icns，生成一套 PNG 让用户用 iconutil 转
# 先把所有需要的尺寸导出
icns_dir = OUT_DIR / "icns_source.iconset"
icns_dir.mkdir(exist_ok=True)

icns_sizes = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]
for name, size in icns_sizes:
    resized = img.resize((size, size), Image.LANCZOS)
    resized.save(icns_dir / name, "PNG")

# 用 macOS iconutil 转 icns
import subprocess
result = subprocess.run(
    ["iconutil", "-c", "icns", str(icns_dir), "-o", str(OUT_DIR / "icon.icns")],
    capture_output=True, text=True,
)
if result.returncode == 0:
    print(f"  ✅ {'icon.icns':30s} (via iconutil)")
else:
    print(f"  ⚠️  iconutil 不可用，跳过 icns 生成: {result.stderr.strip()[:80]}")
    print(f"     可手动运行: iconutil -c icns {icns_dir}")

# 清理临时目录
import shutil
shutil.rmtree(icns_dir, ignore_errors=True)

print(f"\n📁 图标目录: {OUT_DIR}")
