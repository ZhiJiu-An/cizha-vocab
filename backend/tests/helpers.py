"""测试公共设施（P2-7）

每个测试用例拿到一份**全新的内存 SQLite**，通过覆盖 FastAPI 的 `get_db` 依赖
实现隔离 —— 用例之间互不影响，也绝不写真实库。
"""
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app as fastapi_app
from app.models import ReviewLog, Word  # noqa: F401  （供各测试模块复用）


def make_client():
    """返回 (TestClient, SessionLocal)，使用独占的内存库"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,          # 让所有会话共享同一条内存连接
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    SessionLocal.engine = engine      # 便于 tearDown 里 dispose，避免 ResourceWarning

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    from fastapi.testclient import TestClient
    return TestClient(fastapi_app, raise_server_exceptions=False), SessionLocal


class ApiTestCase(unittest.TestCase):
    """带干净内存库的测试基类"""

    def setUp(self):
        self.client, self.SessionLocal = make_client()

    def tearDown(self):
        fastapi_app.dependency_overrides.clear()
        self.SessionLocal.engine.dispose()

    # ---- 便捷方法 ----

    def create_word(self, abbreviation, my_meaning="释义", **fields):
        payload = {"abbreviation": abbreviation, "my_meaning": my_meaning, **fields}
        resp = self.client.post("/api/words", json=payload)
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def list_words(self, **params):
        return self.client.get("/api/words", params=params).json()

    def abbreviations(self, **params):
        return sorted(w["abbreviation"] for w in self.list_words(**params)["items"])

    def set_word(self, word_id, **columns):
        """直接改库，用于构造「到期 / 不到期」等场景"""
        db = self.SessionLocal()
        try:
            word = db.query(Word).filter(Word.id == word_id).first()
            for key, value in columns.items():
                setattr(word, key, value)
            db.commit()
        finally:
            db.close()

    def review_logs(self, word_id):
        db = self.SessionLocal()
        try:
            return db.query(ReviewLog).filter(ReviewLog.word_id == word_id).all()
        finally:
            db.close()
