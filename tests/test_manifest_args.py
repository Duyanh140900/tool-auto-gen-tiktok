import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from src.profile_crawler import ProfileManifestManager


class ManifestManagerArgumentTests(unittest.TestCase):
    def test_filter_runnable_videos_positional_and_keyword_args(self):
        with TemporaryDirectory() as tmp:
            mgr = ProfileManifestManager(Path(tmp) / "test.json")
            videos = [{"url": "https://www.tiktok.com/@u/video/1", "id": "1"}]

            # 1. Test with keyword args
            runnable, skipped, rerun = mgr.filter_runnable_videos(
                crawled_videos=videos,
                profile_url="https://www.tiktok.com/@u",
                force_rerun_all=False,
            )
            self.assertEqual(len(runnable), 1)

            # 2. Test with swapped positional args (backward compat protection)
            runnable2, skipped2, rerun2 = mgr.filter_runnable_videos(
                "https://www.tiktok.com/@u",
                videos,
                False,
            )
            self.assertEqual(len(runnable2), 1)


if __name__ == "__main__":
    unittest.main()
