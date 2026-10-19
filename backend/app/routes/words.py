"""词条 CRUD + CSV 批量导入 / 导出 + 标签聚合 (v0.5)"""
import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..common import normalize_tags, sorted_tag_items, tag_match_expr, today_start
from ..database import get_db
from ..models import Word
from ..schemas import WordCreate, WordUpdate, WordResponse, WordListResponse, TagItem

router = APIRouter(prefix="/api/words", tags=["词条管理"])
tags_router = APIRouter(prefix="/api/tags", tags=["标签"])

# CSV 列顺序（导入 / 导出统一）
# 末尾的 note 是 P0-6 补上的：旧版漏了它，导出再导入会静默丢掉所有备注。
# 旧版 10 列 CSV 仍可导入 —— 见 batch_import 的补齐逻辑。
CSV_COLUMNS = [
    "abbreviation", "full_name", "cn_term", "my_meaning", "domain_detail",
    "phonetic_uk", "phonetic_us", "api_meaning", "examples", "tags", "note",
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

    列顺序：abbreviation,full_name,cn_term,my_meaning,domain_detail,phonetic_uk,phonetic_us,api_meaning,examples,tags,note
    examples 列为 JSON 数组 [{en, zh}] 或 | 分隔的英文句子。
    仅 abbreviation 和 my_meaning 必填；已存在的词条自动跳过。
    旧版 10 列（无 note）的 CSV 仍可直接导入，缺失列按空串补齐。
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
        data["next_review_at"] = today_start()  # 新词默认进复习队列，当天到期
        word = Word(**data)
        db.add(word)
        db.flush()
        created.append(word)

    db.commit()
    for w in created:
        db.refresh(w)
    return created


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
        ])

    csv_bytes = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="danciji_export.csv"'},
    )


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

    db.commit()
    db.refresh(word)
    return word


# ========== 删 ==========
@router.delete("/{word_id}")
def delete_word(word_id: int, db: Session = Depends(get_db)):
    word = db.query(Word).filter(Word.id == word_id).first()
    if not word:
        raise HTTPException(status_code=404, detail="词条不存在")
    db.delete(word)
    db.commit()
    return {"message": "删除成功"}


# ========== 标签 ==========
@tags_router.get("", response_model=list[TagItem])
def list_tags(db: Session = Depends(get_db)):
    """聚合所有标签及使用次数"""
    return [TagItem(name=name, count=count) for name, count in sorted_tag_items(db)]
