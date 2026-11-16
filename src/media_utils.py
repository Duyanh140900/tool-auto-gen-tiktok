"""Reusable media helpers for ffprobe/ffmpeg based workflows."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Sequence

from src.downloader import get_ffmpeg_path, get_ffprobe_path


def ffmpeg_path() -> str:
    """Return bundled/system FFmpeg executable path."""
    return get_ffmpeg_path()


def ffprobe_path() -> str:
    """Return bundled/system ffprobe executable path."""
    return get_ffprobe_path()


def probe_duration(path: Path, *, timeout: int = 20) -> float:
    """Probe media duration in seconds with a normalized error message."""
    result = subprocess.run(
        [
            ffprobe_path(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr.strip()[-500:]}")
    return float(json.loads(result.stdout)["format"]["duration"])


def has_video_stream(path: Path, *, timeout: int = 20) -> bool:
    """Return whether a media file contains at least one video stream."""
    result = subprocess.run(
        [
            ffprobe_path(),
            "-v",
            "error",
            "-select_streams",
            "v",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return bool(result.stdout.strip())


async def run_media_command(cmd: Sequence[str], *, label: str, tail: int = 500) -> None:
    """Run an async FFmpeg-style command and raise a compact diagnostic on failure."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"{label} failed: {stderr.decode(errors='ignore')[-tail:]}")


__all__ = ["ffmpeg_path", "ffprobe_path", "has_video_stream", "probe_duration", "run_media_command"]
