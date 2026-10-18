"""词典自动补全 —— 有道词典 jsonapi

原方案 Free Dictionary API (api.dictionaryapi.dev) 在当前网络不可达（TLS 握手超时），
改用有道：https://dict.youdao.com/jsonapi?q={word}
返回英/美音标、中文通用释义、双语例句；免费、无需 Key。
查不到的缩写术语返回 found=False，由用户手动填写。
"""
import json
import socket
import ssl
import urllib.parse
import urllib.request
import urllib.error

from fastapi import APIRouter, HTTPException

from ..schemas import DictionaryResult

router = APIRouter(prefix="/api/dictionary", tags=["词典"])

API_TMPL = "https://dict.youdao.com/jsonapi?q={word}"
TIMEOUT = 6  # 秒, 避免请求过久无响应

# 需要统一兜住的网络异常（含超时/SSL，避免泄漏成 500）
NET_ERRORS = (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError, OSError)


def _fetch(word: str):
    """请求有道词典，返回原始 JSON；调用失败抛 502"""
    url = API_TMPL.format(word=urllib.parse.quote(word))
    req = urllib.request.Request(url, headers={"User-Agent": "DanCiJi/0.3"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except NET_ERRORS as e:
        raise HTTPException(status_code=502, detail=f"词典服务暂时不可用：{e}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="词典服务返回了无法解析的数据")


def _wrap_phonetic(raw: str) -> str:
    """有道返回的音标不带斜杠，这里补成 /.../"""
    raw = (raw or "").strip()
    if not raw:
        return ""
    return raw if raw.startswith("/") else f"/{raw}/"


def _parse_phonetics(data: dict):
    """优先取 ec（中英词典）的英美音标，退化到 simple"""
    uk = us = ""
    for node in ((data.get("ec") or {}).get("word") or []):
        uk = (node.get("ukphone") or "").strip()
        us = (node.get("usphone") or "").strip()
        if uk or us:
            break
    if not uk and not us:
        for node in ((data.get("simple") or {}).get("word") or []):
            uk = (node.get("ukphone") or "").strip()
            us = (node.get("usphone") or "").strip()
            if uk or us:
                break
    return _wrap_phonetic(uk), _wrap_phonetic(us)


def _parse_meanings(data: dict):
    """取中文通用释义（带词性前缀），最多 3 条，单条截断 300 字"""
    lines = []
    for node in ((data.get("ec") or {}).get("word") or []):
        for group in node.get("trs") or []:
            for tr in group.get("tr") or []:
                for text in ((tr.get("l") or {}).get("i") or []):
                    text = text.strip()
                    if text and text not in lines:
                        lines.append(text[:300])
            if len(lines) >= 3:
                break
        break
    return "\n".join(lines[:3])


def _parse_examples(data: dict):
    """取双语例句，最多 3 条，返回 [{en, zh}]"""
    examples = []
    seen = set()
    pairs = ((data.get("blng_sents_part") or {}).get("sentence-pair")) or []
    for pair in pairs:
        en = (pair.get("sentence") or "").strip()
        zh = (pair.get("sentence-translation") or "").strip()
        if en and en not in seen:
            seen.add(en)
            examples.append({"en": en, "zh": zh})
        if len(examples) >= 3:
            break
    return examples


@router.get("/{word}", response_model=DictionaryResult)
def lookup(word: str):
    """查询词典：返回英/美音标、中文通用释义、例句"""
    word = word.strip()
    if not word:
        raise HTTPException(status_code=400, detail="单词不能为空")

    data = _fetch(word)
    uk, us = _parse_phonetics(data)
    api_meaning = _parse_meanings(data)
    examples = _parse_examples(data)

    if not (uk or us or api_meaning):
        return DictionaryResult(
            word=word,
            found=False,
            message="词典未收录该词，可能是缩写或专业术语，请手动填写音标与释义",
        )

    return DictionaryResult(
        word=word,
        found=True,
        phonetic_uk=uk,
        phonetic_us=us,
        api_meaning=api_meaning,
        examples=examples,
    )
