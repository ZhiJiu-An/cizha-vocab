from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from dotenv import load_dotenv

from .database import engine, Base
from .routes import words, dictionary, translate, review, stats, ocr

# 加载 backend/.env 中的环境变量（LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 等）
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# 确保 data 目录存在（SQLite 文件所在目录）
os.makedirs(os.path.join(os.path.dirname(__file__), "..", "data"), exist_ok=True)

# 自动建表（含 v0.5 新增的 review_logs 表）
Base.metadata.create_all(bind=engine)


def _migrate():
    """SQLite 轻量迁移：给已有 words 表补 v0.5 复习列（幂等，不引 alembic）"""
    from sqlalchemy import text
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


_migrate()

app = FastAPI(title="DanCiJi 术语记录本", version="0.7.0")

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


@app.get("/")
def root():
    return {
        "name": "DanCiJi",
        "version": "0.7.0",
        "docs": "/docs",
        "message": "面向技术从业者的术语 / 单词记录本",
    }
