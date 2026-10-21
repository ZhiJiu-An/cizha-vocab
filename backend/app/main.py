from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from dotenv import load_dotenv

from .database import engine, Base
from .routes import words, dictionary, translate, stats, ocr, review, llm_config

# 加载 backend/.env 中的环境变量（LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 等）
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# 确保 data 目录存在（SQLite 文件所在目录）
os.makedirs(os.path.join(os.path.dirname(__file__), "..", "data"), exist_ok=True)

# 自动建表（含 v0.5 新增的 review_logs 表）
Base.metadata.create_all(bind=engine)


def _migrate():
    """SQLite 轻量迁移：给已有 words 表补 v0.5 复习列（幂等，不引 alembic）"""
    from sqlalchemy import text

    from .common import normalize_tags

    new_columns = {
        "review_stage": "INTEGER DEFAULT 0",
        "next_review_at": "DATETIME",
        "last_reviewed_at": "DATETIME",
        "review_count": "INTEGER DEFAULT 0",
        "in_review": "INTEGER DEFAULT 1",
    }
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(words)"))}
        for col, ddl in new_columns.items():
            if col not in existing:
                conn.execute(text(f"ALTER TABLE words ADD COLUMN {col} {ddl}"))
        # 存量词条：复习日期置为当天（新词当天即到期）
        conn.execute(text(
            "UPDATE words SET next_review_at = date('now') WHERE next_review_at IS NULL"
        ))
        # 复习队列索引（P2-3）：in_review 参与 /review 的全部查询，旧库没有这个索引。
        # 新库由 create_all 依据 models 的 index=True 自动建，这里只补存量库（幂等）。
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_words_in_review ON words (in_review)"
        ))
        # 存量标签归一（P0-5）：把 "大模型, RAG" 统一成 "大模型,RAG"，
        # 否则按「,tag,」边界精确匹配会漏掉带空格的历史标签
        for word_id, tags in conn.execute(
            text("SELECT id, tags FROM words WHERE tags IS NOT NULL")
        ).fetchall():
            normalized = normalize_tags(tags)
            if normalized != tags:
                conn.execute(
                    text("UPDATE words SET tags = :tags WHERE id = :id"),
                    {"tags": normalized, "id": word_id},
                )


_migrate()

app = FastAPI(title="DanCiJi 术语记录本", version="0.12.0")

# 跨域（Vue 前端在另一端口）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(words.router)
app.include_router(words.tags_router)
app.include_router(dictionary.router)
app.include_router(translate.router)
app.include_router(review.router)
app.include_router(stats.router)
app.include_router(ocr.router)
app.include_router(llm_config.router)


@app.get("/")
def root():
    return {
        "name": "DanCiJi",
        "version": "0.12.0",
        "docs": "/docs",
        "message": "面向技术从业者的术语 / 单词记录本",
    }
