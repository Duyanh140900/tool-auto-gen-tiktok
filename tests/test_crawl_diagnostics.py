"""tests/test_crawl_diagnostics.py - Lý do crawl thất bại phải hiện rõ + log ghi ra file."""

import logging
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from loguru import logger as loguru_logger

from src import log_setup
from src.profile_crawler import _looks_like_bot_challenge, crawl_tiktok_profile

WAF_HTML = (
    b'<!DOCTYPE html> <html lang="en"><head><script id="slardar-config" type="application/json">'
    b'{"slardarClient": "SlardarWAF", "bid": "slardar_us_waf"}</script></head></html>'
)


def _fake_ytdl_factory(error_msg):
    """YoutubeDL giả: giống yt-dlp thật với ignoreerrors=True -> báo lỗi qua logger, trả None."""
    def factory(opts):
        ydl = MagicMock()

        def extract_info(url, download=False):
            opts["logger"].error(error_msg)
            return None

        ydl.extract_info.side_effect = extract_info
        ctx = MagicMock()
        ctx.__enter__.return_value = ydl
        return ctx
    return factory


class CrawlDiagnosticsTests(unittest.TestCase):
    def test_detects_waf_page(self):
        self.assertTrue(_looks_like_bot_challenge(WAF_HTML.decode()))
        self.assertFalse(_looks_like_bot_challenge('<html>{"secUid":"x"}' + "a" * 6000))

    @patch("urllib.request.urlopen")
    @patch("src.profile_crawler.yt_dlp.YoutubeDL")
    def test_raises_with_ytdlp_and_waf_reasons(self, mock_ytdl_class, mock_urlopen):
        mock_ytdl_class.side_effect = _fake_ytdl_factory(
            "ERROR: [tiktok:user] minn._lim: Unable to extract secondary user ID."
        )
        resp = MagicMock()
        resp.read.return_value = WAF_HTML
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        with self.assertRaises(RuntimeError) as ctx:
            crawl_tiktok_profile("https://www.tiktok.com/@minn._lim")
        msg = str(ctx.exception)
        self.assertIn("Unable to extract secondary user ID", msg)
        self.assertIn("chống bot", msg)
        self.assertIn("video mẫu", msg)
        self.assertNotIn("ERROR:", msg)

    @patch("src.profile_crawler.yt_dlp.YoutubeDL")
    def test_empty_profile_without_errors_returns_empty_list(self, mock_ytdl_class):
        ydl = MagicMock()
        ydl.extract_info.return_value = {"entries": []}
        mock_ytdl_class.return_value.__enter__.return_value = ydl
        # target tiktokuser: -> không dò secUid, không có lỗi -> trả [] như cũ
        self.assertEqual(crawl_tiktok_profile("tiktokuser:MS4wLjABAAAAabc"), [])


class FileLoggingTests(unittest.TestCase):
    def setUp(self):
        log_setup.teardown_file_logging()
        self._tmp = TemporaryDirectory()

    def tearDown(self):
        log_setup.teardown_file_logging()
        self._tmp.cleanup()

    def test_writes_stdlib_debug_traceback_and_loguru(self):
        log_file = log_setup.setup_file_logging(Path(self._tmp.name))
        # Gọi lần 2 không gắn trùng handler
        self.assertEqual(log_setup.setup_file_logging(Path(self._tmp.name)), log_file)

        logging.getLogger("tiktok.test").debug("chi tiết debug")
        try:
            raise ValueError("boom")
        except ValueError:
            logging.getLogger("tiktok.test").exception("job crashed")
        loguru_logger.info("từ loguru pipeline")
        logging.getLogger("tiktok")  # flush
        for h in logging.getLogger("tiktok").handlers:
            h.flush()

        text = log_file.read_text(encoding="utf-8")
        self.assertIn("chi tiết debug", text)
        self.assertIn("job crashed", text)
        self.assertIn("ValueError: boom", text)
        self.assertIn("từ loguru pipeline", text)


if __name__ == "__main__":
    unittest.main()
