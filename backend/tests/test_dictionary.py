"""词典接口测试（P2-4 重构的行为基线）

刻意只 mock `_fetch` 这一层，不 mock urllib / httpx 具体实现 ——
这样把 `dictionary.py` 从 urllib 换成 httpx 时，这些测试无需改动仍然有效。
"""
import unittest
from unittest import TestCase
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from tests.helpers import ApiTestCase
from app.routes import dictionary as dict_mod

# 有道 jsonapi 的真实返回结构（裁剪版）
SAMPLE = {
    "ec": {
        "word": [{
            "ukphone": "ˈtəʊkən",
            "usphone": "ˈtoʊkən",
            "trs": [
                {"tr": [{"l": {"i": ["n. 词元", "记号"]}}]},
                {"tr": [{"l": {"i": ["n. 代币"]}}]},
                {"tr": [{"l": {"i": ["v. 象征"]}}]},
                {"tr": [{"l": {"i": ["第四条不该出现"]}}]},
            ],
        }]
    },
    "blng_sents_part": {
        "sentence-pair": [
            {"sentence": "A token is small.", "sentence-translation": "词元很小。"},
            {"sentence": "A token is small.", "sentence-translation": "重复句应去重"},
            {"sentence": "Two tokens.", "sentence-translation": "两个词元。"},
            {"sentence": "Three tokens.", "sentence-translation": "三个词元。"},
            {"sentence": "Four tokens.", "sentence-translation": "四个词元。"},
        ]
    },
}


class TestPureParsers(TestCase):
    def test_wrap_phonetic(self):
        self.assertEqual(dict_mod._wrap_phonetic("ˈtəʊkən"), "/ˈtəʊkən/")
        self.assertEqual(dict_mod._wrap_phonetic("/x/"), "/x/")
        self.assertEqual(dict_mod._wrap_phonetic(""), "")
        self.assertEqual(dict_mod._wrap_phonetic(None), "")

    def test_parse_phonetics_from_ec(self):
        uk, us = dict_mod._parse_phonetics(SAMPLE)
        self.assertEqual(uk, "/ˈtəʊkən/")
        self.assertEqual(us, "/ˈtoʊkən/")

    def test_parse_phonetics_falls_back_to_simple(self):
        data = {"simple": {"word": [{"ukphone": "eɪ", "usphone": "eɪ"}]}}
        self.assertEqual(dict_mod._parse_phonetics(data), ("/eɪ/", "/eɪ/"))

    def test_parse_phonetics_empty(self):
        self.assertEqual(dict_mod._parse_phonetics({}), ("", ""))

    def test_parse_meanings_caps_at_three(self):
        meaning = dict_mod._parse_meanings(SAMPLE)
        self.assertEqual(meaning.count("\n"), 2)          # 3 条
        self.assertNotIn("第四条不该出现", meaning)
        self.assertIn("n. 词元", meaning)

    def test_parse_meanings_truncates_long_line(self):
        long_text = "长" * 400
        data = {"ec": {"word": [{"trs": [{"tr": [{"l": {"i": [long_text]}}]}]}]}}
        self.assertEqual(len(dict_mod._parse_meanings(data)), 300)

    def test_parse_examples_caps_at_three_and_dedupes(self):
        examples = dict_mod._parse_examples(SAMPLE)
        self.assertEqual(len(examples), 3)
        self.assertEqual(examples[0], {"en": "A token is small.", "zh": "词元很小。"})
        self.assertEqual(len({e["en"] for e in examples}), 3)

    def test_parse_examples_empty(self):
        self.assertEqual(dict_mod._parse_examples({}), [])


class TestLookupEndpoint(ApiTestCase):
    def test_found_word(self):
        with patch.object(dict_mod, "_fetch", new=AsyncMock(return_value=SAMPLE)):
            resp = self.client.get("/api/dictionary/token")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["found"])
        self.assertEqual(body["word"], "token")
        self.assertEqual(body["phonetic_uk"], "/ˈtəʊkən/")
        self.assertTrue(body["api_meaning"])
        self.assertEqual(len(body["examples"]), 3)

    def test_not_found_word(self):
        with patch.object(dict_mod, "_fetch", new=AsyncMock(return_value={})):
            resp = self.client.get("/api/dictionary/zzz")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["found"])
        self.assertTrue(body["message"])

    def test_empty_word_rejected(self):
        resp = self.client.get("/api/dictionary/%20")
        self.assertEqual(resp.status_code, 400)

    def test_upstream_failure_surfaces_as_502(self):
        http_err = HTTPException(status_code=502, detail="词典服务暂时不可用")
        with patch.object(dict_mod, "_fetch", new=AsyncMock(side_effect=http_err)):
            resp = self.client.get("/api/dictionary/token")
        self.assertEqual(resp.status_code, 502)


class TestFetchNetworkLayer(unittest.IsolatedAsyncioTestCase):
    """P2-4：网络层（httpx）的错误分支必须统一转成 502，不能泄漏成 500"""

    async def test_connection_error_becomes_502(self):
        with patch.object(dict_mod.httpx, "AsyncClient", side_effect=dict_mod.httpx.ConnectError("boom")):
            with self.assertRaises(HTTPException) as ctx:
                await dict_mod._fetch("token")
        self.assertEqual(ctx.exception.status_code, 502)

    async def test_non_200_becomes_502(self):
        resp = AsyncMock()
        resp.status_code = 503
        client = AsyncMock()
        client.get = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch.object(dict_mod.httpx, "AsyncClient", return_value=client):
            with self.assertRaises(HTTPException) as ctx:
                await dict_mod._fetch("token")
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("503", ctx.exception.detail)

    async def test_bad_json_becomes_502(self):
        resp = AsyncMock()
        resp.status_code = 200
        resp.json = lambda: (_ for _ in ()).throw(ValueError("not json"))
        client = AsyncMock()
        client.get = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch.object(dict_mod.httpx, "AsyncClient", return_value=client):
            with self.assertRaises(HTTPException) as ctx:
                await dict_mod._fetch("token")
        self.assertEqual(ctx.exception.status_code, 502)

    async def test_success_returns_json(self):
        resp = AsyncMock()
        resp.status_code = 200
        resp.json = lambda: SAMPLE
        client = AsyncMock()
        client.get = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch.object(dict_mod.httpx, "AsyncClient", return_value=client):
            self.assertEqual(await dict_mod._fetch("token"), SAMPLE)
        # 查询参数走 params，而不是手工拼 URL
        client.get.assert_awaited_once()
        self.assertEqual(client.get.await_args.kwargs["params"], {"q": "token"})
