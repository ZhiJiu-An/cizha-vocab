"""请求 / 响应模型 (v0.4)"""
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List


# ========== 例句（双语） ==========
class ExampleItem(BaseModel):
    en: str = ""    # 英文原句
    zh: str = ""    # 中文翻译


# ========== 词条 ==========
class WordCreate(BaseModel):
    abbreviation: str                            # 缩写或主词（必填）
    full_name: Optional[str] = ""                 # 全称
    cn_term: Optional[str] = ""                   # 中文定名，如 词元
    phonetic_uk: Optional[str] = ""               # 英式音标
    phonetic_us: Optional[str] = ""               # 美式音标
    my_meaning: str                               # ⭐ 我的理解（必填）
    domain_detail: Optional[str] = ""             # 领域详解（大模型生成，长段）
    api_meaning: Optional[str] = ""               # 通用释义
    examples: Optional[List[ExampleItem]] = []    # 例句 [{en, zh}]
    tags: Optional[str] = ""                      # 标签，逗号分隔
    note: Optional[str] = ""                      # 备注


class WordUpdate(BaseModel):
    abbreviation: Optional[str] = None
    full_name: Optional[str] = None
    cn_term: Optional[str] = None
    phonetic_uk: Optional[str] = None
    phonetic_us: Optional[str] = None
    my_meaning: Optional[str] = None
    domain_detail: Optional[str] = None
    api_meaning: Optional[str] = None
    examples: Optional[List[ExampleItem]] = None
    tags: Optional[str] = None
    note: Optional[str] = None


class WordResponse(BaseModel):
    id: int
    abbreviation: str
    full_name: str = ""
    cn_term: str = ""
    phonetic_uk: str = ""
    phonetic_us: str = ""
    my_meaning: str
    domain_detail: str = ""
    api_meaning: str = ""
    examples: List[ExampleItem] = []
    tags: str = ""
    note: str = ""
    has_abbr: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WordListResponse(BaseModel):
    total: int
    items: List[WordResponse]


# ========== 标签 ==========
class TagItem(BaseModel):
    name: str
    count: int


# ========== 词典自动补全 ==========
class DictionaryResult(BaseModel):
    word: str
    found: bool                          # 是否在词典中查到
    message: Optional[str] = None        # 未查到时的提示
    phonetic_uk: str = ""                # 英式音标
    phonetic_us: str = ""                # 美式音标
    api_meaning: str = ""                # 通用释义（中文，按词性分组）
    examples: List[ExampleItem] = []     # 双语例句 [{en, zh}]
