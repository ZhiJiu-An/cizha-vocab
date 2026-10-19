"""记忆复习 API (v0.5)

六档间隔 1/2/4/7/15/30 天，按天对齐：
- 记住 → 升一档（封顶 5）；模糊 → 档位不变；忘记 → 回 0 档
- next_review_at 存当天 00:00，到期条件 <= 今日 23:59:59
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..common import STAGES_DAYS, tag_match_expr, today_start
from ..database import get_db
from ..models import Word, ReviewLog
from ..schemas import (
    ReviewAnswerIn, ReviewAnswerOut, ReviewOverview, ReviewDueResponse,
)

router = APIRouter(prefix="/api/review", tags=["记忆复习"])

# 合法自评结果
RESULTS = ("remember", "fuzzy", "forget")


def _due_query(db: Session, tag: str = ""):
    """到期词条查询：在复习队列 且 下次复习日期 <= 今天"""
    today_end = today_start() + timedelta(days=1)  # 今日 23:59:59 等价于 < 明天 00:00
    query = db.query(Word).filter(
        Word.in_review == 1,
        Word.next_review_at.isnot(None),
        Word.next_review_at < today_end,
    )
    if tag:
        # 与 /api/words 一致：边界精确匹配，避免 tag=AI 命中 OpenAI（P0-5）
        query = query.filter(tag_match_expr(tag.strip()))
    return query


# ========== 概览 ==========
@router.get("/overview", response_model=ReviewOverview)
def get_overview(db: Session = Depends(get_db)):
    """复习概览：今日到期数 / 今日已复习数 / 队列总数"""
    due_today = _due_query(db).count()

    # 今日已复习数：ReviewLog 按天 distinct word_id（防同词重复复习虚增）
    day_start = today_start()
    reviewed_today = (
        db.query(func.count(func.distinct(ReviewLog.word_id)))
        .filter(ReviewLog.reviewed_at >= day_start)
        .scalar()
    ) or 0

    total_in_queue = db.query(Word).filter(Word.in_review == 1).count()

    return {
        "due_today": due_today,
        "reviewed_today": reviewed_today,
        "total_in_queue": total_in_queue,
    }


# ========== 到期词条 ==========
@router.get("/due", response_model=ReviewDueResponse)
def get_due_words(tag: str = "", limit: int = 20, db: Session = Depends(get_db)):
    """取到期词条：按到期时间升序（最久没复习的排前面）"""
    query = _due_query(db, tag)
    total_due = query.count()
    items = (query.order_by(Word.next_review_at.asc())
             .limit(max(1, min(limit, 200)))
             .all())
    return {"total_due": total_due, "items": items}


# ========== 提交自评 ==========
@router.post("/{word_id}/answer", response_model=ReviewAnswerOut)
def submit_answer(word_id: int, answer: ReviewAnswerIn, db: Session = Depends(get_db)):
    """提交自评结果，按三档规则更新档位与下次复习日期，并写复习记录"""
    result = (answer.result or "").strip().lower()
    if result not in RESULTS:
        raise HTTPException(status_code=400, detail="result 只能是 remember / fuzzy / forget")

    word = db.query(Word).filter(Word.id == word_id).first()
    if not word:
        raise HTTPException(status_code=404, detail="词条不存在")

    # ---- 到期守卫（P0-4）----
    # 只允许「今天该复习」的词条提交自评。守卫同时让接口天然幂等：提交成功后
    # next_review_at 最早是「明天 00:00」，当天再次提交必被拦住，不会出现重复点击
    # 把档位多推一档、把复习日期越推越远的问题。
    if word.in_review == 0:
        raise HTTPException(status_code=409, detail="该词条不在复习队列中")
    if word.next_review_at is None:
        raise HTTPException(status_code=409, detail="该词条尚未安排复习时间")
    if word.next_review_at >= today_start() + timedelta(days=1):
        raise HTTPException(
            status_code=409,
            detail=f"该词条今天不需要复习，下次复习日期：{word.next_review_at:%Y-%m-%d}",
        )

    stage_before = word.review_stage or 0

    # 三档规则：记住→升一档(封顶5) / 模糊→不变 / 忘记→回0
    if result == "remember":
        stage_after = min(stage_before + 1, len(STAGES_DAYS) - 1)
    elif result == "forget":
        stage_after = 0
    else:  # fuzzy
        stage_after = stage_before

    # 下次复习日期 = 今天 00:00 + 对应档位天数（按天对齐）
    next_review_at = today_start() + timedelta(days=STAGES_DAYS[stage_after])
    now = datetime.now()

    word.review_stage = stage_after
    word.next_review_at = next_review_at
    word.last_reviewed_at = now
    word.review_count = (word.review_count or 0) + 1

    db.add(ReviewLog(
        word_id=word.id,
        reviewed_at=now,
        result=result,
        stage_before=stage_before,
        stage_after=stage_after,
    ))
    db.commit()

    return {
        "word_id": word.id,
        "review_stage": stage_after,
        "next_review_at": next_review_at,
        "last_reviewed_at": now,
    }
