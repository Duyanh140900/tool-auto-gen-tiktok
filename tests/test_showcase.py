"""Test tích hợp tự thêm sản phẩm vào Showcase sau khi gen xong video."""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.showcase import ShowcaseError, ShowcaseWorker


def _collect():
    updates = []
    lock = threading.Lock()

    def on_update(index, state):
        with lock:
            updates.append((index, dict(state)))

    return updates, on_update


class ShowcaseWorkerTests(unittest.TestCase):
    def test_mock_worker_processes_each_item_once(self):
        updates, on_update = _collect()
        worker = ShowcaseWorker(on_update, mock=True)
        self.assertTrue(worker.submit(1, "https://www.tiktok.com/@a/video/1"))
        self.assertFalse(worker.submit(1, "https://www.tiktok.com/@a/video/1"))
        worker.submit(2, "https://www.tiktok.com/@a/video/2")
        worker.finish(timeout=5)

        final = {idx: st for idx, st in updates if st["status"] in {"done", "error"}}
        self.assertEqual(set(final), {1, 2})
        self.assertEqual(final[1]["status"], "done")
        self.assertEqual(final[1]["results"][0]["status"], "thu")

    def test_device_error_marks_item_error_and_retries_connect(self):
        updates, on_update = _collect()
        with patch("src.showcase.connect", side_effect=ShowcaseError("Không kết nối được điện thoại")) as connect:
            worker = ShowcaseWorker(on_update, delay_between_links=(0, 0))
            worker.submit(1, "https://www.tiktok.com/@a/video/1")
            worker.submit(2, "https://www.tiktok.com/@a/video/2")
            worker.finish(timeout=5)

        self.assertEqual(connect.call_count, 2)
        final = [st for _, st in updates if st["status"] == "error"]
        self.assertEqual(len(final), 2)
        self.assertIn("điện thoại", final[0]["results"][0]["note"])

    def test_real_flow_writes_csv_and_passes_dry_flag(self):
        updates, on_update = _collect()
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "showcase_log.csv"
            with patch("src.showcase.connect", return_value=(object(), "pkg")), patch(
                "src.showcase.process_link", return_value=[("Áo thun", "thu", "chạy thử")]
            ) as process_link:
                worker = ShowcaseWorker(on_update, dry=True, delay_between_links=(0, 0), csv_log_path=csv_path)
                worker.submit(1, "https://www.tiktok.com/@a/video/1")
                worker.finish(timeout=5)

            self.assertTrue(process_link.call_args.args[3])  # dry
            self.assertIn("Áo thun", csv_path.read_text(encoding="utf-8-sig"))
        self.assertEqual(updates[-1][1]["status"], "done")
        self.assertTrue(updates[-1][1]["dry"])

    def test_cancel_skips_remaining_items(self):
        updates, on_update = _collect()
        cancel = threading.Event()
        with patch("src.showcase.connect", return_value=(object(), "pkg")), patch(
            "src.showcase.process_link", return_value=[("SP", "thanh_cong", "")]
        ):
            worker = ShowcaseWorker(on_update, cancel_event=cancel, delay_between_links=(30, 30))
            worker.submit(1, "u1")
            worker.submit(2, "u2")
            time.sleep(0.3)  # item 1 xong, item 2 đang chờ delay 30s
            cancel.set()
            worker.finish(timeout=5)

        final = {idx: st["status"] for idx, st in updates if st["status"] in {"done", "cancelled"}}
        self.assertEqual(final, {1: "done", 2: "cancelled"})


class JobManagerShowcaseTests(unittest.TestCase):
    def test_mock_batch_adds_showcase_to_items_and_manifest(self):
        from src.web.job_manager import JobManager

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "log.json"
            mgr = JobManager()
            with patch("src.web.job_manager.time.sleep"):
                mgr.create_batch(
                    [{"url": "https://www.tiktok.com/@a/video/7691321387801152775"}],
                    mode="mock",
                    log_file_path=str(log_path),
                    auto_showcase=True,
                )
                mgr._thread.join(timeout=10)

            item = mgr.current.items[0]
            self.assertEqual(mgr.current.status, "done")
            self.assertEqual(item.showcase["status"], "done")
            video = json.loads(log_path.read_text(encoding="utf-8"))["videos"][item.url]
            self.assertEqual(video["status"], "done")
            self.assertEqual(video["showcase"]["status"], "done")

    def test_showcase_disabled_by_default(self):
        from src.web.job_manager import JobManager

        with tempfile.TemporaryDirectory() as tmp:
            mgr = JobManager()
            with patch("src.web.job_manager.time.sleep"):
                mgr.create_batch(
                    [{"url": "https://www.tiktok.com/@a/video/1"}],
                    mode="mock",
                    log_file_path=str(Path(tmp) / "log.json"),
                )
                mgr._thread.join(timeout=10)
            self.assertIsNone(mgr.current.items[0].showcase)


class ShowcaseRequestTests(unittest.TestCase):
    def test_requests_accept_showcase_flags(self):
        from src.web.app import AutoGenRequest, BatchRequest, ProfileAiVideoRequest

        self.assertFalse(ProfileAiVideoRequest(profile_url="@a").auto_showcase)
        req = AutoGenRequest(mode="review", items=[{"url": "u"}], auto_showcase=True, showcase_dry=True)
        self.assertTrue(req.auto_showcase and req.showcase_dry)
        self.assertTrue(BatchRequest(items=[{"url": "u"}], auto_showcase=True).auto_showcase)


if __name__ == "__main__":
    unittest.main()
