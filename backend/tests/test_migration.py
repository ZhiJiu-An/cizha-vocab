"""迁移测试（P0-5 存量标签归一 / P2-3 索引 / 幂等性）"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import app.main as main
from app.database import Base, DB_FILENAME, LEGACY_DB_FILENAME, migrate_legacy_db


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


class TestLegacyDbFileMigration(unittest.TestCase):
    """v0.14 改名：danciji.db → cizha.db 的一次性迁移"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cizha-dbmig-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, name, content="data"):
        path = os.path.join(self.dir, name)
        Path(path).write_text(content, encoding="utf-8")
        return path

    def test_copies_legacy_file(self):
        legacy = self.write("danciji.db", "OLD-DB")
        self.assertTrue(migrate_legacy_db(self.dir))
        new = os.path.join(self.dir, "cizha.db")
        self.assertTrue(os.path.exists(new))
        self.assertEqual(Path(new).read_text(encoding="utf-8"), "OLD-DB")
        # 旧文件保留（可能是正在运行的实例在用）
        self.assertTrue(os.path.exists(legacy))

    def test_idempotent_when_target_exists(self):
        self.write("danciji.db", "OLD")
        self.write("cizha.db", "NEW")
        self.assertFalse(migrate_legacy_db(self.dir))
        self.assertEqual(Path(os.path.join(self.dir, "cizha.db")).read_text(encoding="utf-8"), "NEW")

    def test_noop_without_legacy_file(self):
        self.assertFalse(migrate_legacy_db(self.dir))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "cizha.db")))

    def test_defaults_point_at_project_filenames(self):
        self.assertEqual(DB_FILENAME, "cizha.db")
        self.assertEqual(LEGACY_DB_FILENAME, "danciji.db")


class TestNewEnvVarNames(unittest.TestCase):
    """新环境变量名生效，旧名仍可回落

    用子进程跑而不是 importlib.reload：reload 会重新执行模块级代码，
    可能在真实 backend/data 目录里触发一次迁移，污染开发者的数据目录。
    """

    def run_with_env(self, **env):
        import subprocess
        import sys
        target_dir = tempfile.mkdtemp(prefix="cizha-env-")
        self.addCleanup(shutil.rmtree, target_dir, True)
        target = os.path.join(target_dir, "x.db")
        full_env = {**os.environ, "PYTHONPATH": ".", **env}
        # 测试包自己设了 CIZHA_DB_PATH，必须清掉，否则会盖过本用例要验证的值
        for key in ("CIZHA_DB_PATH", "DANCIJI_DB_PATH"):
            full_env.pop(key, None)
        full_env.update(env)
        code = "import os; import app.database as d; print(d.DB_PATH)"
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, env=full_env, cwd=".",
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip(), target

    def test_new_name_is_honored(self):
        got, target = self.run_with_env(CIZHA_DB_PATH="/tmp/from-cizha.db")
        self.assertEqual(got, "/tmp/from-cizha.db")

    def test_legacy_name_still_works(self):
        got, _ = self.run_with_env(DANCIJI_DB_PATH="/tmp/from-danciji.db")
        self.assertEqual(got, "/tmp/from-danciji.db")

# 默认文件名由 TestLegacyDbFileMigration.test_defaults_point_at_project_filenames 覆盖；
    # 这里不再起子进程导入模块，否则会在真实 backend/data 里触发一次迁移。

