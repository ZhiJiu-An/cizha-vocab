"""大模型领域翻译 —— OpenAI 兼容 SSE 流式代理

模型与提示词都来自运行时配置（设置 → 模型配置），代码不硬编码 Key。
后端做透明代理：把上游 SSE 的 data: 行原样转发给前端；
上游错误（非 200 / 连接失败 / 流中断）统一转成 data: {"error": "..."} 事件，
不泄漏为 500，保证前端能正常收尾。
"""
import json

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..config import build_prompt, get_text_model

router = APIRouter(prefix="/api/translate", tags=["大模型翻译"])

TIMEOUT = 60  # 秒，流式响应整体超时放宽


def _error_event(message: str) -> str:
    """包装成一条 SSE error 事件"""
    return f"data: {json.dumps({'error': message}, ensure_ascii=False)}\n\n"


@router.get("/{word}")
async def translate(word: str):
    """大模型领域翻译，SSE 流式返回"""
    word = word.strip()
    if not word:
        raise HTTPException(status_code=400, detail="单词不能为空")

    card = get_text_model()
    if not card:
        raise HTTPException(
            status_code=400,
            detail="大模型未配置：请在「设置 → 模型配置」里添加一个文本模型并设为默认",
        )

    payload = {
        "model": card["model"],
        "stream": True,
        "messages": [{"role": "user", "content": build_prompt(word, card["prompt"])}],
    }
    headers = {"Authorization": f"Bearer {card['api_key']}"}

    async def event_stream():
        """透明转发上游 SSE 的 data: 行；异常统一转成 error 事件"""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                async with client.stream(
                    "POST", f"{card['base_url']}/chat/completions",
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
