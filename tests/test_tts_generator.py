"""tests/test_tts_generator.py - Unit tests for TTS generator, no-fallback rule and credit exhaustion."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from src import tts_generator
from src.tts_generator import (
    TTSCreditExhaustedError,
    TTSResult,
    is_credit_exhausted_error,
    is_free_voice_id,
    is_placeholder_voice_id,
    split_text_for_google_tts,
)


class TTSGeneratorTests(unittest.TestCase):
    def test_is_free_voice_id(self) -> None:
        self.assertTrue(is_free_voice_id("google-free"))
        self.assertTrue(is_free_voice_id("edge-vi-female"))
        self.assertTrue(is_free_voice_id("edge-vi-male"))
        self.assertTrue(is_free_voice_id("free"))
        self.assertFalse(is_free_voice_id("5r2MVjMtzwsSDz1paLjbiY9"))
        self.assertFalse(is_placeholder_voice_id("google-free"))
        self.assertFalse(is_placeholder_voice_id("edge-vi-female"))

    def test_is_credit_exhausted_error(self) -> None:
        self.assertTrue(is_credit_exhausted_error(402, "Payment required"))
        self.assertTrue(is_credit_exhausted_error(429, "Too many requests"))
        self.assertTrue(is_credit_exhausted_error(200, "out of credits, please upgrade"))
        self.assertTrue(is_credit_exhausted_error(200, "Tài khoản không đủ credit"))
        self.assertTrue(is_credit_exhausted_error(200, "exceeded your current quota"))
        self.assertFalse(is_credit_exhausted_error(200, "Success"))
        self.assertFalse(is_credit_exhausted_error(500, "Internal server error"))

    def test_split_text_for_google_tts_strips_emotion_tags(self) -> None:
        text = "[excited] Xin chào các bạn! [laughs] Thùng rác thông minh này cực xịn sò [whispers] nha."
        chunks = split_text_for_google_tts(text, max_chars=150)
        self.assertTrue(len(chunks) >= 1)
        for chunk in chunks:
            self.assertNotIn("[excited]", chunk)
            self.assertNotIn("[laughs]", chunk)
            self.assertNotIn("[whispers]", chunk)
        full = " ".join(chunks)
        self.assertIn("Xin chào các bạn!", full)
        self.assertIn("Thùng rác thông minh này cực xịn sò", full)

    def test_split_text_for_google_tts_long_text(self) -> None:
        text = (
            "Một hai ba bốn năm sáu bảy tám chín mười. "
            "Đây là một câu rất dài nhằm kiểm tra thuật toán chia nhỏ văn bản "
            "thành các đoạn có độ dài dưới 50 ký tự để không bị quá tải endpoint."
        )
        chunks = split_text_for_google_tts(text, max_chars=50)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 50)

    async def _run_synthesize_free_google(self, tmpdir: str) -> None:
        out_path = Path(tmpdir) / "voice_google.mp3"
        mock_google_res = TTSResult(
            provider="google",
            voice_id="google-vi-standard",
            text="Hello free google",
            audio_path=out_path,
        )
        with patch("src.tts_generator.tts_google", new_callable=AsyncMock, return_value=mock_google_res) as mock_google, \
             patch("src.tts_generator.tts_itera102", new_callable=AsyncMock) as mock_itera:
            result = await tts_generator.synthesize(
                "Hello free google",
                out_path,
                voice_id="google-free",
                speed=1.1,
            )
            mock_google.assert_awaited_once_with("Hello free google", out_path, speed=1.1)
            mock_itera.assert_not_awaited()
            self.assertEqual(result.provider, "google")

    def test_synthesize_free_google_bypasses_itera(self) -> None:
        with TemporaryDirectory() as tmpdir:
            asyncio.run(self._run_synthesize_free_google(tmpdir))

    async def _run_synthesize_free_edge(self, tmpdir: str) -> None:
        out_path = Path(tmpdir) / "voice_edge.mp3"
        mock_edge_res = TTSResult(
            provider="edge_tts",
            voice_id="vi-VN-HoaiMyNeural",
            text="Hello free edge",
            audio_path=out_path,
        )
        with patch("src.tts_generator.tts_edge", new_callable=AsyncMock, return_value=mock_edge_res) as mock_edge, \
             patch("src.tts_generator.tts_itera102", new_callable=AsyncMock) as mock_itera:
            result = await tts_generator.synthesize(
                "Hello free edge",
                out_path,
                voice_id="edge-vi-female",
                speed=1.15,
            )
            mock_edge.assert_awaited_once_with("Hello free edge", out_path, voice="vi-VN-HoaiMyNeural", speed=1.15)
            mock_itera.assert_not_awaited()
            self.assertEqual(result.provider, "edge_tts")

    def test_synthesize_free_edge_bypasses_itera(self) -> None:
        with TemporaryDirectory() as tmpdir:
            asyncio.run(self._run_synthesize_free_edge(tmpdir))

    async def _run_synthesize_no_fallback_by_default(self, tmpdir: str) -> None:
        out_path = Path(tmpdir) / "voice_err.m4a"
        with patch(
            "src.tts_generator.tts_itera102",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Itera102 voice synthesis error"),
        ) as mock_itera, patch(
            "src.tts_generator.tts_google",
            new_callable=AsyncMock,
        ) as mock_google:
            with self.assertRaises(RuntimeError):
                await tts_generator.synthesize(
                    "Hello test",
                    out_path,
                    voice_id="voice-123",
                    speed=1.0,
                )
            mock_itera.assert_awaited_once()
            # Không được fallback sang Google
            mock_google.assert_not_awaited()

    def test_synthesize_no_fallback_by_default(self) -> None:
        with TemporaryDirectory() as tmpdir:
            asyncio.run(self._run_synthesize_no_fallback_by_default(tmpdir))

    async def _run_synthesize_credit_exhausted_raises_special_error(self, tmpdir: str) -> None:
        out_path = Path(tmpdir) / "voice_out_of_credit.m4a"
        with patch(
            "src.tts_generator.tts_itera102",
            new_callable=AsyncMock,
            side_effect=TTSCreditExhaustedError("itera102 hết credit / quota (HTTP 402): Payment Required"),
        ) as mock_itera, patch(
            "src.tts_generator.tts_google",
            new_callable=AsyncMock,
        ) as mock_google:
            with self.assertRaises(TTSCreditExhaustedError):
                await tts_generator.synthesize(
                    "Hello credit test",
                    out_path,
                    voice_id="voice-123",
                    allow_fallback=True,  # Kể cả bật fallback, hết credit vẫn raise TTSCreditExhaustedError
                )
            mock_itera.assert_awaited_once()
            mock_google.assert_not_awaited()

    def test_synthesize_credit_exhausted_raises_special_error(self) -> None:
        with TemporaryDirectory() as tmpdir:
            asyncio.run(self._run_synthesize_credit_exhausted_raises_special_error(tmpdir))


if __name__ == "__main__":
    unittest.main()
