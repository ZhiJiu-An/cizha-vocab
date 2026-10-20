"""大模型配置管理 —— 前端可切换模型，无需重启服务

支持两套彼此独立的配置，用 `kind` 查询参数区分：
- `text`   文本模型（翻译、领域详解）
- `vision` 视觉模型（图片取词）

接口：
- GET    /api/llm/config?kind=text|vision  获取当前配置（api_key 脱敏 + 来源标记）
- PUT    /api/llm/config?kind=...          保存配置（保存前自动连通性测试，失败则不保存）
- POST   /api/llm/test?kind=...            仅连通性测试，不保存
- DELETE /api/llm/config?kind=...          只清除该区块的运行时配置，回退到 .env

视觉模型的 Base URL / API Key 允许留空 —— 留空即「与文本模型共用」，
读取时自动回落，因此在设置页可以只填一个模型名就完成切换。
"""
import httpx
from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..config import (
    VISION,
    clear_runtime_config,
    current_api_key,
    fallback_credentials,
    load_runtime_config,
    mask_key,
    normalize_kind,
    runtime_state,
    save_runtime_config,
)

router = APIRouter(prefix="/api/llm", tags=["大模型配置"])

TEST_TIMEOUT = 20  # 连通性测试超时（秒），视觉模型带图会慢一些

# 32×32 白色 PNG（95 字节）：给视觉模型发一次带图的最小请求，验证它确实接受图片输入。
# 尺寸不能再小 —— 实测端点在宽或高 ≤10px 时直接报 InvalidParameter，
# 那样测出来的是「图片太小」而不是「端点不支持视觉」。
TEST_IMAGE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAJklEQVR42u3NMQ0AAAwDoPo33arYsQQMkB6LQCAQCAQCgUAg+BIMi1X0ptsIcT0AAAAASUVORK5CYII="
)


class LlmConfigIn(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""


class LlmConfigOut(BaseModel):
    base_url: str
    api_key: str            # 脱敏后
    model: str
    source: str             # runtime / env / none
    has_runtime: bool       # 该区块是否存在运行时配置


class TestResult(BaseModel):
    ok: bool
    message: str            # 成功或失败的说明


def _prepare(data: LlmConfigIn, kind: str) -> tuple:
    """清洗输入并算出「要保存的值」与「用于测试的生效值」

    返回 (保存用 base_url, 保存用 api_key, 生效 base_url, 生效 api_key, 错误信息)。
    区分两者是必须的：用户留空表示「沿用当前生效值」，而连通测试必须拿真实生效值去试。
    """
    base_url = data.base_url.strip().rstrip("/")
    api_key = data.api_key.strip()
    model = data.model.strip()

    # 前端回显的是脱敏 Key，用户没改动时会带回含 * 的值 → 还原成当前真正生效的 Key
    if "*" in api_key:
        api_key = current_api_key(kind)

    # 留空的字段按回落链补齐（视觉模型会依次尝试 LLM_VISION_* 与文本模型配置）
    eff_base, eff_key = fallback_credentials(kind)
    eff_base = base_url or eff_base
    eff_key = api_key or eff_key

    if not model:
        message = "视觉模型名不能为空" if kind == VISION else "模型名不能为空"
        return base_url, api_key, eff_base, eff_key, message
    if not eff_base:
        return base_url, api_key, eff_base, eff_key, "Base URL 不能为空，且没有可回落的文本模型配置"
    if not eff_key:
        return base_url, api_key, eff_base, eff_key, "API Key 不能为空，且没有可回落的配置"
    return base_url, api_key, eff_base, eff_key, ""


async def _test_connection(eff_base: str, eff_key: str, model: str, kind: str) -> TestResult:
    """发一次最小请求验证连通性（会消耗极少量 token）"""
    if kind == VISION:
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


@router.get("/config", response_model=LlmConfigOut)
def get_config(kind: str = Query("text")):
    """获取指定区块的配置（api_key 脱敏，不返回明文）"""
    state = runtime_state(normalize_kind(kind))
    return LlmConfigOut(
        base_url=state["base_url"],
        api_key=mask_key(state["api_key"]) if state["api_key"] else "",
        model=state["model"],
        source=state["source"],
        has_runtime=state["has_runtime"],
    )


@router.put("/config", response_model=TestResult)
async def put_config(data: LlmConfigIn, kind: str = Query("text")):
    """保存配置：先做连通性测试，通过才写入；失败则不保存"""
    kind = normalize_kind(kind)
    saved_base, saved_key, eff_base, eff_key, error = _prepare(data, kind)
    if error:
        return TestResult(ok=False, message=error)

    result = await _test_connection(eff_base, eff_key, data.model.strip(), kind)
    if not result.ok:
        return result

    # 保存用户真正填写的值：留空的字段保持为空，让「回落」在读取时动态生效
    save_runtime_config(kind, saved_base, saved_key, data.model.strip())
    label = "视觉模型" if kind == VISION else "文本模型"
    return TestResult(ok=True, message=f"连通测试通过，{label}配置已保存并立即生效")


@router.post("/test", response_model=TestResult)
async def test_config(data: LlmConfigIn, kind: str = Query("text")):
    """仅连通性测试，不保存配置（会消耗极少量 token）"""
    kind = normalize_kind(kind)
    _, _, eff_base, eff_key, error = _prepare(data, kind)
    if error:
        return TestResult(ok=False, message=error)
    return await _test_connection(eff_base, eff_key, data.model.strip(), kind)


@router.delete("/config")
def delete_config(kind: str = Query("text")):
    """只清除指定区块的运行时配置，回退到 .env；另一区块不受影响"""
    kind = normalize_kind(kind)
    existed = load_runtime_config(kind) is not None
    clear_runtime_config(kind)
    label = "视觉模型" if kind == VISION else "文本模型"
    if existed:
        return {"message": f"已清除运行时{label}配置，回退到 .env 环境变量"}
    return {"message": f"运行时{label}配置本就为空，无需清除"}
