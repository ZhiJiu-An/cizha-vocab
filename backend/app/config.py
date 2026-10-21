"""大模型配置管理 —— 模型列表 + 默认角色 + 提示词预设（v0.12）

配置文件：backend/data/llm_config.json

    {
      "version": 2,
      "models": [
        {
          "id": "a1b2c3d4",
          "name": "DeepSeek 翻译",
          "type": "text",              # text 文本模型 / vision 视觉模型
          "base_url": "https://api.deepseek.com",
          "api_key": "sk-...",
          "model": "deepseek-chat",
          "role": "default_text",      # default_text / default_vision / 空
          "enabled": true,
          "order": 0,
          "prompt_preset": "llm",      # llm / cs / medical / finance / custom
          "prompt": "你是面向..."
        }
      ]
    }

- 每种类型最多一个默认模型，翻译 / 图片取词只取默认的那张卡。
- 旧版 {"text": {...}, "vision": {...}} 首次读取时自动迁移成两张卡并回写。
- 配置文件不存在时用 .env 的 LLM_* / LLM_VISION_* 初始化一次；之后 .env 不再参与，
  前端设置页是唯一的配置入口。
- 视觉模型的 base_url / api_key 允许留空，读取时回落到默认文本模型。
"""
import json
import os
import uuid
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "data"
CONFIG_FILE = CONFIG_DIR / "llm_config.json"

SCHEMA_VERSION = 2

TEXT = "text"
VISION = "vision"
KINDS = (TEXT, VISION)

ROLE_TEXT = "default_text"
ROLE_VISION = "default_vision"
ROLES = (ROLE_TEXT, ROLE_VISION)
ROLE_FOR_KIND = {TEXT: ROLE_TEXT, VISION: ROLE_VISION}

_FIELDS = ("base_url", "api_key", "model")
_ENV_PREFIX = {TEXT: "LLM_", VISION: "LLM_VISION_"}

# 五段骨架：自定义提示词可以改语境，但不能删掉任何一段，否则前端无法切段渲染
PROMPT_MARKERS = ("【定名】", "【展开】", "【详解】", "【例句】", "【译文】")
WORD_PLACEHOLDER = "{word}"

PROMPT_PRESETS = {
    "llm": {
        "label": "大模型 / AI",
        "prompt": """你是面向大模型 / AI 工程师的术语翻译助手，翻译「{word}」。
严格按以下分段输出，每段以【】标记开头，不要输出多余内容：
【定名】通行中文译名，不超过 8 个字；没有通行译名就写「无」
【展开】若该词是缩写则给出英文全称，否则写「无」
【详解】在 AI / 大模型工程语境下的含义，2~4 句话
【例句】该领域的一条典型英文例句
【译文】例句的中文翻译""",
    },
    "cs": {
        "label": "计算机 / 软件",
        "prompt": """你是面向软件工程师的术语翻译助手，翻译「{word}」。
严格按以下分段输出，每段以【】标记开头，不要输出多余内容：
【定名】通行中文译名，不超过 8 个字；没有通行译名就写「无」
【展开】若该词是缩写则给出英文全称，否则写「无」
【详解】在计算机 / 软件工程语境下的含义，2~4 句话
【例句】该领域的一条典型英文例句
【译文】例句的中文翻译""",
    },
    "medical": {
        "label": "医学 / 医药",
        "prompt": """你是面向医学研究者的术语翻译助手，翻译「{word}」。
严格按以下分段输出，每段以【】标记开头，不要输出多余内容：
【定名】通行中文译名，不超过 8 个字；没有通行译名就写「无」
【展开】若该词是缩写则给出英文全称，否则写「无」
【详解】在医学 / 生物医药语境下的含义，2~4 句话
【例句】该领域的一条典型英文例句
【译文】例句的中文翻译""",
    },
    "finance": {
        "label": "金融 / 投资",
        "prompt": """你是面向金融从业者的术语翻译助手，翻译「{word}」。
严格按以下分段输出，每段以【】标记开头，不要输出多余内容：
【定名】通行中文译名，不超过 8 个字；没有通行译名就写「无」
【展开】若该词是缩写则给出英文全称，否则写「无」
【详解】在金融 / 投资语境下的含义，2~4 句话
【例句】该领域的一条典型英文例句
【译文】例句的中文翻译""",
    },
    "custom": {
        "label": "自定义",
        "prompt": "",
    },
}


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


def _write_models(models: list[dict]):
    _write_all({"version": SCHEMA_VERSION, "models": models})


def _from_env(kind: str) -> dict:
    prefix = _ENV_PREFIX.get(kind, _ENV_PREFIX[TEXT])
    return {
        "base_url": os.environ.get(f"{prefix}BASE_URL", "").strip().rstrip("/"),
        "api_key": os.environ.get(f"{prefix}API_KEY", "").strip(),
        "model": os.environ.get(f"{prefix}MODEL", "").strip(),
    }


def normalize_kind(kind: str | None) -> str:
    """非法类型一律按文本模型处理，避免脏参数导致 500"""
    return kind if kind in KINDS else TEXT


def preset_prompt(key: str) -> str:
    """取预设提示词；未知 / custom 返回空串"""
    preset = PROMPT_PRESETS.get(key or "")
    return preset["prompt"] if preset else ""


def prompt_presets() -> list[dict]:
    """前端提示词选择器用：key + 中文标签 + 预设正文"""
    return [
        {"key": key, "label": item["label"], "prompt": item["prompt"]}
        for key, item in PROMPT_PRESETS.items()
    ]


def validate_prompt(prompt: str) -> str:
    """自定义提示词校验：五段骨架与 {word} 占位符都不能少

    返回错误信息；通过时返回空串。
    """
    text = (prompt or "").strip()
    if not text:
        return "提示词不能为空"
    if WORD_PLACEHOLDER not in text:
        return "提示词缺少 {word} 占位符（查询的单词会替换到这里）"
    missing = [marker for marker in PROMPT_MARKERS if marker not in text]
    if missing:
        return f"提示词缺少分段标记：{'、'.join(missing)}"
    return ""


def build_prompt(word: str, prompt: str) -> str:
    """把 {word} 替换成查询词；用 replace 而非 format，避免自定义提示词里的花括号报错"""
    return (prompt or preset_prompt("llm")).replace(WORD_PLACEHOLDER, word)


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _clean_model(raw: dict, index: int = 0) -> dict:
    """把一条模型卡归一化：类型 / 角色 / 字段 / 提示词"""
    raw = raw if isinstance(raw, dict) else {}
    kind = VISION if str(raw.get("type") or "").strip() == VISION else TEXT

    role = str(raw.get("role") or "").strip()
    if role not in ROLES or role != ROLE_FOR_KIND[kind]:
        role = ""

    preset = str(raw.get("prompt_preset") or "").strip()
    if preset not in PROMPT_PRESETS:
        preset = "custom" if str(raw.get("prompt") or "").strip() else "llm"

    prompt = str(raw.get("prompt") or "").strip()
    if kind == TEXT and not prompt:
        prompt = preset_prompt(preset)

    model = str(raw.get("model") or "").strip()
    name = str(raw.get("name") or "").strip() or model or ("视觉模型" if kind == VISION else "文本模型")

    try:
        order = int(raw.get("order"))
    except (TypeError, ValueError):
        order = index

    return {
        "id": str(raw.get("id") or "").strip() or _new_id(),
        "name": name,
        "type": kind,
        "base_url": str(raw.get("base_url") or "").strip().rstrip("/"),
        "api_key": str(raw.get("api_key") or "").strip(),
        "model": model,
        "role": role,
        "enabled": raw.get("enabled") is not False,
        "order": order,
        "prompt_preset": preset,
        "prompt": prompt,
    }


def _ensure_ids(models: list[dict]):
    """补齐 / 去重 id，保证前端能稳定引用每张卡"""
    seen = set()
    for item in models:
        if not item["id"] or item["id"] in seen:
            item["id"] = _new_id()
        seen.add(item["id"])


def _ensure_defaults(models: list[dict]):
    """每种类型保证有且只有一个默认角色（优先当前默认，其次第一张卡）"""
    for kind, role in ROLE_FOR_KIND.items():
        same = [m for m in models if m["type"] == kind]
        holders = [m for m in same if m["role"] == role]
        for extra in holders[1:]:
            extra["role"] = ""
        if not holders and same:
            candidates = [m for m in same if m["enabled"]] or same
            candidates[0]["role"] = role


def _migrate_legacy(data: dict) -> list[dict]:
    """旧版 {"text": {...}, "vision": {...}} → 模型列表"""
    models = []
    for kind, role in ((TEXT, ROLE_TEXT), (VISION, ROLE_VISION)):
        section = data.get(kind)
        section = section if isinstance(section, dict) else {}
        if not str(section.get("model") or "").strip():
            continue
        models.append(_clean_model({
            **section,
            "type": kind,
            "role": role,
            "prompt_preset": "llm" if kind == TEXT else "custom",
        }, len(models)))
    return models


def _bootstrap_from_env() -> list[dict]:
    """首次初始化：.env 里有可用配置时生成默认卡"""
    models = []
    text = _from_env(TEXT)
    if all(text[field] for field in _FIELDS):
        models.append(_clean_model({
            **text, "type": TEXT, "role": ROLE_TEXT, "prompt_preset": "llm",
        }, len(models)))

    vision = _from_env(VISION)
    if vision["model"]:
        models.append(_clean_model({
            **vision, "type": VISION, "role": ROLE_VISION, "prompt_preset": "custom",
        }, len(models)))
    return models


def list_models() -> list[dict]:
    """读取全部模型卡（含旧结构迁移 / .env 首次初始化）"""
    if not CONFIG_FILE.exists():
        models = _bootstrap_from_env()
        if models:
            _write_models(models)
        return models

    data = _read_all()
    raw_models = data.get("models")
    if isinstance(raw_models, list):
        models = [_clean_model(item, i) for i, item in enumerate(raw_models)]
    else:
        models = _migrate_legacy(data)
        if models:
            _write_models(models)          # 迁移结果只写一次，之后走列表格式
    models = sorted(models, key=lambda m: m["order"])
    _ensure_ids(models)
    return models


def get_model(model_id: str) -> dict | None:
    return next((m for m in list_models() if m["id"] == model_id), None)


def pick_model(kind: str) -> dict | None:
    """取该类型当前生效的模型：默认角色优先，否则第一张启用的卡"""
    kind = normalize_kind(kind)
    same = [m for m in list_models() if m["type"] == kind and m["enabled"]]
    if not same:
        return None
    role = ROLE_FOR_KIND[kind]
    return next((m for m in same if m["role"] == role), same[0])


def get_text_model() -> dict | None:
    """当前生效的文本模型完整卡（含提示词）；字段不全的卡会被跳过"""
    cards = [
        m for m in list_models()
        if m["type"] == TEXT and m["enabled"] and all(m[field] for field in _FIELDS)
    ]
    if not cards:
        return None
    return next((m for m in cards if m["role"] == ROLE_TEXT), cards[0])


def get_llm_config() -> tuple | None:
    """兼容旧调用方：返回 (base_url, api_key, model)"""
    card = get_text_model()
    if not card:
        return None
    return card["base_url"], card["api_key"], card["model"]


def get_vision_config() -> tuple | None:
    """当前生效的视觉模型配置

    视觉模型的地址 / Key 允许留空，留空时回落到默认文本模型（两家可共用端点）；
    model 必须显式配置 —— 文本模型一般不接受图片输入。
    """
    cards = [
        m for m in list_models()
        if m["type"] == VISION and m["enabled"] and m["model"]
    ]
    if not cards:
        return None
    card = next((m for m in cards if m["role"] == ROLE_VISION), cards[0])

    text_config = get_llm_config()
    base_url = card["base_url"] or (text_config[0] if text_config else "")
    api_key = card["api_key"] or (text_config[1] if text_config else "")
    if not (base_url and api_key):
        return None
    return base_url, api_key, card["model"]


def upsert_model(payload: dict, model_id: str | None = None) -> dict:
    """新增（model_id=None）或更新一条模型卡；不存在时抛 KeyError

    payload 是已经清洗过字段的 dict（提示词已校验），这里只处理结构。
    """
    models = list_models()
    existing = next((m for m in models if m["id"] == model_id), None)
    if model_id and not existing:
        raise KeyError(model_id)

    merged = {**(existing or {}), **payload}
    merged["id"] = model_id or _new_id()
    if not existing:
        merged["order"] = max((m["order"] for m in models), default=-1) + 1
        merged["role"] = ""

    card = _clean_model(merged, len(models))
    if existing:
        models = [card if m["id"] == model_id else m for m in models]
    else:
        models.append(card)

    _ensure_defaults(models)
    _write_models(models)
    return next(m for m in models if m["id"] == card["id"])


def set_default_model(model_id: str) -> dict | None:
    """把某张卡设为所属类型的默认模型；返回更新后的卡，找不到返回 None"""
    models = list_models()
    card = next((m for m in models if m["id"] == model_id), None)
    if not card:
        return None

    role = ROLE_FOR_KIND[card["type"]]
    for item in models:
        if item["role"] == role:
            item["role"] = ""
    card["role"] = role
    card["enabled"] = True
    _write_models(models)
    return card


def delete_model(model_id: str) -> bool:
    """删除模型卡；删掉默认卡时自动把同类型的下一张设为默认"""
    models = list_models()
    remaining = [m for m in models if m["id"] != model_id]
    if len(remaining) == len(models):
        return False

    _ensure_defaults(remaining)
    _write_models(remaining)
    return True


def mask_key(key: str) -> str:
    """脱敏：前 4 后 4，中间用 * 代替"""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"
