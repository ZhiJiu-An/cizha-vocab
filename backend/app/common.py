"""跨路由共享的小工具（P2-1）

抽取前这些逻辑各存在多份，改一处必漏一处：
- ``today_start()``   → words.py / review.py / stats.py 各一份
- ``STAGES_DAYS``     → review.py / stats.py 各一份
- 标签聚合            → words.list_tags / stats.summary 各一份
- ``normalize_tags`` / ``tag_match_expr`` → 原在 words.py，被 review.py 与 main.py 反向依赖

统一放这里，路由模块只做 HTTP 层的事。
"""
from datetime import datetime

from sqlalchemy import func, literal

from .models import Word

# 六档间隔天数：stage 0~5 分别对应 1/2/4/7/15/30 天
STAGES_DAYS = [1, 2, 4, 7, 15, 30]


def today_start() -> datetime:
    """今天 00:00 —— 复习日期按天对齐的统一基准"""
    now = datetime.now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def normalize_tags(raw) -> str:
    """标签归一：按逗号切分 → 逐项去空格 → 去空 → 去重（保序）→ 用 `,` 拼回

    统一存储格式后，筛选才能做「,tag,」边界精确匹配（P0-5）。
    只去标签前后的空格，标签内部的空格保留（如 "chain of thought"）。
    """
    tags = []
    for tag in str(raw or "").split(","):
        tag = tag.strip()
        if tag and tag not in tags:
            tags.append(tag)
    return ",".join(tags)


def tag_match_expr(tag: str):
    """构造标签精确匹配表达式（P0-5）

    把列值包成 ``,a,b,``，再用 SQLite 的 ``instr`` 查 ``",tag,"``。
    不用 LIKE：``instr`` 是字面量子串匹配，天然避开 ``%`` / ``_`` 通配符问题，
    也就不会出现 tag=AI 命中 OpenAI、tag=RA 命中 RAG 的情况。
    """
    padded = literal(",").concat(func.coalesce(Word.tags, "")).concat(literal(","))
    return func.instr(padded, f",{tag},") > 0


def tag_counter(db) -> dict:
    """聚合所有标签及使用次数，返回 {标签: 次数}"""
    counter = {}
    for (raw,) in db.query(Word.tags).all():
        for tag in (raw or "").split(","):
            tag = tag.strip()
            if tag:
                counter[tag] = counter.get(tag, 0) + 1
    return counter


def sorted_tag_items(db) -> list:
    """按「次数降序、名称升序」排好的 [(标签, 次数)]，供标签页与统计页共用"""
    return sorted(tag_counter(db).items(), key=lambda item: (-item[1], item[0]))
