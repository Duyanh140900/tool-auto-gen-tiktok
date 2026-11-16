"""
video_editor.py - Merge voice audio into the downloaded video.

Strategy:
  - Voice duration = V
  - Source video duration = S
  - If V > S: loop the video until it covers V (or trim voice to S).
  - If V <= S: trim the video to V, attach the voice.
  - Audio from source video is REPLACED (typical for TikTok review style).

We use FFmpeg directly via subprocess (more reliable than MoviePy for this).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger

from src.media_utils import ffmpeg_path, has_video_stream, probe_duration, run_media_command


@dataclass
class MergeResult:
    video_in: Path
    audio_in: Path
    video_out: Path
    duration_audio: float
    duration_video_used: float
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


async def merge_voice_into_video(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    *,
    replace_audio: bool = True,
    bitrate: str = "192k",
    quality: str = "high",
    script_text: Optional[str] = None,
    video_shift_ratio: float = 0.3333,
    style: str = "style1",
    video_scale: float = 1.08,
) -> MergeResult:
    """
    Merge voice audio into the source video with lower half background & logo layout.

    Args:
        video_path: Source TikTok video (no watermark)
        audio_path: Generated voice audio (mp3/wav)
        output_path: Where to write the final video
        replace_audio: If True, strip source video's audio track; if False, mix.
        bitrate: Audio bitrate (e.g. "192k")
        quality: "high" | "medium" | "low" — controls CRF / preset
        script_text: Text script for lower half display
        style: "style1" (red-bg + logo + nhay) or "style2" (green-bg + logo, no nhay)
    """
    from src.layout_editor import (
        DEFAULT_VIDEO_SCALE,
        DEFAULT_VIDEO_SHIFT_RATIO,
        build_complex_filter_graph,
        compute_video_geometry,
        get_public_assets,
        StyleName,
    )

    style_name: StyleName = style if style in ("style1", "style2", "style3") else "style1"
    video_path = Path(video_path)
    audio_path = Path(audio_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not video_path.exists():
        return MergeResult(
            video_in=video_path, audio_in=audio_path, video_out=output_path,
            duration_audio=0, duration_video_used=0,
            error=f"video not found: {video_path}",
        )
    if not audio_path.exists():
        return MergeResult(
            video_in=video_path, audio_in=audio_path, video_out=output_path,
            duration_audio=0, duration_video_used=0,
            error=f"audio not found: {audio_path}",
        )

    duration_audio = probe_duration(audio_path, timeout=15)

    # Critical: TikTok no-watermark endpoint sometimes returns audio-only files.
    # Detect and fail with a clear message rather than cryptic ffmpeg stream errors.
    if not has_video_stream(video_path, timeout=15):
        return MergeResult(
            video_in=video_path, audio_in=audio_path, video_out=output_path,
            duration_audio=duration_audio, duration_video_used=0,
            error=(
                f"video file has no video stream (TikTok no-watermark fallback returned audio-only). "
                f"Try: (1) the original watermarked URL, (2) different yt-dlp extractor, "
                f"or (3) re-download with format='best'."
            ),
        )

    duration_video = probe_duration(video_path, timeout=15)

    # Speed-fit strategy: scale the video's playback speed so its duration
    # exactly matches the audio. setpts=PTS/SPEED where SPEED = video_dur / audio_dur.
    # - SPEED > 1  → video is shorter than audio → speed up (play faster)
    # - SPEED < 1  → video is longer than audio → slow down (play slower)
    # Cap at 4.0x max and 0.25x min so the result stays watchable. Beyond those
    # limits, we fall back to a small amount of looping + the remaining speed.
    target_speed = duration_video / duration_audio
    if target_speed > 4.0:
        # Loop once, then slow down the remaining portion so the total
        # plays back at a sensible rate. video_dur * 2 = total raw length;
        # we need it to fit into audio_dur, so remaining_speed = 2*video_dur/audio_dur.
        loop_count = 1
        inner_speed = target_speed / (loop_count + 1)  # speed per copy
    elif target_speed < 0.25:
        # Video is way longer than the voice — loop twice, then speed up the
        # remaining tail.
        loop_count = 2
        inner_speed = target_speed / (loop_count + 1)
    else:
        loop_count = 0
        inner_speed = target_speed

    quality_map = {
        "high": ("18", "slow"),
        "medium": ("23", "medium"),
        "low": ("28", "veryfast"),
    }
    crf, preset = quality_map.get(quality, quality_map["high"])

    assets = get_public_assets(style=style_name)

    # Build ffmpeg command (use bundled or system ffmpeg)
    cmd = [ffmpeg_path(), "-y", "-loglevel", "error"]

    # Input 0: video (optionally looped N times, then speed-scaled)
    if loop_count > 0:
        cmd += ["-stream_loop", str(loop_count), "-i", str(video_path)]
    else:
        cmd += ["-i", str(video_path)]

    # Input 1: black-bg
    cmd += ["-i", str(assets.black_bg)]
    # Input 2: card_bg (red-bg for style1, green-bg for style2)
    cmd += ["-i", str(assets.card_bg)]
    # Input 3: logo
    cmd += ["-i", str(assets.logo)]
    # Input 4: nhay (only for style1)
    # For style2, audio will be at index 4 instead of 5
    if style_name == "style1":
        cmd += ["-i", str(assets.nhay)]
        nhay_idx = 4
        audio_idx = 5
    else:
        nhay_idx = None
        audio_idx = 4

    # Input audio
    cmd += ["-i", str(audio_path)]

    filter_graph, _ = build_complex_filter_graph(
        text=script_text or "",
        assets=assets,
        video_input_idx=0,
        black_bg_idx=1,
        card_bg_idx=2,
        logo_idx=3,
        nhay_idx=nhay_idx,
        video_shift_ratio=video_shift_ratio,
        video_scale=video_scale,
    )

    # Insert video setpts into stream 0 if needed
    if abs(inner_speed - 1.0) > 0.001:
        zoomed_w, zoomed_h, _, _ = compute_video_geometry(video_scale, video_shift_ratio)
        speed_str = f"{inner_speed:.6f}"
        video_prep = (
            f"[0:v]setpts=PTS/{speed_str},"
            f"scale={zoomed_w}:{zoomed_h}"
            f":force_original_aspect_ratio=increase,"
            f"setsar=1,fps=30[zoomed_v];"
        )
        # Preserve the shared zoomed overlay while inserting setpts.
        filter_graph = filter_graph.replace(
            f"[0:v]scale={zoomed_w}:{zoomed_h}"
            ":force_original_aspect_ratio=increase,"
            "setsar=1,fps=30[zoomed_v];",
            video_prep,
        )

    cmd += [
        "-filter_complex", filter_graph,
        "-map", "[outv]",
        "-map", f"{audio_idx}:a:0",
        "-c:v", "libx264",
        "-crf", crf,
        "-preset", preset,
        "-c:a", "aac",
        "-b:a", bitrate,
        "-t", f"{duration_audio:.3f}",
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]

    logger.info(f"FFmpeg merge: video={video_path.name} ({duration_video:.1f}s) -> "
                f"audio={audio_path.name} ({duration_audio:.1f}s), "
                f"speed_fit={target_speed:.3f}x (loop={loop_count}, inner={inner_speed:.3f}x)")

    try:
        await run_media_command(cmd, label="ffmpeg merge")
    except RuntimeError as exc:
        return MergeResult(
            video_in=video_path, audio_in=audio_path, video_out=output_path,
            duration_audio=duration_audio, duration_video_used=duration_audio,
            error=str(exc),
        )

    return MergeResult(
        video_in=video_path, audio_in=audio_path, video_out=output_path,
        duration_audio=duration_audio, duration_video_used=duration_audio,
    )


async def generate_thumbnail(video_path: Path, output_path: Path, time_sec: float = 0.5) -> Path:
    """Extract a thumbnail from the video at the given time."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_path(), "-y", "-loglevel", "error",
        "-ss", str(time_sec),
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    await proc.communicate()
    return output_path
