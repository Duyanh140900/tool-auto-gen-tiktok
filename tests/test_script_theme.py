"""tests/test_script_theme.py - Chủ đề kịch bản do người dùng nhập (không gọi LLM thật)."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from src import script_generator as sg

GOOD_JSON = json.dumps({
    "product_name": "Đèn lồng",
    "tiktok_script": "[excited] POV: Trung thu mà nhà chưa có đèn. [laughs] haha",
    "caption": "c",
    "hashtags": ["#trungthu"],
    "style3_headline": "TRUNG THU\\nRỰC RỠ",
}, ensure_ascii=False)


class ThemeDirectiveTests(unittest.TestCase):
    def test_empty_theme_gives_no_directive(self):
        for empty in (None, "", "   \n  "):
            self.assertEqual(sg.build_theme_directive(empty), "")
            self.assertIsNone(sg.normalize_script_theme(empty))

    def test_theme_is_normalized_and_capped(self):
        self.assertEqual(sg.normalize_script_theme("  Tết   Trung\nthu "), "Tết Trung thu")
        self.assertEqual(len(sg.normalize_script_theme("a" * 1000)), sg.SCRIPT_THEME_MAX_CHARS)
        text = sg.build_theme_directive("Tết Trung thu")
        self.assertIn("CHỦ ĐỀ KỊCH BẢN DO NGƯỜI DÙNG CHỌN: Tết Trung thu", text)
        self.assertIn("hashtags", text)


class ThemeInPromptTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = TemporaryDirectory()
        self._patch = patch.object(sg, "_hook_history_path", return_value=Path(self._tmp.name) / "h.json")
        self._patch.start()

    async def asyncTearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    async def test_meta_prompt_contains_theme_and_hook(self):
        with patch.object(sg, "call_llm", return_value=GOOD_JSON) as mock_llm:
            await sg.generate_script_from_tiktok_meta(title="Đèn lồng", theme="Tết Trung thu")
        msg = mock_llm.call_args[0][0]
        self.assertIn("CHỦ ĐỀ KỊCH BẢN DO NGƯỜI DÙNG CHỌN: Tết Trung thu", msg)
        self.assertIn("KIỂU HOOK BẮT BUỘC", msg)
        self.assertLess(msg.index("CHỦ ĐỀ KỊCH BẢN DO"), msg.index("KIỂU HOOK BẮT BUỘC CHO CÂU"))

    async def test_no_theme_keeps_old_behaviour(self):
        with patch.object(sg, "call_llm", return_value=GOOD_JSON) as mock_llm:
            await sg.generate_script_from_tiktok_meta(title="Đèn lồng")
            await sg.generate_script("Đèn lồng")
        for call in mock_llm.call_args_list:
            self.assertNotIn("CHỦ ĐỀ KỊCH BẢN", call[0][0])

    async def test_generate_script_with_theme(self):
        with patch.object(sg, "call_llm", return_value=GOOD_JSON) as mock_llm:
            await sg.generate_script("Đèn lồng", theme="20/10")
        self.assertIn("CHỦ ĐỀ KỊCH BẢN DO NGƯỜI DÙNG CHỌN: 20/10", mock_llm.call_args[0][0])


class ThemePlumbingTests(unittest.TestCase):
    @patch("src.web.job_manager.threading.Thread")
    def test_create_batch_applies_default_and_item_theme(self, mock_thread):
        from src.web.job_manager import JobManager
        mgr = JobManager()
        snap = mgr.create_batch(
            [
                {"url": "https://www.tiktok.com/@a/video/1"},
                {"url": "https://www.tiktok.com/@a/video/2", "script_theme": "  Black   Friday "},
                {"url": "https://www.tiktok.com/@a/video/3", "script_theme": "   "},
            ],
            default_script_theme="Tết Trung thu",
        )
        self.assertEqual([it.script_theme for it in snap.items], ["Tết Trung thu", "Black Friday", "Tết Trung thu"])

    @patch("src.web.job_manager.threading.Thread")
    def test_create_batch_without_theme_is_none(self, mock_thread):
        from src.web.job_manager import JobManager
        snap = JobManager().create_batch([{"url": "https://www.tiktok.com/@a/video/1"}])
        self.assertIsNone(snap.items[0].script_theme)

    @patch("src.web.job_manager.threading.Thread")
    def test_profile_job_passes_theme_to_thread(self, mock_thread):
        from src.web.job_manager import JobManager
        JobManager().create_profile_job(profile_url="@shop", script_theme=" 20/10 ")
        args = mock_thread.call_args.kwargs["args"]
        self.assertEqual(args[-1], "20/10")

    def test_api_schemas_accept_script_theme(self):
        from src.web.app import AutoGenRequest, BatchRequest, ProfileAiVideoRequest
        self.assertEqual(ProfileAiVideoRequest(profile_url="@shop", script_theme="Tết").script_theme, "Tết")
        self.assertIsNone(ProfileAiVideoRequest(profile_url="@shop").script_theme)
        self.assertEqual(AutoGenRequest(mode="review", items=[{"url": "https://www.tiktok.com/@a/video/1"}], script_theme="Noel").script_theme, "Noel")
        req = BatchRequest(items=[{"url": "u", "script_theme": "8/3"}], script_theme="Tết")
        self.assertEqual(req.items[0]["script_theme"], "8/3")
        self.assertEqual(req.script_theme, "Tết")

    def test_pipeline_item_state_has_theme(self):
        from src.pipeline import ItemState
        self.assertIsNone(ItemState(index=1, url="u").script_theme)
        self.assertEqual(ItemState(index=1, url="u", script_theme="Tết").script_theme, "Tết")


if __name__ == "__main__":
    unittest.main()
