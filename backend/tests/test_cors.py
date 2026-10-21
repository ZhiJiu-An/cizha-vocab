"""P1-2：CORS 必须按白名单放行，而不是全开放

全开放 + 浏览器访问任意恶意页面即可读写本地数据；这里锁定默认白名单行为，
避免有人把 allow_origins 改回 ["*"]。
"""

from tests.helpers import ApiTestCase


class TestCorsWhitelist(ApiTestCase):
    ALLOWED = "http://localhost:5173"
    EVIL = "http://evil.example.com"

    def test_allowed_origin_gets_acao_header(self):
        resp = self.client.get("/", headers={"Origin": self.ALLOWED})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), self.ALLOWED)

    def test_unknown_origin_gets_no_acao_header(self):
        resp = self.client.get("/", headers={"Origin": self.EVIL})
        self.assertIsNone(resp.headers.get("access-control-allow-origin"))

    def test_local_dev_origins_all_allowed(self):
        for origin in (
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ):
            with self.subTest(origin=origin):
                resp = self.client.get("/", headers={"Origin": origin})
                self.assertEqual(
                    resp.headers.get("access-control-allow-origin"), origin
                )

    def test_preflight_allowed_origin(self):
        resp = self.client.options(
            "/api/words",
            headers={
                "Origin": self.ALLOWED,
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), self.ALLOWED)
        self.assertIn("DELETE", resp.headers.get("access-control-allow-methods", ""))

    def test_preflight_unknown_origin_rejected(self):
        resp = self.client.options(
            "/api/words",
            headers={
                "Origin": self.EVIL,
                "Access-Control-Request-Method": "DELETE",
            },
        )
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIsNone(resp.headers.get("access-control-allow-origin"))
