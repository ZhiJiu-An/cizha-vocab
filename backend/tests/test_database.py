"""数据库连接配置测试（P2-3：WAL 与 busy_timeout）

只碰临时目录里的库文件，不读也不写真实的 backend/data/。
"""
import os
import shutil
import tempfile
import unittest

from sqlalchemy import create_engine, event, text

from app import database


class PragmaTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cizha-pragma-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def make_engine(self, **connect_args):
        """独立文件库；connect_args 用来构造「驱动默认值」的基线"""
        engine = create_engine(
            f"sqlite:///{os.path.join(self.dir, 'p.db')}", connect_args=connect_args
        )
        self.addCleanup(engine.dispose)
        return engine

    @staticmethod
    def pragma(engine, name):
        with engine.connect() as conn:
            return conn.execute(text(f"PRAGMA {name}")).scalar()

    def test_busy_timeout_constant_is_positive(self):
        self.assertGreater(database.BUSY_TIMEOUT_MS, 0)

    def test_baseline_without_listener(self):
        """没有监听器时保持 SQLite / 驱动的默认值（对照基线）"""
        engine = self.make_engine(timeout=0)
        self.assertEqual(self.pragma(engine, "journal_mode"), "delete")
        self.assertEqual(self.pragma(engine, "busy_timeout"), 0)

    def test_listener_switches_to_wal_and_sets_waits(self):
        engine = self.make_engine(timeout=0)
        event.listen(engine, "connect", database.apply_sqlite_pragmas)

        self.assertEqual(self.pragma(engine, "journal_mode"), "wal")
        self.assertEqual(self.pragma(engine, "busy_timeout"), database.BUSY_TIMEOUT_MS)

    def test_listener_covers_new_pooled_connections(self):
        """busy_timeout 是每连接设置：连接池换新连接后必须仍然生效"""
        engine = self.make_engine(timeout=0)
        event.listen(engine, "connect", database.apply_sqlite_pragmas)
        self.pragma(engine, "journal_mode")     # 先建立一条连接

        engine.dispose()                        # 丢弃池内连接，下次 connect 会新建
        self.assertEqual(self.pragma(engine, "busy_timeout"), database.BUSY_TIMEOUT_MS)


class AppEnginePragmaTest(unittest.TestCase):
    """应用自己的引擎已挂上监听器（tests/__init__ 已把库指向临时文件）"""

    def test_app_engine_uses_wal(self):
        with database.engine.connect() as conn:
            self.assertEqual(conn.execute(text("PRAGMA journal_mode")).scalar(), "wal")
            self.assertEqual(
                conn.execute(text("PRAGMA busy_timeout")).scalar(),
                database.BUSY_TIMEOUT_MS,
            )


if __name__ == "__main__":
    unittest.main()
