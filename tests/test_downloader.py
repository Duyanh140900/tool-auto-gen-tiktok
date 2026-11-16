import os
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unittest.mock import MagicMock, patch

from src.downloader import (
    _download_via_tikvid,
    _download_via_tikwm,
    _download_via_ytdlp,
    _extract_tikvid_media_urls,
    _fetch_tikwm_metadata,
    _get_cookie_file_path,
    download_one,
    has_video_stream,
)
from src.profile_crawler import crawl_tiktok_profile


class DownloaderFormatFallbackTests(unittest.TestCase):
    """Kiểm tra cơ chế fallback format của TikVid, TikWM và yt-dlp khi gặp audio-only và hỗ trợ cookie."""

    def test_get_cookie_file_path_returns_none_when_empty_or_not_found(self):
        with patch("src.downloader.settings") as mock_settings:
            mock_settings.TIKTOK_COOKIES_FILE = ""
            self.assertIsNone(_get_cookie_file_path())

            mock_settings.TIKTOK_COOKIES_FILE = "non_existent_cookies.txt"
            self.assertIsNone(_get_cookie_file_path())

    def test_get_cookie_file_path_returns_valid_path(self):
        with NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
        try:
            with patch("src.downloader.settings") as mock_settings:
                mock_settings.TIKTOK_COOKIES_FILE = tmp_path
                self.assertEqual(_get_cookie_file_path(), tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_extract_tikvid_media_urls_filters_audio_and_finds_mp4(self):
        sample_html = """
        <div class="dl-action">
            <a href="https://dl.snapcdn.app/get?token=mp4hd" class="tik-button-dl">Download MP4 HD</a>
            <a href="https://dl.snapcdn.app/get?token=mp4_1" class="tik-button-dl">Download MP4 [1]</a>
            <a href="https://dl.snapcdn.app/get?token=mp3_audio" class="tik-button-dl">Download MP3 Audio</a>
            <a href="javascript:void(0)" class="tik-button-dl">Other link</a>
        </div>
        """
        urls = _extract_tikvid_media_urls(sample_html)
        self.assertEqual(len(urls), 2)
        self.assertEqual(urls[0]["url"], "https://dl.snapcdn.app/get?token=mp4hd")
        self.assertIn("MP4 HD", urls[0]["text"])
        self.assertEqual(urls[1]["url"], "https://dl.snapcdn.app/get?token=mp4_1")

    @patch("src.downloader.requests.Session")
    @patch("src.downloader.has_video_stream", return_value=True)
    def test_download_via_tikvid_success(self, mock_has_video, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        search_resp = MagicMock(status_code=200)
        search_resp.json.return_value = {
            "status": "ok",
            "data": '<div class="dl-action"><a href="https://dl.snapcdn.app/video.mp4">Download MP4 HD</a></div>',
        }
        mock_session.post.return_value = search_resp

        dl_resp = MagicMock(status_code=200)
        dl_resp.__enter__.return_value = dl_resp
        dl_resp.iter_content.return_value = [b"tikvid-video-content"]
        mock_session.get.return_value = dl_resp

        with TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "output.mp4"
            res = _download_via_tikvid("https://www.tiktok.com/@test/video/123", out_path)

            self.assertEqual(res["source"], "tikvid")
            self.assertTrue(out_path.exists())
            self.assertEqual(out_path.read_bytes(), b"tikvid-video-content")

    @patch("src.downloader.requests.Session")
    @patch("src.downloader.has_video_stream")
    def test_download_via_tikvid_rejects_audio_only_and_tries_next(self, mock_has_video, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        search_resp = MagicMock(status_code=200)
        search_resp.json.return_value = {
            "status": "ok",
            "data": (
                '<div class="dl-action">'
                '<a href="https://cdn/link1.mp4">Download MP4 [1]</a>'
                '<a href="https://cdn/link2.mp4">Download MP4 [2]</a>'
                '</div>'
            ),
        }
        mock_session.post.return_value = search_resp

        dl_resp = MagicMock(status_code=200)
        dl_resp.__enter__.return_value = dl_resp
        dl_resp.iter_content.return_value = [b"content"]
        mock_session.get.return_value = dl_resp

        # First candidate is audio-only (False), second is valid video (True)
        mock_has_video.side_effect = [False, True]

        with TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "output.mp4"
            res = _download_via_tikvid("https://www.tiktok.com/@test/video/123", out_path)

            self.assertEqual(res["source"], "tikvid")
            self.assertEqual(res["cand_url"], "https://cdn/link2.mp4")
            self.assertEqual(mock_has_video.call_count, 2)

    @patch("src.downloader.yt_dlp.YoutubeDL")
    @patch("src.downloader.has_video_stream")
    def test_download_via_ytdlp_falls_back_when_first_format_is_audio_only(
        self, mock_has_video_stream, mock_ytdl_class
    ):
        """Giả lập format đầu tiên chỉ trả về audio (has_video_stream=False),

        format thứ 2 trả về video stream hợp lệ (has_video_stream=True).
        Hàm phải thử tiếp và trả về True.
        """
        # Giả lập has_video_stream: Lần 1 = False (audio only), Lần 2 = True (video hợp lệ)
        mock_has_video_stream.side_effect = [False, True]

        with TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "output.mp4"

            # Giả lập yt-dlp tạo ra file mỗi khi gọi download()
            def fake_download(urls):
                out_path.write_bytes(b"dummy media content")

            mock_instance = MagicMock()
            mock_instance.download.side_effect = fake_download
            mock_ytdl_class.return_value.__enter__.return_value = mock_instance

            success = _download_via_ytdlp("https://www.tiktok.com/@test/video/123", out_path)

            self.assertTrue(success)
            # Phải được gọi 2 lần do format đầu tiên bị reject vì audio-only
            self.assertEqual(mock_has_video_stream.call_count, 2)
            self.assertEqual(mock_ytdl_class.call_count, 2)

    @patch("src.downloader.yt_dlp.YoutubeDL")
    @patch("src.downloader.has_video_stream")
    def test_download_via_ytdlp_fails_if_all_formats_are_audio_only(
        self, mock_has_video_stream, mock_ytdl_class
    ):
        """Nếu tất cả format strategies đều là audio-only, hàm ném ra RuntimeError."""
        mock_has_video_stream.return_value = False

        with TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "output.mp4"

            def fake_download(urls):
                out_path.write_bytes(b"dummy media content")

            mock_instance = MagicMock()
            mock_instance.download.side_effect = fake_download
            mock_ytdl_class.return_value.__enter__.return_value = mock_instance

            with self.assertRaises(RuntimeError) as ctx:
                _download_via_ytdlp("https://www.tiktok.com/@test/video/123", out_path)

            self.assertIn("audio-only file (no video stream)", str(ctx.exception))
            # Đã thử hết 4 format strategies
            self.assertEqual(mock_has_video_stream.call_count, 4)

    @patch("src.downloader.time.sleep")
    @patch("src.downloader.requests.post")
    def test_fetch_tikwm_metadata_retries_rate_limit(self, mock_post, mock_sleep):
        """TikWM rate limit phải được retry thay vì chuyển ngay sang yt-dlp."""
        limited = MagicMock(status_code=200)
        limited.json.return_value = {"code": -1, "msg": "Free Api Limit: 1 request/second."}
        success = MagicMock(status_code=200)
        success.json.return_value = {"code": 0, "data": {"play": "https://cdn/video.mp4"}}
        mock_post.side_effect = [limited, success]

        with patch("src.downloader.TIKWM_MIN_INTERVAL_SEC", 0):
            payload = _fetch_tikwm_metadata("https://www.tiktok.com/@test/video/123")

        self.assertEqual(payload["play"], "https://cdn/video.mp4")
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once_with(0)

    @patch("src.downloader.requests.get")
    @patch("src.downloader._fetch_tikwm_metadata")
    def test_download_via_tikwm_reuses_existing_payload(self, mock_fetch, mock_get):
        """Payload metadata có sẵn phải tránh request TikWM API lần thứ hai."""
        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_content.return_value = [b"video-content"]
        mock_get.return_value = response

        with TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "source.mp4"
            payload = {"play": "https://cdn/video.mp4", "title": "Test"}
            result = _download_via_tikwm("https://www.tiktok.com/@test/video/123", out_path, payload)

            self.assertEqual(result, payload)
            self.assertEqual(out_path.read_bytes(), b"video-content")
            mock_fetch.assert_not_called()

    @patch("src.downloader.has_video_stream", return_value=True)
    @patch("src.downloader._download_via_tikvid")
    @patch("src.downloader.fetch_video_metadata")
    def test_download_one_prefers_tikvid(
        self, mock_metadata, mock_tikvid_download, _mock_has_video
    ):
        """download_one phải thử TikVid đầu tiên trước TikWM và yt-dlp."""
        mock_metadata.return_value = {
            "title": "Video Title",
            "uploader": "Tester",
            "duration": 15,
        }

        def fake_download(_url, out_path):
            out_path.write_bytes(b"tikvid-video-content")
            return {"source": "tikvid"}

        mock_tikvid_download.side_effect = fake_download
        with TemporaryDirectory() as tmp_dir:
            with patch("src.downloader.settings.OUTPUT_DIR", Path(tmp_dir)):
                info = __import__("asyncio").run(
                    download_one("https://www.tiktok.com/@test/video/123", 1)
                )

        self.assertIsNone(info.error)
        self.assertEqual(info.used_strategy, "tikvid")
        mock_tikvid_download.assert_called_once()

    @patch("src.downloader.has_video_stream", return_value=True)
    @patch("src.downloader._download_via_tikwm")
    @patch("src.downloader._download_via_tikvid", side_effect=RuntimeError("TikVid down"))
    @patch("src.downloader.fetch_video_metadata")
    def test_download_one_falls_back_to_tikwm_when_tikvid_fails(
        self, mock_metadata, mock_tikvid, mock_tikwm, _mock_has_video
    ):
        """Nếu TikVid lỗi, download_one phải fallback sang TikWM."""
        payload = {
            "play": "https://cdn/video.mp4",
            "title": "TikWM title",
            "duration": 12,
            "author": {"nickname": "Tester"},
        }
        mock_metadata.return_value = {
            "title": "TikWM title",
            "uploader": "Tester",
            "duration": 12,
            "raw_tikwm": payload,
        }

        def fake_tikwm_download(_url, out_path, received_payload):
            out_path.write_bytes(b"tikwm-video-content")
            return received_payload

        mock_tikwm.side_effect = fake_tikwm_download
        with TemporaryDirectory() as tmp_dir:
            with patch("src.downloader.settings.OUTPUT_DIR", Path(tmp_dir)):
                info = __import__("asyncio").run(
                    download_one("https://www.tiktok.com/@test/video/123", 1)
                )

        self.assertIsNone(info.error)
        self.assertEqual(info.used_strategy, "tikwm-api")
        mock_tikvid.assert_called_once()
        mock_tikwm.assert_called_once()

    @patch("src.profile_crawler.yt_dlp.YoutubeDL")
    def test_crawl_tiktok_profile_passes_cookie_file_when_configured(self, mock_ytdl_class):
        """Kiểm tra crawler nạp cookiefile vào ydl_opts khi có cấu hình."""
        with NamedTemporaryFile(delete=False) as tmp:
            cookie_path = tmp.name
        try:
            with patch("src.profile_crawler.settings") as mock_settings:
                mock_settings.TIKTOK_COOKIES_FILE = cookie_path
                mock_ydl = MagicMock()
                mock_ydl.extract_info.return_value = {"entries": []}
                mock_ytdl_class.return_value.__enter__.return_value = mock_ydl

                crawl_tiktok_profile("https://www.tiktok.com/@user")

                # Lấy opts được truyền vào YoutubeDL
                call_args = mock_ytdl_class.call_args[0][0]
                self.assertIn("cookiefile", call_args)
                self.assertEqual(call_args["cookiefile"], cookie_path)
        finally:
            Path(cookie_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
