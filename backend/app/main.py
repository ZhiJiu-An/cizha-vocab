from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os

from dotenv import load_dotenv

from .database import engine, Base
from .routes import words, dictionary, translate, stats, ocr, review, llm_config

# 版本号只在这里定义一次，/api/health 与根路径兜底都引用它
APP_VERSION = "0.14.0"
APP_NAME = "DanCiJi 术语记录本"

# 加载 backend/.env 中的环境变量（LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 等）
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# 确保 data 目录存在（SQLite 文件所在目录）
os.makedirs(os.path.join(os.path.dirname(__file__), "..", "data"), exist_ok=True)

# 自动建表（含 v0.5 新增的 review_logs 表）
Base.metadata.create_all(bind=engine)


def is_api_path(full_path: str) -> bool:
    """是否是 API 路径（单端口模式下不能让这类请求回落到 index.html）"""
    return full_path == "api" or full_path.startswith("api/")


def resolve_spa_path(full_path: str, dist_root: Path) -> Path | None:
    """把请求路径解析成 dist 内的真实文件；不合法、越界或不存在均返回 None

    抽成纯函数是为了可测：路由在 import 时按 dist 是否存在注册，CI 里没有 dist，
    若不抽出来，这段「静态文件 + 目录逃逸」逻辑永远无法被测试覆盖。

    越界判断放在 is_file() 之前：先确认目标仍在 dist 内，再落到文件系统检查。
    """
    if not full_path:
        return None
    try:
        root = dist_root.resolve()
        target = (root / full_path).resolve()
    except (OSError, RuntimeError):
        return None
    if not target.is_relative_to(root):
        return None
    return target if target.is_file() else None


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

app = FastAPI(title=APP_NAME, version=APP_VERSION)

# 跨域（Vue 前端在另一端口）
# v0.13：不再全开放。默认只允许本地开发/预览端口，可用 DANCIJI_ALLOWED_ORIGINS
# （逗号分隔）覆盖，部署到其他域名时无需改代码。
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "DANCIJI_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
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


@app.get("/api/health")
def health():
    return {
        "name": "DanCiJi",
        "version": APP_VERSION,
        "docs": "/docs",
        "message": "面向技术从业者的术语 / 单词记录本",
    }


# ---- 单端口模式（v0.14）----
# 前端构建产物存在时，由 FastAPI 直接托管 dist：
# 用户只需要启动后端一个进程，访问 http://127.0.0.1:8000 即可。
# 开发时仍可用 `npm run dev`（5173）配合后端热更新。
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

if FRONTEND_DIST.is_dir():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        """静态文件优先，其余路径回落到 index.html（适配 vue-router history 模式）"""
        if is_api_path(full_path):
            raise HTTPException(status_code=404, detail="接口不存在")

        resolved = resolve_spa_path(full_path, FRONTEND_DIST)
        if resolved is not None:
            return FileResponse(resolved)

        index = FRONTEND_DIST / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="前端未构建")
        return FileResponse(index)

else:
    @app.get("/")
    def root():
        """未构建前端时的兜底信息页（开发 / CI 环境）"""
        return {
            "name": "DanCiJi",
            "version": APP_VERSION,
            "docs": "/docs",
            "message": "面向技术从业者的术语 / 单词记录本（前端未构建，请运行 ./setup.sh 或 npm run build）",
        }
