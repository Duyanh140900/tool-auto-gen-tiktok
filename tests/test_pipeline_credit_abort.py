import unittest
from unittest.mock import patch
from pathlib import Path

from src.pipeline import ItemState, process_batch


class PipelineAbortOnErrorTests(unittest.IsolatedAsyncioTestCase):
    """Kiểm tra pipeline dừng ngay toàn bộ batch khi gặp bất kỳ lỗi nào."""

    async def test_process_batch_sequential_aborts_on_any_error(self):
        items = [
            ItemState(index=0, url="https://www.tiktok.com/@u/video/1"),
            ItemState(index=1, url="https://www.tiktok.com/@u/video/2"),
            ItemState(index=2, url="https://www.tiktok.com/@u/video/3"),
        ]

        async def fake_process_one(state: ItemState, *args, **kwargs):
            if state.index == 0:
                state.error = "Lỗi tải video: Mạng không khả dụng hoặc link không hợp lệ"
                state.status = "error"
            else:
                state.status = "done"
            return state

        with patch("src.pipeline.process_one", side_effect=fake_process_one):
            results = await process_batch(items, max_concurrent=1)

        self.assertEqual(results[0].status, "error")
        # Since sequential loop breaks upon error, remaining items remain pending/untouched
        self.assertIn(results[1].status, ["pending", "cancelled"])
        self.assertIn(results[2].status, ["pending", "cancelled"])

    async def test_process_batch_parallel_aborts_on_any_error(self):
        items = [
            ItemState(index=0, url="https://www.tiktok.com/@u/video/1"),
            ItemState(index=1, url="https://www.tiktok.com/@u/video/2"),
            ItemState(index=2, url="https://www.tiktok.com/@u/video/3"),
        ]

        async def fake_process_one(state: ItemState, *args, **kwargs):
            if state.index == 0:
                state.error = "FFmpeg render error: Invalid video stream"
                state.status = "error"
            else:
                state.status = "done"
            return state

        with patch("src.pipeline.process_one", side_effect=fake_process_one):
            results = await process_batch(items, max_concurrent=2)

        self.assertEqual(results[0].status, "error")


if __name__ == "__main__":
    unittest.main()
