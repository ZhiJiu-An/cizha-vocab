"""大模型领域翻译 —— OpenAI 兼容 SSE 流式代理

配置全部走环境变量（LLM_BASE_URL / LLM_API_KEY / LLM_MODEL），代码不硬编码 Key。
后端做透明代理：把上游 SSE 的 data: 行原样转发给前端；
上游错误（非 200 / 连接失败 / 流中断）统一转成 data: {"error": "..."} 事件，
不泄漏为 500，保证前端能正常收尾。
"""
import json
import os

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/translate", tags=["大模型翻译"])

TIMEOUT = 60  # 秒，流式响应整体超时放宽

# 提示词（MVP.md §7.2 定稿）：五段标记输出，前端按【】边收边切段
PROMPT_TMPL = """你是面向大模型/AI 工程师的术语翻译助手，翻译「{word}」。
严格按以下分段输出，每段以【】标记开头，不要输出多余内容：
【定名】通行中文译名，不超过 8 个字；没有通行译名就写「无」
【展开】若该词是缩写则给出英文全称，否则写「无」
【详解】在 AI/大模型工程语境下的含义，2~4 句话
【例句】该领域的一条典型英文例句
【译文】例句的中文翻译"""


def _llm_config():
    """读取环境变量配置；任一缺失返回 None"""
    base_url = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "")
    if not (base_url and api_key and model):
        return None
    return base_url, api_key, model


def _error_event(message: str) -> str:
    """包装成一条 SSE error 事件"""
    return f"data: {json.dumps({'error': message}, ensure_ascii=False)}\n\n"


@router.get("/{word}")
async def translate(word: str):
    """大模型领域翻译，SSE 流式返回"""
    word = word.strip()
    if not word:
        raise HTTPException(status_code=400, detail="单词不能为空")

    config = _llm_config()
    if not config:
        raise HTTPException(
            status_code=400,
            detail="大模型未配置：请设置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 环境变量后重启服务",
        )
    base_url, api_key, model = config

    payload = {
        "model": model,
        "stream": True,
        "messages": [{"role": "user", "content": PROMPT_TMPL.format(word=word)}],
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    async def event_stream():
        """透明转发上游 SSE 的 data: 行；异常统一转成 error 事件"""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                async with client.stream(
                    "POST", f"{base_url}/chat/completions",
                    json=payload, headers=headers,
                ) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", "ignore")[:300]
                        yield _error_event(f"大模型服务返回 {resp.status_code}：{body}")
                        return
                    async for line in resp.aiter_lines():
                        if line.startswith("data:"):
                            yield f"{line}\n\n"
                        # 空行 / 注释行直接跳过
        except httpx.HTTPError as e:
            yield _error_event(f"大模型服务连接失败：{e}")
        except Exception as e:  # 兜底（如流中途断开），避免泄漏为 500
            yield _error_event(f"翻译中断：{e}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
