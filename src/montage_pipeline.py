"""Pipeline riêng cho tab xào video TikTok."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from loguru import logger

from config import settings
from src.downloader import sanitize_filename
from src.media_services import download_tiktok_video, plan_montage_clips, render_montage_video, synthesize_tts
from src.media_utils import has_video_stream, probe_duration
from src.montage_editor import ClipPlan


@dataclass
class MontageState:
    urls: List[str]
    script: str
    job_id: str
    voice_id: Optional[str] = None
    seed: Optional[int] = None
    video_shift_ratio: float = 0.3333
    style: str = "style1"  # "style1" (red-bg + logo + nhay) or "style2" (green-bg + logo, no nhay)
    status: str = "pending"
    message: str = "Đang chờ xử lý"
    error: Optional[str] = None
    downloaded_paths: List[str] = field(default_factory=list)
    audio_path: Optional[str] = None
    final_video_path: Optional[str] = None
    manifest_path: Optional[str] = None
    audio_duration: Optional[float] = None
    clips: List[dict] = field(default_factory=list)


ProgressCallback = Callable[[MontageState], None]


def validate_montage_inputs(urls: List[str], script: str) -> tuple[List[str], str]:
    clean_urls = [url.strip() for url in urls if url and url.strip()]
    clean_script = (script or "").strip()
    if len(clean_urls) < 2:
        raise ValueError("Cần ít nhất 2 URL TikTok để xào video.")
    if not clean_script:
        raise ValueError("Script TTS là bắt buộc trong MVP xào video.")
    return clean_urls, clean_script


async def process_montage(
    state: MontageState,
    on_progress: Optional[ProgressCallback] = None,
) -> MontageState:
    def publish(status: str, message: str) -> None:
        state.status = status
        state.message = message
        if on_progress:
            on_progress(state)

    try:
        state.urls, state.script = validate_montage_inputs(state.urls, state.script)
        if state.seed is None:
            state.seed = int(time.time())

        safe_job = sanitize_filename(state.job_id, max_length=36)
        work_dir = settings.OUTPUT_DIR / "montage" / safe_job
        work_dir.mkdir(parents=True, exist_ok=True)

        publish("downloading", f"Đang tải {len(state.urls)} video nguồn")
        downloaded: List[Path] = []
        for idx, url in enumerate(state.urls, start=1):
            info = await download_tiktok_video(
                url,
                index=idx,
                product_name_hint=f"montage_{safe_job}_{idx:02d}",
            )
            if not has_video_stream(info.video_path):
                raise RuntimeError(f"URL #{idx} không có video stream hợp lệ.")
            downloaded.append(info.video_path)
            state.downloaded_paths = [str(path) for path in downloaded]
            publish("downloading", f"Đã tải {idx}/{len(state.urls)} video")

        publish("tts", "Đang tạo một file TTS cho toàn bộ script")
        audio_path = work_dir / "voice_montage.m4a"
        tts_result = await synthesize_tts(
            state.script,
            audio_path,
            voice_id=state.voice_id,
        )
        state.audio_path = str(tts_result.audio_path)
        state.audio_duration = probe_duration(audio_path)

        publish("planning", "Đang lập kế hoạch cắt ghép 2–4 giây theo thứ tự link")
        clips: List[ClipPlan] = plan_montage_clips(
            downloaded,
            target_duration=state.audio_duration,
            seed=state.seed,
        )
        state.clips = [asdict(clip) for clip in clips]
        (work_dir / "script.txt").write_text(state.script, encoding="utf-8")
        (work_dir / "plan.json").write_text(
            json.dumps({"seed": state.seed, "clips": state.clips}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        publish("rendering", f"Đang render {len(clips)} đoạn thành video 9:16")
        final_dir = settings.FINAL_OUTPUT_DIR
        final_dir.mkdir(parents=True, exist_ok=True)
        output_path = final_dir / f"montage_{safe_job}.mp4"
        result = await render_montage_video(
            clips=clips,
            audio_path=audio_path,
            output_path=output_path,
            work_dir=work_dir,
            seed=state.seed,
            audio_duration=state.audio_duration,
            script_text=state.script,
            video_shift_ratio=state.video_shift_ratio,
            style=state.style,
        )
        state.final_video_path = str(result.output_path)
        state.manifest_path = str(result.manifest_path)
        state.status = "done"
        state.message = "Đã xuất video xào hoàn chỉnh"
    except Exception as exc:
        state.status = "error"
        state.error = str(exc)
        state.message = str(exc)
        logger.exception("montage pipeline failed")

    if on_progress:
        on_progress(state)
    return state


__all__ = ["MontageState", "process_montage", "validate_montage_inputs"]
