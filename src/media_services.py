"""Domain services reused by review and montage pipelines."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Optional

from src import downloader, tts_generator
from src.downloader import VideoInfo
from src.tts_generator import TTSResult

if TYPE_CHECKING:
    from src.montage_editor import ClipPlan, MontageResult
    from src.video_editor import MergeResult


async def download_tiktok_video(
    url: str,
    *,
    index: int,
    product_name_hint: Optional[str] = None,
) -> VideoInfo:
    """Download one TikTok source and raise a workflow-friendly error if it fails."""
    info = await downloader.download_one(
        url,
        index=index,
        product_name_hint=product_name_hint,
    )
    if info.error:
        raise RuntimeError(info.error)
    return info


async def synthesize_tts(
    text: str,
    audio_path: Path,
    *,
    voice_id: Optional[str] = None,
    speed: Optional[float] = None,
) -> TTSResult:
    """Create a TTS audio file through the active TTS provider."""
    return await tts_generator.synthesize(text, audio_path, voice_id=voice_id, speed=speed)


async def merge_video_with_tts(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    *,
    bitrate: str,
    quality: str,
    script_text: Optional[str] = None,
    video_shift_ratio: float = 0.3333,
    style: str = "style1",
    video_scale: float = 1.08,
) -> "MergeResult":
    """Attach TTS audio to a source video and return the FFmpeg merge result."""
    from src.video_editor import merge_voice_into_video

    return await merge_voice_into_video(
        video_path,
        audio_path,
        output_path,
        bitrate=bitrate,
        quality=quality,
        script_text=script_text,
        video_shift_ratio=video_shift_ratio,
        style=style,
        video_scale=video_scale,
    )


def plan_montage_clips(
    sources: Iterable[Path],
    *,
    target_duration: float,
    seed: int,
) -> list["ClipPlan"]:
    """Build deterministic 2–4 second montage clips."""
    from src.montage_editor import build_clip_plan

    return build_clip_plan(sources, target_duration=target_duration, seed=seed)


async def render_montage_video(
    *,
    clips: list["ClipPlan"],
    audio_path: Path,
    output_path: Path,
    work_dir: Path,
    seed: int,
    audio_duration: Optional[float] = None,
    script_text: Optional[str] = None,
    video_shift_ratio: float = 0.3333,
    style: str = "style1",
) -> "MontageResult":
    """Render planned clips and mux the generated TTS audio."""
    from src.montage_editor import render_montage

    return await render_montage(
        clips=clips,
        audio_path=audio_path,
        output_path=output_path,
        work_dir=work_dir,
        seed=seed,
        audio_duration=audio_duration,
        script_text=script_text,
        video_shift_ratio=video_shift_ratio,
        style=style,
    )


__all__ = [
    "download_tiktok_video",
    "merge_video_with_tts",
    "plan_montage_clips",
    "render_montage_video",
    "synthesize_tts",
]
