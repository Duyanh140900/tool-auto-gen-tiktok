"""tests/test_script_hooks.py - Kiểm tra chọn kiểu hook và danh sách tránh lặp (không gọi LLM thật)."""

import json
import os
import random
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src import script_generator as sg


def _llm_json(script: str, headline: str = "HEADLINE MỚI\\nCỰC CUỐN") -> str:
    return json.dumps({
        "product_name": "Bình giữ nhiệt",
        "tiktok_script": script,
        "caption": "Caption",
        "hashtags": ["#a"],
        "overlay_banner_title": "Banner",
        "style3_headline": headline,
        "style3_quote": "Quote",
    }, ensure_ascii=False)


class PickHookStyleTests(unittest.TestCase):
    def test_has_many_distinct_styles(self):
        keys = [s.key for s in sg.HOOK_STYLES]
        self.assertGreaterEqual(len(keys), 10)
        self.assertEqual(len(keys), len(set(keys)))
        for s in sg.HOOK_STYLES:
            self.assertTrue(s.name and s.guide and s.examples)
            for ex in s.examples:
                self.assertIsNone(sg.find_banned_phrase(ex), f"Ví dụ của {s.key} dính cụm cấm: {ex}")

    def test_avoids_recently_used_styles(self):
        recent = [s.key for s in sg.HOOK_STYLES[: sg.RECENT_STYLE_WINDOW]]
        for seed in range(50):
            picked = sg.pick_hook_style(recent, rng=random.Random(seed))
            self.assertNotIn(picked.key, recent)

    def test_only_last_window_is_excluded(self):
        styles = sg.HOOK_STYLES[:3]
        # Cửa sổ bị giới hạn len(pool)-1 = 2 -> chỉ loại 2 kiểu cuối cùng
        recent = [styles[1].key, styles[2].key]
        for seed in range(20):
            self.assertEqual(sg.pick_hook_style(recent, rng=random.Random(seed), styles=styles).key, styles[0].key)

    def test_single_style_pool_still_returns(self):
        only = sg.HOOK_STYLES[:1]
        self.assertEqual(sg.pick_hook_style([only[0].key], styles=only).key, only[0].key)

    def test_selection_varies(self):
        rng = random.Random(123)
        picked = {sg.pick_hook_style([], rng=rng).key for _ in range(100)}
        self.assertGreaterEqual(len(picked), 8)

    def test_env_whitelist(self):
        with patch.dict(os.environ, {"SCRIPT_HOOK_STYLES": "pov, question"}):
            keys = {s.key for s in sg._available_hook_styles()}
        self.assertEqual(keys, {"pov", "question"})
        with patch.dict(os.environ, {"SCRIPT_HOOK_STYLES": "khong_ton_tai"}):
            self.assertEqual(len(sg._available_hook_styles()), len(sg.HOOK_STYLES))


class BannedPhraseAndOpeningTests(unittest.TestCase):
    def test_detects_cliches_with_or_without_accents(self):
        self.assertEqual(sg.find_banned_phrase("Tưởng mua về cho vui, ai ngờ dùng mê"), "tưởng mua")
        self.assertEqual(sg.find_banned_phrase("CỨU TINH CHO HỘI LƯỜI"), "cứu tinh")
        self.assertEqual(sg.find_banned_phrase("cu ngo la do choi"), "cứ ngỡ")
        self.assertIsNone(sg.find_banned_phrase("POV: 6 giờ sáng trễ làm"))

    def test_extract_opening_line_strips_audio_tags(self):
        script = "[gasps] Khoan đã, cái gì vậy trời? [laughs] Nó tự gập luôn haha!"
        self.assertEqual(sg.extract_opening_line(script), "Khoan đã, cái gì vậy trời?")
        self.assertEqual(sg.extract_opening_line(""), "")


class HookHistoryTests(unittest.TestCase):
    def test_record_and_load_roundtrip_with_cap(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "hist.json"
            for i in range(sg.HOOK_HISTORY_MAX + 5):
                sg.record_hook_usage("pov", f"[laughs] Câu số {i}. Thân bài.", "HEAD\\nLINE", path=path)
            hist = sg.load_hook_history(path)
            self.assertEqual(len(hist), sg.HOOK_HISTORY_MAX)
            self.assertEqual(hist[-1]["opening"], f"Câu số {sg.HOOK_HISTORY_MAX + 4}.")
            self.assertEqual(hist[-1]["headline"], "HEAD LINE")
            self.assertEqual(hist[-1]["style"], "pov")

    def test_load_handles_missing_and_corrupt_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "hist.json"
            self.assertEqual(sg.load_hook_history(path), [])
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(sg.load_hook_history(path), [])

    def test_directive_lists_recent_openings_and_bans(self):
        style = sg.HOOK_STYLES[0]
        history = [{"style": "pov", "opening": f"Mở đầu {i}", "headline": ""} for i in range(20)]
        text = sg.build_hook_directive(style, history)
        self.assertIn(style.name, text)
        self.assertIn("tưởng mua", text)
        self.assertIn("Mở đầu 19", text)  # mới nhất có mặt
        self.assertNotIn("Mở đầu 0\"", text)  # cũ quá bị cắt
        self.assertEqual(text.count("\"Mở đầu "), sg.RECENT_OPENINGS_IN_PROMPT)


class GenerateWithHookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = TemporaryDirectory()
        self.hist_path = Path(self._tmp.name) / "hist.json"
        self._patch = patch.object(sg, "_hook_history_path", return_value=self.hist_path)
        self._patch.start()

    async def asyncTearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    async def test_prompt_contains_hook_and_recent_openings_then_records(self):
        sg.record_hook_usage("question", "[sighs] Có ai rửa bình mà thò cả tay vào không? Thân.")
        with patch.object(sg, "call_llm") as mock_llm:
            mock_llm.return_value = _llm_json("[gasps] POV: trễ làm còn 2 phút. [laughs] haha")
            res = await sg.generate_script_from_tiktok_meta(title="Bình giữ nhiệt", caption="cap")
        user_msg = mock_llm.call_args[0][0]
        self.assertIn("KIỂU HOOK BẮT BUỘC", user_msg)
        self.assertIn("Có ai rửa bình mà thò cả tay vào không?", user_msg)
        self.assertEqual(mock_llm.call_count, 1)
        self.assertEqual(res.tiktok_script, "[gasps] POV: trễ làm còn 2 phút. [laughs] haha")

        hist = sg.load_hook_history(self.hist_path)
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[-1]["opening"], "POV: trễ làm còn 2 phút.")
        self.assertNotEqual(hist[-1]["style"], "question")  # vừa dùng nên không chọn lại

    async def test_retries_once_when_opening_uses_cliche(self):
        with patch.object(sg, "call_llm") as mock_llm:
            mock_llm.side_effect = [
                _llm_json("[sarcastic] Tưởng mua về cho vui, ai ngờ mê luôn."),
                _llm_json("[gasps] 7 giây, sạch bong cái bếp. [laughs] haha"),
            ]
            res = await sg.generate_script("Khăn lau bếp")
        self.assertEqual(mock_llm.call_count, 2)
        self.assertIn("tưởng mua", mock_llm.call_args_list[1][0][0])
        self.assertTrue(res.tiktok_script.startswith("[gasps] 7 giây"))

    async def test_keeps_first_result_if_retry_fails(self):
        with patch.object(sg, "call_llm") as mock_llm:
            mock_llm.side_effect = [
                _llm_json("Cứu tinh cho hội lười đây rồi."),
                RuntimeError("quota"),
            ]
            res = await sg.generate_script("Máy hút bụi")
        self.assertEqual(res.tiktok_script, "Cứu tinh cho hội lười đây rồi.")


    async def test_retries_once_when_json_truncated(self):
        truncated = _llm_json("[gasps] Top 1 món đáng tiền nhất nhà tôi. haha")[:120]
        with patch.object(sg, "call_llm") as mock_llm:
            mock_llm.side_effect = [truncated, _llm_json("[gasps] Top 1 món đáng tiền nhất nhà tôi. haha")]
            res = await sg.generate_script("Bút chì")
        self.assertEqual(mock_llm.call_count, 2)
        self.assertIn("CẮT CỤT", mock_llm.call_args_list[1][0][0])
        self.assertEqual(mock_llm.call_args_list[0][1]["max_tokens"], sg._llm_max_tokens())
        self.assertTrue(res.tiktok_script.startswith("[gasps] Top 1"))

    async def test_raises_clear_error_when_json_broken_twice(self):
        truncated = _llm_json("[gasps] Top 1 món đáng tiền. haha")[:120]
        with patch.object(sg, "call_llm") as mock_llm:
            mock_llm.side_effect = [truncated, truncated]
            with self.assertRaises(sg.LLMJSONError) as ctx:
                await sg.generate_script("Bút chì")
        self.assertIn("LLM_MAX_TOKENS", str(ctx.exception))
        self.assertEqual(sg.load_hook_history(self.hist_path), [])


class ExtractJsonTests(unittest.TestCase):
    def test_tolerates_text_around_json_and_raw_newlines(self):
        raw = 'Đây là kết quả:\n{"tiktok_script": "dòng 1\ndòng 2", "caption": "c"}\nHết.'
        data = sg._extract_json(raw)
        self.assertEqual(data["tiktok_script"], "dòng 1\ndòng 2")

    def test_max_tokens_env(self):
        with patch.dict(os.environ, {"LLM_MAX_TOKENS": "4096"}):
            self.assertEqual(sg._llm_max_tokens(), 4096)
        with patch.dict(os.environ, {"LLM_MAX_TOKENS": "abc"}):
            self.assertEqual(sg._llm_max_tokens(), 2048)

if __name__ == "__main__":
    unittest.main()
