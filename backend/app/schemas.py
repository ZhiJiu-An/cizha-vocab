"""请求 / 响应模型 (v0.11)"""
from pydantic import BaseModel, Field
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
    # 复习队列开关（v0.11）：0 = 移出队列（不再安排复习），1 = 在队列。
    # 该列自 v0.5 就存在且被 /review 各处查询，但此前没有任何入口能改它。
    in_review: int | None = Field(default=None, ge=0, le=1)


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
    in_review: int = 1            # 1=在复习队列，0=已移出（v0.11 暴露给前端回显）

    # ---- 复习状态（v0.11）----
    # 这几个字段自 v0.5 就存在，但此前只有 /review/due 的响应才带，
    # 导致词条详情页与悬浮窗完全看不到「我复习到第几档、下次何时考、忘过几次」。
    review_stage: int = 0
    next_review_at: datetime | None = None
    last_reviewed_at: datetime | None = None
    review_count: int = 0

    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class WordLookupResult(BaseModel):
    """本地库精确查找结果（v0.11）

    搜索页每次搜索都会调一次，用于判断「这个词是不是已经收藏过」。
    不命中返回 found=False 而不是 404，避免前端把正常情况当错误处理。
    """
    found: bool = False
    word: WordResponse | None = None


# ========== 批量操作（v0.11） ==========
class BulkIdsIn(BaseModel):
    """一组词条 id（批量删除用）"""
    ids: list[int] = Field(min_length=1, max_length=1000)


class BulkTagIn(BulkIdsIn):
    """为选中词条追加标签：tags 直接收数组，前端不必自己拼逗号分隔串"""
    tags: list[str] = Field(min_length=1, max_length=20)


class BulkResult(BaseModel):
    requested: int = 0            # 去重后实际请求处理的条数
    succeeded: int = 0            # 成功条数
    failed: int = 0               # 失败条数
    missing_ids: list[int] = []   # 数据库中不存在的 id


class WordRestoreItem(BaseModel):
    """撤销删除时回灌的完整词条（含复习进度与创建时间）"""
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
    review_stage: int = 0
    next_review_at: datetime | None = None
    review_count: int = 0
    in_review: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BulkRestoreIn(BaseModel):
    items: list[WordRestoreItem] = Field(min_length=1, max_length=1000)


class RestoreResult(BaseModel):
    requested: int = 0
    restored: int = 0
    skipped: int = 0              # 已存在同名词条而跳过
    words: list[WordResponse] = []


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


class ReviewDueResponse(BaseModel):
    """到期词条列表（v0.11 起 WordResponse 已含复习状态，无需再单独定义子模型）"""
    total_due: int
    items: list[WordResponse]


class ReviewResetOut(BaseModel):
    """重置复习进度的结果（v0.11）"""
    word_id: int
    review_stage: int = 0
    next_review_at: datetime | None = None
    review_count: int = 0


class MistakeItem(WordResponse):
    """错词本条目 = 词条全量字段 + 复习结果统计（v0.11）

    ReviewLog 从 v0.5 起就记录了每次自评的 result，但此前只被用来数「今日已复习 /
    累计复习」。这里把同一份数据聚合成「最常忘记的词」，用于针对性重练。
    """
    forget_times: int = 0                # 累计「忘记」次数
    fuzzy_times: int = 0                 # 累计「模糊」次数
    total_reviews: int = 0               # 该词累计复习次数
    last_forgot_at: datetime | None = None  # 最近一次「忘记」的时间


class MistakeResponse(BaseModel):
    total: int                           # 命中的错词总数（不受 limit 影响）
    items: list[MistakeItem]


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
    # v0.11：趋势图实际覆盖的天数与聚合粒度（day / week），供前端标注标题
    trend_days: int = 7
    trend_granularity: str = "day"


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
