"""复习接口测试 —— 覆盖 P0-4（到期守卫 / 幂等）+ 三档规则"""
from datetime import datetime, timedelta

from tests.helpers import ApiTestCase

STAGES_DAYS = [1, 2, 4, 7, 15, 30]


def today_start():
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


class TestDueGuard(ApiTestCase):
    """P0-4：只有「今天该复习」的词条才能提交自评"""

    def test_second_submit_same_day_returns_409(self):
        word = self.create_word("rag")
        first = self.client.post(f"/api/review/{word['id']}/answer", json={"result": "remember"})
        self.assertEqual(first.status_code, 200, first.text)

        second = self.client.post(f"/api/review/{word['id']}/answer", json={"result": "remember"})
        self.assertEqual(second.status_code, 409, second.text)
        self.assertIn("下次复习日期", second.json()["detail"])

    def test_no_state_double_counted(self):
        word = self.create_word("rag")
        self.client.post(f"/api/review/{word['id']}/answer", json={"result": "remember"})
        self.client.post(f"/api/review/{word['id']}/answer", json={"result": "remember"})
        self.client.post(f"/api/review/{word['id']}/answer", json={"result": "forget"})

        db = self.SessionLocal()
        from app.models import Word
        w = db.query(Word).filter(Word.id == word["id"]).first()
        self.assertEqual(w.review_stage, 1)
        self.assertEqual(w.review_count, 1)
        db.close()
        self.assertEqual(len(self.review_logs(word["id"])), 1)

    def test_future_word_rejected(self):
        word = self.create_word("rag")
        self.set_word(word["id"], next_review_at=today_start() + timedelta(days=5))
        resp = self.client.post(f"/api/review/{word['id']}/answer", json={"result": "remember"})
        self.assertEqual(resp.status_code, 409, resp.text)

    def test_word_out_of_queue_rejected(self):
        word = self.create_word("rag")
        self.set_word(word["id"], in_review=0)
        resp = self.client.post(f"/api/review/{word['id']}/answer", json={"result": "remember"})
        self.assertEqual(resp.status_code, 409, resp.text)

    def test_unknown_word_returns_404(self):
        resp = self.client.post("/api/review/999999/answer", json={"result": "remember"})
        self.assertEqual(resp.status_code, 404)

    def test_invalid_result_returns_400(self):
        word = self.create_word("rag")
        resp = self.client.post(f"/api/review/{word['id']}/answer", json={"result": "nope"})
        self.assertEqual(resp.status_code, 400)

    def test_other_due_words_still_answerable(self):
        a = self.create_word("a")
        b = self.create_word("b")
        self.assertEqual(
            self.client.post(f"/api/review/{a['id']}/answer", json={"result": "fuzzy"}).status_code, 200
        )
        self.assertEqual(
            self.client.post(f"/api/review/{b['id']}/answer", json={"result": "fuzzy"}).status_code, 200
        )


class TestStageRules(ApiTestCase):
    """三档规则：记住→升档(封顶 5) / 模糊→不变 / 忘记→回 0"""

    def answer(self, word_id, result):
        """提交一次自评，并把下次复习改回「今天」以便再次提交"""
        resp = self.client.post(f"/api/review/{word_id}/answer", json={"result": result})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.set_word(word_id, next_review_at=today_start())
        return resp.json()

    def test_remember_advances_stage(self):
        word = self.create_word("w")
        out = self.answer(word["id"], "remember")
        self.assertEqual(out["review_stage"], 1)
        self.assertEqual(out["next_review_at"][:10], (today_start() + timedelta(days=STAGES_DAYS[1])).strftime("%Y-%m-%d"))

    def test_remember_caps_at_stage_five(self):
        word = self.create_word("w")
        for _ in range(8):
            out = self.answer(word["id"], "remember")
        self.assertEqual(out["review_stage"], 5)
        expected = (today_start() + timedelta(days=30)).strftime("%Y-%m-%d")
        self.assertEqual(out["next_review_at"][:10], expected)

    def test_fuzzy_keeps_stage(self):
        word = self.create_word("w")
        self.answer(word["id"], "remember")
        self.answer(word["id"], "remember")
        out = self.answer(word["id"], "fuzzy")
        self.assertEqual(out["review_stage"], 2)

    def test_forget_resets_to_zero(self):
        word = self.create_word("w")
        self.answer(word["id"], "remember")
        self.answer(word["id"], "remember")
        out = self.answer(word["id"], "forget")
        self.assertEqual(out["review_stage"], 0)
        expected = (today_start() + timedelta(days=1)).strftime("%Y-%m-%d")
        self.assertEqual(out["next_review_at"][:10], expected)

    def test_review_count_increments(self):
        word = self.create_word("w")
        for _ in range(3):
            self.answer(word["id"], "remember")
        db = self.SessionLocal()
        from app.models import Word
        w = db.query(Word).filter(Word.id == word["id"]).first()
        self.assertEqual(w.review_count, 3)
        self.assertIsNotNone(w.last_reviewed_at)
        db.close()
        self.assertEqual(len(self.review_logs(word["id"])), 3)


class TestOverviewAndDue(ApiTestCase):
    def test_overview_counts(self):
        a = self.create_word("a")
        self.create_word("b")
        self.client.post(f"/api/review/{a['id']}/answer", json={"result": "remember"})

        ov = self.client.get("/api/review/overview").json()
        self.assertEqual(ov["reviewed_today"], 1)          # 按 distinct word_id
        self.assertEqual(ov["due_today"], 1)               # a 已推到明天，只剩 b
        self.assertEqual(ov["total_in_queue"], 2)

    def test_reviewed_today_not_inflated_by_repeat(self):
        word = self.create_word("a")
        self.client.post(f"/api/review/{word['id']}/answer", json={"result": "fuzzy"})
        self.client.post(f"/api/review/{word['id']}/answer", json={"result": "fuzzy"})  # 被 409 拦下
        ov = self.client.get("/api/review/overview").json()
        self.assertEqual(ov["reviewed_today"], 1)

    def test_due_tag_filter_is_exact(self):
        """P0-5 同样适用于复习接口"""
        self.create_word("w-openai", tags="OpenAI")
        self.create_word("w-ai", tags="AI")
        names = sorted(
            w["abbreviation"]
            for w in self.client.get("/api/review/due", params={"tag": "AI"}).json()["items"]
        )
        self.assertEqual(names, ["w-ai"])

    def test_due_response_shape(self):
        self.create_word("a")
        body = self.client.get("/api/review/due").json()
        self.assertEqual(body["total_due"], 1)
        item = body["items"][0]
        for key in ("id", "abbreviation", "my_meaning", "review_stage", "next_review_at"):
            self.assertIn(key, item)

    def test_due_limit(self):
        for i in range(5):
            self.create_word(f"w{i}")
        self.assertLessEqual(
            len(self.client.get("/api/review/due", params={"limit": 2}).json()["items"]), 2
        )


class TestMistakes(ApiTestCase):
    """B1 错词本：把一直闲置的 ReviewLog.result 变成「最常忘记的词」"""

    def add_logs(self, word_id, forget=0, fuzzy=0, remember=0, days_ago=0):
        from datetime import datetime as dt
        from app.models import ReviewLog
        stamp = dt.now() - timedelta(days=days_ago)
        db = self.SessionLocal()
        try:
            for result, times in (("forget", forget), ("fuzzy", fuzzy), ("remember", remember)):
                for _ in range(times):
                    db.add(ReviewLog(
                        word_id=word_id, reviewed_at=stamp,
                        result=result, stage_before=0, stage_after=0,
                    ))
            db.commit()
        finally:
            db.close()

    def mistakes(self, **params):
        resp = self.client.get("/api/review/mistakes", params=params)
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def test_empty(self):
        self.assertEqual(self.mistakes(), {"total": 0, "items": []})

    def test_only_words_forgotten_at_least_once(self):
        a = self.create_word("never-forgot")
        b = self.create_word("forgot-once")
        self.add_logs(a["id"], remember=5)
        self.add_logs(b["id"], forget=1)

        body = self.mistakes()
        self.assertEqual(body["total"], 1)
        self.assertEqual([i["abbreviation"] for i in body["items"]], ["forgot-once"])

    def test_counts_are_aggregated_per_word(self):
        w = self.create_word("rag")
        self.add_logs(w["id"], forget=3, fuzzy=2, remember=5)
        item = self.mistakes()["items"][0]
        self.assertEqual(item["forget_times"], 3)
        self.assertEqual(item["fuzzy_times"], 2)
        self.assertEqual(item["total_reviews"], 10)

    def test_ordered_by_forget_times_desc(self):
        for name, times in (("w1", 1), ("w3", 5), ("w2", 3)):
            word = self.create_word(name)
            self.add_logs(word["id"], forget=times)
        self.assertEqual(
            [i["abbreviation"] for i in self.mistakes()["items"]], ["w3", "w2", "w1"]
        )

    def test_min_forget_filter(self):
        for name, times in (("once", 1), ("twice", 2), ("thrice", 3)):
            word = self.create_word(name)
            self.add_logs(word["id"], forget=times)
        body = self.mistakes(min_forget=2)
        self.assertEqual(body["total"], 2)
        self.assertEqual([i["abbreviation"] for i in body["items"]], ["thrice", "twice"])

    def test_limit_does_not_shrink_total(self):
        for i in range(5):
            word = self.create_word(f"w{i}")
            self.add_logs(word["id"], forget=i + 1)
        body = self.mistakes(limit=2)
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["total"], 5)

    def test_last_forgot_at_is_reported(self):
        w = self.create_word("rag")
        self.add_logs(w["id"], forget=1, days_ago=3)
        item = self.mistakes()["items"][0]
        self.assertIsNotNone(item["last_forgot_at"])

    def test_returns_full_word_fields(self):
        w = self.create_word("rag", my_meaning="检索增强", tags="a,b")
        self.add_logs(w["id"], forget=1)
        item = self.mistakes()["items"][0]
        for key in ("id", "abbreviation", "my_meaning", "tags", "in_review", "examples"):
            self.assertIn(key, item)
        self.assertEqual(item["my_meaning"], "检索增强")


class TestDueOrdering(ApiTestCase):
    """B1：到期队列可按「历史忘记次数」优先排序，且不破坏到期语义"""

    def add_forgets(self, word_id, times):
        from datetime import datetime as dt
        from app.models import ReviewLog
        db = self.SessionLocal()
        try:
            for _ in range(times):
                db.add(ReviewLog(word_id=word_id, reviewed_at=dt.now(),
                                 result="forget", stage_before=0, stage_after=0))
            db.commit()
        finally:
            db.close()

    def test_default_order_unchanged(self):
        a = self.create_word("a-old")
        b = self.create_word("b-new")
        # a 最久没复习 → 默认应排前面
        self.set_word(a["id"], next_review_at=today_start() - timedelta(days=5))
        self.set_word(b["id"], next_review_at=today_start())
        names = [i["abbreviation"] for i in self.client.get("/api/review/due").json()["items"]]
        self.assertEqual(names, ["a-old", "b-new"])

    def test_mistakes_order_prioritizes_forgotten_words(self):
        a = self.create_word("a-old")
        b = self.create_word("b-new")
        self.set_word(a["id"], next_review_at=today_start() - timedelta(days=5))
        self.set_word(b["id"], next_review_at=today_start())
        self.add_forgets(b["id"], 3)          # b 老忘，但没那么久没复习

        names = [
            i["abbreviation"]
            for i in self.client.get("/api/review/due", params={"order": "mistakes"}).json()["items"]
        ]
        self.assertEqual(names, ["b-new", "a-old"])

    def test_mistakes_order_still_only_returns_due_words(self):
        a = self.create_word("due-now")
        b = self.create_word("not-due")
        self.set_word(b["id"], next_review_at=today_start() + timedelta(days=10))
        self.add_forgets(b["id"], 99)

        body = self.client.get("/api/review/due", params={"order": "mistakes"}).json()
        self.assertEqual([i["abbreviation"] for i in body["items"]], ["due-now"])
        self.assertEqual(body["total_due"], 1)

    def test_unknown_order_falls_back_to_due(self):
        self.create_word("a")
        resp = self.client.get("/api/review/due", params={"order": "bogus"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["items"]), 1)

    def test_order_combines_with_tag_filter(self):
        a = self.create_word("a", tags="LLM")
        b = self.create_word("b", tags="LLM")
        self.create_word("c", tags="other")
        self.add_forgets(b["id"], 2)

        body = self.client.get(
            "/api/review/due", params={"order": "mistakes", "tag": "LLM"}
        ).json()
        self.assertEqual([i["abbreviation"] for i in body["items"]], ["b", "a"])


class TestReviewStateVisible(ApiTestCase):
    """B2：复习状态要在词条接口里可见（此前只有 /review/due 才带）"""

    REVIEW_KEYS = ("review_stage", "next_review_at", "last_reviewed_at",
                   "review_count", "in_review")

    def test_detail_exposes_review_state(self):
        word = self.create_word("rag")
        resp = self.client.get(f"/api/words/{word['id']}")
        self.assertEqual(resp.status_code, 200)
        for key in self.REVIEW_KEYS:
            self.assertIn(key, resp.json())

    def test_list_exposes_review_state(self):
        self.create_word("rag")
        item = self.list_words()["items"][0]
        for key in self.REVIEW_KEYS:
            self.assertIn(key, item)

    def test_values_reflect_progress(self):
        word = self.create_word("rag")
        self.client.post(f"/api/review/{word['id']}/answer", json={"result": "remember"})
        body = self.client.get(f"/api/words/{word['id']}").json()
        self.assertEqual(body["review_stage"], 1)
        self.assertEqual(body["review_count"], 1)
        self.assertIsNotNone(body["next_review_at"])
        self.assertIsNotNone(body["last_reviewed_at"])

    def test_lookup_exposes_review_state(self):
        word = self.create_word("rag")
        self.client.post(f"/api/review/{word['id']}/answer", json={"result": "remember"})
        body = self.client.get("/api/words/lookup", params={"word": "rag"}).json()
        self.assertEqual(body["word"]["review_stage"], 1)
        self.assertEqual(body["word"]["review_count"], 1)


class TestResetProgress(ApiTestCase):
    """B2：误点「记住」推进档位后必须能退回来"""

    def state(self, word_id):
        from app.models import Word
        db = self.SessionLocal()
        try:
            return db.query(Word).filter(Word.id == word_id).first()
        finally:
            db.close()

    def test_reset_clears_schedule_only(self):
        """只清排期：档位归零、下次复习回到今天，累计次数与上次复习时间保留"""
        word = self.create_word("rag")
        for _ in range(3):
            self.client.post(f"/api/review/{word['id']}/answer", json={"result": "remember"})
            self.set_word(word["id"], next_review_at=today_start())  # 绕开同日守卫继续升档
        before = self.state(word["id"])
        self.assertEqual(before.review_stage, 3)
        self.assertEqual(before.review_count, 3)

        resp = self.client.post(f"/api/review/{word['id']}/reset")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["review_stage"], 0)
        self.assertEqual(body["review_count"], 3)      # 累计次数不清零

        after = self.state(word["id"])
        self.assertEqual(after.review_stage, 0)
        self.assertEqual(after.review_count, 3)
        self.assertIsNotNone(after.last_reviewed_at)   # 上次复习时间保留
        self.assertEqual(after.next_review_at.strftime("%Y-%m-%d"),
                         today_start().strftime("%Y-%m-%d"))

    def test_reset_keeps_review_count_consistent_with_mistakes(self):
        """口径一致性：重置后详情页的 review_count 必须与错词本的 total_reviews 相符

        这是之前缺的一类测试 —— 功能用例只验「数对不对」，验不出「同一个概念
        在三个页面用了两套口径」。
        """
        word = self.create_word("rag")
        for result in ("forget", "forget", "remember"):
            self.client.post(f"/api/review/{word['id']}/answer", json={"result": result})
            self.set_word(word["id"], next_review_at=today_start())

        self.client.post(f"/api/review/{word['id']}/reset")

        detail = self.client.get(f"/api/words/{word['id']}").json()
        mistake = self.client.get("/api/review/mistakes").json()["items"][0]
        self.assertEqual(detail["review_count"], mistake["total_reviews"])
        self.assertEqual(detail["review_count"], 3)
        self.assertEqual(mistake["forget_times"], 2)

    def test_reset_makes_word_due_again(self):
        word = self.create_word("rag")
        self.client.post(f"/api/review/{word['id']}/answer", json={"result": "remember"})
        # 刚复习过 → 当天不能再提交
        self.assertEqual(
            self.client.post(f"/api/review/{word['id']}/answer", json={"result": "remember"}).status_code,
            409,
        )
        # 重置后又可以复习了（这正是「误点记住」的补救路径）
        self.client.post(f"/api/review/{word['id']}/reset")
        self.assertEqual(
            self.client.post(f"/api/review/{word['id']}/answer", json={"result": "fuzzy"}).status_code,
            200,
        )

    def test_reset_does_not_pollute_review_logs(self):
        word = self.create_word("rag")
        self.client.post(f"/api/review/{word['id']}/answer", json={"result": "forget"})
        self.client.post(f"/api/review/{word['id']}/reset")
        self.assertEqual(len(self.review_logs(word["id"])), 1)   # 只有那次真实复习
        # 错词本也保留历史（重置排期不等于抹掉遗忘记录）
        self.assertEqual(self.client.get("/api/review/mistakes").json()["total"], 1)

    def test_reset_keeps_content_and_queue_state(self):
        word = self.create_word("rag", my_meaning="检索增强", tags="a,b")
        self.client.put(f"/api/words/{word['id']}", json={"in_review": 0})
        self.client.post(f"/api/review/{word['id']}/reset")
        body = self.client.get(f"/api/words/{word['id']}").json()
        self.assertEqual(body["my_meaning"], "检索增强")
        self.assertEqual(body["tags"], "a,b")
        self.assertEqual(body["in_review"], 0)     # 移出队列的状态不被重置影响

    def test_reset_unknown_word(self):
        self.assertEqual(self.client.post("/api/review/999999/reset").status_code, 404)
