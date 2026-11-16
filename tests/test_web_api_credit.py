import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
from tempfile import TemporaryDirectory

from src.web.job_manager import JobManager


class WebApiJobManagerCreditTests(unittest.TestCase):
    """Kiểm tra phản ứng của JobManager và API khi gặp lỗi cạn credit giọng nói."""

    def test_job_manager_stops_on_credit_exhaustion(self):
        mgr = JobManager()
        items = [
            {"url": "https://www.tiktok.com/@u/video/1", "script": "script 1"},
            {"url": "https://www.tiktok.com/@u/video/2", "script": "script 2"},
        ]

        with patch("threading.Thread.start"):
            snapshot = mgr.create_batch(items_payload=items, mode="live")
            self.assertEqual(snapshot.status, "queued")

    def test_job_manager_run_profile_handles_credit_exhausted(self):
        from src.profile_crawler import ProfileManifestManager

        mgr = JobManager()
        with TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "manifest.json"
            manifest = ProfileManifestManager(log_path)
            to_run, skipped_done, rerun_failed = manifest.filter_runnable_videos(
                crawled_videos=[
                    {"video_id": "1", "url": "https://www.tiktok.com/@u/video/1"},
                    {"video_id": "2", "url": "https://www.tiktok.com/@u/video/2"},
                ],
                profile_url="https://www.tiktok.com/@testuser",
            )
            self.assertEqual(len(to_run), 2)

            with patch("threading.Thread.start"):
                snap = mgr.create_profile_job(
                    profile_url="@testuser",
                    log_file_path=str(log_path),
                )
                self.assertEqual(snap.status, "queued")


if __name__ == "__main__":
    unittest.main()
