import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from src.profile_crawler import (
    extract_video_id,
    normalize_profile_url,
    normalize_video_url,
    crawl_tiktok_profile,
    resolve_tiktok_sec_uid,
    ProfileManifestManager,
    get_default_log_file_path,
)


class ProfileCrawlerTests(unittest.TestCase):
    def test_normalize_profile_url(self):
        self.assertEqual(normalize_profile_url("@user123"), "https://www.tiktok.com/@user123")
        self.assertEqual(normalize_profile_url("user123"), "https://www.tiktok.com/@user123")
        self.assertEqual(normalize_profile_url("https://www.tiktok.com/@myuser?lang=en"), "https://www.tiktok.com/@myuser")
        self.assertEqual(normalize_profile_url("http://tiktok.com/@shop_test/"), "https://www.tiktok.com/@shop_test")

    def test_extract_and_normalize_video_url(self):
        url = "https://www.tiktok.com/@shop_test/video/7331234567890123456"
        self.assertEqual(extract_video_id(url), "7331234567890123456")
        self.assertEqual(normalize_video_url(url), "https://www.tiktok.com/@shop_test/video/7331234567890123456")

        # Normalize with only ID
        self.assertEqual(normalize_video_url("", video_id="7331234567890123456"), "https://www.tiktok.com/video/7331234567890123456")

    @patch("src.profile_crawler.yt_dlp.YoutubeDL")
    def test_crawl_tiktok_profile_success(self, mock_ytdl_class):
        mock_ydl = MagicMock()
        mock_ytdl_class.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            "entries": [
                {"id": "111111", "url": "https://www.tiktok.com/@user/video/111111", "title": "Video 1"},
                {"id": "222222", "url": "https://www.tiktok.com/@user/video/222222", "title": "Video 2"},
                {"id": "111111", "url": "https://www.tiktok.com/@user/video/111111", "title": "Video 1 dup"},
            ]
        }

        videos = crawl_tiktok_profile("https://www.tiktok.com/@user")
        self.assertEqual(len(videos), 2)
        self.assertEqual(videos[0]["id"], "111111")
        self.assertEqual(videos[1]["id"], "222222")

    def test_manifest_manager_filtering_and_status(self):
        with TemporaryDirectory() as tmp_dir:
            log_file = Path(tmp_dir) / "test_manifest.json"
            mgr = ProfileManifestManager(log_file)

            # Filter with 3 videos
            videos = [
                {"url": "https://www.tiktok.com/@u/video/1", "id": "1"},
                {"url": "https://www.tiktok.com/@u/video/2", "id": "2"},
                {"url": "https://www.tiktok.com/@u/video/3", "id": "3"},
            ]
            runnable, skipped, rerun_failed = mgr.filter_runnable_videos(videos, "https://www.tiktok.com/@u")
            self.assertEqual(len(runnable), 3)
            self.assertEqual(len(skipped), 0)
            self.assertEqual(len(rerun_failed), 0)

            # Mark video 1 as done
            mgr.update_video_status(
                url="https://www.tiktok.com/@u/video/1",
                profile_url="https://www.tiktok.com/@u",
                product_name="Kem duong da",
                status="done",
                final_video_path="C:/output/video1.mp4",
                file_name="video1.mp4",
            )

            # Mark video 2 as error
            mgr.update_video_status(
                url="https://www.tiktok.com/@u/video/2",
                profile_url="https://www.tiktok.com/@u",
                product_name="Serum",
                status="error",
                error="TTS synthesis timeout",
            )

            # Filter again: video 1 must be skipped (status=done), video 2 & 3 must be runnable
            runnable2, skipped2, rerun_failed2 = mgr.filter_runnable_videos(videos, "https://www.tiktok.com/@u")
            self.assertEqual(len(runnable2), 2)
            self.assertEqual([v["id"] for v in runnable2], ["2", "3"])
            self.assertEqual(len(skipped2), 1)
            self.assertEqual(skipped2[0]["id"], "1")
            self.assertEqual(len(rerun_failed2), 1)
            self.assertEqual(rerun_failed2[0]["id"], "2")

            # Verify JSON structure
            data = json.loads(log_file.read_text(encoding="utf-8"))
            self.assertIn("videos", data)
            self.assertIn("profiles", data)
            self.assertEqual(len(data["videos"]), 3)
            v1_record = data["videos"]["https://www.tiktok.com/@u/video/1"]
            self.assertEqual(v1_record["status"], "done")
            self.assertEqual(v1_record["product_name"], "Kem duong da")
            self.assertEqual(v1_record["file_name"], "video1.mp4")
            self.assertTrue(v1_record["final_video_path"].endswith("video1.mp4"))

    def test_manifest_manager_get_videos_and_sec_uid(self):
        with TemporaryDirectory() as tmp_dir:
            log_file = Path(tmp_dir) / "manifest.json"
            mgr = ProfileManifestManager(log_file)

            # Initially empty
            self.assertEqual(mgr.get_videos_for_profile("https://www.tiktok.com/@dailynarii"), [])
            self.assertIsNone(mgr.get_profile_sec_uid("https://www.tiktok.com/@dailynarii"))

            # Save sec_uid
            mgr.save_profile_sec_uid("https://www.tiktok.com/@dailynarii", "MS4wLjABAAAA_test_uid")
            self.assertEqual(mgr.get_profile_sec_uid("https://www.tiktok.com/@dailynarii"), "MS4wLjABAAAA_test_uid")
            # Should also match with @dailynarii
            self.assertEqual(mgr.get_profile_sec_uid("@dailynarii"), "MS4wLjABAAAA_test_uid")

            # Add videos
            videos = [
                {"url": "https://www.tiktok.com/@dailynarii/video/1001", "id": "1001", "title": "Vid 1"},
                {"url": "https://www.tiktok.com/@dailynarii/video/1002", "id": "1002", "title": "Vid 2"},
            ]
            mgr.filter_runnable_videos(videos, "https://www.tiktok.com/@dailynarii")

            retrieved = mgr.get_videos_for_profile("https://www.tiktok.com/@dailynarii")
            self.assertEqual(len(retrieved), 2)
            self.assertEqual(retrieved[0]["id"], "1001")
            self.assertEqual(retrieved[1]["id"], "1002")

            # Sample video URL
            sample_url = mgr.get_sample_video_url("https://www.tiktok.com/@dailynarii")
            self.assertIsNotNone(sample_url)
            self.assertIn("100", sample_url)

    @patch("urllib.request.urlopen")
    def test_resolve_tiktok_sec_uid_from_html(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'<html><script>window.__INIT_DATA__ = {"secUid":"MS4wLjABAAAAtest1234567890abcdef"};</script></html>'
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        sec_uid = resolve_tiktok_sec_uid("https://www.tiktok.com/@user")
        self.assertEqual(sec_uid, "MS4wLjABAAAAtest1234567890abcdef")

    @patch("src.profile_crawler.yt_dlp.YoutubeDL")
    def test_resolve_tiktok_sec_uid_from_sample_video(self, mock_ytdl_class):
        mock_ydl = MagicMock()
        mock_ytdl_class.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            "channel_id": "MS4wLjABAAAA_video_sample_sec_uid_1234567890"
        }

        with patch("urllib.request.urlopen", side_effect=Exception("Blocked")):
            sec_uid = resolve_tiktok_sec_uid(
                "https://www.tiktok.com/@user",
                sample_video_url="https://www.tiktok.com/@user/video/7692031412005784840",
            )
            self.assertEqual(sec_uid, "MS4wLjABAAAA_video_sample_sec_uid_1234567890")

    @patch("src.profile_crawler.resolve_tiktok_sec_uid")
    @patch("src.profile_crawler.yt_dlp.YoutubeDL")
    def test_crawl_tiktok_profile_falls_back_to_sec_uid(self, mock_ytdl_class, mock_resolve):
        mock_ydl = MagicMock()
        mock_ytdl_class.return_value.__enter__.return_value = mock_ydl
        mock_resolve.return_value = "MS4wLjABAAAA_resolved_uid"

        # First call fails (simulate yt-dlp Unable to extract secondary user ID)
        # Second call with tiktokuser succeeds
        def extract_side_effect(url, download=False):
            if str(url).startswith("tiktokuser:"):
                return {
                    "entries": [
                        {"id": "9999", "url": "https://www.tiktok.com/@user/video/9999", "title": "SecUID Video"}
                    ]
                }
            raise Exception("Unable to extract secondary user ID")

        mock_ydl.extract_info.side_effect = extract_side_effect

        videos = crawl_tiktok_profile("https://www.tiktok.com/@user")
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["id"], "9999")
        self.assertEqual(videos[0].get("sec_uid"), "MS4wLjABAAAA_resolved_uid")

    def test_job_manager_profile_fallback_to_manifest_on_crawl_failure(self):
        from src.web.job_manager import JobManager
        with TemporaryDirectory() as tmp_dir:
            manifest_file = Path(tmp_dir) / "profile_log.json"
            mgr = ProfileManifestManager(manifest_file)
            # Seed manifest with cached videos
            mgr.filter_runnable_videos(
                [
                    {"url": "https://www.tiktok.com/@dailynarii/video/111", "id": "111", "title": "Cached 1"},
                    {"url": "https://www.tiktok.com/@dailynarii/video/222", "id": "222", "title": "Cached 2"},
                ],
                "https://www.tiktok.com/@dailynarii",
            )

            job_mgr = JobManager()
            with patch("src.profile_crawler.crawl_tiktok_profile", side_effect=RuntimeError("Unable to extract secondary user ID")):
                with patch.object(job_mgr, "_run_mock") as mock_mock:
                    job_mgr._run_profile_job(
                        normalized_profile="https://www.tiktok.com/@dailynarii",
                        video_shift_ratio=-0.1,
                        video_scale=0.85,
                        style="style1",
                        voice_id=None,
                        mode_pipeline="mock",
                        force_rerun_all=False,
                        max_videos=10,
                        manifest_file=manifest_file,
                    )
                    mock_mock.assert_called_once()
                    self.assertEqual(job_mgr.current.status, "done")
                    self.assertEqual(len(job_mgr.current.items), 2)


if __name__ == "__main__":
    unittest.main()
