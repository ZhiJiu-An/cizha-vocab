"""学习统计 API (v0.6)

单接口一次返回全部统计数据（单人本地应用，数据量小）：
概览数字 / 标签分布 Top 8 / 近 7 日趋势（无数据补 0）/ 复习档位分布
"""
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..common import STAGES_DAYS, sorted_tag_items, today_start
from ..database import get_db
from ..models import Word, ReviewLog
from ..schemas import StatsSummary

router = APIRouter(prefix="/api/stats", tags=["学习统计"])

TAG_LIMIT = 8   # 标签分布最多展示条数
TREND_DAYS = 7  # 趋势图天数（含今天）


@router.get("/summary", response_model=StatsSummary)
def get_summary(db: Session = Depends(get_db)):
    """学习统计总览"""
    day_start = today_start()
    week_start = day_start - timedelta(days=TREND_DAYS - 1)  # 含今天共 7 天

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
        .filter(ReviewLog.reviewed_at >= week_start)
        .group_by(review_day)
        .all()
    )

    created_day = func.strftime("%Y-%m-%d", Word.created_at)
    new_by_day = dict(
        db.query(created_day, func.count())
        .filter(Word.created_at >= week_start)
        .group_by(created_day)
        .all()
    )

    # Python 侧只负责把 7 天序列补零铺平
    daily_trend = []
    for i in range(TREND_DAYS):
        day = week_start + timedelta(days=i)
        key = day.strftime("%Y-%m-%d")
        daily_trend.append({
            "date": f"{day.month:02d}-{day.day:02d}",
            "new_words": new_by_day.get(key, 0),
            "reviews": review_by_day.get(key, 0),
        })

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
    }
