"""学习统计 API (v0.6)

单接口一次返回全部统计数据（单人本地应用，数据量小）：
概览数字 / 标签分布 Top 8 / 近 7 日趋势（无数据补 0）/ 复习档位分布
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..common import STAGES_DAYS, sorted_tag_items, today_start
from ..database import get_db
from ..models import Word, ReviewLog
from ..schemas import StatsSummary

router = APIRouter(prefix="/api/stats", tags=["学习统计"])

TAG_LIMIT = 8           # 标签分布最多展示条数
DEFAULT_TREND_DAYS = 7  # 趋势图默认天数（含今天）
MAX_TREND_DAYS = 365    # 趋势图可选的最大天数
DAILY_LIMIT = 31        # 超过这个天数改为按周聚合，避免几十根柱子挤成一团


@router.get("/summary", response_model=StatsSummary)
def get_summary(
    days: int = Query(DEFAULT_TREND_DAYS, ge=1, le=MAX_TREND_DAYS),
    db: Session = Depends(get_db),
):
    """学习统计总览

    days 只影响趋势图窗口（v0.11）：≤31 天按天聚合，更长区间按周聚合
    （每 7 天一个桶、从窗口起点对齐），免得 90 根柱子挤成一团。
    概览里的「近 7 天新增」有自己固定的口径，不受 days 影响。
    """
    day_start = today_start()
    trend_start = day_start - timedelta(days=days - 1)
    week_start = day_start - timedelta(days=6)  # 固定「近 7 天新增」口径

    # ---- 概览数字 ----
    total_words = db.query(Word).count()
    week_new = db.query(Word).filter(Word.created_at >= week_start).count()
    total_reviews = db.query(ReviewLog).count()
    # 今日已复习：按 distinct word_id 统计，防同词多次复习虚增
    reviewed_today = (
        db.query(func.count(func.distinct(ReviewLog.word_id)))
        .filter(ReviewLog.reviewed_at >= day_start)
        .scalar()
    ) or 0

    # ---- 标签分布（Top 8，与 /api/tags 共用同一套聚合逻辑）----
    tag_distribution = [
        {"name": name, "count": count}
        for name, count in sorted_tag_items(db)[:TAG_LIMIT]
    ]

    # ---- 近 7 日趋势 ----
    # 按天聚合交给 SQLite 做（P2-2）：旧版把 7 天内的全部明细行查回 Python 再逐条计数，
    # 数据量一大就是无谓的传输与循环。这里用 strftime 分组，只回传「天 -> 次数」。
    # 注：strftime 是 SQLite 函数，本项目的 backend 固定用 SQLite（见 database.py）。
    review_day = func.strftime("%Y-%m-%d", ReviewLog.reviewed_at)
    review_by_day = dict(
        db.query(review_day, func.count())
        .filter(ReviewLog.reviewed_at >= trend_start)
        .group_by(review_day)
        .all()
    )

    created_day = func.strftime("%Y-%m-%d", Word.created_at)
    new_by_day = dict(
        db.query(created_day, func.count())
        .filter(Word.created_at >= trend_start)
        .group_by(created_day)
        .all()
    )

    # SQL 只负责按天计数；铺平与「按周合并」都在 Python 侧完成
    per_day = []
    for i in range(days):
        day = trend_start + timedelta(days=i)
        key = day.strftime("%Y-%m-%d")
        per_day.append((day, new_by_day.get(key, 0), review_by_day.get(key, 0)))

    granularity = "day" if days <= DAILY_LIMIT else "week"
    if granularity == "day":
        buckets = per_day
    else:
        # 每 7 天一个桶，桶标签取桶内第一天
        buckets = []
        for offset in range(0, days, 7):
            chunk = per_day[offset:offset + 7]
            buckets.append((
                chunk[0][0],
                sum(item[1] for item in chunk),
                sum(item[2] for item in chunk),
            ))

    daily_trend = [
        {
            "date": f"{day.month:02d}-{day.day:02d}",
            "new_words": new_count,
            "reviews": review_count,
        }
        for day, new_count, review_count in buckets
    ]

    # ---- 复习档位分布（恒 6 档，无词补 0）----
    stage_rows = (
        db.query(Word.review_stage, func.count(Word.id))
        .filter(Word.in_review == 1)
        .group_by(Word.review_stage)
        .all()
    )
    stage_count = {stage: count for stage, count in stage_rows}
    stage_distribution = [
        {
            "stage": stage,
            "days": STAGES_DAYS[stage],  # 该档对应的间隔天数
            "count": stage_count.get(stage, 0),
        }
        for stage in range(len(STAGES_DAYS))
    ]

    return {
        "totals": {
            "total_words": total_words,
            "week_new": week_new,
            "total_reviews": total_reviews,
            "reviewed_today": reviewed_today,
        },
        "tag_distribution": tag_distribution,
        "daily_trend": daily_trend,
        "stage_distribution": stage_distribution,
        "trend_days": days,
        "trend_granularity": granularity,
    }
