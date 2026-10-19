"""测试包入口（P2-7）

关键：本文件在**任何** `app.*` 模块被导入之前把数据库指向临时文件。
因为 `app.main` 在 import 阶段就会执行 `create_all()` 与 `_migrate()`，
若不先隔离，跑一次测试就会改动真实的 data/danciji.db。

用法（在 backend/ 下）：
    ./venv/bin/python -m unittest discover -s tests -t . -v
"""
import atexit
import os
import shutil
import tempfile

_TEST_DIR = tempfile.mkdtemp(prefix="danciji-test-")
atexit.register(shutil.rmtree, _TEST_DIR, ignore_errors=True)

# 必须在 import app.* 之前设置
os.environ["DANCIJI_DB_PATH"] = os.path.join(_TEST_DIR, "import-side-effects.db")
