"""迁移测试（P0-5 存量标签归一 / P2-3 索引 / 幂等性）"""
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import app.main as main
from app.database import Base


class MigrateTestBase(unittest.TestCase):
    """建一个干净的内存库 + 直接插库的能力（本类不含测试方法）"""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.addCleanup(self.engine.dispose)

    # ---- 辅助 ----

    def insert_raw(self, abbreviation, tags, next_review_at=None):
        """绕过接口直接插库，模拟旧版本留下的数据"""
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO words (abbreviation, my_meaning, tags, has_abbr, review_stage,"
                    " review_count, in_review, examples, next_review_at)"
                    " VALUES (:a, 'm', :t, 0, 0, 0, 1, '[]', :n)"
                ),
                {"a": abbreviation, "t": tags, "n": next_review_at},
            )

    def tags(self):
        with self.engine.begin() as conn:
            return [r[0] for r in conn.execute(text("SELECT tags FROM words ORDER BY id"))]

    def index_names(self):
        with self.engine.begin() as conn:
            return {r[1] for r in conn.execute(text("PRAGMA index_list(words)"))}

    def run_migrate(self):
        with patch.object(main, "engine", self.engine):
            main._migrate()


class TestTagMigration(MigrateTestBase):
    def test_legacy_tags_are_normalized(self):
        self.insert_raw("w1", "大模型, RAG")
        self.insert_raw("w2", " a ,,a, b ")
        self.assertEqual(self.tags(), ["大模型, RAG", " a ,,a, b "])

        self.run_migrate()
        self.assertEqual(self.tags(), ["大模型,RAG", "a,b"])

    def test_migrate_is_idempotent(self):
        self.insert_raw("w1", " a , b ")
        self.run_migrate()
        first = self.tags()
        self.run_migrate()
        self.run_migrate()
        self.assertEqual(self.tags(), first)
        self.assertEqual(first, ["a,b"])

    def test_migrate_preserves_meaningful_tags(self):
        """含空格的标签不能被压缩成 chainofthought"""
        self.insert_raw("w1", "chain of thought")
        self.run_migrate()
        self.assertEqual(self.tags(), ["chain of thought"])

    def test_migrate_leaves_normalized_data_untouched(self):
        self.insert_raw("w1", "a,b")
        self.run_migrate()
        self.assertEqual(self.tags(), ["a,b"])

    def test_migrate_fills_missing_next_review_at(self):
        self.insert_raw("w1", "", next_review_at=None)
        self.run_migrate()
        with self.engine.begin() as conn:
            values = [r[0] for r in conn.execute(text("SELECT next_review_at FROM words"))]
        self.assertIsNotNone(values[0])


class TestReviewQueueIndex(MigrateTestBase):
    """P2-3：in_review 索引要被建出来（新库 create_all / 存量库 _migrate）"""

    def test_create_all_creates_index(self):
        self.assertIn("ix_words_in_review", self.index_names())   # setUp 已跑 create_all

    def test_migrate_adds_index_to_legacy_table(self):
        with self.engine.begin() as conn:
            conn.execute(text("DROP INDEX IF EXISTS ix_words_in_review"))
        self.assertNotIn("ix_words_in_review", self.index_names())

        self.run_migrate()
        self.assertIn("ix_words_in_review", self.index_names())

    def test_migrate_index_is_idempotent(self):
        self.run_migrate()
        self.run_migrate()
        self.assertIn("ix_words_in_review", self.index_names())
