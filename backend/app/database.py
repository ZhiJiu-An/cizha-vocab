from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

# 允许用环境变量覆盖数据库位置（P2-7）：
# - 测试可以把库指向临时文件，绝不碰真实 data/danciji.db；
# - 也方便把数据放到别处 / 多套数据并存。
DB_PATH = os.environ.get("DANCIJI_DB_PATH") or os.path.join(DATA_DIR, "danciji.db")

# 自己确保 data 目录存在，而不是依赖 main.py 的 makedirs（P1-6）：
# 否则单独 import app.database（写脚本 / 造种子数据 / 跑测试）会因目录缺失
# 报 "unable to open database file"。create_engine 本身不会建目录。
os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)) or DATA_DIR, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},  # SQLite 多线程需要
    pool_pre_ping=True,                          # 连接失效自动重建，长跑更稳
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
