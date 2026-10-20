"""大模型配置管理 —— 支持运行时切换，不重启服务

优先级：运行时 JSON 配置（data/llm_config.json） > .env 环境变量

文件结构为两个互相独立的区块，互不影响：
    {"text": {...}, "vision": {...}}

- text   文本模型（翻译、领域详解），三个字段必须齐全
- vision 视觉模型（图片取词），只要求 model，base_url / api_key 可留空，
         留空时在 get_vision_config() 里按序回落，便于与文本模型共用同一端点

切换后立即生效，translate.py / ocr.py 都从这里取配置。
"""
import json
import os
from pathlib import Path

# 运行时配置文件位置（与 SQLite 同目录）
CONFIG_DIR = Path(__file__).resolve().parent.parent / "data"
CONFIG_FILE = CONFIG_DIR / "llm_config.json"

# 配置区块标识
TEXT = "text"
VISION = "vision"
KINDS = (TEXT, VISION)

_FIELDS = ("base_url", "api_key", "model")

# 环境变量名（区块 -> 变量名前缀）
_ENV_PREFIX = {TEXT: "LLM_", VISION: "LLM_VISION_"}


def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _read_all() -> dict:
    """读取整个配置文件；不存在或损坏时返回空 dict"""
    if not CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_all(data: dict):
    _ensure_dir()
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean_fields(raw) -> dict:
    """把一个区块的三个字段统一去空格；缺失按空串处理"""
    raw = raw if isinstance(raw, dict) else {}
    return {
        "base_url": str(raw.get("base_url") or "").strip().rstrip("/"),
        "api_key": str(raw.get("api_key") or "").strip(),
        "model": str(raw.get("model") or "").strip(),
    }


def _from_env(kind: str) -> dict:
    """从环境变量读一个区块"""
    prefix = _ENV_PREFIX.get(kind, _ENV_PREFIX[TEXT])
    return {
        "base_url": os.environ.get(f"{prefix}BASE_URL", "").strip().rstrip("/"),
        "api_key": os.environ.get(f"{prefix}API_KEY", "").strip(),
        "model": os.environ.get(f"{prefix}MODEL", "").strip(),
    }


def normalize_kind(kind: str) -> str:
    """非法 kind 一律落到 text，避免脏参数导致 500"""
    return kind if kind in KINDS else TEXT


def load_runtime_config(kind: str = TEXT) -> dict | None:
    """读取运行时区块，字段不全按未配置处理

    文本模型要求三个字段齐全（没有可回落对象）；
    视觉模型只要求 model（地址 / Key 可留空，读取时再回落）。
    """
    section = _clean_fields(_read_all().get(kind))
    required = ("model",) if kind == VISION else _FIELDS
    if all(section[field] for field in required):
        return section
    return None


def save_runtime_config(kind: str, base_url: str, api_key: str, model: str):
    """写入指定区块，保留另一区块不受影响；字段允许为空串"""
    data = _read_all()
    data[kind] = {
        "base_url": (base_url or "").strip().rstrip("/"),
        "api_key": (api_key or "").strip(),
        "model": (model or "").strip(),
    }
    _write_all(data)


def clear_runtime_config(kind: str = TEXT):
    """删除指定区块；文件里已无任何区块时一并删掉文件"""
    data = _read_all()
    data.pop(kind, None)
    if data:
        _write_all(data)
    elif CONFIG_FILE.exists():
        CONFIG_FILE.unlink()


def runtime_state(kind: str) -> dict:
    """设置页回显用：返回该区块的**显式**配置（不含回落）+ 来源标记

    source: runtime 运行时配置 / env 环境变量 / none 未配置
    """
    runtime = load_runtime_config(kind)
    if runtime:
        return {**runtime, "source": "runtime", "has_runtime": True}

    section = _from_env(kind)
    source = "env" if section["model"] else "none"
    return {**section, "source": source, "has_runtime": False}


def get_llm_config() -> tuple | None:
    """获取当前生效的文本模型配置：运行时配置优先，否则 .env

    返回 (base_url, api_key, model)；任一缺失返回 None
    """
    runtime = load_runtime_config(TEXT)
    if runtime:
        return runtime["base_url"], runtime["api_key"], runtime["model"]

    section = _from_env(TEXT)
    if not all(section[field] for field in _FIELDS):
        return None
    return section["base_url"], section["api_key"], section["model"]


def get_vision_config() -> tuple | None:
    """获取当前生效的视觉模型配置

    顺序：运行时 vision 区块 > .env 的 LLM_VISION_*
    地址与 Key 缺省时继续回落到文本模型配置（两者可共用一个端点）。
    model 必须显式配置 —— 文本模型一般不接受图片输入。

    回落顺序与 fallback_credentials() 保持一致：保存时按什么顺序取生效值，
    运行时就按什么顺序取，否则「测试通过」的端点与实际调用端点会不一致。
    """
    runtime = load_runtime_config(VISION)
    env_section = _from_env(VISION)
    text_config = get_llm_config()

    base_url = (runtime["base_url"] if runtime else "") or env_section["base_url"]
    api_key = (runtime["api_key"] if runtime else "") or env_section["api_key"]
    model = runtime["model"] if runtime else env_section["model"]

    if text_config:
        base_url = base_url or text_config[0]
        api_key = api_key or text_config[1]

    if not (base_url and api_key and model):
        return None
    return base_url, api_key, model


def fallback_credentials(kind: str) -> tuple:
    """表单里地址 / Key 留空时该用的值（不含该区块自身的运行时配置）

    刻意不读运行时区块：正在被覆盖的那份配置不该当作自己的回落源。
    - 视觉模型：.env 的 LLM_VISION_* 优先，其次回落到文本模型（可共用端点）
    - 文本模型：直接取 .env 的 LLM_*
    """
    section = _from_env(kind)
    if kind != VISION:
        return section["base_url"], section["api_key"]

    text_config = get_llm_config()
    base_url = section["base_url"] or (text_config[0] if text_config else "")
    api_key = section["api_key"] or (text_config[1] if text_config else "")
    return base_url, api_key


def current_api_key(kind: str) -> str:
    """取该区块当前真正生效的 api_key

    用于「前端回传的是脱敏值」时还原成完整 Key —— 依次尝试
    运行时区块 > 环境变量 > 视觉模型回落文本模型。
    """
    runtime = load_runtime_config(kind)
    if runtime and runtime["api_key"]:
        return runtime["api_key"]

    if kind == VISION:
        config = get_vision_config()
    else:
        config = get_llm_config()
    return config[1] if config else ""


def mask_key(key: str) -> str:
    """脱敏：前 4 后 4，中间用 * 代替"""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"
