"""记忆复习 API (v0.5)

六档间隔 1/2/4/7/15/30 天，按天对齐：
- 记住 → 升一档（封顶 5）；模糊 → 档位不变；忘记 → 回 0 档
- next_review_at 存当天 00:00，到期条件 <= 今日 23:59:59
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..common import STAGES_DAYS, tag_match_expr, today_start
from ..database import get_db
from ..models import Word, ReviewLog
from ..schemas import (
    MistakeItem, MistakeResponse, ReviewAnswerIn, ReviewAnswerOut, ReviewOverview,
    ReviewResetOut, ReviewDueResponse,
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


def _review_stats(db):
    """按词条聚合 ReviewLog：忘记次数 / 模糊次数 / 总次数 / 最近一次忘记时间（v0.11）

    用条件聚合一次算出四个值，避免为每个统计口径各查一遍。
    """
    return (
        db.query(
            ReviewLog.word_id.label("word_id"),
            func.sum(case((ReviewLog.result == "forget", 1), else_=0)).label("forget_times"),
            func.sum(case((ReviewLog.result == "fuzzy", 1), else_=0)).label("fuzzy_times"),
            func.count().label("total_reviews"),
            func.max(
                case((ReviewLog.result == "forget", ReviewLog.reviewed_at))
            ).label("last_forgot_at"),
        )
        .group_by(ReviewLog.word_id)
        .subquery()
    )


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
def get_due_words(
    tag: str = "",
    limit: int = 20,
    order: str = "due",
    db: Session = Depends(get_db),
):
    """取到期词条

    order="due"（默认）按到期时间升序：最久没复习的排前面。
    order="mistakes"（v0.11）按「历史忘记次数」降序，再按到期时间升序 ——
    同样只取真正到期的词，因此不会破坏复习排期语义（非到期词提交自评仍会被 409 拦下）。
    """
    query = _due_query(db, tag)
    total_due = query.count()

    if order == "mistakes":
        stats = _review_stats(db)
        query = (
            query.outerjoin(stats, stats.c.word_id == Word.id)
            .order_by(
                func.coalesce(stats.c.forget_times, 0).desc(),
                Word.next_review_at.asc(),
            )
        )
    else:
        query = query.order_by(Word.next_review_at.asc())

    items = query.limit(max(1, min(limit, 200))).all()
    return {"total_due": total_due, "items": items}


# ========== 错词本（v0.11） ==========
@router.get("/mistakes", response_model=MistakeResponse)
def get_mistakes(
    limit: int = 20,
    min_forget: int = 1,
    db: Session = Depends(get_db),
):
    """错词本：按「忘记」次数降序返回最需要重练的词

    ReviewLog 从 v0.5 起就在记每次自评结果，但此前只被用来数「今日已复习」。
    这份数据正好回答「哪些词我老是记不住」，无需任何迁移。
    min_forget=1 表示只返回至少忘过一次的词。
    """
    stats = _review_stats(db)
    threshold = max(1, min_forget)

    total = (
        db.query(func.count())
        .select_from(stats)
        .filter(stats.c.forget_times >= threshold)
        .scalar()
    ) or 0

    rows = (
        db.query(
            Word,
            stats.c.forget_times,
            stats.c.fuzzy_times,
            stats.c.total_reviews,
            stats.c.last_forgot_at,
        )
        .join(stats, stats.c.word_id == Word.id)
        .filter(stats.c.forget_times >= threshold)
        .order_by(
            stats.c.forget_times.desc(),
            stats.c.last_forgot_at.desc(),
            Word.id.asc(),
        )
        .limit(max(1, min(limit, 200)))
        .all()
    )

    items = []
    for word, forget_times, fuzzy_times, total_reviews, last_forgot_at in rows:
        item = MistakeItem.model_validate(word)
        item.forget_times = int(forget_times or 0)
        item.fuzzy_times = int(fuzzy_times or 0)
        item.total_reviews = int(total_reviews or 0)
        item.last_forgot_at = last_forgot_at
        items.append(item)

    return {"total": total, "items": items}


# ========== 重置复习进度（v0.11） ==========
@router.post("/{word_id}/reset", response_model=ReviewResetOut)
def reset_progress(word_id: int, db: Session = Depends(get_db)):
    """把某个词的复习**排期**归零，从第 0 档重新开始

    此前误点「记住」把档位推进去之后没有任何办法退回来 —— 只能删词重建。

    刻意只重置「排期」（档位 + 下次复习日期），**不动累计次数与上次复习时间**，
    也不写 ReviewLog。理由：
    - 你确实复习过 N 次，这个事实不该被一个按钮抹掉；
    - 更重要的是口径一致：详情页读 review_count、错词本与统计读 COUNT(review_logs)，
      若这里清零而日志保留，同一个词会出现「累计复习 0 次」与「总复习 4 次」并存。
    - 想彻底忘掉一个词，应当另设「清除全部复习记录」动作（连带删 ReviewLog），
      而不是让「重置排期」一个动作承担两种口径。
    """
    word = db.query(Word).filter(Word.id == word_id).first()
    if not word:
        raise HTTPException(status_code=404, detail="词条不存在")

    word.review_stage = 0
    word.next_review_at = today_start()   # 立刻回到今天可复习
    # review_count / last_reviewed_at 保持不变（见 docstring）
    db.commit()
    db.refresh(word)

    return {
        "word_id": word.id,
        "review_stage": word.review_stage,
        "next_review_at": word.next_review_at,
        "review_count": word.review_count,   # 保留累计次数
    }


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
