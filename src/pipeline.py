"""
pipeline.py - Orchestrate the full workflow for one or many products.

Workflow per item:
  1. Download TikTok video (no watermark)
  2. Generate review script via LLM (with template fallback)
  3. Synthesize voice audio via LucyAI / Edge TTS
  4. Merge voice into video via FFmpeg (standalone MP4 fallback)
  5. Edit the CapCut template project with new video + audio + text
  6. Open the new project in CapCut and trigger export

Each step's result is persisted to JSON so the GUI / pipeline can be
resumed after a failure without redoing completed work.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from loguru import logger

from config import settings
from src import script_generator
from src.capcut_editor import (
    edit_template, find_template_project, open_project_in_capcut,
    reopen_project_fresh, trigger_export, CapCutEditResult,
)
from src.downloader import sanitize_filename
from src.media_services import download_tiktok_video, merge_video_with_tts, synthesize_tts
from src.media_utils import probe_duration
from src.tts_generator import TTSCreditExhaustedError


def build_output_video_filename(caption: Optional[str], hashtags: Optional[List[str]], default_name: str) -> str:
    """
    Build a clean filename combining Caption and Hashtags for TikTok upload auto-captioning.
    Example: 'Meo_tiet_kiem_cuc_dinh_cho_anh_em_#hopgotietkiem_#tietkiemtien.mp4'
    """
    cap = (caption or "").strip()
    tags = [t.strip() for t in (hashtags or []) if t and t.strip()]
    
    parts = []
    if cap:
        parts.append(cap)
    if tags:
        parts.append(" ".join(tags))
        
    combined = " ".join(parts).strip()
    if not combined:
        return f"{default_name}.mp4"

    # Sanitize for filesystem while keeping hashtags readable
    safe_str = sanitize_filename(combined, max_length=120)
    # Remove chars not allowed in filenames: <>:"/\|?*
    cleaned = re.sub(r'[<>:"/\\|?*]', '', combined)
    cleaned = re.sub(r'[\r\n\t]+', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if len(cleaned) > 120:
        cleaned = cleaned[:120].rstrip()
    
    return f"{cleaned}.mp4" if cleaned else f"{default_name}.mp4"


@dataclass
class ItemState:
    """Pipeline state for one product."""
    index: int
    url: str
    product_name_hint: Optional[str] = None
    custom_script: Optional[str] = None     # User-supplied script for TTS audio; bypasses LLM
    overlay_text: Optional[str] = None     # Separate text displayed on video overlay
    video_shift_ratio: float = 0.3333
    video_scale: float = 1.08
    tts_voice_id: Optional[str] = None       # Per-item voice override; falls back to job-level default
    style: str = "style1"                    # "style1" (red-bg + logo + nhay) or "style2" (green-bg + logo, no nhay)
    script_theme: Optional[str] = None       # Chủ đề kịch bản (vd ngày lễ); None = AI tự chọn

    # Stage results
    video_info: Optional[dict] = None
    script: Optional[dict] = None
    tts: Optional[dict] = None
    merge: Optional[dict] = None
    capcut: Optional[dict] = None

    # Final status
    status: str = "pending"      # pending | downloading | scripting | tts | merging | done | error
    error: Optional[str] = None

    # Output paths (filled in as we go)
    video_path: Optional[str] = None
    script_path: Optional[str] = None
    audio_path: Optional[str] = None
    final_video_path: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        # Convert Path objects to strings if any sneaked in
        for k, v in d.items():
            if isinstance(v, Path):
                d[k] = str(v)
        return d


ProgressCallback = Callable[[ItemState], None]


async def process_one(
    state: ItemState,
    on_progress: Optional[ProgressCallback] = None,
    *,
    tts_voice_id: Optional[str] = None,
    tts_speed: Optional[float] = None,
    style: Optional[str] = None,
) -> ItemState:
    """Run the full pipeline for a single item. Updates state in-place.

    Args:
        state: Trạng thái của item đang xử lý.
        on_progress: Callback được gọi sau mỗi bước (downloading, scripting, tts, merging...).
        tts_voice_id: Voice id (vd. ``5r2MVjMtzwsSDz1paLjbiY9``) cho itera102. Nếu
            ``None`` sẽ dùng ``ITERA102_VOICE_ID`` trong env.
        tts_speed: Override tốc độ đọc; ``None`` lấy giá trị từ env.
    """
    idx = state.index
    logger.info(f"[{idx}] === Starting processing for {state.url} ===")
    state.status = "downloading"
    if on_progress:
        on_progress(state)

    try:
        # Step 1: Download TikTok video
        video_result = await download_tiktok_video(
            state.url,
            index=idx,
            product_name_hint=state.product_name_hint,
        )
        if video_result.error:
            raise RuntimeError(f"download failed: {video_result.error}")
        state.video_path = str(video_result.video_path)
        hashtags = getattr(video_result, "hashtags", None) or []
        caption = getattr(video_result, "caption", None) or ""
        state.video_info = {
            "title": video_result.title,
            "duration": video_result.duration,
            "caption": caption,
            "hashtags": hashtags,
        }

        # Step 2: Generate review script with multimodal vision + metadata analysis
        state.status = "scripting"
        if on_progress:
            on_progress(state)

        # Ưu tiên custom_script từ FE (giao diện batch đã cho nhập script riêng)
        if state.custom_script and state.custom_script.strip():
            script_data = {
                "product_name": (state.product_name_hint or "").strip() or "Sản phẩm",
                "caption": caption,
                "hashtags": hashtags,
                "body": state.custom_script.strip(),
                "call_to_action": "",
                "tiktok_script": state.custom_script.strip(),
            }
            full_script = state.custom_script.strip()
            logger.info(f"[{idx}] Using custom_script from request (length={len(state.custom_script)})")
        else:
            script_obj = await script_generator.generate_script_from_tiktok_meta(
                title=video_result.title or "",
                description=caption,
                caption=caption,
                hashtags=hashtags,
                product_hint=state.product_name_hint,
                video_path=video_result.video_path,
                theme=state.script_theme,
            )
            script_data = {
                "product_name": script_obj.product_name,
                "caption": script_obj.caption,
                "hashtags": script_obj.hashtags,
                "tiktok_script": script_obj.tiktok_script,
                "body": script_obj.tiktok_script,
                "overlay_banner_title": script_obj.overlay_banner_title,
                "style3_headline": script_obj.style3_headline,
                "style3_quote": script_obj.style3_quote,
            }
            full_script = script_obj.tiktok_script or script_obj.caption or script_obj.product_name
        state.script = script_data

        # Save script JSON
        script_out = settings.OUTPUT_DIR / f"{idx:03d}_script.json"
        script_out.write_text(json.dumps(script_data, ensure_ascii=False, indent=2), encoding="utf-8")
        state.script_path = str(script_out)

        # Step 3: Synthesize voice
        state.status = "tts"
        if on_progress:
            on_progress(state)

        audio_out = settings.OUTPUT_DIR / f"{idx:03d}_voice.mp3"
        # Ưu tiên voice_id từ request/FE, fallback env
        resolved_voice_id = tts_voice_id or state.tts_voice_id
        tts_result = await synthesize_tts(
            full_script,
            audio_out,
            voice_id=resolved_voice_id,
            speed=tts_speed,
        )
        if tts_result.error:
            raise RuntimeError(f"TTS failed: {tts_result.error}")
        state.audio_path = str(tts_result.audio_path)
        state.tts = {
            "duration": tts_result.duration_sec,
            "provider": tts_result.provider,
            "voice_id": resolved_voice_id or tts_result.voice_id,
        }

        # Step 4: Merge video + voice using Layout Editor & FFmpeg overlay
        state.status = "merging"
        if on_progress:
            on_progress(state)

        resolved_style = style or state.style or "style1"
        final_video_name = build_output_video_filename(
            caption=script_data.get("caption"),
            hashtags=script_data.get("hashtags"),
            default_name=f"{idx:03d}_{sanitize_filename(script_data['product_name'])}",
        )
        final_mp4 = settings.FINAL_OUTPUT_DIR / final_video_name
        settings.FINAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        merge_res = await merge_video_with_tts(
            Path(state.video_path),
            Path(state.audio_path),
            final_mp4,
            bitrate=settings.AUDIO_BITRATE,
            quality=settings.VIDEO_QUALITY,
            script_text=state.overlay_text or script_data.get("overlay_banner_title") or script_data.get("product_name"),
            video_shift_ratio=state.video_shift_ratio,
            style=resolved_style,
            video_scale=state.video_scale,
        )
        if merge_res.error:
            raise RuntimeError(f"FFmpeg render error: {merge_res.error}")

        state.merge = {
            "success": merge_res.success,
            "output": str(merge_res.video_out),
            "duration": merge_res.duration_video_used,
        }
        state.final_video_path = str(final_mp4)

        # Step 5 & 6: CapCut template editing and export (macOS only)
        try:
            capcut_project_dir = find_template_project(settings.CAPCUT_TEMPLATE_NAME)
        except Exception:
            capcut_project_dir = None
        if capcut_project_dir:
            logger.info(f"[{idx}] Found CapCut project: {capcut_project_dir}")
            state.status = "capcut"
            if on_progress:
                on_progress(state)

            edit_res = edit_template(
                template_dir=capcut_project_dir,
                new_video_path=Path(state.video_path),
                new_audio_path=Path(state.audio_path),
                product_name=script_data["product_name"],
                video_duration_sec=merge_res.duration_video_used,
                audio_duration_sec=tts_result.duration_sec,
            )
            state.capcut = asdict(edit_res)

            if edit_res.success and settings.AUTO_OPEN_CAPCUT:
                reopen_project_fresh(capcut_project_dir)
                trigger_export(settings.OUTPUT_DIR)
        else:
            logger.info(
                f"[{idx}] CapCut template '{settings.CAPCUT_TEMPLATE_NAME}' not found. "
                "Skipping CapCut step (final video created via FFmpeg)."
            )

        state.status = "done"
        logger.info(f"[{idx}] === Finished successfully -> {state.final_video_path} ===")

    except TTSCreditExhaustedError as e:
        state.status = "error"
        state.error = f"TTS credit exhausted: {e}"
        logger.critical(f"[{idx}] ⛔ CRITICAL TTS ERROR: {e}. Aborting pipeline.")
        raise
    except Exception as e:
        state.status = "error"
        state.error = str(e)
        logger.error(f"[{idx}] Pipeline failed: {e}")
    finally:
        if on_progress:
            on_progress(state)

    return state


async def process_batch(
    items: List[ItemState],
    on_progress: Optional[ProgressCallback] = None,
    max_concurrent: Optional[int] = None,
    *,
    tts_voice_id: Optional[str] = None,
    tts_speed: Optional[float] = None,
    style: Optional[str] = None,
    check_control: Optional[Callable[[], bool]] = None,
) -> List[ItemState]:
    """Run pipeline for all items in batch.

    Args:
        items: Danh sách ItemState cần xử lý.
        on_progress: Callback cập nhật tiến độ UI.
        max_concurrent: Số luồng xử lý đồng thời (mặc định từ config).
        tts_voice_id: Voice id cho itera102 (dùng cho toàn batch nếu item không override).
        tts_speed: Tốc độ đọc voice (dùng cho toàn batch).
        style: Layout overlay ("style1", "style2", "style3").
        check_control: Callback kiểm tra pause/cancel. Trả về True nếu được tiếp tục, False nếu cancel.
    """
    settings.ensure_dirs()
    limit = max_concurrent or settings.MAX_CONCURRENT

    if limit <= 1:
        # Sequential processing (safe default for CapCut GUI automation)
        for item in items:
            if check_control and not check_control():
                logger.info("Batch cancelled by control check.")
                break
            await process_one(
                item,
                on_progress,
                tts_voice_id=tts_voice_id,
                tts_speed=tts_speed,
                style=style,
            )
            if item.error:
                logger.error(f"Item #{item.index} failed with error: {item.error}. Aborting entire batch.")
                break
    else:
        # Concurrent processing with semaphore
        semaphore = asyncio.Semaphore(limit)
        abort_event = asyncio.Event()

        async def _worker(worker_id: int):
            for item in items:
                if abort_event.is_set():
                    break
                if check_control and not check_control():
                    abort_event.set()
                    break

                async with semaphore:
                    if abort_event.is_set():
                        break
                    try:
                        await process_one(
                            item,
                            on_progress,
                            tts_voice_id=tts_voice_id,
                            tts_speed=tts_speed,
                            style=style,
                        )
                        if item.error:
                            logger.error(f"Item #{item.index} failed with error: {item.error}. Aborting entire batch.")
                            abort_event.set()
                            break
                    except Exception as exc:
                        logger.error(f"Item #{item.index} raised uncaught exception: {exc}. Aborting entire batch.")
                        abort_event.set()
                        break

        workers = [_worker(i) for i in range(limit)]
        await asyncio.gather(*workers)

    return items
