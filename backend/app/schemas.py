"""请求 / 响应模型 (v0.7)"""
from pydantic import BaseModel
from datetime import datetime


# ========== 例句（双语） ==========
class ExampleItem(BaseModel):
    en: str = ""    # 英文原句
    zh: str = ""    # 中文翻译


# ========== 词条 ==========
class WordCreate(BaseModel):
    abbreviation: str                            # 缩写或主词（必填）
    full_name: str | None = ""                 # 全称
    cn_term: str | None = ""                   # 中文定名，如 词元
    phonetic_uk: str | None = ""               # 英式音标
    phonetic_us: str | None = ""               # 美式音标
    my_meaning: str                               # ⭐ 我的理解（必填）
    domain_detail: str | None = ""             # 领域详解（大模型生成，长段）
    api_meaning: str | None = ""               # 通用释义
    examples: list[ExampleItem] | None = []    # 例句 [{en, zh}]
    tags: str | None = ""                      # 标签，逗号分隔
    note: str | None = ""                      # 备注


class WordUpdate(BaseModel):
    abbreviation: str | None = None
    full_name: str | None = None
    cn_term: str | None = None
    phonetic_uk: str | None = None
    phonetic_us: str | None = None
    my_meaning: str | None = None
    domain_detail: str | None = None
    api_meaning: str | None = None
    examples: list[ExampleItem] | None = None
    tags: str | None = None
    note: str | None = None


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
    examples: list[ExampleItem] = []
    tags: str = ""
    note: str = ""
    has_abbr: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class WordListResponse(BaseModel):
    total: int
    items: list[WordResponse]


# ========== 标签 ==========
class TagItem(BaseModel):
    name: str
    count: int


# ========== 词典自动补全 ==========
class DictionaryResult(BaseModel):
    word: str
    found: bool                          # 是否在词典中查到
    message: str | None = None        # 未查到时的提示
    phonetic_uk: str = ""                # 英式音标
    phonetic_us: str = ""                # 美式音标
    api_meaning: str = ""                # 通用释义（中文，按词性分组）
    examples: list[ExampleItem] = []     # 双语例句 [{en, zh}]


# ========== 记忆复习 ==========
class ReviewAnswerIn(BaseModel):
    result: str                          # remember / fuzzy / forget


class ReviewAnswerOut(BaseModel):
    word_id: int
    review_stage: int                    # 自评后档位
    next_review_at: datetime
    last_reviewed_at: datetime


class ReviewOverview(BaseModel):
    due_today: int                       # 今日到期数
    reviewed_today: int                  # 今日已复习数（按 distinct word_id）
    total_in_queue: int                  # 复习队列总词条数


class ReviewWordItem(WordResponse):
    """到期词条 = 词条全量字段 + 复习状态"""
    review_stage: int = 0
    next_review_at: datetime | None = None
    last_reviewed_at: datetime | None = None
    review_count: int = 0


class ReviewDueResponse(BaseModel):
    total_due: int
    items: list[ReviewWordItem]


# ========== 学习统计 ==========
class StatsTotals(BaseModel):
    total_words: int = 0                 # 累计词条数
    week_new: int = 0                    # 近 7 天新增
    total_reviews: int = 0               # 累计复习打卡次数
    reviewed_today: int = 0              # 今日已复习（distinct word_id）


class TagDistItem(BaseModel):
    name: str
    count: int


class DailyTrendItem(BaseModel):
    date: str                            # MM-DD
    new_words: int = 0                   # 当日新增词条数
    reviews: int = 0                     # 当日复习打卡次数


class StageDistItem(BaseModel):
    stage: int                           # 档位 0~5
    days: int                            # 对应间隔天数 [1,2,4,7,15,30]
    count: int = 0                       # 该档词条数


class StatsSummary(BaseModel):
    totals: StatsTotals
    tag_distribution: list[TagDistItem]
    daily_trend: list[DailyTrendItem]
    stage_distribution: list[StageDistItem]


# ========== 图片取词 ==========
class OcrWordItem(BaseModel):
    word: str                            # 识别出的单词 / 短语
    zh: str = ""                         # 中文意思（模型附带，便于用户挑选）
    in_library: bool = False             # 是否已在词库中（前端标灰显示「已收藏」）


class OcrExtractResponse(BaseModel):
    total: int
    original_text: str = ""               # 图片中的原文（整体文字）
    translation: str = ""                 # 原文的中文翻译
    words: list[OcrWordItem]
