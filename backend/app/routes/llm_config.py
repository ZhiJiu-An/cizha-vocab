"""大模型配置管理 —— 前端可切换模型，无需重启服务

接口：
- GET  /api/llm/config        获取当前生效配置（api_key 脱敏 + 来源标记）
- PUT  /api/llm/config        保存配置（保存前自动连通性测试，失败则不保存）
- POST /api/llm/test          连通性测试（不保存）
- DELETE /api/llm/config      删除运行时配置，回退到 .env
"""
import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from ..config import (
    clear_runtime_config,
    get_llm_config,
    load_runtime_config,
    mask_key,
    save_runtime_config,
)

router = APIRouter(prefix="/api/llm", tags=["大模型配置"])

TEST_TIMEOUT = 15  # 连通性测试超时（秒）


class LlmConfigIn(BaseModel):
    base_url: str
    api_key: str
    model: str


class LlmConfigOut(BaseModel):
    base_url: str
    api_key: str            # 脱敏后
    model: str
    source: str             # runtime / env
    has_runtime: bool       # 是否存在运行时配置


class TestResult(BaseModel):
    ok: bool
    message: str            # 成功或失败的说明


def _normalize(base_url: str, api_key: str, model: str):
    """清洗输入，返回 (base_url, api_key, model)"""
    return (
        base_url.strip().rstrip("/"),
        api_key.strip(),
        model.strip(),
    )


async def _test_connection(base_url: str, api_key: str, model: str) -> TestResult:
    """向 /chat/completions 发最小请求验证连通性（会消耗极少量 token）"""
    if not (base_url and api_key and model):
        return TestResult(ok=False, message="base_url / api_key / model 均不能为空")

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,        # 只取 1 个 token，最小消耗
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        async with httpx.AsyncClient(timeout=TEST_TIMEOUT) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                json=payload, headers=headers,
            )
        if resp.status_code == 200:
            return TestResult(ok=True, message="连通测试通过")
        body = resp.text[:300]
        return TestResult(ok=False, message=f"服务返回 {resp.status_code}：{body}")
    except httpx.HTTPError as e:
        return TestResult(ok=False, message=f"连接失败：{e}")


@router.get("/config", response_model=LlmConfigOut)
def get_config():
    """获取当前生效的配置（api_key 脱敏，不返回明文）"""
    config = get_llm_config()
    if not config:
        return LlmConfigOut(
            base_url="", api_key="", model="", source="none", has_runtime=False,
        )
    base_url, api_key, model = config
    runtime = load_runtime_config()
    source = "runtime" if runtime else "env"
    return LlmConfigOut(
        base_url=base_url,
        api_key=mask_key(api_key),
        model=model,
        source=source,
        has_runtime=runtime is not None,
    )


@router.put("/config", response_model=TestResult)
async def put_config(data: LlmConfigIn):
    """保存配置：先做连通性测试，通过才写入；失败则不保存"""
    base_url, api_key, model = _normalize(data.base_url, data.api_key, data.model)

    # 处理脱敏 key：前端传回的 key 若含 '*'，说明用户没改 key，保留旧值
    if "*" in api_key:
        runtime = load_runtime_config()
        if runtime:
            api_key = runtime["api_key"]
        else:
            # 没有运行时配置，无法还原旧 key，要求重填
            return TestResult(ok=False, message="API Key 已脱敏，请重新填写完整的 Key")

    # 连通性测试（自动，不消耗太多 token）
    result = await _test_connection(base_url, api_key, model)
    if not result.ok:
        return result

    save_runtime_config(base_url, api_key, model)
    return TestResult(ok=True, message="连通测试通过，配置已保存并立即生效")


@router.post("/test", response_model=TestResult)
async def test_config(data: LlmConfigIn):
    """仅连通性测试，不保存配置（会消耗极少量 token）"""
    base_url, api_key, model = _normalize(data.base_url, data.api_key, data.model)

    # 脱敏 key 处理同上
    if "*" in api_key:
        runtime = load_runtime_config()
        if runtime:
            api_key = runtime["api_key"]
        else:
            return TestResult(ok=False, message="API Key 已脱敏，请重新填写完整的 Key")

    return await _test_connection(base_url, api_key, model)


@router.delete("/config")
def delete_config():
    """删除运行时配置，回退到 .env 环境变量"""
    clear_runtime_config()
    return {"message": "已清除运行时配置，回退到 .env 环境变量"}
