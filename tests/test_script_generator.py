"""tests/test_script_generator.py - Unit tests for multimodal product recognition and script generation."""

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from src.script_generator import (
    ScriptResult,
    _call_anthropic,
    _call_openai_compatible,
    _extract_json,
    call_llm,
    extract_video_frames,
    generate_script_from_tiktok_meta,
)


class ScriptGeneratorMultimodalTests(unittest.IsolatedAsyncioTestCase):
    """Test suite for multimodal frame extraction and prompt generation."""

    def setUp(self):
        # Không ghi lịch sử hook vào FINAL_OUTPUT_DIR thật khi chạy test
        self._hook_tmp = TemporaryDirectory()
        hook_patch = patch("src.script_generator._hook_history_path",
                           return_value=Path(self._hook_tmp.name) / "hook_history.json")
        hook_patch.start()
        self.addCleanup(hook_patch.stop)
        self.addCleanup(self._hook_tmp.cleanup)

    def test_extract_json_clean_and_fenced(self):
        raw_clean = '{"product_name": "Kệ đa năng", "tiktok_script": "Tuyệt vời"}'
        self.assertEqual(_extract_json(raw_clean)["product_name"], "Kệ đa năng")

        raw_fenced = '```json\n{"product_name": "Hộp đựng cơm", "tiktok_script": "Ngon"}\n```'
        self.assertEqual(_extract_json(raw_fenced)["product_name"], "Hộp đựng cơm")

    @patch("src.script_generator.probe_duration", return_value=10.0)
    @patch("src.script_generator.asyncio.create_subprocess_exec")
    async def test_extract_video_frames_distribution(self, mock_subprocess, mock_probe):
        with TemporaryDirectory() as tmp_dir:
            video_file = Path(tmp_dir) / "dummy.mp4"
            video_file.write_bytes(b"dummy video data")

            # Fake FFmpeg subprocess creation creating output files
            async def fake_exec(*args, **kwargs):
                # Target output jpg is the last arg in cmd
                out_path = Path(args[-1])
                out_path.write_bytes(b"\xff\xd8\xff dummy jpeg data")
                proc = MagicMock()
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
                return proc

            mock_subprocess.side_effect = fake_exec

            frames = await extract_video_frames(video_file, num_frames=3)
            self.assertEqual(len(frames), 3)
            for f in frames:
                self.assertTrue(f.exists())
                self.assertTrue(f.name.endswith(".jpg"))

    @patch("src.script_generator.aiohttp.ClientSession")
    @patch("src.script_generator.settings")
    async def test_call_anthropic_formats_multimodal_payload(self, mock_settings, mock_session_class):
        mock_settings.LLM_API_KEY = "test_anthropic_key"
        mock_settings.LLM_MODEL = "claude-3-5-sonnet-20241022"

        with TemporaryDirectory() as tmp_dir:
            img1 = Path(tmp_dir) / "frame_00.jpg"
            img1.write_bytes(b"image_bytes_1")

            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={"content": [{"text": '{"product_name": "Máy cạo râu"}'}]})
            
            mock_session = MagicMock()
            mock_session.post.return_value.__aenter__.return_value = mock_resp
            mock_session_class.return_value.__aenter__.return_value = mock_session

            res = await _call_anthropic("User prompt", "System prompt", 1024, [img1])
            self.assertIn("Máy cạo râu", res)

            # Check that post was called with image block
            _, kwargs = mock_session.post.call_args
            payload = kwargs["json"]
            self.assertEqual(len(payload["messages"]), 1)
            content = payload["messages"][0]["content"]
            self.assertIsInstance(content, list)
            self.assertEqual(content[0]["type"], "image")
            self.assertEqual(content[0]["source"]["type"], "base64")
            self.assertEqual(content[1]["type"], "text")

    @patch("src.script_generator.aiohttp.ClientSession")
    @patch("src.script_generator.settings")
    async def test_call_openai_compatible_formats_vision_payload(self, mock_settings, mock_session_class):
        mock_settings.LLM_API_KEY = "test_openai_key"
        mock_settings.LLM_MODEL = "gpt-4o"

        with TemporaryDirectory() as tmp_dir:
            img1 = Path(tmp_dir) / "frame_00.jpg"
            img1.write_bytes(b"image_bytes_1")

            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.text = AsyncMock(return_value=json.dumps({
                "choices": [{"message": {"content": '{"product_name": "Bàn chải điện"}'}}]
            }))

            mock_session = MagicMock()
            mock_session.post.return_value.__aenter__.return_value = mock_resp
            mock_session_class.return_value.__aenter__.return_value = mock_session

            res = await _call_openai_compatible("User prompt", "System prompt", 1024, [img1])
            self.assertIn("Bàn chải điện", res)

            # Check that post was called with image_url block
            _, kwargs = mock_session.post.call_args
            payload = kwargs["json"]
            user_msg = payload["messages"][1]
            self.assertEqual(user_msg["role"], "user")
            self.assertIsInstance(user_msg["content"], list)
            self.assertEqual(user_msg["content"][0]["type"], "text")
            self.assertEqual(user_msg["content"][1]["type"], "image_url")
            self.assertTrue(user_msg["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    @patch("src.script_generator.extract_video_frames")
    @patch("src.script_generator.call_llm")
    async def test_generate_script_from_tiktok_meta_includes_caption_hashtags_and_frames(
        self, mock_call_llm, mock_extract_frames
    ):
        with TemporaryDirectory() as tmp_dir:
            video_file = Path(tmp_dir) / "video.mp4"
            video_file.write_bytes(b"fake video")

            frame1 = Path(tmp_dir) / "frame_0.jpg"
            frame1.write_bytes(b"fake frame")
            mock_extract_frames.return_value = [frame1]

            mock_call_llm.return_value = json.dumps({
                "product_name": "Tai nghe Bluetooth Pro",
                "tiktok_script": "[excited] Quá đã các con vợ ơi [laughs] haha!",
                "caption": "Múc ngay tai nghe này",
                "hashtags": ["#tainghe", "#bluetooth"],
                "overlay_banner_title": "TAI NGHE CHỐNG ỒN ĐỈNH CAO",
                "style3_headline": "ĐỪNG VỘI MUA TAI NGHE\\nNẾU CHƯA BIẾT ĐIỀU NÀY",
                "style3_quote": "Chống ồn siêu thực, đeo êm tai không đau",
            })

            res = await generate_script_from_tiktok_meta(
                title="Review tai nghe siêu đỉnh",
                caption="Tai nghe chống ồn thế hệ mới dùng bao phê",
                hashtags=["#tainghe", "#review"],
                product_hint=None,
                video_path=video_file,
            )

            self.assertEqual(res.product_name, "Tai nghe Bluetooth Pro")
            self.assertIn("[excited]", res.tiktok_script)
            self.assertEqual(res.style3_headline, "ĐỪNG VỘI MUA TAI NGHE\\nNẾU CHƯA BIẾT ĐIỀU NÀY")
            
            # Verify call_llm received prompt with caption and hashtags, along with image frames
            called_user_msg, = mock_call_llm.call_args[0]
            self.assertIn("Review tai nghe siêu đỉnh", called_user_msg)
            self.assertIn("Tai nghe chống ồn thế hệ mới", called_user_msg)
            self.assertIn("#tainghe, #review", called_user_msg)
            
            called_kwargs = mock_call_llm.call_args[1]
            self.assertEqual(called_kwargs.get("image_paths"), [frame1])

    @patch("src.script_generator.settings")
    async def test_call_llm_raises_when_api_key_missing(self, mock_settings):
        mock_settings.LLM_API_KEY = ""
        with self.assertRaises(RuntimeError) as ctx:
            await call_llm("test")
        self.assertIn("LLM_API_KEY is not set", str(ctx.exception))

    @patch("src.script_generator.extract_video_frames")
    @patch("src.script_generator.call_llm")
    async def test_generate_script_from_tiktok_meta_raises_on_llm_error(
        self, mock_call_llm, mock_extract_frames
    ):
        mock_extract_frames.return_value = [Path("fake_frame.jpg")]
        mock_call_llm.side_effect = RuntimeError("Vision API quota exceeded")

        with self.assertRaises(RuntimeError) as ctx:
            await generate_script_from_tiktok_meta(
                title="Review test",
                caption="Caption test",
                hashtags=["#test"],
                video_path=Path("fake_video.mp4"),
            )
        self.assertIn("Vision API quota exceeded", str(ctx.exception))


    def test_system_prompt_includes_adam_persona_and_comedic_slang(self):
        from src.script_generator import SYSTEM_PROMPT
        self.assertIn("ADAM", SYSTEM_PROMPT)
        self.assertIn("má ơi", SYSTEM_PROMPT)
        self.assertIn("khùng thiệt", SYSTEM_PROMPT)
        self.assertIn("Storytelling Angles", SYSTEM_PROMPT)
        self.assertIn("Skeptical to Converted", SYSTEM_PROMPT)
        self.assertIn("Reverse Psychology", SYSTEM_PROMPT)
        self.assertIn("TUYỆT ĐỐI CẤM", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
