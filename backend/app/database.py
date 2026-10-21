from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

DB_FILENAME = "cizha.db"
LEGACY_DB_FILENAME = "danciji.db"   # v0.14 之前的文件名，用于一次性迁移


def migrate_legacy_db(data_dir: str, new_name: str = DB_FILENAME,
                      old_name: str = LEGACY_DB_FILENAME) -> bool:
    """把旧版数据库文件迁移成新文件名，返回是否发生了迁移

    v0.14 起项目改名为「词札单词库」，库文件从 danciji.db 改为 cizha.db。
    这里用**复制**而不是重命名：即使有一个旧实例正开着 danciji.db，
    也不会因为文件被移走而崩掉；旧文件保留，确认无误后可自行删除。

    只用 copyfile（复制内容）而不用 copy2：copy2 还会复制权限 / 时间等元数据，
    在受限环境里可能因 utime/chmod 被拒而整体失败 —— 那样会静默建成一个空库，
    用户会以为"数据全没了"。失败时打印警告，便于排查。

    只在目标不存在、且调用方没有用环境变量指定路径时才会触发
    （见下方 DB_PATH 的构造），因此测试与自定义路径不受影响。
    """
    new_path = os.path.join(data_dir, new_name)
    old_path = os.path.join(data_dir, old_name)
    if os.path.exists(new_path) or not os.path.exists(old_path):
        return False
    try:
        shutil.copyfile(old_path, new_path)
        return True
    except OSError as exc:
        print(
            f"警告：旧数据库 {old_path} 迁移到 {new_path} 失败（{exc}）。"
            f"应用将使用新建的空库；如需保留旧数据，请手动复制 {old_path} 到 {new_path}。",
            file=sys.stderr,
        )
        # 迁移失败不应阻止启动，但要让用户看见；删掉可能残留的半成品文件，
        # 以免下次启动误判为"已迁移过"而永久跳过。
        try:
            if os.path.exists(new_path):
                os.remove(new_path)
        except OSError:
            pass
        return False


# 允许用环境变量覆盖数据库位置（P2-7）：
# - 测试可以把库指向临时文件，绝不碰真实的 data/cizha.db；
# - 也方便把数据放到别处 / 多套数据并存。
_env_db_path = os.environ.get("CIZHA_DB_PATH") or os.environ.get(
    "DANCIJI_DB_PATH"   # 旧名兼容，v0.14 后弃用
)
if _env_db_path:
    DB_PATH = _env_db_path
else:
    # 没有显式指定时才做旧文件迁移，避免污染测试与自定义路径
    migrate_legacy_db(DATA_DIR)
    DB_PATH = os.path.join(DATA_DIR, DB_FILENAME)

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
