"""学习统计 API (v0.6)

单接口一次返回全部统计数据（单人本地应用，数据量小）：
概览数字 / 标签分布 Top 8 / 近 7 日趋势（无数据补 0）/ 复习档位分布
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Word, ReviewLog
from ..schemas import StatsSummary

router = APIRouter(prefix="/api/stats", tags=["学习统计"])

# 六档间隔天数（与 review.py 保持一致）：stage 0~5
STAGES_DAYS = [1, 2, 4, 7, 15, 30]
TAG_LIMIT = 8   # 标签分布最多展示条数
TREND_DAYS = 7  # 趋势图天数（含今天）


def _today_start() -> datetime:
    """今天 00:00"""
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/summary", response_model=StatsSummary)
def get_summary(db: Session = Depends(get_db)):
    """学习统计总览"""
    today_start = _today_start()
    week_start = today_start - timedelta(days=TREND_DAYS - 1)  # 含今天共 7 天

    # ---- 概览数字 ----
    total_words = db.query(Word).count()
    week_new = db.query(Word).filter(Word.created_at >= week_start).count()
    total_reviews = db.query(ReviewLog).count()
    # 今日已复习：按 distinct word_id 统计，防同词多次复习虚增
    reviewed_today = (
        db.query(func.count(func.distinct(ReviewLog.word_id)))
        .filter(ReviewLog.reviewed_at >= today_start)
        .scalar()
    ) or 0

    # ---- 标签分布（Top 8，复用 list_tags 的聚合逻辑）----
    counter = {}
    for (raw,) in db.query(Word.tags).all():
        for tag in (raw or "").split(","):
            tag = tag.strip()
            if tag:
                counter[tag] = counter.get(tag, 0) + 1
    top_tags = sorted(counter.items(), key=lambda x: (-x[1], x[0]))[:TAG_LIMIT]
    tag_distribution = [{"name": name, "count": count} for name, count in top_tags]

    # ---- 近 7 日趋势（Python 侧组装完整序列，无数据补 0）----
    review_by_day = {}
    for (reviewed_at,) in (
        db.query(ReviewLog.reviewed_at).filter(ReviewLog.reviewed_at >= week_start).all()
    ):
        key = reviewed_at.date()
        review_by_day[key] = review_by_day.get(key, 0) + 1

    new_by_day = {}
    for (created_at,) in (
        db.query(Word.created_at).filter(Word.created_at >= week_start).all()
    ):
        key = created_at.date()
        new_by_day[key] = new_by_day.get(key, 0) + 1

    daily_trend = []
    for i in range(TREND_DAYS):
        day = (week_start + timedelta(days=i)).date()
        daily_trend.append({
            "date": f"{day.month:02d}-{day.day:02d}",
            "new_words": new_by_day.get(day, 0),
            "reviews": review_by_day.get(day, 0),
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
