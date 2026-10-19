"""图片取词 —— 上传图片交给视觉大模型，提取图中术语 (v0.7)

网页版无法监听全局快捷键 / 截屏，故不做系统级截图取词；
改为在搜索页上传图片（或直接粘贴截图）→ 视觉模型识别 → 返回候选术语，
点击候选词回填搜索框并触发现有双栏查询。

配置走环境变量，代码不硬编码 Key：
  LLM_VISION_MODEL     必填，视觉模型名（如 qwen-vl-max / glm-4v）
  LLM_VISION_BASE_URL  可选，缺省回落 LLM_BASE_URL
  LLM_VISION_API_KEY   可选，缺省回落 LLM_API_KEY
DeepSeek 官方 API 无视觉模型，故支持独立端点以便接任意 OpenAI 兼容视觉服务。
"""
import base64
import json
import os
import re

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Word
from ..schemas import OcrExtractResponse, OcrWordItem

router = APIRouter(prefix="/api/ocr", tags=["图片取词"])

TIMEOUT = 60              # 秒，视觉模型响应较慢，放宽超时
MAX_SIZE = 10 * 1024 * 1024   # 10MB 上限
MAX_WORDS = 15
ALLOWED_MIME = ("image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif", "image/bmp")

# 提取提示词：只出 JSON，便于后端解析
PROMPT = """请从这张图片中提取出与计算机 / 人工智能 / 大模型领域相关的英文单词或短语。
要求：
1. 只提取专业术语、技术名词或领域常见表达，忽略普通词汇、人名、页码等无关文字
2. 保留图片中的原始拼写，明显识别错误可纠正
3. 去重后按重要程度排序，最多 15 条
4. 只输出 JSON 数组，不要任何解释文字或代码块标记
格式：[{"word": "retrieval-augmented generation", "zh": "检索增强生成"}]"""


def _vision_config():
    """读取视觉模型配置；model 缺失返回 None（base/key 可回落到通用 LLM 配置）"""
    base_url = os.environ.get("LLM_VISION_BASE_URL", "").strip().rstrip("/")
    api_key = os.environ.get("LLM_VISION_API_KEY", "").strip()
    model = os.environ.get("LLM_VISION_MODEL", "").strip()

    # 未单独配置视觉端点时，回落到 v0.4 的通用 LLM 配置
    base_url = base_url or os.environ.get("LLM_BASE_URL", "").strip().rstrip("/")
    api_key = api_key or os.environ.get("LLM_API_KEY", "").strip()

    if not (base_url and api_key and model):
        return None
    return base_url, api_key, model


def _parse_words(text: str, collected: set) -> list:
    """从模型输出里解析术语列表：剥掉代码块围栏 → 取首个 JSON 数组 → 清洗去重"""
    text = (text or "").strip()
    # 剥掉 ```json ... ``` 之类的围栏
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    # 只取第一个 [ ... ] 片段，容忍模型加了前后说明
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("模型返回内容中没有 JSON 数组")
    raw = json.loads(text[start:end + 1])
    if not isinstance(raw, list):
        raise ValueError("模型返回的 JSON 不是数组")

    words, seen = [], set()
    for item in raw:
        if isinstance(item, dict):
            word = str(item.get("word") or "").strip()
            zh = str(item.get("zh") or "").strip()
        else:                       # 容忍模型直接返回字符串数组
            word, zh = str(item).strip(), ""
        key = word.lower()
        if not word or key in seen:
            continue
        seen.add(key)
        words.append(OcrWordItem(word=word, zh=zh, in_library=key in collected))
        if len(words) >= MAX_WORDS:
            break
    return words


@router.post("/extract", response_model=OcrExtractResponse)
async def extract(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """上传图片 → 视觉模型识别图中的单词/短语 → 返回候选术语列表"""
    # ---- 入参校验 ----
    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="仅支持图片文件（png / jpg / webp / gif / bmp）")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="图片内容为空")
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="图片过大，请压缩到 10MB 以内")

    config = _vision_config()
    if not config:
        raise HTTPException(
            status_code=400,
            detail="未配置视觉模型：请在 backend/.env 设置 LLM_VISION_MODEL"
                   "（可选 LLM_VISION_BASE_URL / LLM_VISION_API_KEY）后重启服务",
        )
    base_url, api_key, model = config

    # ---- 调用视觉模型（图片转 base64 data URL，不落盘）----
    b64 = base64.b64encode(data).decode("ascii")
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"视觉模型服务连接失败：{e}")

    if resp.status_code != 200:
        body = resp.text[:300]
        raise HTTPException(status_code=502, detail=f"视觉模型服务返回 {resp.status_code}：{body}")

    # ---- 解析模型输出 ----
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as e:
        raise HTTPException(status_code=502, detail=f"视觉模型返回结构异常：{e}")

    # ---- 标注已在词库中的术语（前端标灰显示「已收藏」）----
    collected = {a.lower() for (a,) in db.query(Word.abbreviation).all()}
    try:
        words = _parse_words(content, collected)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=502, detail=f"模型返回内容无法解析：{e}")

    return OcrExtractResponse(total=len(words), words=words)
