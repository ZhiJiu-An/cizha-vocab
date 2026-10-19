"""词条接口测试 —— 覆盖 P0-1 / P0-2 / P0-3 / P0-5 / P0-6 / P0-7 / P1-4"""

from tests.helpers import ApiTestCase


class TestPartialUpdate(ApiTestCase):
    """P0-1：部分更新不得清空未提交的字段"""

    def test_partial_update_keeps_examples(self):
        word = self.create_word(
            "token", examples=[{"en": "A token.", "zh": "一个词元"}], note="原备注"
        )
        resp = self.client.put(f"/api/words/{word['id']}", json={"note": "只改备注"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["examples"], [{"en": "A token.", "zh": "一个词元"}])
        self.assertEqual(body["note"], "只改备注")

    def test_explicit_examples_still_replace(self):
        word = self.create_word("token", examples=[{"en": "A token.", "zh": "一个词元"}])
        resp = self.client.put(
            f"/api/words/{word['id']}", json={"examples": [{"en": "New.", "zh": "新"}]}
        )
        self.assertEqual(resp.json()["examples"], [{"en": "New.", "zh": "新"}])

    def test_explicit_empty_examples_clears(self):
        word = self.create_word("token", examples=[{"en": "A token.", "zh": "一个词元"}])
        resp = self.client.put(f"/api/words/{word['id']}", json={"examples": []})
        self.assertEqual(resp.json()["examples"], [])


class TestNullFields(ApiTestCase):
    """P0-2 / P0-3：显式 null 不得造成 500"""

    def test_null_optional_field_becomes_empty_string(self):
        word = self.create_word("token", full_name="Some Full Name")
        resp = self.client.put(f"/api/words/{word['id']}", json={"full_name": None})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["full_name"], "")
        # 读回也必须正常（旧版这里会 ResponseValidationError -> 500）
        self.assertEqual(self.client.get(f"/api/words/{word['id']}").status_code, 200)

    def test_null_required_field_returns_400_not_500(self):
        word = self.create_word("token")
        for field in ("my_meaning", "abbreviation"):
            with self.subTest(field=field):
                resp = self.client.put(f"/api/words/{word['id']}", json={field: None})
                self.assertEqual(resp.status_code, 400, resp.text)

    def test_blank_required_field_rejected_on_create(self):
        resp = self.client.post("/api/words", json={"abbreviation": "x", "my_meaning": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_duplicate_abbreviation_rejected_case_insensitively(self):
        self.create_word("Token")
        self.assertEqual(
            self.client.post("/api/words", json={"abbreviation": "token", "my_meaning": "m"}).status_code,
            400,
        )


class TestTagMatching(ApiTestCase):
    """P0-5：标签筛选必须是边界精确匹配"""

    def setUp(self):
        super().setUp()
        self.create_word("w-openai", tags="OpenAI")
        self.create_word("w-ai", tags="AI")
        self.create_word("w-rag", tags="RAG")
        self.create_word("w-cot", tags="chain of thought")
        self.create_word("w-multi", tags="大模型,LLM")

    def test_tag_is_not_substring_match(self):
        self.assertEqual(self.abbreviations(tag="AI"), ["w-ai"])
        self.assertEqual(self.abbreviations(tag="OpenAI"), ["w-openai"])
        self.assertEqual(self.abbreviations(tag="RA"), [])
        self.assertEqual(self.abbreviations(tag="RAG"), ["w-rag"])
        self.assertEqual(self.abbreviations(tag="chain"), [])

    def test_tag_with_spaces_matches_exactly(self):
        self.assertEqual(self.abbreviations(tag="chain of thought"), ["w-cot"])

    def test_multiple_tags_each_match(self):
        self.assertEqual(self.abbreviations(tag="大模型"), ["w-multi"])
        self.assertEqual(self.abbreviations(tag="LLM"), ["w-multi"])

    def test_tags_normalized_on_write(self):
        word = self.create_word("w-messy", tags=" b , a ,, a ")
        self.assertEqual(word["tags"], "b,a")
        updated = self.client.put(f"/api/words/{word['id']}", json={"tags": " z ,  z , y "})
        self.assertEqual(updated.json()["tags"], "z,y")

    def test_list_tags_aggregation(self):
        tags = {t["name"]: t["count"] for t in self.client.get("/api/tags").json()}
        self.assertEqual(tags["AI"], 1)
        self.assertEqual(tags["OpenAI"], 1)
        self.assertNotIn("", tags)


class TestCsv(ApiTestCase):
    """P0-6：导出必须包含 note，且导出→导入不丢字段"""

    def test_export_header_includes_note(self):
        header = self.client.get("/api/words/export").text.splitlines()[0].lstrip("\ufeff")
        self.assertTrue(header.endswith(",note"), header)

    def test_export_contains_note_value(self):
        self.create_word("w-note", note="我的备注XYZ")
        self.assertIn("我的备注XYZ", self.client.get("/api/words/export").text)

    def test_roundtrip_preserves_all_fields(self):
        self.create_word(
            "rag",
            my_meaning="检索增强",
            full_name="Retrieval-Augmented Generation",
            cn_term="检索增强",
            phonetic_uk="/ræɡ/",
            api_meaning="通用释义",
            tags="大模型,RAG",
            note='重要备注,含逗号和引号"x"',
            examples=[{"en": "RAG works.", "zh": "RAG 有效"}],
        )
        csv_bytes = self.client.get("/api/words/export").content

        # 导入到另一个干净库里验证（同一库里会因「已存在」被跳过）
        from tests.helpers import make_client
        fresh, fresh_sessions = make_client()
        self.addCleanup(fresh_sessions.engine.dispose)
        resp = fresh.post("/api/words/batch", files={"file": ("export.csv", csv_bytes, "text/csv")})
        self.assertEqual(resp.status_code, 200, resp.text)
        imported = resp.json()
        self.assertEqual(len(imported), 1)
        row = imported[0]
        self.assertEqual(row["note"], '重要备注,含逗号和引号"x"')
        self.assertEqual(row["tags"], "大模型,RAG")
        self.assertEqual(row["examples"], [{"en": "RAG works.", "zh": "RAG 有效"}])
        self.assertEqual(row["full_name"], "Retrieval-Augmented Generation")
        self.assertEqual(row["phonetic_uk"], "/ræɡ/")

    def test_legacy_ten_column_csv_still_imports(self):
        old = (
            "abbreviation,full_name,cn_term,my_meaning,domain_detail,"
            "phonetic_uk,phonetic_us,api_meaning,examples,tags\n"
            "legacy10,,,旧词义,,,,,[],oldtag\n"
        ).encode()
        resp = self.client.post("/api/words/batch", files={"file": ("old.csv", old, "text/csv")})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()[0]["note"], "")
        self.assertEqual(resp.json()[0]["tags"], "oldtag")


class TestKeywordEscaping(ApiTestCase):
    """P0-7：关键词里的 LIKE 通配符必须按字面处理"""

    def setUp(self):
        super().setUp()
        self.create_word("alpha", my_meaning="阿尔法")
        self.create_word("a_b", my_meaning="下划线词")

    def total(self, keyword):
        return self.list_words(keyword=keyword)["total"]

    def test_wildcards_are_literal(self):
        self.assertEqual(self.total("%"), 0)
        self.assertEqual(self.total("_lpha"), 0)
        self.assertEqual(self.total("a%b"), 0)
        self.assertEqual(self.total("\\"), 0)
        self.assertEqual(self.total("%%"), 0)

    def test_literal_underscore_matches_word_containing_it(self):
        self.assertEqual(self.abbreviations(keyword="_"), ["a_b"])

    def test_normal_search_still_works(self):
        self.assertEqual(self.abbreviations(keyword="alpha"), ["alpha"])
        self.assertEqual(self.abbreviations(keyword="阿尔法"), ["alpha"])


class TestPagination(ApiTestCase):
    """P1-4：limit / skip 约束与分页正确性"""

    def test_limit_bounds(self):
        self.assertEqual(self.client.get("/api/words", params={"limit": 10 ** 9}).status_code, 422)
        self.assertEqual(self.client.get("/api/words", params={"limit": 0}).status_code, 422)
        self.assertEqual(self.client.get("/api/words", params={"limit": 501}).status_code, 422)
        self.assertEqual(self.client.get("/api/words", params={"limit": 500}).status_code, 200)

    def test_skip_bounds(self):
        self.assertEqual(self.client.get("/api/words", params={"skip": -1}).status_code, 422)

    def test_pages_cover_all_rows_without_duplicates(self):
        for i in range(25):
            self.create_word(f"word{i:02d}", tags="pg")

        first = self.list_words(tag="pg", limit=10)
        self.assertEqual(len(first["items"]), 10)
        self.assertEqual(first["total"], 25)

        ids = []
        for skip in (0, 10, 20):
            ids += [w["id"] for w in self.list_words(tag="pg", limit=10, skip=skip)["items"]]
        self.assertEqual(len(ids), 25)
        self.assertEqual(len(set(ids)), 25)
        self.assertEqual(len(self.list_words(tag="pg", limit=10, skip=20)["items"]), 5)

    def test_skip_beyond_total_returns_empty(self):
        self.create_word("only", tags="pg")
        self.assertEqual(self.list_words(tag="pg", limit=10, skip=100)["items"], [])
