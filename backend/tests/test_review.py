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
