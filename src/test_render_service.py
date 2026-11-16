"""Test render preview service without calling TTS APIs."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from loguru import logger
from config import settings
from src.downloader import sanitize_filename
from src.media_services import download_tiktok_video, plan_montage_clips, render_montage_video
from src.media_utils import ffmpeg_path, probe_duration, run_media_command
from src.montage_editor import ClipPlan
from src.video_editor import merge_voice_into_video


@dataclass
class TestRenderState:
    mode: str  # "review" or "montage"
    video_url: str  # Single URL for review or line-separated / primary URL
    urls: List[str]
    script: str
    duration_sec: float = 10.0
    video_shift_ratio: float = 0.3333
    status: str = "pending"
    message: str = "Đang chờ thử nghiệm render"
    error: Optional[str] = None
    final_video_path: Optional[str] = None


async def generate_silent_audio(output_path: Path, duration_sec: float = 10.0) -> Path:
    """Generate a silent AAC audio track using FFmpeg without calling TTS."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = ffmpeg_path()
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r=44100:cl=stereo",
        "-t",
        f"{duration_sec:.2f}",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(output_path),
    ]
    await run_media_command(cmd, label="ffmpeg silent audio")
    return output_path


async def run_test_render(
    mode: str,
    urls: List[str],
    script: str,
    duration_sec: float = 10.0,
    video_shift_ratio: float = 0.3333,
    style: str = "style1",
) -> TestRenderState:
    """Run test render pipeline locally without consuming TTS credits."""
    clean_urls = [u.strip() for u in urls if u and u.strip()]
    clean_script = (script or "NỘI DUNG SCRIPT THỬ NGHIỆM RENDER LAYOUT 9:16 KHÔNG DÙNG TTS").strip()

    if not clean_urls:
        raise ValueError("Cần ít nhất 1 URL TikTok để thử render.")

    timestamp = int(time.time())
    safe_job = f"test_{mode}_{timestamp}"
    work_dir = settings.OUTPUT_DIR / "test_render" / safe_job
    work_dir.mkdir(parents=True, exist_ok=True)

    silent_audio_path = work_dir / "silent_voice.m4a"
    await generate_silent_audio(silent_audio_path, duration_sec=duration_sec)

    final_dir = settings.FINAL_OUTPUT_DIR
    final_dir.mkdir(parents=True, exist_ok=True)
    output_path = final_dir / f"{safe_job}.mp4"

    if mode == "montage":
        if len(clean_urls) < 2:
            raise ValueError("Chế độ montage cần ít nhất 2 URL TikTok.")

        downloaded: List[Path] = []
        for idx, url in enumerate(clean_urls, start=1):
            info = await download_tiktok_video(url, index=idx, product_name_hint=f"test_montage_{idx}")
            downloaded.append(info.video_path)

        clips: List[ClipPlan] = plan_montage_clips(
            downloaded,
            target_duration=duration_sec,
            seed=timestamp,
        )

        result = await render_montage_video(
            clips=clips,
            audio_path=silent_audio_path,
            output_path=output_path,
            work_dir=work_dir,
            seed=timestamp,
            audio_duration=duration_sec,
            script_text=clean_script,
            video_shift_ratio=video_shift_ratio,
            style=style,
        )
        final_video_path = str(result.output_path)
    else:
        # Review mode single video test
        info = await download_tiktok_video(clean_urls[0], index=1, product_name_hint="test_review")
        merge_res = await merge_voice_into_video(
            info.video_path,
            silent_audio_path,
            output_path,
            bitrate=settings.AUDIO_BITRATE,
            quality=settings.VIDEO_QUALITY,
            script_text=clean_script,
            video_shift_ratio=video_shift_ratio,
            style=style,
        )
        if merge_res.error:
            raise RuntimeError(merge_res.error)
        final_video_path = str(merge_res.video_out)

    return TestRenderState(
        mode=mode,
        video_url=clean_urls[0],
        urls=clean_urls,
        script=clean_script,
        duration_sec=duration_sec,
        video_shift_ratio=video_shift_ratio,
        status="done",
        message="Đã render thử nghiệm bố cục thành công (không tốn credit TTS)",
        final_video_path=final_video_path,
    )
