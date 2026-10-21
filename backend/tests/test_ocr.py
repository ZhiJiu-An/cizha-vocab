"""P2-3：图片上传必须分块限量读取，超限立即中断

旧版 await file.read() 会把整个文件读进内存后才判断 10MB，超大文件先撑
内存再被拒。这里锁定「越限即停」的行为，并覆盖空文件 / 正常文件路径。
"""
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.routes import ocr
from tests.helpers import ApiTestCase


class FakeUpload:
    """模拟 UploadFile.read(size)：记录读取次数与已消费字节数"""

    def __init__(self, payload: bytes):
        self.payload = payload
        self.pos = 0
        self.reads = 0

    async def read(self, size: int = -1) -> bytes:
        self.reads += 1
        chunk = self.payload[self.pos:self.pos + size]
        self.pos += len(chunk)
        return chunk


class TestReadLimited(unittest.IsolatedAsyncioTestCase):
    async def test_returns_full_content_under_limit(self):
        payload = b"png-bytes"
        self.assertEqual(await ocr._read_limited(FakeUpload(payload), 100), payload)

    async def test_empty_content_returns_empty_bytes(self):
        self.assertEqual(await ocr._read_limited(FakeUpload(b""), 100), b"")

    async def test_exceeding_limit_stops_reading_immediately(self):
        # 10 个分块的内容，上限设为 2.5 个分块：应在第 3 块后中断，而不是读完
        payload = b"x" * (ocr.READ_CHUNK * 10)
        fake = FakeUpload(payload)
        with self.assertRaises(HTTPException) as ctx:
            await ocr._read_limited(fake, ocr.READ_CHUNK * 2 + 1)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(fake.reads, 3)
        self.assertEqual(fake.pos, ocr.READ_CHUNK * 3)
        self.assertLess(fake.pos, len(payload))


class TestExtractSizeGuard(ApiTestCase):
    """路由层：超限 / 空内容都应在调用视觉模型前返回 400"""

    def post(self, content: bytes):
        return self.client.post(
            "/api/ocr/extract",
            files={"file": ("shot.png", content, "image/png")},
        )

    def test_oversized_image_rejected_before_reading_model_config(self):
        with patch.object(ocr, "MAX_SIZE", 8):
            resp = self.post(b"x" * 64)
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("图片过大", resp.json()["detail"])

    def test_empty_image_rejected(self):
        resp = self.post(b"")
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("图片内容为空", resp.json()["detail"])

    def test_non_image_mime_rejected(self):
        resp = self.client.post(
            "/api/ocr/extract",
            files={"file": ("note.txt", b"hello", "text/plain")},
        )
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("仅支持图片文件", resp.json()["detail"])
