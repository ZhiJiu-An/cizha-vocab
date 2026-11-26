"""用户偏好持久化：昵称 / 发音口音 / 学习提醒

为什么不用 localStorage：
桌面版后端用 `--port 0` 随机端口启动，WebView 的 localStorage 按
`scheme://host:port` 的 origin 隔离，每次启动端口变化就等于换了存储空间，
昵称、口音、提醒设置重启后全部回默认值。偏好必须落盘到数据目录。

文件：`<data_dir>/prefs.json`，原子写；文件损坏或字段非法时回退默认值。
"""
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import PROMPT_PRESETS
from ..paths import get_data_dir

router = APIRouter(prefix="/api/prefs", tags=["用户偏好"])

DEFAULT_PREFS: dict = {
    "nickname": "词札学习者",
    "accent": "us",
    # 主窗口搜索框的领域提示词：llm / cs / medical / finance，空串 = 用模型卡自己的提示词
    "translate_preset": "",
    "reminder": {"enabled": False, "time": "20:00", "last_notified": ""},
    # 应用内快捷键：动作 ID -> 组合键（如 "Mod+K"）。
    # 全局快捷键由 Rust 壳持有（shortcuts.json），不在这里，避免启动时依赖后端。
    "shortcuts": {"in_app": {}},
}

_write_lock = threading.Lock()


class ReminderPrefs(BaseModel):
    enabled: bool = False
    time: str = Field("20:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    # 前端每天只提醒一次；日期随偏好一起持久化，避免重启后重复提醒
    last_notified: str = Field("", max_length=32)


class ShortcutPrefs(BaseModel):
    # 只存用户改过的动作也没问题：前端会与默认表合并后再使用
    in_app: dict[str, str] = Field(default_factory=dict)


class PrefsPayload(BaseModel):
    nickname: str = Field("词札学习者", max_length=16)
    accent: Literal["us", "uk"] = "us"
    translate_preset: str = Field("", max_length=32)
    reminder: ReminderPrefs = Field(default_factory=ReminderPrefs)
    shortcuts: ShortcutPrefs = Field(default_factory=ShortcutPrefs)


def _prefs_path() -> Path:
    """测试会 patch 这个函数，把文件指到临时目录。"""
    return get_data_dir() / "prefs.json"


def _merge(raw: dict) -> dict:
    """把磁盘上的半截 / 旧版数据补成完整结构，非法字段直接忽略。"""
    data = json.loads(json.dumps(DEFAULT_PREFS))
    if isinstance(raw.get("nickname"), str):
        data["nickname"] = raw["nickname"][:16]
    if raw.get("accent") in ("us", "uk"):
        data["accent"] = raw["accent"]
    if raw.get("translate_preset") in PROMPT_PRESETS:
        data["translate_preset"] = raw["translate_preset"]
    reminder = raw.get("reminder")
    if isinstance(reminder, dict):
        if isinstance(reminder.get("enabled"), bool):
            data["reminder"]["enabled"] = reminder["enabled"]
        if isinstance(reminder.get("time"), str):
            data["reminder"]["time"] = reminder["time"]
        if isinstance(reminder.get("last_notified"), str):
            data["reminder"]["last_notified"] = reminder["last_notified"]
    shortcuts = raw.get("shortcuts")
    if isinstance(shortcuts, dict):
        in_app = shortcuts.get("in_app")
        if isinstance(in_app, dict):
            cleaned = {
                key[:32]: value[:64]
                for key, value in in_app.items()
                if isinstance(key, str) and isinstance(value, str)
            }
            data["shortcuts"]["in_app"] = dict(list(cleaned.items())[:32])
    return data


@router.get("")
def read_prefs() -> dict:
    try:
        raw = json.loads(_prefs_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _merge({})
    return _merge(raw if isinstance(raw, dict) else {})


@router.put("")
def save_prefs(payload: PrefsPayload) -> dict:
    # 走一次 _merge：截断超长键值，并保证旧客户端提交时缺失的新字段有默认值
    data = _merge(payload.model_dump())
    path = _prefs_path()
    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".prefs-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    return data
