from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from .database import engine, Base
from .routes import words, dictionary

# 确保 data 目录存在（SQLite 文件所在目录）
os.makedirs(os.path.join(os.path.dirname(__file__), "..", "data"), exist_ok=True)

# 自动建表
Base.metadata.create_all(bind=engine)

app = FastAPI(title="DanCiJi 术语记录本", version="0.3.0")

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


@app.get("/")
def root():
    return {
        "name": "DanCiJi",
        "version": "0.3.0",
        "docs": "/docs",
        "message": "面向技术从业者的术语 / 单词记录本",
    }
