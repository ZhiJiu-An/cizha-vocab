"""模型配置测试（v0.12：模型列表 + 默认角色 + 提示词预设）

关注：
1. 旧版 {"text", "vision"} 结构自动迁移成模型列表
2. .env 只在配置文件不存在时用于初始化，之后不再参与
3. 每种类型只有一个默认模型，切换 / 删除后自动补位
4. 文本模型提示词必须保留五段标记与 {word} 占位符
5. 视觉模型的地址 / Key 留空时回落到默认文本模型
6. 脱敏 Key 回传时能被还原，不会把 * 写进配置

所有用例把 llm_config.json 指向临时目录，绝不写真实的 backend/data/。
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import config
from app.routes import llm_config as route_mod
from tests.helpers import ApiTestCase

ENV_KEYS = (
    "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
    "LLM_VISION_BASE_URL", "LLM_VISION_API_KEY", "LLM_VISION_MODEL",
)

TEXT_PAYLOAD = {
    "name": "DeepSeek 翻译",
    "type": "text",
    "base_url": "https://text.example/v1",
    "api_key": "sk-text-12345678",
    "model": "deepseek-chat",
    "prompt_preset": "llm",
    "prompt": "",
}

VISION_PAYLOAD = {
    "name": "千问视觉",
    "type": "vision",
    "base_url": "",
    "api_key": "",
    "model": "qwen3-vl-plus",
    "prompt_preset": "custom",
    "prompt": "",
}


class ConfigTestCase(ApiTestCase):
    """把配置文件与环境变量都隔离到临时状态"""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmp_dir = Path(tmp.name)

        path_patcher = patch.multiple(
            config, CONFIG_DIR=tmp_dir, CONFIG_FILE=tmp_dir / "llm_config.json",
        )
        path_patcher.start()
        self.addCleanup(path_patcher.stop)

        env_patcher = patch.dict(os.environ, {key: "" for key in ENV_KEYS})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

        # 连通测试走网络，统一在用例里替换掉
        self.probe = AsyncMock(return_value=route_mod.TestResult(ok=True, message="连通测试通过"))
        probe_patcher = patch.object(route_mod, "_test_connection", new=self.probe)
        probe_patcher.start()
        self.addCleanup(probe_patcher.stop)

    # ---- 辅助 ----

    def set_env(self, **values):
        for key, value in values.items():
            os.environ[key] = value

    def configure_text_env(self):
        self.set_env(LLM_BASE_URL="https://text.example/v1",
                     LLM_API_KEY="sk-text-12345678", LLM_MODEL="deepseek-chat")

    def write_legacy(self, data: dict):
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config.CONFIG_FILE.write_text(json.dumps(data), encoding="utf-8")

    def get_models(self):
        resp = self.client.get("/api/llm/models")
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def create(self, **overrides):
        payload = {**TEXT_PAYLOAD, **overrides}
        return self.client.post("/api/llm/models", json=payload).json()

    def create_ok(self, **overrides):
        body = self.create(**overrides)
        self.assertTrue(body["ok"], body)
        return body["model"]

    def update(self, model_id, **overrides):
        payload = {**TEXT_PAYLOAD, **overrides}
        return self.client.put(f"/api/llm/models/{model_id}", json=payload).json()


class TestBootstrap(ConfigTestCase):
    def test_empty_when_nothing_configured(self):
        self.assertEqual(self.get_models()["models"], [])

    def test_env_bootstraps_default_cards_once(self):
        self.configure_text_env()
        self.set_env(LLM_VISION_MODEL="qwen3-vl-plus")

        body = self.get_models()
        models = body["models"]
        self.assertEqual(len(models), 2)
        roles = {m["type"]: m["role"] for m in models}
        self.assertEqual(roles, {"text": "default_text", "vision": "default_vision"})
        self.assertTrue(config.CONFIG_FILE.exists())
        self.assertIn("【定名】", next(m for m in models if m["type"] == "text")["prompt"])

        # 首次初始化后 .env 不再参与
        self.set_env(LLM_MODEL="env-model")
        self.assertEqual(len(self.get_models()["models"]), 2)
        self.assertEqual(config.get_llm_config()[2], "deepseek-chat")

    def test_legacy_structure_migrates(self):
        self.write_legacy({
            "text": {"base_url": "https://text.example/v1",
                     "api_key": "sk-text-12345678", "model": "deepseek-chat"},
            "vision": {"base_url": "", "api_key": "", "model": "qwen3-vl-plus"},
        })

        models = self.get_models()["models"]
        self.assertEqual(len(models), 2)
        self.assertEqual({m["type"] for m in models}, {"text", "vision"})

        text = next(m for m in models if m["type"] == "text")
        self.assertEqual(text["role"], "default_text")
        self.assertIn("【译文】", text["prompt"])
        self.assertEqual(config.get_llm_config(),
                         ("https://text.example/v1", "sk-text-12345678", "deepseek-chat"))

        saved = json.loads(config.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(saved["version"], 2)
        self.assertEqual(len(saved["models"]), 2)

        # 再次读取不会重复迁移
        self.assertEqual(len(self.get_models()["models"]), 2)

    def test_legacy_partial_section_skipped(self):
        self.write_legacy({"text": {"model": "", "base_url": "https://x/v1"}})
        self.assertEqual(self.get_models()["models"], [])


class TestCrud(ConfigTestCase):
    def test_create_text_model_becomes_default(self):
        card = self.create_ok()
        self.assertEqual(card["role"], "default_text")
        self.assertEqual(config.get_llm_config(), ("https://text.example/v1",
                                                   "sk-text-12345678", "deepseek-chat"))
        self.assertEqual(config.CONFIG_FILE.stat().st_size > 0, True)

    def test_create_returns_masked_key(self):
        card = self.create_ok()
        self.assertIn("*", card["api_key"])
        self.assertNotIn("sk-text-12345678", card["api_key"])

    def test_failed_probe_is_not_saved(self):
        self.probe.return_value = route_mod.TestResult(ok=False, message="服务返回 404")
        body = self.create()
        self.assertFalse(body["ok"])
        self.assertEqual(self.get_models()["models"], [])

    def test_update_restores_masked_key(self):
        card = self.create_ok()
        masked = self.get_models()["models"][0]["api_key"]

        body = self.update(card["id"], name="DeepSeek 新", api_key=masked)
        self.assertTrue(body["ok"], body)
        saved = config.get_model(card["id"])
        self.assertEqual(saved["api_key"], "sk-text-12345678")
        self.assertEqual(saved["name"], "DeepSeek 新")
        self.assertNotIn("*", saved["api_key"])

    def test_update_missing_model(self):
        resp = self.client.put("/api/llm/models/nope", json=TEXT_PAYLOAD)
        self.assertEqual(resp.status_code, 404)

    def test_delete_promotes_next_model(self):
        first = self.create_ok()
        second = self.create_ok(name="备用模型", model="deepseek-reasoner")
        self.assertEqual(config.get_model(first["id"])["role"], "default_text")

        resp = self.client.delete(f"/api/llm/models/{first['id']}")
        self.assertEqual(resp.status_code, 200)
        remaining = config.get_model(second["id"])
        self.assertEqual(remaining["role"], "default_text")
        self.assertEqual(config.get_llm_config()[2], "deepseek-reasoner")

    def test_delete_missing_model(self):
        self.assertEqual(self.client.delete("/api/llm/models/nope").status_code, 404)

    def test_set_default_switches_translation_model(self):
        self.create_ok()
        other = self.create_ok(name="备用", model="deepseek-reasoner")

        resp = self.client.post(f"/api/llm/models/{other['id']}/default")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["role"], "default_text")
        self.assertEqual(config.get_llm_config()[2], "deepseek-reasoner")

        roles = [m["role"] for m in config.list_models()]
        self.assertEqual(roles.count("default_text"), 1)

    def test_set_default_missing_model(self):
        self.assertEqual(self.client.post("/api/llm/models/nope/default").status_code, 404)


class TestPrompts(ConfigTestCase):
    def test_empty_prompt_filled_from_preset(self):
        card = self.create_ok(prompt="", prompt_preset="medical")
        self.assertIn("医学", card["prompt"])
        self.assertIn("【定名】", card["prompt"])

    def test_custom_prompt_saved(self):
        custom = ("你是医学术语翻译，翻译「{word}」。\n"
                  "【定名】中文名\n【展开】全称\n【详解】解释\n【例句】例句\n【译文】翻译")
        card = self.create_ok(prompt=custom, prompt_preset="custom")
        self.assertEqual(card["prompt"], custom)

    def test_prompt_missing_marker_rejected(self):
        custom = "翻译「{word}」\n【定名】中文名\n【展开】全称\n【详解】解释"
        body = self.create(prompt=custom, prompt_preset="custom")
        self.assertFalse(body["ok"])
        self.assertIn("【例句】", body["message"])
        self.assertEqual(self.get_models()["models"], [])

    def test_prompt_missing_word_placeholder_rejected(self):
        custom = "翻译这个词\n【定名】中文名\n【展开】全称\n【详解】解释\n【例句】例句\n【译文】翻译"
        body = self.create(prompt=custom, prompt_preset="custom")
        self.assertFalse(body["ok"])
        self.assertIn("{word}", body["message"])

    def test_vision_prompt_is_cleared(self):
        self.configure_text_env()
        self.client.get("/api/llm/models")            # 初始化文本卡
        card = self.create_ok(**VISION_PAYLOAD)
        self.assertEqual(card["prompt"], "")
        self.assertEqual(card["prompt_preset"], "custom")

    def test_build_prompt_replaces_word(self):
        text = config.build_prompt("token", "翻译「{word}」")
        self.assertEqual(text, "翻译「token」")

    def test_build_prompt_ignores_other_braces(self):
        text = config.build_prompt("token", "输出 JSON：{'word': '{word}'}")
        self.assertEqual(text, "输出 JSON：{'word': 'token'}")


class TestVisionFallback(ConfigTestCase):
    def test_only_model_required(self):
        self.create_ok()                              # 默认文本模型
        card = self.create_ok(**VISION_PAYLOAD)
        self.assertEqual(card["base_url"], "")
        self.assertEqual(card["api_key"], "")
        self.assertEqual(config.get_vision_config(),
                         ("https://text.example/v1", "sk-text-12345678", "qwen3-vl-plus"))

        args = self.probe.await_args.args
        self.assertEqual(args[0], "https://text.example/v1")
        self.assertEqual(args[1], "sk-text-12345678")
        self.assertEqual(args[2], "qwen3-vl-plus")
        self.assertEqual(args[3], "vision")

    def test_vision_own_endpoint(self):
        self.create_ok()
        self.create_ok(**{**VISION_PAYLOAD,
                          "base_url": "https://vision.example/v1",
                          "api_key": "sk-vis-12345678"})
        self.assertEqual(config.get_vision_config(),
                         ("https://vision.example/v1", "sk-vis-12345678", "qwen3-vl-plus"))

    def test_vision_needs_model(self):
        self.create_ok()
        body = self.create(**{**VISION_PAYLOAD, "model": "  "})
        self.assertFalse(body["ok"])
        self.assertIn("模型名", body["message"])

    def test_vision_rejected_without_fallback(self):
        body = self.create(**VISION_PAYLOAD)
        self.assertFalse(body["ok"])
        self.assertIn("Base URL", body["message"])
        self.assertEqual(self.get_models()["models"], [])


class TestProbe(ConfigTestCase):
    def test_probe_uses_effective_values(self):
        self.create_ok()
        args = self.probe.await_args.args
        self.assertEqual(args[:3], ("https://text.example/v1",
                                    "sk-text-12345678", "deepseek-chat"))

    def test_test_endpoint_restores_masked_key(self):
        card = self.create_ok()
        masked = self.get_models()["models"][0]["api_key"]
        self.probe.reset_mock()

        resp = self.client.post("/api/llm/models/test",
                                json={**TEXT_PAYLOAD, "api_key": masked, "id": card["id"]})
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(self.probe.await_args.args[1], "sk-text-12345678")

    def test_test_endpoint_does_not_save(self):
        before = self.get_models()
        self.client.post("/api/llm/models/test", json=TEXT_PAYLOAD)
        self.assertEqual(self.get_models()["models"], before["models"])


class TestProbePayload(unittest.IsolatedAsyncioTestCase):
    """连通测试的请求体：视觉模型必须真的带图，文本模型只发纯文本"""

    def _client(self, status_code=200):
        resp = AsyncMock()
        resp.status_code = status_code
        resp.text = "boom"
        client = AsyncMock()
        client.post = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    async def test_vision_sends_image(self):
        client = self._client()
        with patch.object(route_mod.httpx, "AsyncClient", return_value=client):
            result = await route_mod._test_connection(
                "https://x/v1", "sk-1", "qwen3-vl-plus", "vision")
        self.assertTrue(result.ok)
        content = client.post.await_args.kwargs["json"]["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    async def test_test_image_is_big_enough(self):
        """实测端点在宽或高 ≤10px 时报 InvalidParameter，测试图必须够大"""
        import base64
        import struct
        png = base64.b64decode(route_mod.TEST_IMAGE_B64)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", png[16:24])
        self.assertGreater(width, 10)
        self.assertGreater(height, 10)

    async def test_text_sends_plain_string(self):
        client = self._client()
        with patch.object(route_mod.httpx, "AsyncClient", return_value=client):
            await route_mod._test_connection("https://x/v1", "sk-1", "deepseek-chat", "text")
        content = client.post.await_args.kwargs["json"]["messages"][0]["content"]
        self.assertIsInstance(content, str)

    async def test_minimal_token_request(self):
        client = self._client()
        with patch.object(route_mod.httpx, "AsyncClient", return_value=client):
            await route_mod._test_connection("https://x/v1", "sk-1", "m", "text")
        self.assertEqual(client.post.await_args.kwargs["json"]["max_tokens"], 1)

    async def test_non_200_reports_status(self):
        client = self._client(status_code=401)
        with patch.object(route_mod.httpx, "AsyncClient", return_value=client):
            result = await route_mod._test_connection("https://x/v1", "sk-1", "m", "text")
        self.assertFalse(result.ok)
        self.assertIn("401", result.message)


class TestPureHelpers(unittest.TestCase):
    def test_normalize_kind(self):
        self.assertEqual(config.normalize_kind("vision"), "vision")
        self.assertEqual(config.normalize_kind(""), "text")
        self.assertEqual(config.normalize_kind("../etc/passwd"), "text")

    def test_mask_key(self):
        self.assertEqual(config.mask_key("sk-1234567890"), "sk-1*****7890")
        self.assertEqual(config.mask_key("short"), "*****")
        self.assertEqual(config.mask_key(""), "")

    def test_validate_prompt(self):
        self.assertTrue(config.validate_prompt(""))
        self.assertIn("【定名】", config.validate_prompt("翻译 {word}"))
        self.assertEqual(config.validate_prompt(config.preset_prompt("llm")), "")

    def test_unknown_preset_falls_back_to_custom(self):
        card = config._clean_model({"type": "text", "prompt_preset": "banana",
                                    "prompt": "", "model": "m"})
        self.assertEqual(card["prompt_preset"], "llm")
        self.assertIn("【定名】", card["prompt"])
