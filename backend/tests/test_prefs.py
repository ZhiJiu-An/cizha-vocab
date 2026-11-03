"""用户偏好持久化测试（v0.16）

背景：桌面版后端随机端口启动，localStorage 随 origin 变化而丢失设置，
偏好改由 `<data_dir>/prefs.json` 落盘。

关注：
1. 文件不存在时返回默认值
2. 写入后重启（重新读）能拿到同样的值
3. 非法 accent / 提醒时间被拒
4. 坏文件回退默认值，不抛 500
5. 半截文件自动补全
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.routes import prefs as prefs_mod
from tests.helpers import ApiTestCase


class PrefsTestCase(ApiTestCase):
    """把 prefs.json 指到临时目录，绝不写真实的 backend/data/"""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "prefs.json"
        patcher = patch.object(prefs_mod, "_prefs_path", lambda: self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_defaults_when_file_missing(self):
        data = self.client.get("/api/prefs").json()
        self.assertEqual(data["nickname"], "词札学习者")
        self.assertEqual(data["accent"], "us")
        self.assertFalse(data["reminder"]["enabled"])
        self.assertEqual(data["reminder"]["time"], "20:00")

    def test_roundtrip_survives_restart(self):
        payload = {
            "nickname": "阿榛",
            "accent": "uk",
            "reminder": {
                "enabled": True,
                "time": "21:30",
                "last_notified": "2026-11-03 21:30",
            },
        }
        resp = self.client.put("/api/prefs", json=payload)
        self.assertEqual(resp.status_code, 200, resp.text)

        # 再读一次等价于重启后的 loadPrefs
        self.assertEqual(self.client.get("/api/prefs").json(), payload)
        on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["accent"], "uk")

    def test_invalid_accent_rejected(self):
        resp = self.client.put("/api/prefs", json={"accent": "au"})
        self.assertEqual(resp.status_code, 422)

    def test_invalid_reminder_time_rejected(self):
        resp = self.client.put("/api/prefs", json={"reminder": {"time": "25:99"}})
        self.assertEqual(resp.status_code, 422)

    def test_corrupt_file_falls_back_to_defaults(self):
        self.path.write_text("{not json", encoding="utf-8")
        data = self.client.get("/api/prefs").json()
        self.assertEqual(data["nickname"], "词札学习者")

    def test_partial_file_is_merged(self):
        self.path.write_text(json.dumps({"accent": "uk"}), encoding="utf-8")
        data = self.client.get("/api/prefs").json()
        self.assertEqual(data["accent"], "uk")
        self.assertFalse(data["reminder"]["enabled"])
        self.assertEqual(data["nickname"], "词札学习者")
