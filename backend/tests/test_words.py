"""词条接口测试 —— 覆盖 P0-1 / P0-2 / P0-3 / P0-5 / P0-6 / P0-7 / P1-4"""

from app.models import ReviewLog
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
        self.assertIn("note", header.split(","))

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

    def test_oversized_csv_rejected_before_full_read(self):
        """v0.14：CSV 与 OCR 同口径限 10MB，超限返回 400 而非读爆内存"""
        big = b"a," * (5 * 1024 * 1024 + 1)  # 10MB + 2 字节
        self.assertGreater(len(big), 10 * 1024 * 1024)
        resp = self.client.post("/api/words/batch", files={"file": ("big.csv", big, "text/csv")})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("10MB", resp.json()["detail"])

    def test_csv_exactly_at_limit_accepted(self):
        # 恰好在上限内的文件不被误伤
        row = b"atlimit,,,x,,,,,[],,\n"
        payload = row * ((10 * 1024 * 1024) // len(row))
        self.assertLessEqual(len(payload), 10 * 1024 * 1024)
        resp = self.client.post("/api/words/batch", files={"file": ("ok.csv", payload, "text/csv")})
        self.assertEqual(resp.status_code, 200, resp.text)


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


class TestCsvReviewProgress(ApiTestCase):
    """A3：复习进度必须随 CSV 往返保真，否则换机器备份即丢学习进度

    状态直接从库里读，不依赖响应模型 —— 复习字段是否暴露给前端是 B2 的事。
    """

    def header(self):
        return self.client.get("/api/words/export").text.splitlines()[0].lstrip("\ufeff").split(",")

    def db_state(self, sessions, abbreviation):
        from app.models import Word
        db = sessions()
        try:
            w = db.query(Word).filter(Word.abbreviation == abbreviation).first()
            self.assertIsNotNone(w, f"库里没有 {abbreviation}")
            return {
                "review_stage": w.review_stage,
                "review_count": w.review_count,
                "in_review": w.in_review,
                "next_review_at": w.next_review_at,
            }
        finally:
            db.close()

    def import_rows(self, csv_text, client=None):
        client = client or self.client
        body = csv_text.encode("utf-8") if isinstance(csv_text, str) else csv_text
        resp = client.post("/api/words/batch", files={"file": ("x.csv", body, "text/csv")})
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    REVIEW_HEADER = (
        "abbreviation,full_name,cn_term,my_meaning,domain_detail,"
        "phonetic_uk,phonetic_us,api_meaning,examples,tags,note,"
        "review_stage,next_review_at,review_count,in_review\n"
    )

    def test_export_header_ends_with_review_columns(self):
        self.assertEqual(
            self.header()[-4:],
            ["review_stage", "next_review_at", "review_count", "in_review"],
        )

    def test_roundtrip_preserves_review_progress(self):
        from datetime import datetime, timedelta
        from tests.helpers import make_client

        word = self.create_word("rag")
        target = (datetime.now() + timedelta(days=4)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self.set_word(
            word["id"], review_stage=2, next_review_at=target, review_count=3, in_review=0
        )
        csv_bytes = self.client.get("/api/words/export").content

        fresh, fresh_sessions = make_client()
        self.addCleanup(fresh_sessions.engine.dispose)
        self.import_rows(csv_bytes, client=fresh)

        state = self.db_state(fresh_sessions, "rag")
        self.assertEqual(state["review_stage"], 2)
        self.assertEqual(state["review_count"], 3)
        self.assertEqual(state["in_review"], 0)
        self.assertEqual(state["next_review_at"].strftime("%Y-%m-%d"), target.strftime("%Y-%m-%d"))

    def test_explicit_review_columns_are_honored(self):
        self.import_rows(
            self.REVIEW_HEADER + "imported,,,含义,,,,,[],,,4,2030-01-02T00:00:00,9,0\n"
        )
        state = self.db_state(self.SessionLocal, "imported")
        self.assertEqual(state["review_stage"], 4)
        self.assertEqual(state["review_count"], 9)
        self.assertEqual(state["in_review"], 0)
        self.assertEqual(state["next_review_at"].strftime("%Y-%m-%d"), "2030-01-02")

    def test_dirty_review_values_fall_back_to_defaults(self):
        from datetime import datetime
        self.import_rows(
            self.REVIEW_HEADER + "dirty,,,含义,,,,,[],,,abc,not-a-date,xyz,7\n"
        )
        state = self.db_state(self.SessionLocal, "dirty")
        self.assertEqual(state["review_stage"], 0)                       # 脏值 → 0 档
        self.assertEqual(state["review_count"], 0)                       # 脏值 → 0 次
        self.assertEqual(state["in_review"], 1)                          # 脏值 → 在队列
        self.assertEqual(state["next_review_at"].strftime("%Y-%m-%d"),
                         datetime.now().strftime("%Y-%m-%d"))            # 脏值 → 今天到期

    def test_out_of_range_values_are_clamped(self):
        self.import_rows(self.REVIEW_HEADER + "clamped,,,含义,,,,,[],,,99,,-5,-5\n")
        state = self.db_state(self.SessionLocal, "clamped")
        self.assertEqual(state["review_stage"], 5)     # 99 夹到最高档（6 档的最后一档）
        self.assertEqual(state["review_count"], 0)     # -5 夹到 0
        self.assertEqual(state["in_review"], 0)        # -5 夹到合法区间内最小 0 → 移出队列

    def test_legacy_eleven_column_csv_defaults_progress(self):
        from datetime import datetime
        legacy = (
            "abbreviation,full_name,cn_term,my_meaning,domain_detail,"
            "phonetic_uk,phonetic_us,api_meaning,examples,tags,note\n"
            "legacy11,,,含义,,,,,[],,备注\n"
        )
        self.import_rows(legacy)
        state = self.db_state(self.SessionLocal, "legacy11")
        self.assertEqual(state["review_stage"], 0)
        self.assertEqual(state["review_count"], 0)
        self.assertEqual(state["in_review"], 1)
        self.assertEqual(state["next_review_at"].strftime("%Y-%m-%d"),
                         datetime.now().strftime("%Y-%m-%d"))


class TestReviewQueueToggle(ApiTestCase):
    """A2：in_review 此前没有任何入口能改，这里验证它真正可用了"""

    def state(self, word_id):
        from app.models import Word
        db = self.SessionLocal()
        try:
            return db.query(Word).filter(Word.id == word_id).first()
        finally:
            db.close()

    def test_default_is_in_queue(self):
        word = self.create_word("rag")
        self.assertEqual(word["in_review"], 1)

    def test_remove_from_queue(self):
        word = self.create_word("rag")
        resp = self.client.put(f"/api/words/{word['id']}", json={"in_review": 0})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["in_review"], 0)
        self.assertEqual(self.state(word["id"]).in_review, 0)

        # 从到期队列与队列总数中消失
        self.assertEqual(self.client.get("/api/review/due").json()["total_due"], 0)
        self.assertEqual(self.client.get("/api/review/overview").json()["total_in_queue"], 0)

    def test_removed_word_cannot_be_answered(self):
        word = self.create_word("rag")
        self.client.put(f"/api/words/{word['id']}", json={"in_review": 0})
        resp = self.client.post(f"/api/review/{word['id']}/answer", json={"result": "remember"})
        self.assertEqual(resp.status_code, 409, resp.text)

    def test_join_back_without_schedule_becomes_due_today(self):
        from datetime import datetime
        word = self.create_word("rag")
        self.set_word(word["id"], in_review=0, next_review_at=None)

        resp = self.client.put(f"/api/words/{word['id']}", json={"in_review": 1})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["in_review"], 1)

        w = self.state(word["id"])
        self.assertIsNotNone(w.next_review_at)
        self.assertEqual(w.next_review_at.strftime("%Y-%m-%d"),
                         datetime.now().strftime("%Y-%m-%d"))
        self.assertEqual(self.client.get("/api/review/due").json()["total_due"], 1)

    def test_join_back_keeps_existing_schedule(self):
        from datetime import datetime, timedelta
        word = self.create_word("rag")
        future = (datetime.now() + timedelta(days=9)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self.set_word(word["id"], in_review=0, next_review_at=future)

        self.client.put(f"/api/words/{word['id']}", json={"in_review": 1})
        w = self.state(word["id"])
        # 已有计划则「恢复原计划」，不硬拉回今天
        self.assertEqual(w.next_review_at.strftime("%Y-%m-%d"), future.strftime("%Y-%m-%d"))
        self.assertEqual(w.in_review, 1)

    def test_invalid_value_rejected(self):
        word = self.create_word("rag")
        for bad in (2, -1):
            with self.subTest(value=bad):
                resp = self.client.put(f"/api/words/{word['id']}", json={"in_review": bad})
                self.assertEqual(resp.status_code, 422, resp.text)

    def test_other_fields_unaffected_by_toggle(self):
        word = self.create_word("rag", my_meaning="检索增强", tags="a,b",
                                examples=[{"en": "x", "zh": "y"}])
        resp = self.client.put(f"/api/words/{word['id']}", json={"in_review": 0}).json()
        self.assertEqual(resp["my_meaning"], "检索增强")
        self.assertEqual(resp["tags"], "a,b")
        self.assertEqual(resp["examples"], [{"en": "x", "zh": "y"}])


class TestLookupEndpoint(ApiTestCase):
    """A4：搜索页据此判断「是否已收藏」，命中就不再调用大模型"""

    def test_not_found_returns_200(self):
        resp = self.client.get("/api/words/lookup", params={"word": "nope"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json(), {"found": False, "word": None})

    def test_empty_word(self):
        self.assertEqual(
            self.client.get("/api/words/lookup", params={"word": "  "}).json()["found"], False
        )

    def test_found_is_case_insensitive(self):
        created = self.create_word("RAG", my_meaning="检索增强", tags="a,b")
        for probe in ("RAG", "rag", "Rag", "  rAg  "):
            with self.subTest(probe=probe):
                body = self.client.get("/api/words/lookup", params={"word": probe}).json()
                self.assertTrue(body["found"], body)
                self.assertEqual(body["word"]["id"], created["id"])

    def test_requires_exact_match(self):
        self.create_word("retrieval")
        self.assertFalse(
            self.client.get("/api/words/lookup", params={"word": "retrie"}).json()["found"]
        )

    def test_returns_full_word_fields(self):
        self.create_word("token", my_meaning="词元", tags="LLM")
        body = self.client.get("/api/words/lookup", params={"word": "token"}).json()
        word = body["word"]
        for key in ("id", "abbreviation", "my_meaning", "cn_term", "tags", "examples", "in_review"):
            self.assertIn(key, word)
        self.assertEqual(word["my_meaning"], "词元")
        self.assertEqual(word["in_review"], 1)

    def test_reflects_queue_state(self):
        word = self.create_word("rag")
        self.client.put(f"/api/words/{word['id']}", json={"in_review": 0})
        body = self.client.get("/api/words/lookup", params={"word": "rag"}).json()
        self.assertEqual(body["word"]["in_review"], 0)


class TestBulkOperations(ApiTestCase):
    """C1：批量接口收成单请求 + 单事务，替代前端循环发 N 个请求"""

    def ids_of(self, *names):
        return [self.create_word(n)["id"] for n in names]

    def test_bulk_delete(self):
        ids = self.ids_of("a", "b", "c")
        self.create_word("keep")
        resp = self.client.post("/api/words/bulk-delete", json={"ids": ids})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual((body["requested"], body["succeeded"], body["failed"]), (3, 3, 0))
        self.assertEqual(self.abbreviations(), ["keep"])

    def test_bulk_delete_reports_missing_ids(self):
        ids = self.ids_of("a")
        resp = self.client.post("/api/words/bulk-delete", json={"ids": ids + [999, 1000]})
        body = resp.json()
        self.assertEqual(body["succeeded"], 1)
        self.assertEqual(body["failed"], 2)
        self.assertEqual(body["missing_ids"], [999, 1000])

    def test_bulk_delete_dedupes_ids(self):
        wid = self.create_word("a")["id"]
        body = self.client.post("/api/words/bulk-delete", json={"ids": [wid, wid, wid]}).json()
        self.assertEqual(body["requested"], 1)
        self.assertEqual(body["succeeded"], 1)

    def test_bulk_delete_is_atomic(self):
        """中途失败不应留下半删状态（单事务）"""
        ids = self.ids_of("a", "b")
        resp = self.client.post("/api/words/bulk-delete", json={"ids": ids + [999]})
        self.assertEqual(resp.status_code, 200)
        # 存在的两条都被删；不存在的只被报告，不影响其余
        self.assertEqual(self.abbreviations(), [])
        self.assertEqual(resp.json()["missing_ids"], [999])

    def test_bulk_delete_rejects_empty(self):
        self.assertEqual(self.client.post("/api/words/bulk-delete", json={"ids": []}).status_code, 422)

    def test_bulk_delete_rejects_huge_batch(self):
        resp = self.client.post("/api/words/bulk-delete", json={"ids": list(range(1, 1002))})
        self.assertEqual(resp.status_code, 422)

    def test_bulk_tag_merges_and_dedupes(self):
        a = self.create_word("a", tags="LLM,论文")
        b = self.create_word("b", tags="")
        resp = self.client.post(
            "/api/words/bulk-tag", json={"ids": [a["id"], b["id"]], "tags": ["论文", "RAG"]}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["succeeded"], 2)

        a2 = self.client.get(f"/api/words/{a['id']}").json()
        b2 = self.client.get(f"/api/words/{b['id']}").json()
        self.assertEqual(a2["tags"], "LLM,论文,RAG")   # 已存在的「论文」不重复
        self.assertEqual(b2["tags"], "论文,RAG")

    def test_bulk_tag_requires_non_empty_tags(self):
        wid = self.create_word("a")["id"]
        for payload in ({"ids": [wid], "tags": []}, {"ids": [wid], "tags": ["  ", ""]}):
            with self.subTest(payload=payload):
                self.assertEqual(
                    self.client.post("/api/words/bulk-tag", json=payload).status_code, 422
                    if not payload["tags"] else 400
                )

    def test_bulk_tag_missing_ids(self):
        wid = self.create_word("a")["id"]
        body = self.client.post(
            "/api/words/bulk-tag", json={"ids": [wid, 999], "tags": ["x"]}
        ).json()
        self.assertEqual(body["succeeded"], 1)
        self.assertEqual(body["missing_ids"], [999])


class TestRestoreDeleted(ApiTestCase):
    """C2：删除可撤销，撤销后排期不丢（历史打卡不回填）"""

    def test_restore_preserves_review_progress(self):
        from datetime import datetime, timedelta

        word = self.create_word("rag", my_meaning="检索增强", tags="a,b",
                                examples=[{"en": "x", "zh": "y"}], note="备注")
        target = (datetime.now() + timedelta(days=5)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self.set_word(word["id"], review_stage=3, next_review_at=target,
                      review_count=7, in_review=0)

        snapshot = self.client.get(f"/api/words/{word['id']}").json()
        self.client.delete(f"/api/words/{word['id']}")
        self.assertEqual(self.abbreviations(), [])

        resp = self.client.post("/api/words/restore", json={"items": [snapshot]})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["restored"], 1)

        restored = resp.json()["words"][0]
        # 注意：SQLite 会复用被删行的 rowid，所以 id 可能恰好等于原 id。
        # 这里不把 id 当契约，只校验内容与进度完整恢复。
        self.assertIsInstance(restored["id"], int)
        self.assertEqual(restored["my_meaning"], "检索增强")
        self.assertEqual(restored["tags"], "a,b")
        self.assertEqual(restored["note"], "备注")
        self.assertEqual(restored["examples"], [{"en": "x", "zh": "y"}])
        self.assertEqual(restored["review_stage"], 3)
        # v0.13：日志已随删除清空，累计次数归零，避免与统计口径矛盾
        self.assertEqual(restored["review_count"], 0)
        self.assertEqual(self.review_logs(restored["id"]), [])
        self.assertEqual(restored["in_review"], 0)
        self.assertEqual(restored["next_review_at"][:10], target.strftime("%Y-%m-%d"))

    def test_restore_keeps_created_at(self):
        word = self.create_word("rag")
        snapshot = self.client.get(f"/api/words/{word['id']}").json()
        self.client.delete(f"/api/words/{word['id']}")
        restored = self.client.post("/api/words/restore", json={"items": [snapshot]}).json()["words"][0]
        self.assertEqual(restored["created_at"][:19], snapshot["created_at"][:19])

    def test_restore_skips_existing_abbreviation(self):
        word = self.create_word("rag")
        snapshot = self.client.get(f"/api/words/{word['id']}").json()
        # 不删除，直接恢复 → 同名词条已存在
        body = self.client.post("/api/words/restore", json={"items": [snapshot]}).json()
        self.assertEqual(body["restored"], 0)
        self.assertEqual(body["skipped"], 1)
        # 原词条没有被覆盖
        self.assertEqual(self.client.get(f"/api/words/{word['id']}").json()["my_meaning"], "释义")

    def test_restore_bulk(self):
        a = self.create_word("a")
        b = self.create_word("b")
        snapshots = [self.client.get(f"/api/words/{i['id']}").json() for i in (a, b)]
        self.client.post("/api/words/bulk-delete", json={"ids": [a["id"], b["id"]]})
        self.assertEqual(self.abbreviations(), [])
        body = self.client.post("/api/words/restore", json={"items": snapshots}).json()
        self.assertEqual(body["restored"], 2)
        self.assertEqual(self.abbreviations(), ["a", "b"])

    def test_restore_rejects_empty(self):
        self.assertEqual(self.client.post("/api/words/restore", json={"items": []}).status_code, 422)


class TestDeleteCleansReviewLogs(ApiTestCase):
    """v0.13：删除词条必须同事务清理 ReviewLog，统计与错词榜不得残留"""

    def add_logs(self, word_id, count=2, result="remember"):
        db = self.SessionLocal()
        try:
            for _ in range(count):
                db.add(ReviewLog(word_id=word_id, result=result))
            db.commit()
        finally:
            db.close()

    def total_reviews(self):
        return self.client.get("/api/stats/summary").json()["totals"]["total_reviews"]

    def test_single_delete_removes_logs_and_keeps_stats_consistent(self):
        word = self.create_word("rag")
        self.add_logs(word["id"], 2, result="forget")
        self.assertEqual(self.total_reviews(), 2)
        self.assertEqual(
            self.client.get("/api/review/overview").json()["reviewed_today"], 1
        )

        self.assertEqual(self.client.delete(f"/api/words/{word['id']}").status_code, 200)

        self.assertEqual(self.review_logs(word["id"]), [])
        self.assertEqual(self.total_reviews(), 0)
        self.assertEqual(self.client.get("/api/review/overview").json()["reviewed_today"], 0)
        self.assertEqual(self.client.get("/api/review/mistakes").json()["items"], [])

    def test_bulk_delete_removes_logs_for_found_words(self):
        a = self.create_word("a")
        b = self.create_word("b")
        self.add_logs(a["id"], 2)
        self.add_logs(b["id"], 1)

        body = self.client.post(
            "/api/words/bulk-delete", json={"ids": [a["id"], b["id"], 999]}
        ).json()
        self.assertEqual(body["succeeded"], 2)
        self.assertEqual(body["failed"], 1)
        self.assertEqual(self.review_logs(a["id"]), [])
        self.assertEqual(self.review_logs(b["id"]), [])
        self.assertEqual(self.total_reviews(), 0)

    def test_restore_does_not_bring_back_logs(self):
        word = self.create_word("rag")
        self.add_logs(word["id"], 3, result="forget")
        snapshot = self.client.get(f"/api/words/{word['id']}").json()
        self.client.delete(f"/api/words/{word['id']}")

        restored = self.client.post(
            "/api/words/restore", json={"items": [snapshot]}
        ).json()["words"][0]
        self.assertEqual(restored["review_count"], 0)
        self.assertEqual(self.review_logs(restored["id"]), [])
        self.assertEqual(self.total_reviews(), 0)
        self.assertEqual(self.client.get("/api/review/mistakes").json()["items"], [])

    def test_new_word_after_delete_does_not_inherit_logs(self):
        """SQLite 会复用最大 rowid，新词条不得继承被删词条的日志"""
        word = self.create_word("rag")
        self.add_logs(word["id"], 2, result="forget")
        self.client.delete(f"/api/words/{word['id']}")

        fresh = self.create_word("rag2")
        self.assertEqual(fresh["review_count"], 0)
        self.assertEqual(self.review_logs(fresh["id"]), [])
        self.assertEqual(self.total_reviews(), 0)
