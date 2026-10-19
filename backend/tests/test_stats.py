"""学习统计接口测试 —— 为 P2-2（改 SQL 聚合）留下行为基线"""
from datetime import datetime, timedelta

from tests.helpers import ApiTestCase

STAGES_DAYS = [1, 2, 4, 7, 15, 30]


class TestStatsSummary(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.create_word("a", tags="大模型,RAG")
        self.create_word("b", tags="大模型")
        self.create_word("c", tags="")

    def get_summary(self):
        resp = self.client.get("/api/stats/summary")
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def test_totals(self):
        word = self.create_word("d")
        self.client.post(f"/api/review/{word['id']}/answer", json={"result": "remember"})
        totals = self.get_summary()["totals"]
        self.assertEqual(totals["total_words"], 4)
        self.assertEqual(totals["week_new"], 4)
        self.assertEqual(totals["total_reviews"], 1)
        self.assertEqual(totals["reviewed_today"], 1)

    def test_tag_distribution_sorted_and_capped(self):
        for i in range(10):
            self.create_word(f"x{i}", tags=f"tag{i}")
        dist = self.get_summary()["tag_distribution"]
        self.assertLessEqual(len(dist), 8)
        counts = [d["count"] for d in dist]
        self.assertEqual(counts, sorted(counts, reverse=True))
        # 「大模型」出现 2 次，应为第一名
        self.assertEqual(dist[0]["name"], "大模型")
        self.assertEqual(dist[0]["count"], 2)

    def test_daily_trend_always_seven_days(self):
        trend = self.get_summary()["daily_trend"]
        self.assertEqual(len(trend), 7)
        today = datetime.now()
        self.assertEqual(trend[-1]["date"], f"{today.month:02d}-{today.day:02d}")

    def test_daily_trend_counts_today(self):
        word = self.create_word("e")
        self.client.post(f"/api/review/{word['id']}/answer", json={"result": "remember"})
        trend = self.get_summary()["daily_trend"]
        today = trend[-1]
        self.assertEqual(today["new_words"], 4)   # setUp 的 3 个 + 这里的 1 个
        self.assertEqual(today["reviews"], 1)

    def test_daily_trend_zero_fills_missing_days(self):
        trend = self.get_summary()["daily_trend"]
        dates = [d["date"] for d in trend]
        self.assertEqual(len(set(dates)), 7)          # 7 个不同日期，无空洞无重复
        self.assertTrue(all("new_words" in d and "reviews" in d for d in trend))

    def test_stage_distribution_always_six_stages(self):
        stage = self.get_summary()["stage_distribution"]
        self.assertEqual(len(stage), 6)
        self.assertEqual([s["stage"] for s in stage], list(range(6)))
        self.assertEqual([s["days"] for s in stage], STAGES_DAYS)
        # 3 个词都还没复习，全在 0 档
        self.assertEqual(stage[0]["count"], 3)

    def test_stage_distribution_reflects_reviews(self):
        word = self.create_word("f")
        self.client.post(f"/api/review/{word['id']}/answer", json={"result": "remember"})
        stage = self.get_summary()["stage_distribution"]
        counts = {s["stage"]: s["count"] for s in stage}
        self.assertEqual(counts[0], 3)
        self.assertEqual(counts[1], 1)

    def test_daily_trend_buckets_by_calendar_day(self):
        """P2-2 改为 SQL 聚合后，跨天数据必须仍落在正确的日期桶里"""
        from app.models import ReviewLog, Word as WordModel

        word = self.create_word("hist")
        db = self.SessionLocal()
        try:
            now = datetime.now()
            # 今天 2 条、昨天 1 条、3 天前 3 条、8 天前 1 条（应被 7 天窗口排除）
            for days_ago, times in ((0, 2), (1, 1), (3, 3), (8, 1)):
                stamp = now - timedelta(days=days_ago)
                for _ in range(times):
                    db.add(ReviewLog(word_id=word["id"], reviewed_at=stamp,
                                     result="remember", stage_before=0, stage_after=0))
            # 昨天的「新增」也要能统计到
            db.add(WordModel(abbreviation="yesterday", my_meaning="m",
                             created_at=now - timedelta(days=1),
                             next_review_at=now.replace(hour=0, minute=0, second=0, microsecond=0)))
            db.commit()
        finally:
            db.close()

        trend = self.get_summary()["daily_trend"]
        by_date = {d["date"]: d for d in trend}

        def label(days_ago):
            day = datetime.now() - timedelta(days=days_ago)
            return f"{day.month:02d}-{day.day:02d}"

        self.assertEqual(trend[-1]["reviews"], 2)          # 今天（含 setUp 里的没复习）
        self.assertEqual(by_date[label(1)]["reviews"], 1)
        self.assertEqual(by_date[label(3)]["reviews"], 3)
        self.assertEqual(by_date[label(1)]["new_words"], 1)
        # 8 天前那条应被 7 天窗口排除，不应影响总和
        self.assertEqual(sum(d["reviews"] for d in trend), 6)

    def test_empty_database_is_safe(self):
        """全新库（无任何词条）也要返回完整结构，不能除零 / 报错"""
        from tests.helpers import make_client
        fresh, fresh_sessions = make_client()
        self.addCleanup(fresh_sessions.engine.dispose)
        body = fresh.get("/api/stats/summary").json()
        self.assertEqual(body["totals"]["total_words"], 0)
        self.assertEqual(len(body["daily_trend"]), 7)
        self.assertEqual(len(body["stage_distribution"]), 6)
        self.assertEqual(body["tag_distribution"], [])
