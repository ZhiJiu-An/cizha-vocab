"""模型配置 API（v0.12）—— 模型列表 / 增删改 / 默认模型 / 连通测试

一个"模型"是一张完整的卡：名称、类型（文本 / 视觉）、地址、Key、模型名，
文本模型额外带提示词（领域预设 + 可微调）。每种类型最多一个默认模型，
翻译与图片取词只使用默认模型。

接口：
- GET    /api/llm/models               模型列表 + 提示词预设
- POST   /api/llm/models               新增（先连通测试，通过才写入）
- PUT    /api/llm/models/{id}          编辑（同样先测后存）
- DELETE /api/llm/models/{id}          删除（自动补位默认模型）
- POST   /api/llm/models/test          仅连通测试，不保存
- POST   /api/llm/models/{id}/default  设为该类型的默认模型（不触发连通测试）

保存 / 测试都会向模型发一次 max_tokens=1 的最小请求，会消耗极少量 token。
"""
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config

router = APIRouter(prefix="/api/llm", tags=["模型配置"])

TEST_TIMEOUT = 20  # 连通性测试超时（秒），视觉模型带图会慢一些

# 32×32 白色 PNG（95 字节）：给视觉模型发一次带图的最小请求，验证它确实接受图片输入。
# 尺寸不能再小 —— 实测端点在宽或高 ≤10px 时直接报 InvalidParameter，
# 那样测出来的是「图片太小」而不是「端点不支持视觉」。
TEST_IMAGE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAJklEQVR42u3NMQ0AAAwDoPo33arYsQQMkB6LQCAQCAQCgUAg+BIMi1X0ptsIcT0AAAAASUVORK5CYII="
)


class ModelIn(BaseModel):
    name: str = ""
    type: str = "text"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    enabled: bool = True
    prompt_preset: str = "llm"
    prompt: str = ""
    # 仅「仅测试连通」使用：带上正在编辑的模型 id 才能还原脱敏 Key
    id: str | None = None


class ModelOut(BaseModel):
    id: str
    name: str
    type: str
    base_url: str
    api_key: str            # 脱敏后
    model: str
    role: str               # default_text / default_vision / ""
    enabled: bool
    order: int
    prompt_preset: str
    prompt: str


class PresetOut(BaseModel):
    key: str
    label: str
    prompt: str


class ModelListOut(BaseModel):
    models: list[ModelOut]
    presets: list[PresetOut]


class TestResult(BaseModel):
    ok: bool
    message: str            # 成功或失败的说明


class SaveResult(TestResult):
    model: ModelOut | None = None


def _masked(card: dict) -> ModelOut:
    return ModelOut(**{**card, "api_key": config.mask_key(card["api_key"])})


def _prepare(data: ModelIn, existing: dict | None) -> tuple[dict, str, str, str]:
    """清洗输入并算出真实生效的地址 / Key

    返回 (要保存的字段, 生效 base_url, 生效 api_key, 错误信息)。

    留空表示「沿用已有值」：前端回传的脱敏 Key 会还原成完整 Key；
    视觉模型的地址 / Key 留空时回落到默认文本模型（两家共用端点）。
    """
    kind = config.normalize_kind(data.type)
    model = (data.model or "").strip()
    base_url = (data.base_url or "").strip().rstrip("/")
    api_key = (data.api_key or "").strip()

    # 脱敏值一律还原；文本模型留空表示沿用已有 Key；视觉模型留空表示回落文本模型
    if "*" in api_key:
        api_key = (existing or {}).get("api_key", "")
    elif not api_key and kind == config.TEXT:
        api_key = (existing or {}).get("api_key", "")
    if not base_url and kind == config.TEXT:
        base_url = (existing or {}).get("base_url", "")

    preset = (data.prompt_preset or "").strip()
    if preset not in config.PROMPT_PRESETS:
        preset = "custom"
    prompt = (data.prompt or "").strip()
    if kind == config.TEXT and not prompt:
        prompt = config.preset_prompt(preset)
    if kind == config.VISION:
        prompt, preset = "", "custom"

    saved = {
        "name": (data.name or "").strip() or model,
        "type": kind,
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "enabled": data.enabled,
        "prompt_preset": preset,
        "prompt": prompt,
    }

    if not model:
        return saved, "", "", "模型名不能为空"

    if kind == config.TEXT:
        if not base_url:
            return saved, "", "", "Base URL 不能为空"
        if not api_key:
            return saved, "", "", "API Key 不能为空"
        error = config.validate_prompt(prompt)
        if error:
            return saved, "", "", error
        return saved, base_url, api_key, ""

    eff_base, eff_key = base_url, api_key
    text_card = config.pick_model(config.TEXT)
    if text_card:
        eff_base = eff_base or text_card["base_url"]
        eff_key = eff_key or text_card["api_key"]
    if not eff_base:
        return saved, "", "", "Base URL 不能为空，且没有可回落的文本模型"
    if not eff_key:
        return saved, "", "", "API Key 不能为空，且没有可回落的文本模型"
    return saved, eff_base, eff_key, ""


async def _test_connection(eff_base: str, eff_key: str, model: str, kind: str) -> TestResult:
    """发一次最小请求验证连通性（会消耗极少量 token）"""
    if kind == config.VISION:
        content = [
            {"type": "text", "text": "hi"},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{TEST_IMAGE_B64}"}},
        ]
    else:
        content = "hi"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 1,        # 只取 1 个 token，最小消耗
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {eff_key}"}

    try:
        async with httpx.AsyncClient(timeout=TEST_TIMEOUT) as client:
            resp = await client.post(
                f"{eff_base}/chat/completions",
                json=payload, headers=headers,
            )
        if resp.status_code == 200:
            return TestResult(ok=True, message="连通测试通过")
        return TestResult(ok=False, message=f"服务返回 {resp.status_code}：{resp.text[:300]}")
    except httpx.HTTPError as e:
        return TestResult(ok=False, message=f"连接失败：{e}")


async def _save(data: ModelIn, model_id: str | None) -> SaveResult:
    """先连通测试再写入，测试失败不落盘"""
    existing = config.get_model(model_id) if model_id else None
    if model_id and not existing:
        raise HTTPException(status_code=404, detail="模型不存在")

    saved, eff_base, eff_key, error = _prepare(data, existing)
    if error:
        return SaveResult(ok=False, message=error)

    result = await _test_connection(eff_base, eff_key, saved["model"], saved["type"])
    if not result.ok:
        return result

    card = config.upsert_model(saved, model_id)
    label = "视觉模型" if card["type"] == config.VISION else "文本模型"
    action = "已保存并立即生效" if existing else "已添加"
    return SaveResult(ok=True, message=f"连通测试通过，{label}「{card['name']}」{action}", model=_masked(card))


@router.get("/models", response_model=ModelListOut)
def list_models():
    """模型列表（api_key 一律脱敏）与文本模型的提示词预设"""
    return ModelListOut(
        models=[_masked(card) for card in config.list_models()],
        presets=[PresetOut(**item) for item in config.prompt_presets()],
    )


@router.post("/models", response_model=SaveResult)
async def create_model(data: ModelIn):
    return await _save(data, None)


@router.put("/models/{model_id}", response_model=SaveResult)
async def update_model(model_id: str, data: ModelIn):
    return await _save(data, model_id)


@router.delete("/models/{model_id}")
def delete_model(model_id: str):
    if not config.delete_model(model_id):
        raise HTTPException(status_code=404, detail="模型不存在")
    return {"message": "模型已删除"}


@router.post("/models/test", response_model=TestResult)
async def test_model(data: ModelIn):
    """仅连通性测试，不保存配置（会消耗极少量 token）"""
    existing = config.get_model(data.id) if data.id else None
    _, eff_base, eff_key, error = _prepare(data, existing)
    if error:
        return TestResult(ok=False, message=error)
    return await _test_connection(eff_base, eff_key, (data.model or "").strip(),
                                  config.normalize_kind(data.type))


@router.post("/models/{model_id}/default", response_model=ModelOut)
def make_default(model_id: str):
    card = config.set_default_model(model_id)
    if not card:
        raise HTTPException(status_code=404, detail="模型不存在")
    return _masked(card)
