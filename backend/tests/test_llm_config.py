"""大模型配置测试（v0.9：text / vision 双区块，各自独立）

关注三点：
1. 两个区块互不干扰（存一个不影响另一个，删一个不牵连另一个）
2. 视觉模型的地址 / Key 允许留空并正确回落到文本模型
3. 脱敏 Key 回传时能被还原，不会把 * 写进配置

所有用例把 llm_config.json 指向临时目录，绝不写真实的 backend/data/。
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from tests.helpers import ApiTestCase
from app import config
from app.routes import llm_config as route_mod

ENV_KEYS = (
    "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
    "LLM_VISION_BASE_URL", "LLM_VISION_API_KEY", "LLM_VISION_MODEL",
)


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

        # 清掉 .env 带来的变量，避免真实配置影响断言
        env_patcher = patch.dict(os.environ, {key: "" for key in ENV_KEYS})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

        # 连通测试走网络，统一在用例里替换掉
        self.probe = AsyncMock(return_value=route_mod.TestResult(ok=True, message="连通测试通过"))
        probe_patcher = patch.object(route_mod, "_test_connection", new=self.probe)
        probe_patcher.start()
        self.addCleanup(probe_patcher.stop)

    # ---- 辅助 ----

    def save_runtime(self, kind, base_url="", api_key="", model=""):
        config.save_runtime_config(kind, base_url, api_key, model)

    def set_env(self, **values):
        for key, value in values.items():
            os.environ[key] = value

    def configure_text_env(self):
        """给一份完整的文本模型环境变量，供视觉模型回落"""
        self.set_env(LLM_BASE_URL="https://text.example/v1",
                     LLM_API_KEY="sk-text-12345678", LLM_MODEL="deepseek-chat")

    def get_config(self, kind="text"):
        return self.client.get("/api/llm/config", params={"kind": kind}).json()

    def put_config(self, kind, **payload):
        return self.client.put("/api/llm/config", json=payload, params={"kind": kind}).json()


class TestGetConfig(ConfigTestCase):
    def test_text_falls_back_to_env(self):
        self.set_env(LLM_BASE_URL="https://env.example/v1", LLM_API_KEY="sk-env-12345678",
                     LLM_MODEL="deepseek-chat")
        body = self.get_config("text")
        self.assertEqual(body["source"], "env")
        self.assertFalse(body["has_runtime"])
        self.assertEqual(body["model"], "deepseek-chat")
        self.assertIn("*", body["api_key"])            # 明文不外泄
        self.assertNotIn("sk-env-12345678", body["api_key"])

    def test_nothing_configured(self):
        body = self.get_config("text")
        self.assertEqual(body["source"], "none")
        self.assertEqual(body["model"], "")

    def test_runtime_wins_over_env(self):
        self.set_env(LLM_BASE_URL="https://env.example/v1", LLM_API_KEY="sk-env-12345678",
                     LLM_MODEL="env-model")
        self.save_runtime("text", "https://runtime.example/v1", "sk-run-12345678", "run-model")
        body = self.get_config("text")
        self.assertEqual(body["source"], "runtime")
        self.assertTrue(body["has_runtime"])
        self.assertEqual(body["model"], "run-model")

    def test_vision_reports_none_without_model(self):
        self.assertEqual(self.get_config("vision")["source"], "none")

    def test_vision_source_is_env(self):
        self.set_env(LLM_VISION_MODEL="qwen3-vl-plus")
        body = self.get_config("vision")
        self.assertEqual(body["source"], "env")
        self.assertEqual(body["model"], "qwen3-vl-plus")

    def test_illegal_kind_falls_back_to_text(self):
        """脏参数不能 500，按文本模型处理"""
        self.set_env(LLM_MODEL="deepseek-chat", LLM_API_KEY="sk-env-12345678")
        self.assertEqual(self.get_config("banana")["model"], "deepseek-chat")


class TestSaveConfig(ConfigTestCase):
    def test_text_save_success(self):
        body = self.put_config("text", base_url="https://api.deepseek.com/v1",
                               api_key="sk-real-12345678", model="deepseek-chat")
        self.assertTrue(body["ok"], body)
        self.assertEqual(config.load_runtime_config("text")["model"], "deepseek-chat")
        self.assertEqual(self.get_config("text")["source"], "runtime")

    def test_failed_probe_is_not_saved(self):
        self.probe.return_value = route_mod.TestResult(ok=False, message="服务返回 404")
        body = self.put_config("text", base_url="https://x/v1", api_key="sk-real-12345678",
                               model="nope")
        self.assertFalse(body["ok"])
        self.assertIsNone(config.load_runtime_config("text"))

    def test_masked_key_is_restored_not_saved_literally(self):
        """表单回显的是脱敏值，保存时不能把 **** 写进配置"""
        self.save_runtime("text", "https://x/v1", "sk-real-12345678", "m1")
        body = self.put_config("text", base_url="https://y/v1",
                               api_key="sk-r**********5678", model="m2")
        self.assertTrue(body["ok"], body)
        saved = config.load_runtime_config("text")
        self.assertEqual(saved["api_key"], "sk-real-12345678")
        self.assertNotIn("*", saved["api_key"])
        self.assertEqual(saved["base_url"], "https://y/v1")

    def test_empty_model_rejected(self):
        body = self.put_config("text", base_url="https://x/v1", api_key="sk-a", model="  ")
        self.assertFalse(body["ok"])
        self.assertIn("模型名", body["message"])


class TestVisionFallback(ConfigTestCase):
    """视觉模型只填一个模型名就该能工作 —— 地址与 Key 回落文本模型"""

    def test_only_model_required(self):
        self.configure_text_env()
        body = self.put_config("vision", model="qwen3-vl-plus")
        self.assertTrue(body["ok"], body)

        saved = config.load_runtime_config("vision")
        self.assertEqual(saved["base_url"], "")          # 留空就存空，回落保持动态
        self.assertEqual(saved["model"], "qwen3-vl-plus")

        base_url, api_key, model = config.get_vision_config()
        self.assertEqual(base_url, "https://text.example/v1")
        self.assertEqual(api_key, "sk-text-12345678")
        self.assertEqual(model, "qwen3-vl-plus")

    def test_vision_own_endpoint_wins(self):
        self.save_runtime("text", "https://text.example/v1", "sk-text-12345678", "deepseek-chat")
        self.save_runtime("vision", "https://vision.example/v1", "sk-vis-12345678", "qwen3-vl-plus")
        self.assertEqual(config.get_vision_config(),
                         ("https://vision.example/v1", "sk-vis-12345678", "qwen3-vl-plus"))

    def test_blank_fields_fall_back_to_vision_env(self):
        """.env 已配视觉端点时，表单留空应沿用该端点，而不是错落到文本模型"""
        self.configure_text_env()                       # 文本模型在 deepseek 端点
        self.set_env(LLM_VISION_BASE_URL="https://vision.example/v1",
                     LLM_VISION_API_KEY="sk-vis-12345678")
        body = self.put_config("vision", model="qwen3-vl-plus")
        self.assertTrue(body["ok"], body)
        args = self.probe.await_args.args
        self.assertEqual(args[0], "https://vision.example/v1")
        self.assertEqual(args[1], "sk-vis-12345678")

    def test_vision_env_endpoint_beats_text_fallback(self):
        """回落链顺序：LLM_VISION_* 优先于文本模型"""
        self.configure_text_env()
        self.set_env(LLM_VISION_BASE_URL="https://vision.example/v1",
                     LLM_VISION_API_KEY="sk-vis-12345678")
        self.assertEqual(config.fallback_credentials("vision"),
                         ("https://vision.example/v1", "sk-vis-12345678"))

    def test_saved_blank_fields_still_use_vision_env(self):
        """只填模型名保存后，实际调用端点必须与保存时测试的端点一致

        回归用例：运行时 vision 区块地址 / Key 为空时，仍要先看 .env 的
        LLM_VISION_*，不能直接跳到文本模型 —— 否则「测试通过」的端点和
        图片取词真正请求的端点会不是同一个。
        """
        self.configure_text_env()                       # 文本模型在 text 端点
        self.set_env(LLM_VISION_BASE_URL="https://vision.example/v1",
                     LLM_VISION_API_KEY="sk-vis-12345678")
        self.assertTrue(self.put_config("vision", model="qwen3-vl-plus")["ok"])

        probed = self.probe.await_args.args             # 保存时测的端点
        self.assertEqual(config.get_vision_config(),     # 运行时用的端点
                         (probed[0], probed[1], "qwen3-vl-plus"))
        self.assertEqual(probed[0], "https://vision.example/v1")

    def test_probe_uses_effective_values(self):
        """留空回落时，连通测试必须拿真实生效值去试，而不是空串"""
        self.configure_text_env()
        self.put_config("vision", model="qwen3-vl-plus")
        args = self.probe.await_args.args
        self.assertEqual(args[0], "https://text.example/v1")
        self.assertEqual(args[1], "sk-text-12345678")
        self.assertEqual(args[2], "qwen3-vl-plus")
        self.assertEqual(args[3], "vision")

    def test_vision_usable_via_env_only(self):
        self.configure_text_env()
        self.set_env(LLM_VISION_MODEL="glm-4v")
        self.assertEqual(config.get_vision_config(),
                         ("https://text.example/v1", "sk-text-12345678", "glm-4v"))

    def test_vision_needs_model_even_with_credentials(self):
        """只有地址和 Key、没有模型名 —— 仍算未配置（文本模型不接受图片）"""
        self.configure_text_env()
        self.assertIsNone(config.get_vision_config())

    def test_vision_save_rejected_without_any_fallback(self):
        """没有任何可回落的配置时，只填模型名无法完成连通测试，应拒绝保存"""
        body = self.put_config("vision", model="qwen3-vl-plus")
        self.assertFalse(body["ok"])
        self.assertIn("Base URL", body["message"])
        self.assertIsNone(config.load_runtime_config("vision"))


class TestSectionsAreIsolated(ConfigTestCase):
    def test_saving_vision_keeps_text(self):
        self.put_config("text", base_url="https://text.example/v1",
                        api_key="sk-text-12345678", model="deepseek-chat")
        self.put_config("vision", base_url="https://vision.example/v1",
                        api_key="sk-vis-12345678", model="qwen3-vl-plus")
        self.assertEqual(config.load_runtime_config("text")["model"], "deepseek-chat")
        self.assertEqual(config.load_runtime_config("vision")["model"], "qwen3-vl-plus")

    def test_deleting_vision_keeps_text(self):
        self.put_config("text", base_url="https://text.example/v1",
                        api_key="sk-text-12345678", model="deepseek-chat")
        self.configure_text_env()          # 视觉模型只填模型名，靠环境变量回落
        self.assertTrue(self.put_config("vision", model="qwen3-vl-plus")["ok"])

        resp = self.client.delete("/api/llm/config", params={"kind": "vision"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(config.load_runtime_config("vision"))
        self.assertEqual(config.load_runtime_config("text")["model"], "deepseek-chat")

    def test_deleting_last_section_removes_file(self):
        self.configure_text_env()
        self.assertTrue(self.put_config("vision", model="qwen3-vl-plus")["ok"])
        self.assertTrue(config.CONFIG_FILE.exists())
        self.client.delete("/api/llm/config", params={"kind": "vision"})
        self.assertFalse(config.CONFIG_FILE.exists())


class TestRuntimeState(ConfigTestCase):
    def test_state_none(self):
        state = config.runtime_state("vision")
        self.assertEqual(state["source"], "none")
        self.assertFalse(state["has_runtime"])

    def test_state_runtime_with_blank_fields_still_visible(self):
        """留空回落的视觉配置要能回显出来，否则设置页会显示成「未配置」"""
        self.save_runtime("vision", "", "", "qwen3-vl-plus")
        state = config.runtime_state("vision")
        self.assertEqual(state["source"], "runtime")
        self.assertTrue(state["has_runtime"])
        self.assertEqual(state["model"], "qwen3-vl-plus")
        self.assertEqual(state["base_url"], "")
        self.assertEqual(config.mask_key(state["api_key"]), "")

    def test_text_state_requires_all_three(self):
        """文本模型缺字段算未配置（没有可回落对象）"""
        self.save_runtime("text", "https://x/v1", "", "m")
        self.assertIsNone(config.load_runtime_config("text"))


class TestVisionProbePayload(unittest.IsolatedAsyncioTestCase):
    """视觉连通测试要真的发一张图 —— 否则测不出端点是否支持图片输入"""

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
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")          # 确实是 PNG
        width, height = struct.unpack(">II", png[16:24])         # 读 IHDR
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

    def test_current_api_key_reads_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            with patch.multiple(config, CONFIG_DIR=tmp_dir,
                                CONFIG_FILE=tmp_dir / "llm_config.json"), \
                    patch.dict(os.environ, {key: "" for key in ENV_KEYS}):
                # 区块里没存 Key，且无处可回落 → 空
                config.save_runtime_config("vision", "", "", "qwen3-vl-plus")
                self.assertEqual(config.current_api_key("vision"), "")
                # 区块里存了完整 Key → 直接返回
                config.save_runtime_config("vision", "", "sk-vis-12345678", "qwen3-vl-plus")
                self.assertEqual(config.current_api_key("vision"), "sk-vis-12345678")
