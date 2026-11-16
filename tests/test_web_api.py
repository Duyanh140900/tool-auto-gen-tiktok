"""Test chống tái phát lỗi 422 cho TestRenderRequest schema."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError


class FolderPickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_folder_picker_runs_dialog_in_worker_thread(self):
        from src.web.app import pick_folder

        with patch(
            "src.web.app.asyncio.to_thread",
            new=AsyncMock(return_value=r"D:\TikTok Videos"),
        ) as to_thread:
            result = await pick_folder()

        self.assertEqual(result, {"path": r"D:\TikTok Videos"})
        to_thread.assert_awaited_once()

    def test_windows_folder_picker_uses_sta_and_utf8(self):
        from src.web import app as web_app

        completed = type(
            "Completed",
            (),
            {"returncode": 0, "stdout": "D:\\Video tiếng Việt\n", "stderr": ""},
        )()
        with patch.object(web_app.sys, "platform", "win32"), patch.object(
            web_app.subprocess, "run", return_value=completed
        ) as run:
            result = web_app._pick_folder_dialog()

        self.assertEqual(result, "D:\\Video tiếng Việt")
        args, kwargs = run.call_args
        self.assertIn("-STA", args[0])
        self.assertEqual(kwargs["encoding"], "utf-8")


class TestRenderRequestSchemaTests(unittest.TestCase):
    """Validate TestRenderRequest schema rules:
    - mode: only 'review' or 'montage'
    - review mode: >= 1 URL
    - montage mode: >= 2 URLs
    """

    def _import(self):
        from src.web.app import TestRenderRequest
        return TestRenderRequest

    def test_review_mode_single_url_ok(self):
        """Review mode with 1 URL should be valid."""
        TestRenderRequest = self._import()
        req = TestRenderRequest(
            mode="review",
            urls=["https://www.tiktok.com/@user/video/123"],
            script="Noi dung test",
            duration_sec=10.0,
        )
        self.assertEqual(req.mode, "review")
        self.assertEqual(len(req.urls), 1)
        self.assertEqual(req.script, "Noi dung test")

    def test_review_mode_empty_urls_fails(self):
        """Review mode with 0 URLs should fail."""
        TestRenderRequest = self._import()
        with self.assertRaises(ValidationError) as ctx:
            TestRenderRequest(
                mode="review",
                urls=[],
                script="Noi dung test",
            )
        exc_str = str(ctx.exception).lower()
        self.assertTrue(
            "1" in exc_str and "url" in exc_str,
            f"Expected '1 URL' in error: {ctx.exception}",
        )

    def test_montage_mode_two_urls_ok(self):
        """Montage mode with 2 URLs should be valid."""
        TestRenderRequest = self._import()
        req = TestRenderRequest(
            mode="montage",
            urls=[
                "https://www.tiktok.com/@user/video/1",
                "https://www.tiktok.com/@user/video/2",
            ],
            script="Noi dung test",
        )
        self.assertEqual(req.mode, "montage")
        self.assertEqual(len(req.urls), 2)

    def test_montage_mode_single_url_fails(self):
        """Montage mode with only 1 URL should fail."""
        TestRenderRequest = self._import()
        with self.assertRaises(ValidationError) as ctx:
            TestRenderRequest(
                mode="montage",
                urls=["https://www.tiktok.com/@user/video/1"],
                script="Noi dung test",
            )
        exc_str = str(ctx.exception).lower()
        self.assertTrue(
            "2" in exc_str and "url" in exc_str,
            f"Expected '2 URL' in error: {ctx.exception}",
        )

    def test_montage_mode_zero_urls_fails(self):
        """Montage mode with 0 URLs should fail."""
        TestRenderRequest = self._import()
        with self.assertRaises(ValidationError):
            TestRenderRequest(
                mode="montage",
                urls=[],
                script="Noi dung test",
            )

    def test_invalid_mode_fails(self):
        """Mode 'live' or 'mock' should be rejected."""
        TestRenderRequest = self._import()
        for bad_mode in ("live", "mock", "LIVERENDER"):
            with self.assertRaises(ValidationError) as ctx:
                TestRenderRequest(
                    mode=bad_mode,
                    urls=["https://www.tiktok.com/@user/video/1"],
                    script="Test",
                )
            self.assertTrue(any(
                "'review' or 'montage'" in str(e).lower() or "review" in str(e).lower()
                for e in ctx.exception.errors()
            ))

    def test_mode_case_insensitive(self):
        """Mode should be case-insensitive."""
        TestRenderRequest = self._import()
        req = TestRenderRequest(
            mode="REVIEW",
            urls=["https://www.tiktok.com/@user/video/1"],
            script="Test",
        )
        self.assertEqual(req.mode, "review")

    def test_url_whitespace_stripped(self):
        """URLs with extra whitespace should be stripped."""
        TestRenderRequest = self._import()
        req = TestRenderRequest(
            mode="review",
            urls=["  https://www.tiktok.com/@user/video/1  ", "  \n  "],
            script="  Test script  ",
        )
        self.assertEqual(req.urls, ["https://www.tiktok.com/@user/video/1"])
        self.assertEqual(req.script, "Test script")

    def test_test_render_ratio_default(self):
        """TestRenderRequest should default video_shift_ratio to 0.3333 and style to 'style1'."""
        TestRenderRequest = self._import()
        req = TestRenderRequest(mode="review", urls=["https://tiktok.com/v/1"], script="Test")
        self.assertEqual(req.video_shift_ratio, 0.3333)
        self.assertEqual(req.style, "style1")

    def test_test_render_accepts_style2(self):
        """TestRenderRequest should accept style2."""
        TestRenderRequest = self._import()
        req = TestRenderRequest(mode="review", urls=["https://tiktok.com/v/1"], script="Test", style="style2")
        self.assertEqual(req.style, "style2")

    def test_test_render_accepts_style3(self):
        """TestRenderRequest should accept style3."""
        TestRenderRequest = self._import()
        req = TestRenderRequest(mode="review", urls=["https://tiktok.com/v/1"], script="Test", style="style3")
        self.assertEqual(req.style, "style3")

    def test_test_render_ratio_boundary(self):
        """TestRenderRequest should accept 0, 0.5, 1.0."""
        TestRenderRequest = self._import()
        for ratio in (0.0, 0.5, 1.0):
            req = TestRenderRequest(mode="review", urls=["https://tiktok.com/v/1"], script="Test", video_shift_ratio=ratio)
            self.assertEqual(req.video_shift_ratio, ratio)

    def test_test_render_ratio_out_of_range_fails(self):
        """TestRenderRequest should reject ratios outside 0..1."""
        TestRenderRequest = self._import()
        for bad in (-0.1, 1.5, 2.0):
            with self.assertRaises(ValidationError):
                TestRenderRequest(mode="review", urls=["https://tiktok.com/v/1"], script="Test", video_shift_ratio=bad)


class MontageRequestSchemaTests(unittest.TestCase):
    """Validate MontageRequest schema."""

    def _import(self):
        from src.web.app import MontageRequest
        return MontageRequest

    def test_montage_requires_two_urls(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self._import()(urls=["https://tiktok.com/v/1"], script="Test")

    def test_montage_ratio_default(self):
        req = self._import()(urls=["https://tiktok.com/v/1", "https://tiktok.com/v/2"], script="Test")
        self.assertEqual(req.video_shift_ratio, 0.3333)

    def test_montage_ratio_boundary(self):
        for ratio in (0.0, 0.5, 1.0):
            req = self._import()(urls=["https://tiktok.com/v/1", "https://tiktok.com/v/2"], script="Test", video_shift_ratio=ratio)
            self.assertEqual(req.video_shift_ratio, ratio)

    def test_montage_ratio_out_of_range_fails(self):
        from pydantic import ValidationError
        for bad in (-0.1, 1.5):
            with self.assertRaises(ValidationError):
                self._import()(urls=["https://tiktok.com/v/1", "https://tiktok.com/v/2"], script="Test", video_shift_ratio=bad)


class BatchItemRequestSchemaTests(unittest.TestCase):
    """Validate BatchItemRequest schema."""

    def _import(self):
        from src.web.app import BatchItemRequest
        return BatchItemRequest

    def test_batch_item_ratio_default(self):
        req = self._import()(url="https://tiktok.com/v/1")
        self.assertEqual(req.video_shift_ratio, 0.3333)

    def test_batch_item_ratio_boundary(self):
        for ratio in (0.0, 0.5, 1.0):
            req = self._import()(url="https://tiktok.com/v/1", video_shift_ratio=ratio)
            self.assertEqual(req.video_shift_ratio, ratio)

    def test_batch_item_ratio_out_of_range_fails(self):
        from pydantic import ValidationError
        for bad in (-0.1, 1.5):
            with self.assertRaises(ValidationError):
                self._import()(url="https://tiktok.com/v/1", video_shift_ratio=bad)

    def test_batch_item_voice_id(self):
        """BatchItemRequest accepts optional voice_id."""
        req = self._import()(url="https://tiktok.com/v/1", voice_id="5r2MVjMfzwsSDzTpaLjbY9")
        self.assertEqual(req.voice_id, "5r2MVjMfzwsSDzTpaLjbY9")


class AutoGenRequestSchemaTests(unittest.TestCase):
    """Validate AutoGenRequest schema."""

    def _import(self):
        from src.web.app import AutoGenRequest
        return AutoGenRequest

    def test_review_mode_requires_items(self):
        """Review mode requires at least one item in 'items'."""
        from pydantic import ValidationError
        with self.assertRaises(ValidationError) as ctx:
            self._import()(mode="review", items=[])
        self.assertTrue(any("item" in str(e).lower() for e in ctx.exception.errors()))

    def test_review_mode_with_item_ok(self):
        """Review mode with one item should be valid."""
        req = self._import()(
            mode="review",
            items=[{"url": "https://tiktok.com/v/1"}],
        )
        self.assertEqual(req.mode, "review")
        self.assertEqual(len(req.items), 1)

    def test_review_mode_with_voice_id(self):
        """Review mode accepts job-level voice_id."""
        req = self._import()(
            mode="review",
            items=[{"url": "https://tiktok.com/v/1"}],
            voice_id="5r2MVjMfzwsSDzTpaLjbY9",
        )
        self.assertEqual(req.voice_id, "5r2MVjMfzwsSDzTpaLjbY9")

    def test_montage_mode_requires_two_urls(self):
        """Montage mode requires at least 2 URLs."""
        from pydantic import ValidationError
        with self.assertRaises(ValidationError) as ctx:
            self._import()(mode="montage", urls=["https://tiktok.com/v/1"], script="Test")
        self.assertTrue(any("2" in str(e) or "url" in str(e).lower() for e in ctx.exception.errors()))

    def test_montage_mode_requires_script(self):
        """Montage mode requires a non-empty script."""
        from pydantic import ValidationError
        with self.assertRaises(ValidationError) as ctx:
            self._import()(mode="montage", urls=["https://tiktok.com/v/1", "https://tiktok.com/v/2"], script="")
        self.assertTrue(any("script" in str(e).lower() for e in ctx.exception.errors()))

    def test_montage_mode_ok(self):
        """Montage mode with 2+ URLs and script should be valid."""
        req = self._import()(
            mode="montage",
            urls=["https://tiktok.com/v/1", "https://tiktok.com/v/2"],
            script="Test script TTS",
            voice_id="5r2MVjMfzwsSDzTpaLjbY9",
        )
        self.assertEqual(req.mode, "montage")
        self.assertEqual(len(req.urls), 2)
        self.assertEqual(req.voice_id, "5r2MVjMfzwsSDzTpaLjbY9")

    def test_invalid_mode_rejected(self):
        """Invalid mode values should be rejected."""
        from pydantic import ValidationError
        for bad_mode in ("live", "mock", "invalid"):
            with self.assertRaises(ValidationError):
                self._import()(mode=bad_mode, items=[{"url": "https://tiktok.com/v/1"}])


class WebApiPickFileAndSettingsTests(unittest.TestCase):
    def test_settings_update_accepts_custom_asset_paths(self):
        from src.web.app import SettingsUpdate
        req = SettingsUpdate(
            custom_logo_path="C:/custom/logo.png",
            custom_card_bg_path="C:/custom/bg.png",
            custom_nhay_path="C:/custom/nhay.png",
            custom_black_bg_path="C:/custom/black.png",
        )
        self.assertEqual(req.custom_logo_path, "C:/custom/logo.png")
        self.assertEqual(req.custom_card_bg_path, "C:/custom/bg.png")
        self.assertEqual(req.custom_nhay_path, "C:/custom/nhay.png")
        self.assertEqual(req.custom_black_bg_path, "C:/custom/black.png")

    def test_pick_file_payload_defaults(self):
        from src.web.app import PickFilePayload
        payload = PickFilePayload()
        self.assertEqual(payload.title, "Chọn file ảnh")
        self.assertIn("Image Files", payload.filter)


class ProfileAiVideoRequestSchemaTests(unittest.TestCase):
    def test_profile_ai_video_request_defaults(self):
        from src.web.app import ProfileAiVideoRequest
        req = ProfileAiVideoRequest(profile_url="@testuser")
        self.assertEqual(req.profile_url, "@testuser")
        self.assertEqual(req.video_shift_ratio, 0.25)
        self.assertEqual(req.style, "style1")
        self.assertEqual(req.mode_pipeline, "live")
        self.assertEqual(req.force_rerun_all, False)

    def test_profile_ai_video_custom_shift_ratio(self):
        from src.web.app import ProfileAiVideoRequest
        req = ProfileAiVideoRequest(
            profile_url="https://www.tiktok.com/@testuser",
            video_shift_ratio=0.5,
            voice_id="custom_voice",
        )
        self.assertEqual(req.video_shift_ratio, 0.5)
        self.assertEqual(req.voice_id, "custom_voice")


    def test_post_profile_ai_video_endpoint_flow(self):
        from pathlib import Path
        from unittest.mock import patch
        from starlette.testclient import TestClient
        from src.web.app import app
        from tempfile import TemporaryDirectory

        client = TestClient(app, raise_server_exceptions=False)

        with TemporaryDirectory() as tmp_dir:
            log_path = f"{tmp_dir}/test_manifest.json"
            with patch("src.web.app.get_default_log_file_path", return_value=Path(log_path)):
                with patch("src.web.job_manager.threading.Thread.start"):
                    res = client.post(
                        "/api/profile-ai-video",
                        json={"profile_url": "@testuser", "video_shift_ratio": 0.25},
                    )
                    self.assertEqual(res.status_code, 200, res.text)
                    data = res.json()
                    self.assertEqual(data["status"], "started")
                    self.assertEqual(data["profile_url"], "https://www.tiktok.com/@testuser")

    def test_create_profile_job_direct_execution(self):
        from src.web.job_manager import JobManager
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        mgr = JobManager()
        with TemporaryDirectory() as tmp_dir:
            log_path = f"{tmp_dir}/profile_log.json"
            with patch("threading.Thread.start"):
                snapshot = mgr.create_profile_job(
                    profile_url="@testchannel",
                    video_shift_ratio=0.25,
                    log_file_path=log_path,
                )
                self.assertEqual(snapshot.status, "queued")
                self.assertTrue(snapshot.mode.startswith("profile-"))




class JobControlTests(unittest.TestCase):
    """Kiểm tra chức năng Tạm dừng, Tiếp tục, Dừng hẳn trong JobManager và FastAPI endpoints."""

    def test_job_manager_pause_resume_cancel(self):
        from src.web.job_manager import JobManager
        from unittest.mock import patch

        mgr = JobManager()
        self.assertFalse(mgr.is_running())
        with self.assertRaises(RuntimeError):
            mgr.pause()
        with self.assertRaises(RuntimeError):
            mgr.resume()

        with patch("threading.Thread.start"):
            snapshot = mgr.create_batch(
                items=[{"url": "https://www.tiktok.com/@u/video/123", "script": "hello"}],
                mode="review",
                mock=True,
            )
            self.assertTrue(mgr.is_running())
            self.assertEqual(snapshot.status, "queued")

            # Pause
            snap_paused = mgr.pause()
            self.assertEqual(snap_paused.status, "paused")
            self.assertFalse(mgr._pause_event.is_set())

            # Resume
            snap_resumed = mgr.resume()
            self.assertEqual(snap_resumed.status, "running")
            self.assertTrue(mgr._pause_event.is_set())

            # Cancel
            snap_cancelled = mgr.cancel()
            self.assertEqual(snap_cancelled.status, "cancelled")
            self.assertTrue(mgr._cancel_event.is_set())
            self.assertTrue(mgr._pause_event.is_set())

    def test_job_control_api_endpoints(self):
        from fastapi.testclient import TestClient
        from src.web.app import app
        from unittest.mock import patch

        client = TestClient(app)

        with patch("threading.Thread.start"):
            res_start = client.post(
                "/api/batch",
                json={
                    "mode": "review",
                    "items": [{"url": "https://www.tiktok.com/@u/video/123", "script": "test"}],
                    "mock": True,
                },
            )
            self.assertEqual(res_start.status_code, 200)

            # Pause endpoint
            res_pause = client.post("/api/job/pause")
            self.assertEqual(res_pause.status_code, 200)
            self.assertEqual(res_pause.json()["snapshot"]["status"], "paused")

            # Resume endpoint
            res_resume = client.post("/api/job/resume")
            self.assertEqual(res_resume.status_code, 200)
            self.assertEqual(res_resume.json()["snapshot"]["status"], "running")

            # Cancel endpoint
            res_cancel = client.post("/api/job/cancel")
            self.assertEqual(res_cancel.status_code, 200)
            self.assertEqual(res_cancel.json()["snapshot"]["status"], "cancelled")


class JobWebSocketSerializationTests(unittest.TestCase):
    """Chống tái phát việc Path trong snapshot làm sập WebSocket."""

    def _build_snapshot_with_paths(self):
        from pathlib import Path
        from src.web.job_manager import BatchItem, JobSnapshot

        return JobSnapshot(
            job_id="path-regression",
            created_at="2026-08-20T00:00:00+00:00",
            status="running",
            items=[
                BatchItem(
                    index=1,
                    url="https://www.tiktok.com/@u/video/123",
                    status="scripting",
                    video_path=Path("C:/work/source.mp4"),  # type: ignore[arg-type]
                    video_info={
                        "download_dir": Path("C:/work"),
                        "alternatives": [Path("C:/work/other.mp4")],
                    },
                )
            ],
        )

    def test_serialize_snapshot_converts_nested_paths(self):
        import json
        from src.web.app import _serialize_snapshot

        payload = _serialize_snapshot(self._build_snapshot_with_paths())

        self.assertEqual(payload["items"][0]["video_path"], "C:\\work\\source.mp4")
        self.assertEqual(payload["items"][0]["video_info"]["download_dir"], "C:\\work")
        self.assertEqual(
            payload["items"][0]["video_info"]["alternatives"][0],
            "C:\\work\\other.mp4",
        )
        json.dumps(payload)

    def test_job_websocket_sends_snapshot_containing_paths(self):
        from fastapi.testclient import TestClient
        from src.web.app import app, job_manager

        previous_snapshot = job_manager._snapshot
        job_manager._snapshot = self._build_snapshot_with_paths()
        try:
            with TestClient(app) as client:
                with client.websocket_connect("/api/job/ws") as websocket:
                    payload = websocket.receive_json()
                    self.assertEqual(payload["job_id"], "path-regression")
                    self.assertEqual(
                        payload["items"][0]["video_path"],
                        "C:\\work\\source.mp4",
                    )
        finally:
            job_manager._snapshot = previous_snapshot


class PipelineCallerRegressionTests(unittest.IsolatedAsyncioTestCase):
    """Kiểm tra chống tái phát lỗi keyword argument / positional arguments giữa pipeline và media_services."""

    async def test_process_one_calls_download_tiktok_video_with_keyword_args(self):
        from pathlib import Path
        from unittest.mock import AsyncMock, patch, MagicMock
        from src.pipeline import ItemState, process_one
        from src.downloader import VideoInfo
        from src.tts_generator import TTSResult

        fake_info = VideoInfo(
            url="https://www.tiktok.com/@u/video/123",
            index=1,
            product_name="Test Product",
            video_path=Path("C:/fake/video.mp4"),
            title="Test Title",
            duration=15.0,
        )

        state = ItemState(
            index=1,
            url="https://www.tiktok.com/@u/video/123",
            product_name_hint="Test Product",
            custom_script="Custom script text",
            video_shift_ratio=0.25,
            video_scale=1.08,
            style="style1",
        )

        with patch("src.pipeline.download_tiktok_video", new_callable=AsyncMock) as mock_download:
            mock_download.return_value = fake_info
            with patch("src.pipeline.synthesize_tts", new_callable=AsyncMock) as mock_tts:
                mock_tts.return_value = TTSResult(
                    provider="mock",
                    voice_id="mock-voice",
                    text="Custom script text",
                    audio_path=Path("C:/fake/audio.mp3"),
                    duration_sec=10.0,
                )
                with patch("src.pipeline.merge_video_with_tts") as mock_merge:
                    from src.video_editor import MergeResult
                    mock_merge.return_value = MergeResult(
                        video_in=Path("C:/fake/video.mp4"),
                        audio_in=Path("C:/fake/audio.mp3"),
                        video_out=Path("C:/fake/out.mp4"),
                        duration_audio=10.0,
                        duration_video_used=10.0,
                        error=None,
                    )
                    with patch("pathlib.Path.write_text"):
                        res_state = await process_one(state)

            mock_download.assert_awaited_once_with(
                "https://www.tiktok.com/@u/video/123",
                index=1,
                product_name_hint="Test Product",
            )
            self.assertEqual(res_state.status, "done")
            self.assertEqual(res_state.tts["duration"], 10.0)
            self.assertEqual(res_state.tts["provider"], "mock")


    def test_merge_result_and_montage_result_success_property(self):
        from pathlib import Path
        from src.video_editor import MergeResult
        from src.montage_editor import MontageResult

        m_ok = MergeResult(Path("in.mp4"), Path("in.mp3"), Path("out.mp4"), 1.0, 1.0, error=None)
        self.assertTrue(m_ok.success)

        m_err = MergeResult(Path("in.mp4"), Path("in.mp3"), Path("out.mp4"), 0.0, 0.0, error="FFmpeg error")
        self.assertFalse(m_err.success)

        mont_ok = MontageResult(Path("out.mp4"), Path("manifest.json"), [], 5.0, error=None)
        self.assertTrue(mont_ok.success)

        mont_err = MontageResult(Path("out.mp4"), Path("manifest.json"), [], 0.0, error="Montage error")
        self.assertFalse(mont_err.success)


class GoogleVoiceRegressionTests(unittest.TestCase):
    """Regression tests for Google voice selection - ensures Google voice never falls back to Itera.

    Addresses: "Sao dùng giọng google mà vẫn trừ credit giọng itera"
    Root cause: Frontend sent voiceId="default" or undefined, causing backend to fall back
    to Itera Adam voice. Fix: Frontend now sends "google-free" explicitly.
    """

    def test_test_render_request_accepts_google_free_voice_id(self):
        """TestRenderRequest should accept voice_id='google-free' without errors."""
        from src.web.app import TestRenderRequest
        req = TestRenderRequest(
            mode="review",
            urls=["https://tiktok.com/@user/video/123"],
            script="Test script",
            voice_id="google-free",
        )
        self.assertEqual(req.voice_id, "google-free")

    def test_test_render_request_accepts_edge_free_voice_id(self):
        """TestRenderRequest should accept voice_id='edge-free' (Edge TTS free voice)."""
        from src.web.app import TestRenderRequest
        req = TestRenderRequest(
            mode="review",
            urls=["https://tiktok.com/@user/video/123"],
            script="Test script",
            voice_id="edge-free",
        )
        self.assertEqual(req.voice_id, "edge-free")

    def test_test_render_request_voice_id_defaults_to_none(self):
        """TestRenderRequest.voice_id should default to None (not a specific voice)."""
        from src.web.app import TestRenderRequest
        req = TestRenderRequest(
            mode="review",
            urls=["https://tiktok.com/@user/video/123"],
            script="Test script",
        )
        self.assertIsNone(req.voice_id)

    def test_is_free_voice_id_google_free(self):
        """is_free_voice_id should return True for google-free."""
        from src.tts_generator import is_free_voice_id
        self.assertTrue(is_free_voice_id("google-free"))

    def test_is_free_voice_id_edge_free(self):
        """is_free_voice_id should return True for edge-free."""
        from src.tts_generator import is_free_voice_id
        self.assertTrue(is_free_voice_id("edge-free"))

    def test_is_free_voice_id_itera(self):
        """is_free_voice_id should return False for itera voices."""
        from src.tts_generator import is_free_voice_id
        self.assertFalse(is_free_voice_id("itera-102-voice-id"))
        self.assertFalse(is_free_voice_id("adam"))

    def test_is_free_voice_id_google_vi_standard(self):
        """is_free_voice_id should return True for google-vi-standard."""
        from src.tts_generator import is_free_voice_id
        self.assertTrue(is_free_voice_id("google-vi-standard"))
        self.assertTrue(is_free_voice_id("google-tts"))
        self.assertTrue(is_free_voice_id("gtts"))
        self.assertTrue(is_free_voice_id("free-google"))

    def test_batch_item_request_with_google_free_voice_id(self):
        """BatchItemRequest should accept voice_id='google-free' in item dict."""
        from src.web.app import BatchItemRequest
        item = BatchItemRequest(
            url="https://tiktok.com/@user/video/123",
            voice_id="google-free",
        )
        self.assertEqual(item.voice_id, "google-free")

    def test_batch_request_with_default_voice_id_google_free(self):
        """BatchRequest with default_voice_id='google-free' should propagate correctly."""
        from src.web.app import BatchRequest
        req = BatchRequest(
            items=[
                {"url": "https://tiktok.com/@user/video/123", "voice_id": "google-free"},
            ],
            default_voice_id="google-free",
        )
        # default_voice_id is stored at the BatchRequest level
        self.assertEqual(req.default_voice_id, "google-free")



class ProfileAiVideoMaxVideosRegressionTests(unittest.TestCase):
    """Regression tests for ProfileAiVideoRequest max_videos quota logic.

    Ensures that the max_videos field is correctly accepted and propagated
    for limiting the number of runnable videos in profile AI video jobs.
    """

    def test_profile_ai_video_request_accepts_max_videos(self):
        """ProfileAiVideoRequest should accept max_videos parameter without errors."""
        from src.web.app import ProfileAiVideoRequest
        req = ProfileAiVideoRequest(
            profile_url="@test_user",
            max_videos=10,
        )
        self.assertEqual(req.max_videos, 10)

    def test_profile_ai_video_request_max_videos_zero_means_unlimited(self):
        """max_videos=0 should be accepted (means unlimited, not an error)."""
        from src.web.app import ProfileAiVideoRequest
        req = ProfileAiVideoRequest(
            profile_url="@test_user",
            max_videos=0,
        )
        self.assertEqual(req.max_videos, 0)

    def test_profile_ai_video_request_max_videos_none_by_default(self):
        """max_videos should default to None when not specified."""
        from src.web.app import ProfileAiVideoRequest
        req = ProfileAiVideoRequest(profile_url="@test_user")
        self.assertIsNone(req.max_videos)

    def test_profile_ai_video_request_max_videos_large_value(self):
        """ProfileAiVideoRequest should accept large max_videos values (e.g., 500)."""
        from src.web.app import ProfileAiVideoRequest
        req = ProfileAiVideoRequest(
            profile_url="@test_user",
            max_videos=500,
        )
        self.assertEqual(req.max_videos, 500)

    def test_profile_ai_video_request_max_videos_with_all_params(self):
        """max_videos works alongside other parameters like voice_id and style."""
        from src.web.app import ProfileAiVideoRequest
        req = ProfileAiVideoRequest(
            profile_url="@test_user",
            max_videos=25,
            voice_id="google-free",
            style="style2",
            video_shift_ratio=0.3,
            video_scale=1.1,
        )
        self.assertEqual(req.max_videos, 25)
        self.assertEqual(req.voice_id, "google-free")
        self.assertEqual(req.style, "style2")
        self.assertEqual(req.video_shift_ratio, 0.3)
        self.assertEqual(req.video_scale, 1.1)

    def test_profile_ai_video_request_max_videos_negative_rejected(self):
        """Negative max_videos should be rejected by Pydantic validation."""
        from src.web.app import ProfileAiVideoRequest
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            ProfileAiVideoRequest(
                profile_url="@test_user",
                max_videos=-5,
            )


if __name__ == "__main__":
    unittest.main()
