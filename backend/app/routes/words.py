"""词条 CRUD + CSV 批量导入 / 导出 + 标签聚合 (v0.5)"""
import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..common import (
    STAGES_DAYS, normalize_tags, sorted_tag_items, tag_match_expr, today_start,
)
from ..database import get_db
from ..models import ReviewLog, Word
from ..schemas import (
    BulkIdsIn, BulkRestoreIn, BulkResult, BulkTagIn, RestoreResult, TagItem,
    WordCreate, WordListResponse, WordLookupResult, WordResponse, WordUpdate,
)

router = APIRouter(prefix="/api/words", tags=["词条管理"])
tags_router = APIRouter(prefix="/api/tags", tags=["标签"])

# CSV 列顺序（导入 / 导出统一）
# - note 是 v0.8.1 补的：旧版漏了它，导出再导入会静默丢掉所有备注。
# - review_* 是 v0.11 补的：旧版只导内容不导进度，换机器备份后所有词条会被打回
#   第 0 档、下次复习日期重置为导入当天，几个月积攒的学习进度白丢。
# 旧版 10 / 11 列 CSV 仍可导入 —— 缺的列由 _parse_review_fields 按默认值补齐。
CSV_COLUMNS = [
    "abbreviation", "full_name", "cn_term", "my_meaning", "domain_detail",
    "phonetic_uk", "phonetic_us", "api_meaning", "examples", "tags", "note",
    "review_stage", "next_review_at", "review_count", "in_review",
]


def _derive_has_abbr(full_name: str) -> int:
    """有全称即视为缩写术语"""
    return 1 if (full_name or "").strip() else 0


def _norm_examples(items) -> list[dict]:
    """把例句统一成 [{en, zh}] 结构；兼容旧的纯字符串元素"""
    result = []
    for item in items or []:
        if isinstance(item, dict):
            en = str(item.get("en") or "").strip()
            zh = str(item.get("zh") or "").strip()
        else:
            en, zh = str(item).strip(), ""
        if en:
            result.append({"en": en, "zh": zh})
    return result


STRING_FIELDS = (
    "abbreviation", "full_name", "cn_term", "phonetic_uk", "phonetic_us",
    "my_meaning", "domain_detail", "api_meaning", "tags", "note",
)


def _clean(data: dict) -> dict:
    """统一去空格，保证字符串字段不为 None

    用 `key in data` 判断而不是 `data.get(key) is not None`：
    - 缺省的键保持缺省（部分更新不会凭空补字段）；
    - 显式传入 null 的键归一成空串。若像旧逻辑那样跳过 None，None 会一路流到
      setattr 落库 —— 非空列触发 IntegrityError、响应模型触发校验错误，两者都是 500。
      必填字段（abbreviation / my_meaning）变空串后由调用方的既有校验拦成 400。
    """
    for key in STRING_FIELDS:
        if key in data:
            data[key] = (data[key] or "").strip()
    # 标签统一归一，保证「,tag,」边界匹配始终准确（P0-5）
    if "tags" in data:
        data["tags"] = normalize_tags(data["tags"])
    # 仅当 examples 键确实存在时才归一化：部分更新（PUT 只提交变更字段）不能把未提交的
    # examples 覆盖成 []，否则会清空既有例句（P0-1）
    if "examples" in data:
        data["examples"] = _norm_examples(data.get("examples"))
    return data


def _parse_examples(raw: str) -> list[dict]:
    """CSV 里的例句列：优先按 JSON 数组解析，否则按 | 分隔（仅英文）"""
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            value = json.loads(raw)
            if isinstance(value, list):
                return _norm_examples(value)
        except json.JSONDecodeError:
            pass
    return _norm_examples([part for part in raw.split("|") if part.strip()])


def _parse_int(raw, default: int, lo: int = None, hi: int = None) -> int:
    """宽松解析整数：空值 / 脏值回落 default，并夹在 [lo, hi] 内"""
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def _parse_datetime(raw, default: datetime) -> datetime:
    """解析 ISO 日期时间；空值 / 格式错误回落 default"""
    raw = str(raw or "").strip()
    if not raw:
        return default
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return default


def _parse_review_fields(data: dict) -> dict:
    """把 CSV 的复习进度列解析成可直接落库的类型（v0.11）

    旧版 CSV 没有这些列，取到的是空串 → 全部回落默认值，行为与之前一致：
    第 0 档 / 今天到期 / 复习 0 次 / 在复习队列。
    """
    data["review_stage"] = _parse_int(data.get("review_stage"), 0, 0, len(STAGES_DAYS) - 1)
    data["next_review_at"] = _parse_datetime(data.get("next_review_at"), today_start())
    data["review_count"] = _parse_int(data.get("review_count"), 0, 0)
    data["in_review"] = 1 if _parse_int(data.get("in_review"), 1, 0, 1) else 0
    return data


# ========== 增 ==========
@router.post("", response_model=WordResponse)
def create_word(word_data: WordCreate, db: Session = Depends(get_db)):
    """新建词条"""
    data = _clean(word_data.model_dump())

    if not data["abbreviation"]:
        raise HTTPException(status_code=400, detail="缩写/主词不能为空")
    if not data["my_meaning"]:
        raise HTTPException(status_code=400, detail="「我的理解」不能为空")

    existing = (db.query(Word)
                .filter(func.lower(Word.abbreviation) == data["abbreviation"].lower())
                .first())
    if existing:
        raise HTTPException(status_code=400, detail=f"词条「{data['abbreviation']}」已存在")

    data["has_abbr"] = _derive_has_abbr(data["full_name"])
    data["next_review_at"] = today_start()  # 新词默认进复习队列，当天到期
    word = Word(**data)
    db.add(word)
    db.commit()
    db.refresh(word)
    return word


# ========== 批量导入 ==========
@router.post("/batch", response_model=list[WordResponse])
def batch_import(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """CSV 批量导入

    列顺序：abbreviation,full_name,cn_term,my_meaning,domain_detail,phonetic_uk,phonetic_us,api_meaning,examples,tags,note,review_stage,next_review_at,review_count,in_review
    examples 列为 JSON 数组 [{en, zh}] 或 | 分隔的英文句子。
    仅 abbreviation 和 my_meaning 必填；已存在的词条自动跳过。
    旧版 10 / 11 列（无 note / 无复习进度）的 CSV 仍可直接导入，缺失列按默认值补齐。
    """
    content = file.file.read().decode("utf-8-sig")
    reader = csv.reader(io.StringIO(content))

    created = []
    for idx, row in enumerate(reader):
        if not row or not row[0].strip():
            continue
        # 跳过表头
        if idx == 0 and row[0].strip().lower() in ("abbreviation", "缩写", "缩写/主词", "word", "单词"):
            continue

        values = (row + [""] * len(CSV_COLUMNS))[:len(CSV_COLUMNS)]
        data = dict(zip(CSV_COLUMNS, values, strict=True))
        data["examples"] = _parse_examples(data.get("examples", ""))
        data = _clean(data)

        if not data["my_meaning"]:
            continue

        exists = (db.query(Word)
                  .filter(func.lower(Word.abbreviation) == data["abbreviation"].lower())
                  .first())
        if exists:
            continue

        data["has_abbr"] = _derive_has_abbr(data["full_name"])
        data = _parse_review_fields(data)  # 有进度列则恢复，没有则按新词默认值
        word = Word(**data)
        db.add(word)
        db.flush()
        created.append(word)

    db.commit()
    for w in created:
        db.refresh(w)
    return created


# ========== 批量操作（v0.11） ==========
# 此前批量删除 / 批量加标签只能由前端循环发 N 个单条请求（代码里自己写着「后端无批量接口」），
# 删 100 条就是 100 次 HTTP 往返，且没有原子性。这里收成单请求 + 单事务。
def _split_ids(raw_ids: list[int]) -> tuple[list[int], set[int]]:
    """去重并保留顺序；返回 (去重后的 ids, 集合)"""
    ids = list(dict.fromkeys(raw_ids))
    return ids, set(ids)


@router.post("/bulk-delete", response_model=BulkResult)
def bulk_delete(payload: BulkIdsIn, db: Session = Depends(get_db)):
    """按 id 批量删除（词条 + 复习日志），单事务提交"""
    ids, _ = _split_ids(payload.ids)
    words = db.query(Word).filter(Word.id.in_(ids)).all()
    found = {w.id for w in words}

    # v0.13：删除是彻底移除，日志必须同步清理，否则统计仍会算上已删词条，
    # 且 SQLite 复用 rowid 时新词条可能继承旧日志。
    if found:
        db.query(ReviewLog).filter(ReviewLog.word_id.in_(found)).delete(
            synchronize_session=False
        )
    for word in words:
        db.delete(word)
    db.commit()

    missing = [i for i in ids if i not in found]
    return {
        "requested": len(ids),
        "succeeded": len(found),
        "failed": len(missing),
        "missing_ids": missing,
    }


@router.post("/bulk-tag", response_model=BulkResult)
def bulk_add_tag(payload: BulkTagIn, db: Session = Depends(get_db)):
    """批量为词条追加标签（与原有标签合并去重），单事务提交"""
    new_tags = [t.strip() for t in payload.tags if t and t.strip()]
    if not new_tags:
        raise HTTPException(status_code=400, detail="标签不能为空")

    ids, _ = _split_ids(payload.ids)
    words = db.query(Word).filter(Word.id.in_(ids)).all()
    found = {w.id for w in words}
    for word in words:
        # 合并后统一走 normalize_tags：去空格、去空项、去重保序
        word.tags = normalize_tags(f"{word.tags or ''},{','.join(new_tags)}")
    db.commit()

    missing = [i for i in ids if i not in found]
    return {
        "requested": len(ids),
        "succeeded": len(found),
        "failed": len(missing),
        "missing_ids": missing,
    }


# ========== 撤销删除（v0.11） ==========
@router.post("/restore", response_model=RestoreResult)
def restore_words(payload: BulkRestoreIn, db: Session = Depends(get_db)):
    """把刚删除的词条回灌（保留当前复习排期与创建时间）

    删除是不可逆的，但「误删」很常见。前端在删除时缓存完整词条 JSON，
    这里按原样插回复习档位、下次复习日期与创建时间，撤销不会把排期打回原点。
    同名词条已存在时跳过，不覆盖。

    v0.13 起删除会一并清掉 ReviewLog，因此撤销不再保留累计次数（置 0），
    避免详情页「累计 N 次」与统计页 / 错词榜口径互相矛盾。
    """
    restored = []
    skipped = 0

    for item in payload.items:
        data = _clean(item.model_dump())
        if not data["abbreviation"] or not data["my_meaning"]:
            skipped += 1
            continue

        exists = (
            db.query(Word)
            .filter(func.lower(Word.abbreviation) == data["abbreviation"].lower())
            .first()
        )
        if exists:
            skipped += 1
            continue

        data["has_abbr"] = _derive_has_abbr(data["full_name"])
        data["review_stage"] = max(
            0, min(int(data.get("review_stage") or 0), len(STAGES_DAYS) - 1)
        )
        data["review_count"] = 0          # 日志已随删除清空，累计次数同步归零
        data["in_review"] = 1 if data.get("in_review") is None else (1 if data["in_review"] else 0)
        if data.get("next_review_at") is None:
            data["next_review_at"] = today_start()
        # None 时删掉键，让 Column 的默认值生效，而不是写入 NULL
        for key in ("created_at", "updated_at"):
            if data.get(key) is None:
                data.pop(key, None)

        word = Word(**data)
        db.add(word)
        db.flush()
        restored.append(word)

    db.commit()
    for word in restored:
        db.refresh(word)

    return {
        "requested": len(payload.items),
        "restored": len(restored),
        "skipped": skipped,
        "words": restored,
    }


# ========== 导出 ==========
@router.get("/export")
def export_csv(keyword: str = "", tag: str = "", db: Session = Depends(get_db)):
    """导出为 CSV（带 BOM，Excel 可直接打开）"""
    words = _apply_filters(db.query(Word), keyword, tag).order_by(Word.created_at.desc()).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for w in words:
        writer.writerow([
            w.abbreviation, w.full_name, w.cn_term, w.my_meaning, w.domain_detail,
            w.phonetic_uk, w.phonetic_us, w.api_meaning,
            json.dumps(_norm_examples(w.examples), ensure_ascii=False), w.tags, w.note,
            w.review_stage or 0,
            w.next_review_at.isoformat(timespec="seconds") if w.next_review_at else "",
            w.review_count or 0,
            1 if w.in_review is None else w.in_review,
        ])

    csv_bytes = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="danciji_export.csv"'},
    )


# ========== 本地库精确查找（v0.11） ==========
@router.get("/lookup", response_model=WordLookupResult)
def lookup_word(word: str = "", db: Session = Depends(get_db)):
    """按缩写精确查找（大小写不敏感），供搜索页判断「是否已收藏」

    在此之前，搜索页查一个早就收藏过的词仍会完整调用一次大模型，点收藏才报
    「已存在」—— 既费 token 又费时间。不命中返回 200 + found=false：这是搜索页
    每次都会调的接口，不该走 404 错误分支。
    """
    word = (word or "").strip()
    if not word:
        return {"found": False, "word": None}
    hit = (
        db.query(Word)
        .filter(func.lower(Word.abbreviation) == word.lower())
        .first()
    )
    return {"found": hit is not None, "word": hit}


# ========== 列表 ==========
def _escape_like(text: str) -> str:
    """转义 LIKE 模式里的通配符（P0-7）

    `%` / `_` 不转义会被当成通配符：keyword=% 会匹配全部词条、keyword=_lpha 会命中
    alpha。必须先转义反斜杠本身，再转义通配符；配合 ilike(..., escape="\\\\") 使用。
    """
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _apply_filters(query, keyword: str, tag: str):
    if keyword:
        like = f"%{_escape_like(keyword.strip())}%"
        query = query.filter(or_(
            Word.abbreviation.ilike(like, escape="\\"),
            Word.full_name.ilike(like, escape="\\"),
            Word.cn_term.ilike(like, escape="\\"),
            Word.my_meaning.ilike(like, escape="\\"),
            Word.domain_detail.ilike(like, escape="\\"),
            Word.api_meaning.ilike(like, escape="\\"),
            Word.tags.ilike(like, escape="\\"),
            Word.note.ilike(like, escape="\\"),
        ))
    if tag:
        # 边界精确匹配：tag=AI 不再命中 OpenAI / RAG（P0-5）
        query = query.filter(tag_match_expr(tag.strip()))
    return query


SORT_MAP = {
    "time_desc": lambda q: q.order_by(Word.created_at.desc()),
    "time_asc": lambda q: q.order_by(Word.created_at.asc()),
    "alpha_asc": lambda q: q.order_by(func.lower(Word.abbreviation).asc()),
    "alpha_desc": lambda q: q.order_by(func.lower(Word.abbreviation).desc()),
}


@router.get("", response_model=WordListResponse)
def list_words(
    keyword: str = "",
    tag: str = "",
    sort: str = "time_desc",
    skip: int = Query(0, ge=0, description="跳过条数（分页偏移）"),
    limit: int = Query(100, ge=1, le=500, description="每页条数，上限 500"),
    db: Session = Depends(get_db),
):
    """词条列表：支持关键词搜索、标签筛选、排序、分页

    limit 有上限（P1-4）：旧版默认 200 且不校验，传 limit=1e9 也能通过。
    """
    query = _apply_filters(db.query(Word), keyword, tag)
    total = query.count()
    query = SORT_MAP.get(sort, SORT_MAP["time_desc"])(query)
    items = query.offset(skip).limit(limit).all()
    return {"total": total, "items": items}


# ========== 详情 ==========
@router.get("/{word_id}", response_model=WordResponse)
def get_word(word_id: int, db: Session = Depends(get_db)):
    word = db.query(Word).filter(Word.id == word_id).first()
    if not word:
        raise HTTPException(status_code=404, detail="词条不存在")
    return word


# ========== 改 ==========
@router.put("/{word_id}", response_model=WordResponse)
def update_word(word_id: int, word_data: WordUpdate, db: Session = Depends(get_db)):
    word = db.query(Word).filter(Word.id == word_id).first()
    if not word:
        raise HTTPException(status_code=404, detail="词条不存在")

    changes = _clean(word_data.model_dump(exclude_unset=True))

    if "abbreviation" in changes:
        if not changes["abbreviation"]:
            raise HTTPException(status_code=400, detail="缩写/主词不能为空")
        dup = (db.query(Word)
               .filter(func.lower(Word.abbreviation) == changes["abbreviation"].lower(),
                       Word.id != word_id)
               .first())
        if dup:
            raise HTTPException(status_code=400, detail=f"词条「{changes['abbreviation']}」已存在")

    if changes.get("my_meaning") == "":
        raise HTTPException(status_code=400, detail="「我的理解」不能为空")

    for key, value in changes.items():
        setattr(word, key, value)

    # 全称变化后重新推导类型
    if "full_name" in changes:
        word.has_abbr = _derive_has_abbr(word.full_name)

    # 重新加入复习队列时，若从未安排过复习日期则立刻到期（v0.11）；
    # 已有计划则保留原计划，等同于「恢复」而不是「重学」。
    if changes.get("in_review") == 1 and not word.next_review_at:
        word.next_review_at = today_start()

    db.commit()
    db.refresh(word)
    return word


# ========== 删 ==========
@router.delete("/{word_id}")
def delete_word(word_id: int, db: Session = Depends(get_db)):
    """彻底删除词条及其复习日志（同一事务）"""
    word = db.query(Word).filter(Word.id == word_id).first()
    if not word:
        raise HTTPException(status_code=404, detail="词条不存在")
    db.query(ReviewLog).filter(ReviewLog.word_id == word_id).delete(
        synchronize_session=False
    )
    db.delete(word)
    db.commit()
    return {"message": "删除成功"}


# ========== 标签 ==========
@tags_router.get("", response_model=list[TagItem])
def list_tags(db: Session = Depends(get_db)):
    """聚合所有标签及使用次数"""
    return [TagItem(name=name, count=count) for name, count in sorted_tag_items(db)]
