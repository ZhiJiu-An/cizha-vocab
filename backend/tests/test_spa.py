"""单端口托管与健康检查测试（v0.14）

两个目的：
1. `/api/health` 之前零测试 —— 它是 v0.14 新增的服务信息入口；
2. 单端口模式的路径解析（静态文件优先 + 目录逃逸防护）在路由里按 dist 是否存在
   注册，CI 上没有 `frontend/dist` 就永远测不到。所以把它抽成纯函数
   `resolve_spa_path()`，这里用临时目录造一个假 dist 直接测。
"""
import tempfile
import unittest
from pathlib import Path

from app.main import APP_NAME, APP_VERSION, is_api_path, resolve_spa_path
from tests.helpers import make_client


def make_dist() -> Path:
    """造一个最小可用的假 dist：index.html + assets/app.js + favicon.svg"""
    root = Path(tempfile.mkdtemp(prefix="cizha-dist-"))
    (root / "index.html").write_text("<!doctype html><title>spa</title>", encoding="utf-8")
    (root / "assets").mkdir()
    (root / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (root / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return root


class TestResolveSpaPath(unittest.TestCase):
    def setUp(self):
        self.dist = make_dist()

    def test_serves_existing_file(self):
        resolved = resolve_spa_path("assets/app.js", self.dist)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.name, "app.js")

    def test_root_file(self):
        self.assertEqual(resolve_spa_path("favicon.svg", self.dist).name, "favicon.svg")

    def test_unknown_path_returns_none(self):
        """未知路径返回 None，交给路由回落 index.html（vue-router history 模式）"""
        for path in ("words", "stats", "words/42", "a/b/c"):
            with self.subTest(path=path):
                self.assertIsNone(resolve_spa_path(path, self.dist))

    def test_empty_path_returns_none(self):
        self.assertIsNone(resolve_spa_path("", self.dist))

    def test_directory_is_not_a_file(self):
        self.assertIsNone(resolve_spa_path("assets", self.dist))

    def test_traversal_is_rejected(self):
        """目录逃逸必须被拦住，且不能泄露 dist 之外的文件"""
        secret = self.dist.parent / "secret.txt"
        secret.write_text("TOP-SECRET", encoding="utf-8")
        self.addCleanup(secret.unlink, True)

        attacks = (
            "../secret.txt",
            "../../secret.txt",
            "assets/../../secret.txt",
            "./../secret.txt",
        )
        for attack in attacks:
            with self.subTest(attack=attack):
                self.assertIsNone(resolve_spa_path(attack, self.dist))

    def test_traversal_cannot_reach_repo_files(self):
        """再确认一次：拿真实存在的敏感文件名试，也必须返回 None"""
        self.assertIsNone(resolve_spa_path("../../../backend/.env", self.dist))
        self.assertIsNone(resolve_spa_path("/etc/passwd", self.dist))


class TestIsApiPath(unittest.TestCase):
    def test_api_paths(self):
        for path in ("api", "api/", "api/words", "api/words/1", "api/review/due"):
            with self.subTest(path=path):
                self.assertTrue(is_api_path(path))

    def test_non_api_paths(self):
        for path in ("", "words", "apix", "apiary", "stats", "assets/app.js"):
            with self.subTest(path=path):
                self.assertFalse(is_api_path(path))


class TestHealthEndpoint(unittest.TestCase):
    def setUp(self):
        self.client, sessions = make_client()
        self.addCleanup(sessions.engine.dispose)

    def test_health_returns_version(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["version"], APP_VERSION)
        self.assertEqual(body["name"], APP_NAME)
        self.assertEqual(body["docs"], "/docs")
        self.assertIn("message", body)

    def test_health_is_not_swallowed_by_spa_fallback(self):
        """即使 dist 存在、catch-all 已注册，/api/health 也必须返回 JSON"""
        resp = self.client.get("/api/health")
        self.assertTrue(resp.headers["content-type"].startswith("application/json"))

    def test_unknown_api_path_returns_json_404(self):
        resp = self.client.get("/api/does-not-exist")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["detail"], "接口不存在")


class TestVersionConsistency(unittest.TestCase):
    """版本号在代码里只应有一个来源"""

    def test_app_version_format(self):
        parts = APP_VERSION.split(".")
        self.assertEqual(len(parts), 3, APP_VERSION)
        self.assertTrue(all(p.isdigit() for p in parts), APP_VERSION)

    def test_app_name_matches(self):
        self.assertEqual(APP_NAME, "词札单词库")
