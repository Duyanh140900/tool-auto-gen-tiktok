"""job_manager.py

Quản lý một job pipeline tại một thời điểm cho giao diện web localhost.

Thiết kế:
  - Một ``Job`` snapshot tương thích với type ``JobSnapshot`` ở frontend
    (``src/web/app.py``).
  - Chạy pipeline qua ``pipeline.process_batch`` trên một luồng nền; tiến độ
    được phát qua callback thread-safe tới các subscriber (FastAPI SSE).
  - Hỗ trợ 2 mode:
        * ``live``  — gọi pipeline thật, phụ thuộc internet/API thật.
        * ``mock``  — dùng callback nội bộ để mô phỏng tiến độ mà không gọi
          TTS/LLM/yt-dlp; phục vụ smoke test và phát triển UI khi chưa có key.
  - Mọi truy cập vào state được bảo vệ bằng ``threading.RLock``.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from src.pipeline import ItemState, process_batch

logger = logging.getLogger("tiktok.web.job_manager")


# ---------- Snapshot types ----------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_theme(value: Any) -> Optional[str]:
    """Chủ đề kịch bản: chuỗi rỗng/khoảng trắng -> None (AI tự chọn như cũ)."""
    text = " ".join(str(value or "").split())
    return text[:300] or None


def _clean_post_at(value: Any) -> Optional[str]:
    """Chuẩn hóa giờ đăng hẹn riêng về ISO 'YYYY-MM-DDTHH:MM'; sai định dạng -> None (dùng slot tự động)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip()).isoformat(timespec="minutes")
    except ValueError:
        return None


@dataclass
class BatchItem:
    index: int
    url: str
    product_name_hint: Optional[str] = None
    custom_script: Optional[str] = None
    overlay_text: Optional[str] = None  # Text displayed on video overlay (separate from TTS script)
    video_shift_ratio: float = 0.3333
    video_scale: float = 1.08
    tts_voice_id: Optional[str] = None  # Per-item voice override
    style: str = "style1"  # "style1" or "style2"
    script_theme: Optional[str] = None  # Chủ đề kịch bản AI (vd ngày lễ); None = AI tự chọn
    post_at: Optional[str] = None  # Giờ đăng hẹn riêng ISO 'YYYY-MM-DDTHH:MM'; None = slot tự động
    status: str = "pending"
    error: Optional[str] = None
    video_path: Optional[str] = None
    script_path: Optional[str] = None
    audio_path: Optional[str] = None
    final_video_path: Optional[str] = None
    video_info: Optional[Dict[str, Any]] = None
    script: Optional[Dict[str, Any]] = None
    tts: Optional[Dict[str, Any]] = None
    merge: Optional[Dict[str, Any]] = None
    capcut: Optional[Dict[str, Any]] = None
    showcase: Optional[Dict[str, Any]] = None  # Kết quả thêm sản phẩm vào Showcase (src.showcase)
    post: Optional[Dict[str, Any]] = None  # Kết quả đăng hẹn giờ TikTok Studio (src.tiktok_poster)

    @classmethod
    def from_state(cls, state: ItemState) -> "BatchItem":
        return cls(
            index=state.index,
            url=state.url,
            product_name_hint=state.product_name_hint,
            custom_script=state.custom_script,
            overlay_text=state.overlay_text,
            video_shift_ratio=state.video_shift_ratio,
            video_scale=getattr(state, "video_scale", 1.08),
            tts_voice_id=state.tts_voice_id,
            style=state.style,
            script_theme=getattr(state, "script_theme", None),
            status=state.status,
            error=state.error,
            video_path=state.video_path,
            script_path=state.script_path,
            audio_path=state.audio_path,
            final_video_path=state.final_video_path,
            video_info=state.video_info,
            script=state.script,
            tts=state.tts,
            merge=state.merge,
            capcut=state.capcut,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class JobSnapshot:
    job_id: str
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    status: str = "queued"  # queued | running | done | error | cancelled
    error: Optional[str] = None
    mode: str = "live"
    items: List[BatchItem] = field(default_factory=list)
    montage: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "error": self.error,
            "mode": self.mode,
            "items": [it.to_dict() for it in self.items],
            "montage": self.montage,
        }


def list_post_backlog(manifest_file: Path) -> List[BatchItem]:
    """Video đã gen (manifest done), còn file trên đĩa và chưa hẹn xong + xóa trong sổ lịch."""
    from src.post_schedule import PostSchedule
    from src.profile_crawler import ProfileManifestManager
    from src.tiktok_poster import caption_from_filename

    videos = ProfileManifestManager(manifest_file).load().get("videos", {}).values()
    schedule = PostSchedule()
    items: List[BatchItem] = []
    for video in sorted(videos, key=lambda v: v.get("created_at") or ""):
        path = video.get("final_video_path")
        if video.get("status") != "done" or not path or not Path(path).exists():
            continue
        posted = schedule.find(path)
        if posted and posted.get("status") == "scheduled" and posted.get("deleted"):
            continue
        items.append(BatchItem(
            index=len(items) + 1,
            url=video["url"],
            product_name_hint=video.get("product_name"),
            status="done",
            final_video_path=path,
            script={"caption": caption_from_filename(path)},
            showcase=video.get("showcase"),
        ))
    return items


# ---------- Job manager -------------------------------------------------------

ProgressListener = Callable[[JobSnapshot], None]


class JobManager:
    """Single-user job manager cho web UI."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshot = JobSnapshot(
            job_id=str(uuid.uuid4()),
            created_at=_now_iso(),
            status="idle",
            mode="idle",
        )
        self._listeners: List[ProgressListener] = []
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        # Tùy chọn tự thêm sản phẩm vào Showcase cho job hiện tại
        self._showcase_enabled = False
        self._showcase_dry = False
        # Tùy chọn đăng hẹn giờ TikTok Studio sau bước Showcase
        self._post_enabled = False
        self._post_dry = False
        self._post_delete_after = False
        self._post_worker: Optional[Any] = None

    # -------- Subscription --------
    def subscribe(self, listener: ProgressListener) -> None:
        with self._lock:
            self._listeners.append(listener)
            try:
                listener(self._snapshot)
            except Exception:  # pragma: no cover - listener chỉ log
                logger.exception("listener failed on subscribe")

    def unsubscribe(self, listener: ProgressListener) -> None:
        with self._lock:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

    # -------- State --------
    @property
    def current(self) -> JobSnapshot:
        with self._lock:
            return self._snapshot

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def pause(self) -> JobSnapshot:
        with self._lock:
            if not self.is_running():
                raise RuntimeError("Không có job nào đang chạy để tạm dừng.")
            self._pause_event.clear()
            self._update_status("paused")
            return self._snapshot

    def resume(self) -> JobSnapshot:
        with self._lock:
            if not self.is_running():
                raise RuntimeError("Không có job nào đang chạy để tiếp tục.")
            self._pause_event.set()
            self._update_status("running")
            return self._snapshot

    def cancel(self) -> JobSnapshot:
        with self._lock:
            self._cancel_event.set()
            self._pause_event.set()  # Unblock if currently paused
            if self._snapshot.status in ("queued", "running", "paused"):
                self._update_status("cancelled")
            return self._snapshot

    def _check_pause_and_cancel(self) -> bool:
        """Kiểm tra pause/cancel giữa các video mà không ngắt quãng render dang dở."""
        if self._cancel_event.is_set():
            return False
        while not self._pause_event.is_set():
            if self._cancel_event.is_set():
                return False
            time.sleep(0.5)
        return not self._cancel_event.is_set()

    # -------- Public API --------
    def create_batch(
        self,
        items_payload: List[Dict[str, Any]],
        *,
        max_concurrent: int = 1,
        mode: str = "live",
        default_voice_id: Optional[str] = None,
        default_style: str = "style1",
        profile_url: Optional[str] = None,
        log_file_path: Optional[str] = None,
        auto_showcase: bool = False,
        showcase_dry: bool = False,
        auto_post: bool = False,
        post_dry: bool = False,
        post_delete_after: bool = False,
        default_script_theme: Optional[str] = None,
    ) -> JobSnapshot:
        """Khởi tạo job mới, lưu snapshot, chạy nền và trả về snapshot hiện tại.

        Args:
            default_voice_id: Voice ID dùng khi item không có voice_id riêng.
            default_style: Style dùng khi item không có style riêng ("style1" hoặc "style2").
            profile_url: Link profile TikTok nếu chạy từ màn profile crawl.
            log_file_path: Đường dẫn file JSON log tùy chọn.
            auto_showcase: Gen xong mỗi video thì thêm sản phẩm của video nguồn vào Showcase.
            showcase_dry: Chạy thử Showcase, không bấm nút thêm.
            auto_post: Sau Showcase thì đăng hẹn giờ lên TikTok Studio, gắn giỏ hàng sản phẩm đó.
            post_dry: Chạy thử đăng bài, điền đủ nhưng không bấm Lên lịch.
            post_delete_after: Hẹn xong thì chuyển file video vào Thùng rác.
            default_script_theme: Chủ đề kịch bản AI dùng khi item không có script_theme riêng.
        """
        if self.is_running():
            raise RuntimeError("Một job khác đang chạy. Vui lòng đợi hoàn tất.")

        items: List[BatchItem] = []
        for idx, raw in enumerate(items_payload or [], start=1):
            ratio_raw = raw.get("video_shift_ratio", 0.3333)
            try:
                ratio = float(ratio_raw)
            except (TypeError, ValueError):
                ratio = 0.3333
            # Per-item voice_id override; fall back to job-level default
            item_voice_id = raw.get("voice_id") or None
            if not item_voice_id:
                item_voice_id = default_voice_id
            # Per-item style override; fall back to job-level default
            item_style = raw.get("style") or default_style
            if item_style not in ("style1", "style2", "style3"):
                item_style = default_style
            items.append(
                BatchItem(
                    index=raw.get("index") or idx,
                    url=raw.get("url", "").strip(),
                    product_name_hint=(raw.get("product_name_hint") or None),
                    custom_script=(raw.get("custom_script") or None),
                    overlay_text=(raw.get("overlay_text") or None),
                    video_shift_ratio=ratio,
                    video_scale=float(raw.get("video_scale", 1.08)),
                    tts_voice_id=item_voice_id,
                    style=item_style,
                    script_theme=_clean_theme(raw.get("script_theme")) or _clean_theme(default_script_theme),
                    post_at=_clean_post_at(raw.get("post_at")),
                )
            )
        if not items:
            raise ValueError("Batch không có item nào.")

        with self._lock:
            self._cancel_event.clear()
            # Đăng hẹn giờ không cần Showcase: không có tên Showcase thì AI chọn sản phẩm của video nguồn
            self._showcase_enabled = auto_showcase
            self._showcase_dry = showcase_dry
            self._post_enabled = auto_post
            self._post_dry = post_dry
            self._post_delete_after = post_delete_after
            self._snapshot = JobSnapshot(
                job_id=str(uuid.uuid4()),
                created_at=_now_iso(),
                status="queued",
                mode=mode,
                items=items,
            )
            self._publish()
            self._thread = threading.Thread(
                target=self._run_job,
                args=(max_concurrent, mode, default_voice_id, default_style, profile_url, log_file_path),
                name="tiktok-job",
                daemon=True,
            )
            self._thread.start()
        return self._snapshot

    def create_profile_job(
        self,
        *,
        profile_url: str,
        video_shift_ratio: float = 0.25,
        video_scale: float = 1.08,
        style: str = "style1",
        voice_id: Optional[str] = None,
        mode_pipeline: str = "live",
        force_rerun_all: bool = False,
        max_videos: Optional[int] = None,
        log_file_path: Optional[str] = None,
        auto_showcase: bool = False,
        showcase_dry: bool = False,
        auto_post: bool = False,
        post_dry: bool = False,
        post_delete_after: bool = False,
        script_theme: Optional[str] = None,
    ) -> JobSnapshot:
        """Khởi tạo job crawl TikTok profile và render AI Video bất đồng bộ."""
        if self.is_running():
            raise RuntimeError("Một job khác đang chạy. Vui lòng đợi hoàn tất.")

        from src.profile_crawler import (
            normalize_profile_url,
            crawl_tiktok_profile,
            ProfileManifestManager,
            get_default_log_file_path,
        )

        normalized_profile = normalize_profile_url(profile_url)
        manifest_file = Path(log_file_path) if log_file_path else get_default_log_file_path()

        with self._lock:
            self._cancel_event.clear()
            # Đăng hẹn giờ không cần Showcase: không có tên Showcase thì AI chọn sản phẩm của video nguồn
            self._showcase_enabled = auto_showcase
            self._showcase_dry = showcase_dry
            self._post_enabled = auto_post
            self._post_dry = post_dry
            self._post_delete_after = post_delete_after
            self._snapshot = JobSnapshot(
                job_id=str(uuid.uuid4()),
                created_at=_now_iso(),
                status="queued",
                mode=f"profile-{mode_pipeline}",
                items=[],
            )
            self._publish()
            self._thread = threading.Thread(
                target=self._run_profile_job,
                args=(
                    normalized_profile,
                    video_shift_ratio,
                    video_scale,
                    style,
                    voice_id,
                    mode_pipeline,
                    force_rerun_all,
                    max_videos,
                    manifest_file,
                    _clean_theme(script_theme),
                ),
                name="tiktok-profile-job",
                daemon=True,
            )
            self._thread.start()
        return self._snapshot

    def _run_profile_job(
        self,
        normalized_profile: str,
        video_shift_ratio: float,
        video_scale: float,
        style: str,
        voice_id: Optional[str],
        mode_pipeline: str,
        force_rerun_all: bool,
        max_videos: Optional[int],
        manifest_file: Path,
        script_theme: Optional[str] = None,
    ) -> None:
        """Thực thi crawl profile và batch pipeline trên background thread."""
        from src.profile_crawler import crawl_tiktok_profile, ProfileManifestManager

        try:
            self._update_status("running", started_at=_now_iso())
            logger.info(f"Bắt đầu background crawl profile: {normalized_profile}")

            manifest_mgr = ProfileManifestManager(manifest_file)
            saved_sec_uid = manifest_mgr.get_profile_sec_uid(normalized_profile)
            sample_video_url = manifest_mgr.get_sample_video_url(normalized_profile)

            # Crawl the FULL profile to update manifest (no artificial limit).
            # max_videos only controls how many runnable items are queued, NOT how many
            # are crawled. This ensures the manifest gets all available videos even if
            # the user only wants to run a small batch right now.
            crawled_items: List[Dict[str, Any]] = []
            crawl_error: Optional[Exception] = None
            try:
                crawled_items = crawl_tiktok_profile(
                    normalized_profile,
                    max_videos=None,
                    sample_video_url=sample_video_url,
                    sec_uid=saved_sec_uid,
                )
            except Exception as exc:
                crawl_error = exc
                logger.warning(f"Lỗi khi crawl live profile {normalized_profile}: {exc}")

            if not crawled_items:
                # Fallback sang danh sách video đã lưu trong manifest log nếu có
                cached_videos = manifest_mgr.get_videos_for_profile(normalized_profile)
                if cached_videos:
                    logger.warning(
                        f"Live crawl TikTok không trả về video (lỗi: {crawl_error}). "
                        f"Tự động fallback sử dụng {len(cached_videos)} video đã có trong manifest log: {manifest_file}"
                    )
                    crawled_items = cached_videos
                else:
                    err_msg = "Không tìm thấy video nào trong profile TikTok này"
                    if crawl_error:
                        err_msg += f" (lỗi crawl: {crawl_error})"
                    raise RuntimeError(err_msg)
            else:
                logger.info(f"Crawl đầy đủ: {len(crawled_items)} video từ profile {normalized_profile}")

            runnable_items, skipped_items, _ = manifest_mgr.filter_runnable_videos(
                crawled_videos=crawled_items,
                profile_url=normalized_profile,
                force_rerun_all=force_rerun_all,
            )
            logger.info(
                f"After manifest filter: {len(runnable_items)} runnable, "
                f"{len(skipped_items)} skipped (done). max_videos quota={max_videos}"
            )

            # Apply quota: queue only the requested number of items.
            if max_videos and max_videos > 0 and len(runnable_items) > max_videos:
                runnable_items = runnable_items[:max_videos]
                logger.info(f"Applied max_videos quota={max_videos}, queued items={len(runnable_items)}")

            if not runnable_items:
                logger.info("Toàn bộ video trong profile đã có trạng thái done.")
                self._update_status("done", finished_at=_now_iso())
                return

            items: List[BatchItem] = []
            for idx, item in enumerate(runnable_items, start=1):
                items.append(
                    BatchItem(
                        index=idx,
                        url=item["url"],
                        video_shift_ratio=video_shift_ratio,
                        video_scale=video_scale,
                        tts_voice_id=voice_id,
                        style=style,
                        script_theme=script_theme,
                    )
                )

            with self._lock:
                self._snapshot.items = items
                self._publish()

            if mode_pipeline == "mock":
                self._run_mock(profile_url=normalized_profile, log_file_path=str(manifest_file))
            else:
                self._run_real(
                    max_concurrent=1,
                    default_voice_id=voice_id,
                    default_style=style,
                    profile_url=normalized_profile,
                    log_file_path=str(manifest_file),
                )

            final_status = "done"
            job_error_msg = None
            with self._lock:
                if self._cancel_event.is_set():
                    final_status = "cancelled"
                elif any(it.status == "error" for it in self._snapshot.items):
                    final_status = "error"
                    for it in self._snapshot.items:
                        if it.status == "error" and it.error:
                            if any(kw in it.error.lower() for kw in ["hết credit", "quota", "credit", "402", "payment required", "insufficient"]):
                                job_error_msg = f"Dừng toàn bộ luồng: Giọng đọc đã hết credit/quota ({it.error})"
                                break
                            if not job_error_msg:
                                job_error_msg = it.error
            if job_error_msg:
                self._update_status(final_status, error=job_error_msg, finished_at=_now_iso())
            else:
                self._update_status(final_status, finished_at=_now_iso())

        except Exception as exc:
            logger.exception("profile ai video background job crashed")
            self._update_status("error", error=str(exc), finished_at=_now_iso())

    def create_post_backlog_job(
        self,
        *,
        post_dry: bool = False,
        post_delete_after: bool = False,
        log_file_path: Optional[str] = None,
    ) -> JobSnapshot:
        """Lên lịch các video đã gen trước đó (manifest done, còn file, chưa hẹn).

        Video chưa có kết quả Showcase thì thêm Showcase (điện thoại) trước rồi mới đăng.
        """
        if self.is_running():
            raise RuntimeError("Một job khác đang chạy. Vui lòng đợi hoàn tất.")
        from src.profile_crawler import get_default_log_file_path

        manifest_file = Path(log_file_path) if log_file_path else get_default_log_file_path()
        items = list_post_backlog(manifest_file)
        if not items:
            raise ValueError("Không còn video đã tạo nào chờ lên lịch.")

        with self._lock:
            self._cancel_event.clear()
            self._showcase_enabled = False  # Showcase người dùng tự làm trước; đăng thẳng
            self._showcase_dry = False
            self._post_enabled = True
            self._post_dry = post_dry
            self._post_delete_after = post_delete_after
            self._snapshot = JobSnapshot(
                job_id=str(uuid.uuid4()),
                created_at=_now_iso(),
                status="queued",
                mode="post-backlog",
                items=items,
            )
            self._publish()
            self._thread = threading.Thread(
                target=self._run_post_backlog,
                args=(manifest_file,),
                name="tiktok-post-backlog",
                daemon=True,
            )
            self._thread.start()
        return self._snapshot

    def _run_post_backlog(self, manifest_file: Path) -> None:
        from src.profile_crawler import ProfileManifestManager

        try:
            self._update_status("running", started_at=_now_iso())
            showcase_worker = self._start_showcase(mock=False, manifest_mgr=ProfileManifestManager(manifest_file))
            try:
                for item in list(self._snapshot.items):
                    if self._cancel_event.is_set():
                        break
                    if (item.showcase or {}).get("status") == "done":
                        self._post_worker.submit(self._post_task_for(item))
                    else:
                        showcase_worker.submit(item.index, item.url)
            finally:
                self._finish_automation(showcase_worker)

            with self._lock:
                if self._cancel_event.is_set():
                    final_status = "cancelled"
                elif any((it.post or {}).get("status") == "error" for it in self._snapshot.items):
                    final_status = "error"
                else:
                    final_status = "done"
            self._update_status(final_status, finished_at=_now_iso())
        except Exception as exc:
            logger.exception("post backlog job crashed")
            self._update_status("error", error=str(exc), finished_at=_now_iso())

    def create_montage(
        self,
        *,
        urls: List[str],
        script: str,
        voice_id: Optional[str] = None,
        seed: Optional[int] = None,
        video_shift_ratio: float = 0.3333,
        style: str = "style1",
        mode: str = "live",
    ) -> JobSnapshot:
        """Khởi tạo job xào video TikTok mới."""
        if self.is_running():
            raise RuntimeError("Một job khác đang chạy. Vui lòng đợi hoàn tất.")

        clean_urls = [url.strip() for url in urls if url and url.strip()]
        clean_script = (script or "").strip()
        if len(clean_urls) < 2:
            raise ValueError("Cần ít nhất 2 URL TikTok để xào video.")
        if not clean_script:
            raise ValueError("Script TTS là bắt buộc trong MVP xào video.")

        with self._lock:
            self._cancel_event.clear()
            self._snapshot = JobSnapshot(
                job_id=str(uuid.uuid4()),
                created_at=_now_iso(),
                status="queued",
                mode=f"montage-{mode}",
                items=[],
                montage={
                    "urls": clean_urls,
                    "script": clean_script,
                    "voice_id": voice_id,
                    "seed": seed,
                    "video_shift_ratio": video_shift_ratio,
                    "style": style,
                    "status": "pending",
                    "message": "Đang chờ xử lý",
                    "downloaded_paths": [],
                    "clips": [],
                },
            )
            self._publish()
            self._thread = threading.Thread(
                target=self._run_montage_job,
                args=(clean_urls, clean_script, voice_id, seed, video_shift_ratio, style, mode),
                name="tiktok-montage-job",
                daemon=True,
            )
            self._thread.start()
        return self._snapshot

    # -------- Thread runner --------
    def _run_job(
        self,
        max_concurrent: int,
        mode: str,
        default_voice_id: Optional[str] = None,
        default_style: str = "style1",
        profile_url: Optional[str] = None,
        log_file_path: Optional[str] = None,
    ) -> None:
        try:
            self._update_status("running", started_at=_now_iso())
            if mode == "mock":
                self._run_mock(profile_url=profile_url, log_file_path=log_file_path)
            else:
                self._run_real(
                    max_concurrent,
                    default_voice_id=default_voice_id,
                    default_style=default_style,
                    profile_url=profile_url,
                    log_file_path=log_file_path,
                )
            final_status = "done"
            with self._lock:
                if self._cancel_event.is_set():
                    final_status = "cancelled"
                elif any(it.status == "error" for it in self._snapshot.items):
                    final_status = "error"
            self._update_status(final_status, finished_at=_now_iso())
        except Exception as exc:  # pragma: no cover - bất thường
            logger.exception("job crashed")
            self._update_status("error", error=str(exc), finished_at=_now_iso())

    def _run_montage_job(
        self,
        urls: List[str],
        script: str,
        voice_id: Optional[str],
        seed: Optional[int],
        video_shift_ratio: float,
        style: str,
        mode: str,
    ) -> None:
        try:
            self._update_status("running", started_at=_now_iso())
            if mode == "mock":
                self._run_montage_mock(urls, script, voice_id, seed, video_shift_ratio)
            else:
                self._run_montage_real(urls, script, voice_id, seed, video_shift_ratio, style)
            final_status = "done"
            with self._lock:
                if self._snapshot.montage and self._snapshot.montage.get("status") == "error":
                    final_status = "error"
                    self._snapshot.error = self._snapshot.montage.get("error")
            self._update_status(final_status, finished_at=_now_iso())
        except Exception as exc:
            logger.exception("montage job crashed")
            with self._lock:
                if self._snapshot.montage is not None:
                    self._snapshot.montage["status"] = "error"
                    self._snapshot.montage["error"] = str(exc)
                    self._snapshot.montage["message"] = str(exc)
            self._update_status("error", error=str(exc), finished_at=_now_iso())

    def _run_montage_real(
        self,
        urls: List[str],
        script: str,
        voice_id: Optional[str],
        seed: Optional[int],
        video_shift_ratio: float,
        style: str,
    ) -> None:
        from src.montage_pipeline import MontageState, process_montage

        state = MontageState(
            urls=urls,
            script=script,
            job_id=self._snapshot.job_id,
            voice_id=voice_id,
            seed=seed,
            video_shift_ratio=video_shift_ratio,
            style=style,
        )

        def on_progress(next_state: MontageState) -> None:
            with self._lock:
                self._snapshot.montage = asdict(next_state)
                self._publish()

        self._loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(process_montage(state, on_progress=on_progress))
        finally:
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None

    def _run_montage_mock(
        self,
        urls: List[str],
        script: str,
        voice_id: Optional[str],
        seed: Optional[int],
        video_shift_ratio: float,
    ) -> None:
        stages = [
            ("validating", "Đã kiểm tra URL và script"),
            ("downloading", "Đang tải video nguồn"),
            ("tts", "Đang tạo TTS"),
            ("planning", "Đang lập kế hoạch clip 2–4 giây"),
            ("rendering", "Đang render video 9:16"),
            ("done", "Đã xuất video xào hoàn chỉnh"),
        ]
        for status, message in stages:
            with self._lock:
                self._snapshot.montage = {
                    "urls": urls,
                    "script": script,
                    "voice_id": voice_id,
                    "seed": seed or 12345,
                    "status": status,
                    "message": message,
                    "downloaded_paths": [f"/mock/source_{idx}.mp4" for idx, _ in enumerate(urls, start=1)],
                    "audio_path": "/mock/voice_montage.m4a" if status in {"planning", "rendering", "done"} else None,
                    "final_video_path": "/mock/montage.mp4" if status == "done" else None,
                    "manifest_path": "/mock/manifest.json" if status == "done" else None,
                    "audio_duration": 18.0,
                    "clips": [
                        {"source_index": 1, "start": 0.5, "duration": 3.0},
                        {"source_index": 2, "start": 1.5, "duration": 3.5},
                    ],
                }
                self._publish()
            time.sleep(0.2)

    def _run_real(
        self,
        max_concurrent: int,
        default_voice_id: Optional[str] = None,
        default_style: str = "style1",
        profile_url: Optional[str] = None,
        log_file_path: Optional[str] = None,
    ) -> None:
        from pathlib import Path
        from src.voices import VoiceStore, VOICES_FILE
        from src.profile_crawler import ProfileManifestManager

        manifest_mgr = ProfileManifestManager(Path(log_file_path)) if log_file_path else ProfileManifestManager()

        # Build ItemState with per-item voice_id and style, falling back to job-level defaults
        states = [
            ItemState(
                index=it.index,
                url=it.url,
                product_name_hint=it.product_name_hint,
                custom_script=it.custom_script,
                overlay_text=it.overlay_text,
                video_shift_ratio=it.video_shift_ratio,
                video_scale=it.video_scale,
                tts_voice_id=it.tts_voice_id,  # per-item override
                style=it.style if it.style in ("style1", "style2", "style3") else default_style,
                script_theme=it.script_theme,
            )
            for it in self._snapshot.items
        ]

        # Resolve job-level fallback: per-item voice_id already embedded in states.
        # Use default_voice_id when item has no per-item override.
        active_voice_id = default_voice_id
        source = "auto-gen request"
        if not active_voice_id:
            try:
                store = VoiceStore(VOICES_FILE)
                active_voice = store.active
                if active_voice and active_voice.voice_id:
                    active_voice_id = active_voice.voice_id
                    source = "VoiceStore (UI)"
            except Exception:
                pass
        if not active_voice_id:
            import os as _os
            active_voice_id = (
                _os.environ.get("ITERA102_VOICE_ID")
                or _os.environ.get("LUCY_VOICE_ID")
                or "google-free"
            )
            source = "env"
        from src.tts_generator import is_free_voice_id, is_placeholder_voice_id

        # active_voice_id đã được resolve ở trên (FE → default_voice_id → VoiceStore → env).
        # Nếu nó là placeholder, thử fallback sang ITERA102_VOICE_ID trong .env
        # trước khi báo lỗi.
        if is_placeholder_voice_id(str(active_voice_id or "")):
            env_voice = (
                _os.environ.get("ITERA102_VOICE_ID")
                or _os.environ.get("LUCY_VOICE_ID")
                or ""
            ).strip()
            if env_voice and not is_placeholder_voice_id(env_voice):
                logger.info(
                    f"[job_manager] FE sent placeholder voice, falling back to "
                    f"ITERA102_VOICE_ID from .env: {env_voice}"
                )
                active_voice_id = env_voice
                source = "env (fallback from placeholder)"
            else:
                raise RuntimeError(
                    "Chưa chọn voice active trên FE và ITERA102_VOICE_ID trong .env "
                    "cũng chưa hợp lệ. Vào Voice Manager chọn voice Itera rồi chạy lại."
                )

        if is_placeholder_voice_id(str(active_voice_id or "")):
            raise RuntimeError(
                "ITERA102_VOICE_ID trong .env cũng là placeholder. "
                "Vui lòng cấu hình voice Itera hợp lệ trong .env."
            )
        logger.info(
            f"[job_manager] using TTS voice_id={active_voice_id} (source={source})"
        )

        def on_progress(state: ItemState) -> None:
            logger.info(
                "[job_manager] realtime item=%s status=%s video=%s script=%s audio=%s final=%s",
                state.index,
                state.status,
                bool(state.video_path),
                bool(state.script_path),
                bool(state.audio_path),
                bool(state.final_video_path),
            )
            with self._lock:
                for item in self._snapshot.items:
                    if item.index == state.index:
                        item.video_info = state.video_info
                        item.script = state.script
                        item.tts = state.tts
                        item.merge = state.merge
                        item.capcut = state.capcut
                        item.status = state.status
                        item.error = state.error
                        item.video_path = state.video_path
                        item.script_path = state.script_path
                        item.audio_path = state.audio_path
                        item.final_video_path = state.final_video_path
                        break
                self._publish()

            if showcase_worker and state.status == "done":
                showcase_worker.submit(state.index, state.url)

            # Cập nhật manifest JSON
            try:
                p_name = None
                if state.script and isinstance(state.script, dict):
                    p_name = state.script.get("product_name")
                if not p_name:
                    p_name = state.product_name_hint

                v_title = None
                if state.video_info and isinstance(state.video_info, dict):
                    v_title = state.video_info.get("title")

                manifest_mgr.update_video_status(
                    url=state.url,
                    profile_url=profile_url,
                    title=v_title,
                    product_name=p_name,
                    status=state.status,
                    error=state.error,
                    final_video_path=state.final_video_path,
                )
            except Exception as manifest_err:
                logger.warning(f"Không thể cập nhật JSON log cho {state.url}: {manifest_err}")

        showcase_worker = self._start_showcase(mock=False, manifest_mgr=manifest_mgr)
        self._loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(
                process_batch(
                    states,
                    on_progress=on_progress,
                    max_concurrent=max_concurrent,
                    tts_voice_id=active_voice_id,
                    style=default_style,
                    check_control=self._check_pause_and_cancel,
                )
            )
        finally:
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None

            # Đồng bộ lại snapshot cuối cùng từ state
            with self._lock:
                for state in states:
                    for item in self._snapshot.items:
                        if item.index == state.index:
                            item.status = state.status
                            item.error = state.error
                            item.final_video_path = state.final_video_path
                            break
                self._publish()

            # Video đã xong hết; chờ điện thoại thêm nốt sản phẩm vào Showcase
            if showcase_worker:
                for state in states:
                    if state.status == "done":
                        showcase_worker.submit(state.index, state.url)
                self._finish_automation(showcase_worker)

    def _run_mock(
        self,
        profile_url: Optional[str] = None,
        log_file_path: Optional[str] = None,
    ) -> None:
        """Mô phỏng pipeline với 5 bước, không gọi API ngoài."""
        from pathlib import Path
        from src.profile_crawler import ProfileManifestManager

        manifest_mgr = ProfileManifestManager(Path(log_file_path)) if log_file_path else ProfileManifestManager()
        showcase_worker = self._start_showcase(mock=True, manifest_mgr=manifest_mgr)
        try:
            self._run_mock_items(manifest_mgr, profile_url, showcase_worker)
        finally:
            if showcase_worker:
                self._finish_automation(showcase_worker)

    def _run_mock_items(self, manifest_mgr: Any, profile_url: Optional[str], showcase_worker: Optional[Any]) -> None:
        stages = ["pending", "downloading", "scripting", "tts", "merging", "done"]
        for item in self._snapshot.items:
            for stage in stages:
                if self._cancel_event.is_set():
                    item.status = "cancelled"
                    break
                item.status = stage
                if stage == "scripting":
                    item.script = {"product_name": f"Mock Product #{item.index}"}
                elif stage == "done":
                    item.final_video_path = f"/mock/{item.index}.mp4"

                try:
                    p_name = None
                    if item.script and isinstance(item.script, dict):
                        p_name = item.script.get("product_name")
                    manifest_mgr.update_video_status(
                        url=item.url,
                        profile_url=profile_url,
                        product_name=p_name,
                        status=item.status,
                        error=item.error,
                        final_video_path=item.final_video_path,
                    )
                except Exception as manifest_err:
                    logger.warning(f"Mock manifest update failed: {manifest_err}")

                with self._lock:
                    self._publish()
                time.sleep(0.2)
            else:
                item.final_video_path = f"/mock/{item.index}.mp4"
                if showcase_worker:
                    showcase_worker.submit(item.index, item.url)

    # -------- Showcase --------
    def _start_showcase(self, *, mock: bool, manifest_mgr: Any) -> Optional[Any]:
        """Tạo worker thêm sản phẩm vào Showcase nếu job bật ``auto_showcase``.

        Tắt Showcase mà bật đăng hẹn giờ: trả về bộ chuyển thẳng video sang hàng đăng
        (cùng giao diện ``submit``/``finish``) để các luồng chạy job không phải đổi.
        """
        if not self._showcase_enabled:
            post_worker = self._start_post_worker(mock=mock)
            return _DirectPostFeeder(self, post_worker) if post_worker else None
        from src.showcase import TERMINAL_STATUSES, ShowcaseWorker, get_default_csv_log_path

        post_worker = self._start_post_worker(mock=mock)

        def on_update(index: int, showcase: Dict[str, Any]) -> None:
            target = None
            with self._lock:
                for item in self._snapshot.items:
                    if item.index == index:
                        item.showcase = showcase
                        target = item
                        break
                self._publish()
            if target and showcase["status"] in TERMINAL_STATUSES:
                try:
                    manifest_mgr.update_showcase_status(target.url, showcase)
                except Exception as manifest_err:
                    logger.warning(f"Không thể lưu kết quả Showcase cho {target.url}: {manifest_err}")
                if post_worker and showcase["status"] != "cancelled":
                    post_worker.submit(self._post_task_for(target))

        return ShowcaseWorker(
            on_update,
            dry=self._showcase_dry,
            mock=mock,
            cancel_event=self._cancel_event,
            csv_log_path=None if mock else get_default_csv_log_path(),
        )

    @staticmethod
    def _post_task_for(item: BatchItem) -> Any:
        from src.tiktok_poster import PostTask, build_caption, pick_product_name

        return PostTask(
            index=item.index,
            video_path=item.final_video_path or "",
            caption=build_caption(item.script, fallback=item.product_name_hint or ""),
            product_name=pick_product_name(item.showcase),
            source_url=item.url,
            product_hint=str((item.script or {}).get("product_name") or item.product_name_hint or ""),
            post_at=item.post_at,
        )

    def _start_post_worker(self, *, mock: bool) -> Optional[Any]:
        """Tạo worker đăng hẹn giờ TikTok Studio nếu job bật ``auto_post``."""
        self._post_worker = None
        if not self._post_enabled:
            return None
        from src.tiktok_poster import PostWorker, make_short_name

        def on_update(index: int, post: Dict[str, Any]) -> None:
            with self._lock:
                for item in self._snapshot.items:
                    if item.index == index:
                        item.post = post
                        break
                self._publish()

        self._post_worker = PostWorker(
            on_update,
            dry=self._post_dry,
            mock=mock,
            cancel_event=self._cancel_event,
            delete_after=self._post_delete_after,
            short_namer=(lambda name, caption: f"{name.split()[0]} vui") if mock else make_short_name,
        )
        return self._post_worker

    def _finish_automation(self, showcase_worker: Any) -> None:
        """Chờ Showcase xong hết rồi chờ đăng hẹn giờ xong hết."""
        showcase_worker.finish()
        if self._post_worker:
            self._post_worker.finish()
            self._post_worker = None

    # -------- Internals --------
    def _update_status(self, status: str, **fields: Any) -> None:
        with self._lock:
            self._snapshot.status = status
            for key, value in fields.items():
                setattr(self._snapshot, key, value)
            self._publish()

    def _publish(self) -> None:
        snapshot = self._snapshot
        for listener in list(self._listeners):
            try:
                listener(snapshot)
            except Exception:  # pragma: no cover
                logger.exception("listener raised")


class _DirectPostFeeder:
    """Thay ShowcaseWorker khi tắt Showcase: video xong là đưa thẳng vào hàng đăng hẹn giờ."""

    def __init__(self, manager: "JobManager", post_worker: Any) -> None:
        self._manager = manager
        self._post_worker = post_worker

    def submit(self, index: int, url: str) -> None:
        with self._manager._lock:
            item = next((it for it in self._manager._snapshot.items if it.index == index), None)
        if item is not None:
            self._post_worker.submit(self._manager._post_task_for(item))

    def finish(self, timeout: Optional[float] = None) -> None:
        pass  # PostWorker do _finish_automation kết thúc


__all__ = ["BatchItem", "JobManager", "JobSnapshot", "ProgressListener"]
