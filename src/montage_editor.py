"""FFmpeg montage helpers for the TikTok remix/xào video MVP."""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from loguru import logger

from config import settings
from src.media_utils import ffmpeg_path, has_video_stream, probe_duration, run_media_command


@dataclass
class ClipPlan:
    source_index: int
    source_path: str
    source_duration: float
    start: float
    duration: float


@dataclass
class MontageResult:
    output_path: Path
    manifest_path: Path
    clips: List[ClipPlan]
    audio_duration: float
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


def ffprobe_duration(path: Path) -> float:
    return probe_duration(path)


def build_clip_plan(
    sources: Iterable[Path],
    *,
    target_duration: float,
    seed: int,
    min_clip: float = 2.0,
    max_clip: float = 4.0,
) -> List[ClipPlan]:
    """Build deterministic random clips while preserving source order in a loop."""
    source_paths = [Path(path) for path in sources]
    if len(source_paths) < 2:
        raise ValueError("Cần tối thiểu 2 video nguồn để xào video.")
    if target_duration <= 0:
        raise ValueError("Thời lượng audio TTS phải lớn hơn 0.")

    durations = [ffprobe_duration(path) for path in source_paths]
    for path, duration in zip(source_paths, durations):
        if duration < 0.6:
            raise ValueError(f"Video quá ngắn để cắt ghép: {path} ({duration:.2f}s)")

    rng = random.Random(seed)
    clips: List[ClipPlan] = []
    total = 0.0
    cursor = 0
    while total < target_duration - 0.05:
        source_pos = cursor % len(source_paths)
        source_path = source_paths[source_pos]
        source_duration = durations[source_pos]
        remaining = target_duration - total
        desired = min(rng.uniform(min_clip, max_clip), remaining)
        clip_duration = min(desired, max(0.5, source_duration))
        max_start = max(0.0, source_duration - clip_duration - 0.05)
        start = rng.uniform(0.0, max_start) if max_start > 0 else 0.0
        clips.append(
            ClipPlan(
                source_index=source_pos + 1,
                source_path=str(source_path),
                source_duration=source_duration,
                start=round(start, 3),
                duration=round(clip_duration, 3),
            )
        )
        total += clip_duration
        cursor += 1
    return clips


async def render_montage(
    *,
    clips: List[ClipPlan],
    audio_path: Path,
    output_path: Path,
    work_dir: Path,
    seed: int,
    audio_duration: Optional[float] = None,
    script_text: Optional[str] = None,
    video_shift_ratio: float = 0.3333,
    style: str = "style1",
) -> MontageResult:
    """Render clip plan to 9:16 MP4 with lower half background & logo overlay, remove original audio and attach TTS."""
    from src.layout_editor import build_complex_filter_graph, get_public_assets, StyleName

    style_name: StyleName = style if style in ("style1", "style2", "style3") else "style1"

    if not clips:
        raise ValueError("Clip plan trống.")
    if audio_duration is None:
        audio_duration = ffprobe_duration(audio_path)

    assets = get_public_assets(style=style_name)

    work_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = work_dir / "clips"
    temp_dir.mkdir(parents=True, exist_ok=True)
    rendered_clips: List[Path] = []
    ffmpeg = ffmpeg_path()

    for idx, clip in enumerate(clips, start=1):
        rendered = temp_dir / f"clip_{idx:03d}.mp4"
        vf = (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,setsar=1,fps=30,format=yuv420p"
        )
        cmd = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{clip.start:.3f}",
            "-t",
            f"{clip.duration:.3f}",
            "-i",
            clip.source_path,
            "-an",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            str(rendered),
        ]
        logger.info("FFmpeg render clip %s/%s: %s", idx, len(clips), rendered)
        await run_media_command(cmd, label="ffmpeg render clip")
        rendered_clips.append(rendered)

    concat_file = work_dir / "concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{path.as_posix()}'" for path in rendered_clips),
        encoding="utf-8",
    )
    silent_video = work_dir / "montage_silent.mp4"
    concat_cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        str(silent_video),
    ]
    await run_media_command(concat_cmd, label="ffmpeg concat")

    # Determine nhay_idx based on style
    if style_name == "style1":
        nhay_idx = 4
        audio_idx = 5
    else:
        nhay_idx = None
        audio_idx = 4

    filter_graph, layout_meta = build_complex_filter_graph(
        text=script_text or "",
        assets=assets,
        video_input_idx=0,
        black_bg_idx=1,
        card_bg_idx=2,
        logo_idx=3,
        nhay_idx=nhay_idx,
        video_shift_ratio=video_shift_ratio,
    )

    # Build the input list and map based on style
    # Style 1: silent_video + black_bg + red_bg + logo + nhay + audio
    # Style 2: silent_video + black_bg + green_bg + logo + audio
    final_cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(silent_video),
        "-i",
        str(assets.black_bg),
        "-i",
        str(assets.card_bg),
        "-i",
        str(assets.logo),
    ]

    if style_name == "style1":
        final_cmd += ["-i", str(assets.nhay)]

    final_cmd += [
        "-i",
        str(audio_path),
        "-filter_complex",
        filter_graph,
        "-t",
        f"{audio_duration:.3f}",
        "-map",
        "[outv]",
        "-map",
        f"{audio_idx}:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20" if settings.VIDEO_QUALITY == "high" else "23",
        "-c:a",
        "aac",
        "-b:a",
        settings.AUDIO_BITRATE,
        "-shortest",
        "-movflags",
        "+faststart",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    await run_media_command(final_cmd, label="ffmpeg final mux")

    manifest_path = work_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "seed": seed,
                "audio_path": str(audio_path),
                "audio_duration": audio_duration,
                "output_path": str(output_path),
                "clips": [asdict(clip) for clip in clips],
                "layout": layout_meta,
                "assets": {
                    "black_bg": str(assets.black_bg),
                    "card_bg": str(assets.card_bg),
                    "logo": str(assets.logo),
                    "nhay": str(assets.nhay) if assets.nhay else None,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return MontageResult(
        output_path=output_path,
        manifest_path=manifest_path,
        clips=clips,
        audio_duration=audio_duration,
    )


__all__ = [
    "ClipPlan",
    "MontageResult",
    "build_clip_plan",
    "ffprobe_duration",
    "has_video_stream",
    "render_montage",
]
