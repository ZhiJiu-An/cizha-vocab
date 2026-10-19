"""大模型配置管理 —— 支持运行时切换，不重启服务

优先级：运行时 JSON 配置（data/llm_config.json） > .env 环境变量
切换后立即生效，translate.py / ocr.py 都从这里取配置。
"""
import json
import os
from pathlib import Path
from typing import Optional

# 运行时配置文件位置（与 SQLite 同目录）
CONFIG_DIR = Path(__file__).resolve().parent.parent / "data"
CONFIG_FILE = CONFIG_DIR / "llm_config.json"


def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_runtime_config() -> Optional[dict]:
    """读取运行时配置文件；不存在或格式错误返回 None"""
    if not CONFIG_FILE.exists():
        return None
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("base_url") and data.get("api_key") and data.get("model"):
            return {
                "base_url": str(data["base_url"]).strip().rstrip("/"),
                "api_key": str(data["api_key"]).strip(),
                "model": str(data["model"]).strip(),
            }
    except (json.JSONDecodeError, OSError):
        return None
    return None


def save_runtime_config(base_url: str, api_key: str, model: str):
    """保存运行时配置到 JSON 文件"""
    _ensure_dir()
    data = {
        "base_url": base_url.strip().rstrip("/"),
        "api_key": api_key.strip(),
        "model": model.strip(),
    }
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_runtime_config():
    """删除运行时配置，回退到 .env 环境变量"""
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()


def get_llm_config() -> Optional[tuple]:
    """获取当前生效的文本模型配置：优先运行时配置，否则 .env

    返回 (base_url, api_key, model)；任一缺失返回 None
    """
    runtime = load_runtime_config()
    if runtime:
        return runtime["base_url"], runtime["api_key"], runtime["model"]

    base_url = os.environ.get("LLM_BASE_URL", "").strip().rstrip("/")
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()
    if not (base_url and api_key and model):
        return None
    return base_url, api_key, model


def get_vision_config() -> Optional[tuple]:
    """获取视觉模型配置：视觉用 .env（本期不做前端切换）

    LLM_VISION_BASE_URL / API_KEY 缺省时回落到文本模型配置
    """
    base_url = os.environ.get("LLM_VISION_BASE_URL", "").strip().rstrip("/")
    api_key = os.environ.get("LLM_VISION_API_KEY", "").strip()
    model = os.environ.get("LLM_VISION_MODEL", "").strip()

    # 回落到文本模型配置（可能来自运行时或 .env）
    text_config = get_llm_config()
    if text_config:
        base_url = base_url or text_config[0]
        api_key = api_key or text_config[1]
    if not (base_url and api_key and model):
        return None
    return base_url, api_key, model


def mask_key(key: str) -> str:
    """脱敏：前 4 后 4，中间用 * 代替"""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"
