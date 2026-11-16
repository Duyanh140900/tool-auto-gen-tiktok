"""app.py - FastAPI application cho TikTok Review Tool web UI.

Module này định nghĩa tất cả API mà frontend Next.js (`frontend/src/lib/api.ts`)
đang gọi:

  * ``GET  /api/health``
  * ``GET  /api/settings``
  * ``POST /api/settings``
  * ``GET  /api/voices``
  * ``GET  /api/results``
  * ``GET  /api/job``
  * ``POST /api/batch``
  * ``POST /api/profile-ai-video``
  * ``GET  /api/profile-ai-video/log``
  * ``GET  /api/job/events``   (Server-Sent Events)
  * ``POST /api/pick-folder``
  * ``POST /api/open-folder``
  * ``POST /api/reveal-file``

Ứng dụng cố tình bám localhost: CORS chỉ cho phép các origin ``http://localhost``
và ``http://127.0.0.1``. Mọi thao tác hệ thống (chọn/mở thư mục, reveal file)
đều có whitelist đường dẫn để tránh truy cập ngoài ý muốn.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from config import settings
from src.env_persistence import apply_updates, build_ui_settings
from src.profile_crawler import (
    crawl_tiktok_profile,
    get_default_log_file_path,
    normalize_profile_url,
    ProfileManifestManager,
)
from src.voices import VOICES_FILE, VoiceStore, list_voice_options
from src.web.job_manager import JobManager, JobSnapshot
from src import ai_video_defaults, telegram_bot

logger = logging.getLogger("tiktok.web.app")
logging.basicConfig(level=os.environ.get("TIKTOK_WEB_LOG", "INFO").upper())
try:
    from src.log_setup import setup_file_logging
    setup_file_logging()
except Exception as _log_exc:  # không để lỗi ghi log làm sập backend
    logger.warning(f"Không bật được file log: {_log_exc}")


# ---------- FastAPI app + CORS -----------------------------------------------

app = FastAPI(
    title="TikTok Review Tool Web API",
    version="1.0.0",
    description="Localhost-only API cho giao diện Next.js.",
)

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

job_manager = JobManager()


@app.on_event("startup")
async def _start_telegram_bot() -> None:
    # Không chạy bot trong test (TestClient cũng gọi startup).
    if "pytest" in sys.modules or os.environ.get("TELEGRAM_BOT_DISABLED"):
        return
    try:
        telegram_bot.start_from_env(job_manager)
    except Exception:
        logger.exception("Không khởi động được Telegram bot")


@app.on_event("shutdown")
async def _stop_telegram_bot() -> None:
    telegram_bot.stop()


# ---------- Pydantic schemas -------------------------------------------------


class SettingsUpdate(BaseModel):
    final_output_dir: Optional[str] = None
    itera102_voice_id: Optional[str] = None
    itera102_speed: Optional[float] = Field(default=None, ge=0.7, le=1.2)
    itera102_stability: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    itera102_similarity_boost: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    itera102_style: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    itera102_use_speaker_boost: Optional[bool] = None
    edge_tts_voice: Optional[str] = None
    edge_tts_speed: Optional[str] = None
    custom_logo_path: Optional[str] = None
    custom_card_bg_path: Optional[str] = None
    custom_nhay_path: Optional[str] = None
    custom_black_bg_path: Optional[str] = None
    custom_style1_logo_path: Optional[str] = None
    custom_style1_card_bg_path: Optional[str] = None
    custom_style1_nhay_path: Optional[str] = None
    custom_style1_black_bg_path: Optional[str] = None
    custom_style2_logo_path: Optional[str] = None
    custom_style2_card_bg_path: Optional[str] = None
    custom_style2_nhay_path: Optional[str] = None
    custom_style2_black_bg_path: Optional[str] = None
    custom_style3_logo_path: Optional[str] = None
    custom_style3_card_bg_path: Optional[str] = None
    custom_style3_nhay_path: Optional[str] = None
    custom_style3_black_bg_path: Optional[str] = None

    @field_validator("edge_tts_speed")
    @classmethod
    def _strip_speed(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        try:
            float(value)
        except ValueError as exc:
            raise ValueError("edge_tts_speed phải là số (vd '1.15').") from exc
        return value


class BatchItemRequest(BaseModel):
    """Per-row schema for BatchRequest items, with explicit validation."""
    url: str
    product_name_hint: Optional[str] = None
    custom_script: Optional[str] = None   # Script text for TTS audio
    overlay_text: Optional[str] = None   # Separate text displayed on video overlay
    video_shift_ratio: float = Field(default=0.3333, ge=0.0, le=1.0)
    video_scale: float = Field(default=1.08, ge=0.1, le=3.0)
    voice_id: Optional[str] = None  # Per-item voice override
    style: Optional[str] = "style1"  # "style1", "style2", or "style3"
    script_theme: Optional[str] = Field(default=None, max_length=300)  # Chủ đề kịch bản riêng của item


class BatchRequest(BaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    max_concurrent: int = Field(default=1, ge=1, le=8)
    mode: str = Field(default="live")
    default_voice_id: Optional[str] = None
    default_style: str = Field(default="style1")
    auto_showcase: bool = False  # Gen xong video thì thêm sản phẩm vào Showcase (src/showcase.py)
    showcase_dry: bool = False
    auto_post: bool = False  # Sau Showcase thì đăng hẹn giờ TikTok Studio (src/tiktok_poster.py)
    post_dry: bool = False
    post_delete_after: bool = False  # hẹn xong thì chuyển video vào Thùng rác
    script_theme: Optional[str] = Field(default=None, max_length=300)  # Chủ đề kịch bản AI (vd ngày lễ)

    @field_validator("mode")
    @classmethod
    def _mode(cls, value: str) -> str:
        value = (value or "live").strip().lower()
        if value not in {"live", "mock"}:
            raise ValueError("mode chỉ nhận 'live' hoặc 'mock'.")
        return value

    @model_validator(mode="after")
    def _validate_items(self) -> "BatchRequest":
        """Validate each batch item dict against BatchItemRequest schema."""
        validated = []
        for idx, raw in enumerate(self.items or [], start=1):
            try:
                item = BatchItemRequest(**(raw or {}))
                validated.append(item.model_dump())
            except Exception as exc:
                raise ValueError(f"Item {idx}: {exc}") from exc
        self.items = validated  # type: ignore[assignment]
        return self


class MontageRequest(BaseModel):
    urls: List[str] = Field(default_factory=list, min_length=2)
    script: str = Field(min_length=1)
    voice_id: Optional[str] = None
    seed: Optional[int] = None
    video_shift_ratio: float = Field(default=0.3333, ge=0.0, le=1.0)
    style: str = Field(default="style1")
    mode: str = Field(default="live")


class TestRenderRequest(BaseModel):
    """Legacy request — kept for backward compatibility with existing tests and endpoints.

    For new integrations use ``AutoGenRequest`` instead.
    """
    mode: str = Field(default="review")
    urls: List[str] = Field(default_factory=list)
    script: str = Field(default="")
    duration_sec: float = Field(default=10.0, ge=1.0, le=300.0)
    video_shift_ratio: float = Field(default=0.3333, ge=0.0, le=1.0)
    style: str = Field(default="style1")
    voice_id: Optional[str] = None

    @field_validator("urls", mode="before")
    @classmethod
    def _urls(cls, value: List[str]) -> List[str]:
        clean = [item.strip() for item in value if item and item.strip()]
        return clean

    @field_validator("script", mode="before")
    @classmethod
    def _script(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("mode", mode="before")
    @classmethod
    def _mode(cls, value: str) -> str:
        value = (value or "review").strip().lower()
        if value not in {"review", "montage"}:
            raise ValueError("mode chỉ nhận 'review' hoặc 'montage'.")
        return value

    @model_validator(mode="after")
    def _validate_payloads(self) -> "TestRenderRequest":
        """Ràng buộc số lượng URL tối thiểu tùy theo mode."""
        if self.mode == "montage" and len(self.urls) < 2:
            raise ValueError("Cần ít nhất 2 URL TikTok để test luồng Montage.")
        if self.mode == "review" and len(self.urls) < 1:
            raise ValueError("Cần ít nhất 1 URL TikTok để test luồng Review.")
        return self


class AutoGenRequest(BaseModel):
    """Unified payload for the Auto gen video workflow.

    Dispatches to review or montage pipeline based on ``mode``.
    Supports per-item voice selection and style selection.
    """
    mode: str = Field(default="review")
    # Review mode: one or more items; each item is a dict with url + optional fields
    items: List[Dict[str, Any]] = Field(default_factory=list)
    # Montage mode: multiple URLs sharing one script
    urls: List[str] = Field(default_factory=list)
    script: str = Field(default="")
    voice_id: Optional[str] = None  # Job-level voice (fallback for review items)
    seed: Optional[int] = None
    video_shift_ratio: float = Field(default=0.3333, ge=0.0, le=1.0)
    video_scale: float = Field(default=1.08, ge=0.1, le=3.0)
    style: str = Field(default="style1")  # "style1", "style2", or "style3"
    mode_pipeline: str = Field(default="live")  # "live" or "mock"
    auto_showcase: bool = False  # Gen xong video thì thêm sản phẩm vào Showcase (review mode)
    showcase_dry: bool = False
    auto_post: bool = False  # Sau Showcase thì đăng hẹn giờ TikTok Studio (review mode)
    post_dry: bool = False
    post_delete_after: bool = False  # hẹn xong thì chuyển video vào Thùng rác
    script_theme: Optional[str] = Field(default=None, max_length=300)  # Chủ đề kịch bản AI (review mode)

    @field_validator("mode", mode="before")
    @classmethod
    def _mode(cls, value: str) -> str:
        value = (value or "review").strip().lower()
        if value not in {"review", "montage"}:
            raise ValueError("mode chỉ nhận 'review' hoặc 'montage'.")
        return value

    @model_validator(mode="after")
    def _validate_payloads(self) -> "AutoGenRequest":
        if self.mode == "review":
            if not self.items:
                raise ValueError("Review mode requires at least one item in 'items'.")
        else:  # montage
            clean_urls = [u.strip() for u in self.urls if u.strip()]
            if len(clean_urls) < 2:
                raise ValueError("Montage mode requires at least 2 TikTok URLs.")
            if not self.script.strip():
                raise ValueError("Montage mode requires a TTS script.")
        return self


class ProfileAiVideoRequest(BaseModel):
    """Payload for the Profile AI Video workflow."""
    profile_url: str = Field(..., description="TikTok profile URL or @username")
    video_shift_ratio: float = Field(default=0.25, ge=0.0, le=1.0)
    video_scale: float = Field(default=1.08, ge=0.1, le=3.0)
    style: str = Field(default="style1")
    voice_id: Optional[str] = None
    mode_pipeline: str = Field(default="live")  # "live" or "mock"
    max_videos: Optional[int] = Field(default=None, ge=0, description="Max number of runnable videos to queue. 0 or None means unlimited.")
    force_rerun_all: bool = False
    auto_showcase: bool = False  # Gen xong video thì thêm sản phẩm vào Showcase
    showcase_dry: bool = False
    auto_post: bool = False  # Sau Showcase thì đăng hẹn giờ TikTok Studio
    post_dry: bool = False
    post_delete_after: bool = False  # hẹn xong thì chuyển video vào Thùng rác
    script_theme: Optional[str] = Field(default=None, max_length=300)  # Chủ đề kịch bản AI (vd ngày lễ)

    @field_validator("profile_url")
    @classmethod
    def _validate_profile(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("Vui lòng nhập link profile TikTok hoặc @username.")
        return value


class PathPayload(BaseModel):
    path: str


# ---------- Helpers ----------------------------------------------------------


def _validate_local_path(path: str) -> Path:
    """Đảm bảo đường dẫn nằm trong các thư mục được phép (whitelist)."""
    if not path:
        raise HTTPException(status_code=400, detail="Đường dẫn trống.")

    expanded = Path(path).expanduser().resolve(strict=False)
    allowed_roots = [
        settings.OUTPUT_DIR.expanduser().resolve(strict=False),
        settings.FINAL_OUTPUT_DIR.expanduser().resolve(strict=False),
        Path.home(),
        Path.cwd(),
    ]
    allowed_roots = [root if isinstance(root, Path) else Path(root) for root in allowed_roots]

    logger.info(
        "local path validation: requested=%r resolved=%s exists=%s allowed_roots=%s",
        path,
        expanded,
        expanded.exists(),
        [str(root) for root in allowed_roots],
    )

    def is_within(candidate: Path, root: Path) -> bool:
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            return False

    if not any(is_within(expanded, root) for root in allowed_roots):
        logger.warning("local path rejected by whitelist: %s", expanded)
        raise HTTPException(
            status_code=403,
            detail="Đường dẫn không thuộc thư mục được phép.",
        )
    return expanded


def _build_results_payload() -> Dict[str, Any]:
    """Liệt kê các file video cuối cùng trong FINAL_OUTPUT_DIR."""
    base = settings.FINAL_OUTPUT_DIR
    items: List[Dict[str, Any]] = []
    if base.exists():
        for entry in sorted(base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if entry.is_file() and entry.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
                stat = entry.stat()
                items.append(
                    {
                        "file_name": entry.name,
                        "file_path": str(entry),
                        "size_bytes": stat.st_size,
                        "modified_at": datetime.fromtimestamp(
                            stat.st_mtime, tz=timezone.utc
                        ).isoformat(),
                        "download_url": f"/api/results/download?path={entry.name}",
                    }
                )
    return {"items": items}


def _pick_folder_dialog() -> Optional[str]:
    """Mở dialog chọn thư mục native của hệ điều hành."""
    try:
        if sys.platform.startswith("win"):
            script = (
                "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8;"
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$f = New-Object System.Windows.Forms.FolderBrowserDialog;"
                "$f.Description = 'Chọn thư mục output cho TikTok Review Tool';"
                "$f.ShowNewFolderButton = $true;"
                "$owner = New-Object System.Windows.Forms.Form;"
                "$owner.TopMost = $true;"
                "$owner.ShowInTaskbar = $false;"
                "$owner.StartPosition = 'CenterScreen';"
                "try {"
                "  if ($f.ShowDialog($owner) -eq 'OK') { Write-Output $f.SelectedPath }"
                "} finally {"
                "  $owner.Dispose();"
                "  $f.Dispose();"
                "}"
            )
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command", script],
                capture_output=True, text=True, encoding="utf-8", timeout=120,
            )
            if completed.returncode == 0:
                chosen = completed.stdout.strip()
                return chosen or None
            logger.warning(
                "Windows folder picker failed (exit=%s): %s",
                completed.returncode,
                completed.stderr.strip(),
            )
        elif sys.platform == "darwin":
            script = (
                "try\n"
                "  set theFolder to choose folder with prompt \"Chọn thư mục output\"\n"
                "  POSIX path of theFolder\n"
                "on error\n"
                "  return \"\"\n"
                "end try"
            )
            completed = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=120,
            )
            if completed.returncode == 0:
                chosen = completed.stdout.strip()
                return chosen or None
        else:
            # Linux/WSL: thử zenity, nếu không có thì trả None.
            try:
                completed = subprocess.run(
                    ["zenity", "--file-selection", "--directory", "--title=Chọn thư mục output"],
                    capture_output=True, text=True, timeout=60,
                )
                if completed.returncode == 0:
                    return completed.stdout.strip() or None
            except FileNotFoundError:
                return None
    except Exception:
        logger.exception("pick_folder_dialog failed")
    return None


def _pick_file_dialog(title: str = "Chọn file ảnh", file_filter: str = "Image Files|*.png;*.jpg;*.jpeg;*.webp;*.bmp|All Files|*.*") -> Optional[str]:
    """Mở dialog chọn file native của hệ điều hành."""
    try:
        if sys.platform.startswith("win"):
            # Escape single quotes in title/filter for PowerShell
            safe_title = title.replace("'", "''")
            safe_filter = file_filter.replace("'", "''")
            script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$f = New-Object System.Windows.Forms.OpenFileDialog;"
                f"$f.Title = '{safe_title}';"
                f"$f.Filter = '{safe_filter}';"
                "if ($f.ShowDialog() -eq 'OK') { Write-Output $f.FileName }"
            )
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=120,
            )
            if completed.returncode == 0:
                chosen = completed.stdout.strip()
                return chosen or None
        elif sys.platform == "darwin":
            safe_title = title.replace('"', '\\"')
            script = (
                "try\n"
                f"  set theFile to choose file with prompt \"{safe_title}\"\n"
                "  POSIX path of theFile\n"
                "on error\n"
                "  return \"\"\n"
                "end try"
            )
            completed = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=120,
            )
            if completed.returncode == 0:
                chosen = completed.stdout.strip()
                return chosen or None
        else:
            try:
                completed = subprocess.run(
                    ["zenity", "--file-selection", f"--title={title}"],
                    capture_output=True, text=True, timeout=60,
                )
                if completed.returncode == 0:
                    return completed.stdout.strip() or None
            except FileNotFoundError:
                return None
    except Exception:
        logger.exception("pick_file_dialog failed")
    return None


def _open_path(path: Path) -> bool:
    """Mở đường dẫn bằng ứng dụng mặc định của hệ điều hành."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
        return True
    except Exception:
        logger.exception("open_path failed: %s", path)
        return False


def _reveal_file(path: Path) -> bool:
    """Mở thư mục chứa file và bôi đậm file đó (nếu được)."""
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["explorer", "/select,", str(path)], check=False)
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path.parent)], check=False)
        return True
    except Exception:
        logger.exception("reveal_file failed: %s", path)
        return False


def _serialize_snapshot(snapshot: JobSnapshot) -> Dict[str, Any]:
    """Trả về snapshot JSON-safe đúng schema frontend.

    Trạng thái pipeline có thể chứa ``Path`` trong các trường trực tiếp hoặc
    dictionary lồng nhau. Chuẩn hóa toàn bộ payload trước khi đưa cho
    ``json.dumps`` để một đường dẫn không làm sập kết nối WebSocket.
    """
    payload = snapshot.to_dict()
    if "job_id" not in payload:
        payload = {**payload, "job": snapshot.to_dict()}
    return jsonable_encoder(payload)


# ---------- Routes -----------------------------------------------------------


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "tiktok-review-tool-web",
        "version": app.version,
        "time": datetime.now(timezone.utc).isoformat(),
        "current_job_running": job_manager.is_running(),
    }


@app.get("/api/settings")
async def get_settings() -> Dict[str, Any]:
    return build_ui_settings(settings)


@app.post("/api/settings")
async def post_settings(payload: SettingsUpdate) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    if payload.final_output_dir:
        updates["FINAL_OUTPUT_DIR"] = payload.final_output_dir
    if payload.itera102_voice_id is not None:
        updates["ITERA102_VOICE_ID"] = payload.itera102_voice_id
    if payload.itera102_speed is not None:
        updates["ITERA102_SPEED"] = payload.itera102_speed
    if payload.itera102_stability is not None:
        updates["ITERA102_STABILITY"] = payload.itera102_stability
    if payload.itera102_similarity_boost is not None:
        updates["ITERA102_SIMILARITY_BOOST"] = payload.itera102_similarity_boost
    if payload.itera102_style is not None:
        updates["ITERA102_STYLE"] = payload.itera102_style
    if payload.itera102_use_speaker_boost is not None:
        updates["ITERA102_USE_SPEAKER_BOOST"] = payload.itera102_use_speaker_boost
    if payload.edge_tts_voice:
        updates["EDGE_TTS_VOICE"] = payload.edge_tts_voice
    if payload.edge_tts_speed:
        updates["EDGE_TTS_SPEED"] = payload.edge_tts_speed
    if payload.custom_logo_path is not None:
        updates["CUSTOM_LOGO_PATH"] = payload.custom_logo_path
        updates["CUSTOM_STYLE1_LOGO_PATH"] = payload.custom_logo_path
    if payload.custom_card_bg_path is not None:
        updates["CUSTOM_CARD_BG_PATH"] = payload.custom_card_bg_path
        updates["CUSTOM_STYLE1_CARD_BG_PATH"] = payload.custom_card_bg_path
    if payload.custom_nhay_path is not None:
        updates["CUSTOM_NHAY_PATH"] = payload.custom_nhay_path
        updates["CUSTOM_STYLE1_NHAY_PATH"] = payload.custom_nhay_path
    if payload.custom_black_bg_path is not None:
        updates["CUSTOM_BLACK_BG_PATH"] = payload.custom_black_bg_path
        updates["CUSTOM_STYLE1_BLACK_BG_PATH"] = payload.custom_black_bg_path

    if payload.custom_style1_logo_path is not None:
        updates["CUSTOM_STYLE1_LOGO_PATH"] = payload.custom_style1_logo_path
    if payload.custom_style1_card_bg_path is not None:
        updates["CUSTOM_STYLE1_CARD_BG_PATH"] = payload.custom_style1_card_bg_path
    if payload.custom_style1_nhay_path is not None:
        updates["CUSTOM_STYLE1_NHAY_PATH"] = payload.custom_style1_nhay_path
    if payload.custom_style1_black_bg_path is not None:
        updates["CUSTOM_STYLE1_BLACK_BG_PATH"] = payload.custom_style1_black_bg_path

    if payload.custom_style2_logo_path is not None:
        updates["CUSTOM_STYLE2_LOGO_PATH"] = payload.custom_style2_logo_path
    if payload.custom_style2_card_bg_path is not None:
        updates["CUSTOM_STYLE2_CARD_BG_PATH"] = payload.custom_style2_card_bg_path
    if payload.custom_style2_nhay_path is not None:
        updates["CUSTOM_STYLE2_NHAY_PATH"] = payload.custom_style2_nhay_path
    if payload.custom_style2_black_bg_path is not None:
        updates["CUSTOM_STYLE2_BLACK_BG_PATH"] = payload.custom_style2_black_bg_path

    if payload.custom_style3_logo_path is not None:
        updates["CUSTOM_STYLE3_LOGO_PATH"] = payload.custom_style3_logo_path
    if payload.custom_style3_card_bg_path is not None:
        updates["CUSTOM_STYLE3_CARD_BG_PATH"] = payload.custom_style3_card_bg_path
    if payload.custom_style3_nhay_path is not None:
        updates["CUSTOM_STYLE3_NHAY_PATH"] = payload.custom_style3_nhay_path
    if payload.custom_style3_black_bg_path is not None:
        updates["CUSTOM_STYLE3_BLACK_BG_PATH"] = payload.custom_style3_black_bg_path

    written_map = apply_updates(updates)
    written: Dict[str, str] = {k: v.cast for k, v in written_map.items()}

    # apply_updates() persists values to .env, but the web process remains
    # alive. Keep both os.environ and the shared Settings instance in sync so
    # subsequent jobs and path validation use the values just saved by UI.
    for key, value in written.items():
        os.environ[key] = value

    if "FINAL_OUTPUT_DIR" in written:
        final_output_dir = Path(written["FINAL_OUTPUT_DIR"]).expanduser().resolve(strict=False)
        final_output_dir.mkdir(parents=True, exist_ok=True)
        settings.FINAL_OUTPUT_DIR = final_output_dir
    if "LUCY_VOICE_ID" in written:
        settings.LUCY_VOICE_ID = written["LUCY_VOICE_ID"]
    if "EDGE_TTS_VOICE" in written:
        settings.EDGE_TTS_VOICE = written["EDGE_TTS_VOICE"]
    if "EDGE_TTS_SPEED" in written:
        settings.EDGE_TTS_SPEED = float(written["EDGE_TTS_SPEED"])

    logger.info(
        "settings updated at runtime: keys=%s final_output_dir=%s",
        sorted(written),
        settings.FINAL_OUTPUT_DIR,
    )
    return {"ok": True, "updated": written, "settings": build_ui_settings(settings)}


@app.get("/api/voices")
async def get_voices() -> Dict[str, Any]:
    voices = list_voice_options(VOICES_FILE)
    return {"voices": voices}


@app.get("/api/results")
async def get_results() -> Dict[str, Any]:
    return _build_results_payload()


@app.get("/api/job")
async def get_job() -> Dict[str, Any]:
    snapshot = job_manager.current
    payload = _serialize_snapshot(snapshot)
    return payload


@app.post("/api/batch")
async def create_batch(payload: BatchRequest) -> Dict[str, Any]:
    try:
        # Tạo job ở thread riêng để tránh block event loop khi validate nặng.
        snapshot = await asyncio.to_thread(
            job_manager.create_batch,
            payload.items,
            max_concurrent=payload.max_concurrent,
            mode=payload.mode,
            default_voice_id=payload.default_voice_id,
            default_style=payload.default_style,
            auto_showcase=payload.auto_showcase,
            showcase_dry=payload.showcase_dry,
            auto_post=payload.auto_post,
            post_dry=payload.post_dry,
            post_delete_after=payload.post_delete_after,
            default_script_theme=payload.script_theme,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return snapshot.to_dict()


class AiVideoDefaults(BaseModel):
    video_shift_ratio: float = 0.3333
    video_scale: float = 1.08
    voice_id: str = "google-free"
    style: str = "style1"
    auto_showcase: bool = False
    showcase_dry: bool = False
    auto_post: bool = False
    post_dry: bool = False
    post_delete_after: bool = False
    script_theme: str = Field(default="", max_length=300)


@app.get("/api/ai-video/defaults")
async def get_ai_video_defaults() -> Dict[str, Any]:
    # saved=False: chưa ai lưu (trang dùng localStorage của nó)
    return {**ai_video_defaults.load(), "saved": ai_video_defaults.DEFAULTS_FILE.exists()}


@app.post("/api/ai-video/defaults")
async def post_ai_video_defaults(payload: AiVideoDefaults) -> Dict[str, Any]:
    """Trang /ai-video ghi lại setting đang chọn để bot Telegram dùng."""
    return await asyncio.to_thread(ai_video_defaults.save, payload.model_dump())


@app.post("/api/montage")
async def create_montage(payload: MontageRequest) -> Dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(
            job_manager.create_montage,
            urls=payload.urls,
            script=payload.script,
            voice_id=payload.voice_id,
            seed=payload.seed,
            video_shift_ratio=payload.video_shift_ratio,
            style=payload.style,
            mode=payload.mode,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return snapshot.to_dict()


@app.post("/api/test-render")
async def post_test_render(payload: TestRenderRequest) -> Dict[str, Any]:
    from src.test_render_service import run_test_render
    try:
        res = await run_test_render(
            mode=payload.mode,
            urls=payload.urls,
            script=payload.script,
            duration_sec=payload.duration_sec,
            video_shift_ratio=payload.video_shift_ratio,
            style=payload.style,
            voice_id=payload.voice_id,
        )
        return {
            "status": res.status,
            "message": res.message,
            "final_video_path": res.final_video_path,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/auto-gen")
async def post_auto_gen(payload: AutoGenRequest) -> Dict[str, Any]:
    """Unified Auto gen video endpoint — dispatches to review or montage pipeline.

    Returns a ``JobSnapshot`` so the frontend can subscribe to realtime updates
    via the existing WebSocket connection.
    """
    try:
        if payload.mode == "montage":
            snapshot = await asyncio.to_thread(
                job_manager.create_montage,
                urls=[u.strip() for u in payload.urls if u.strip()],
                script=payload.script,
                voice_id=payload.voice_id or None,
                seed=payload.seed,
                video_shift_ratio=payload.video_shift_ratio,
                style=payload.style,
                mode=payload.mode_pipeline,
            )
        else:
            # review mode — normalize items with video_shift_ratio from request-level
            items = []
            for raw in payload.items or []:
                item_ratio = raw.get("video_shift_ratio")
                if item_ratio is None:
                    item_ratio = payload.video_shift_ratio
                item_scale = raw.get("video_scale")
                if item_scale is None:
                    item_scale = payload.video_scale
                items.append({
                    **raw,
                    "video_shift_ratio": item_ratio,
                    "video_scale": item_scale,
                    "style": payload.style,
                })
            snapshot = await asyncio.to_thread(
                job_manager.create_batch,
                items,
                max_concurrent=1,
                mode=payload.mode_pipeline,
                default_voice_id=payload.voice_id or None,
                default_style=payload.style,
                auto_showcase=payload.auto_showcase,
                showcase_dry=payload.showcase_dry,
                auto_post=payload.auto_post,
                post_dry=payload.post_dry,
                post_delete_after=payload.post_delete_after,
                default_script_theme=payload.script_theme,
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return snapshot.to_dict()


@app.post("/api/profile-ai-video")
async def post_profile_ai_video(payload: ProfileAiVideoRequest) -> Dict[str, Any]:
    """Khởi tạo job crawl profile TikTok và tạo video AI (chạy nền để tránh timeout proxy Next.js)."""
    manifest_file = get_default_log_file_path()

    try:
        snapshot = await asyncio.to_thread(
            job_manager.create_profile_job,
            profile_url=payload.profile_url,
            video_shift_ratio=payload.video_shift_ratio,
            video_scale=payload.video_scale,
            style=payload.style,
            voice_id=payload.voice_id or None,
            mode_pipeline=payload.mode_pipeline,
            force_rerun_all=payload.force_rerun_all,
            max_videos=payload.max_videos,
            log_file_path=str(manifest_file),
            auto_showcase=payload.auto_showcase,
            showcase_dry=payload.showcase_dry,
            auto_post=payload.auto_post,
            post_dry=payload.post_dry,
            post_delete_after=payload.post_delete_after,
            script_theme=payload.script_theme,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Đọc manifest sau khi job đã bắt đầu để trả số liệu crawl về cho frontend.
    # Job chạy nền (daemon thread) nên manifest đã được ghi bởi _run_profile_job.
    manifest_mgr = ProfileManifestManager(manifest_file)
    manifest_data = manifest_mgr.load()
    profile_data = manifest_data.get("profiles", {}).get(normalize_profile_url(payload.profile_url), {})
    crawled_count = profile_data.get("total_crawled", 0)
    skipped_count = profile_data.get("done_count", 0)
    queued_count = profile_data.get("runnable_count", 0)
    # Nếu chưa có (job chưa kịp ghi), ước tính từ số item trong snapshot
    if not queued_count:
        queued_count = len(snapshot.items)

    return {
        "status": "started",
        "message": f"Đã tiếp nhận yêu cầu crawl profile. Đã cào {crawled_count} video, {skipped_count} done (bỏ qua), queue {queued_count} video.",
        "profile_url": normalize_profile_url(payload.profile_url),
        "manifest_path": str(manifest_file),
        "crawled_count": crawled_count,
        "skipped_count": skipped_count,
        "queued_count": queued_count,
        "job": snapshot.to_dict(),
    }


@app.get("/api/showcase/device")
async def get_showcase_device() -> Dict[str, Any]:
    """Kiểm tra điện thoại Android (adb + app TikTok) dùng để thêm sản phẩm vào Showcase."""
    from src.showcase import check_device

    return await asyncio.to_thread(check_device)


_post_flush_thread: Optional[threading.Thread] = None


@app.get("/api/post-schedule")
async def get_post_schedule() -> Dict[str, Any]:
    """Đang hẹn đăng đến ngày giờ nào, slot kế tiếp, số bài chờ."""
    from src.post_schedule import PostSchedule

    from src.web.job_manager import list_post_backlog

    summary = await asyncio.to_thread(PostSchedule().summary)
    summary["flush_running"] = bool(_post_flush_thread and _post_flush_thread.is_alive())
    try:
        backlog = await asyncio.to_thread(list_post_backlog, get_default_log_file_path())
        summary["backlog_count"] = len(backlog)
    except Exception as exc:  # manifest hỏng không được làm hỏng cả màn hình
        logger.warning(f"Không đếm được video chờ lên lịch: {exc}")
        summary["backlog_count"] = 0
    return summary


class PostBacklogRequest(BaseModel):
    post_dry: bool = False
    post_delete_after: bool = False


@app.post("/api/post-backlog")
async def post_backlog(payload: PostBacklogRequest) -> Dict[str, Any]:
    """Lên lịch các video đã gen trước đó (còn file, chưa hẹn), tiếp nối lịch trên TikTok Studio."""
    if _post_flush_thread and _post_flush_thread.is_alive():
        raise HTTPException(status_code=409, detail="Đang đăng hàng chờ, đợi xong rồi chạy.")
    try:
        snapshot = await asyncio.to_thread(
            job_manager.create_post_backlog_job,
            post_dry=payload.post_dry,
            post_delete_after=payload.post_delete_after,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return snapshot.to_dict()


@app.post("/api/post-schedule/check-studio")
async def check_post_schedule_studio() -> Dict[str, Any]:
    """Mở TikTok Studio, đọc màn Posts xem đang hẹn đến ngày giờ nào."""
    from src.tiktok_poster import PostError, check_studio_schedule

    if job_manager.is_running() or (_post_flush_thread and _post_flush_thread.is_alive()):
        raise HTTPException(status_code=409, detail="Đang có tác vụ dùng trình duyệt đăng bài, đợi xong rồi kiểm tra.")
    try:
        return await asyncio.to_thread(check_studio_schedule)
    except PostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/post-schedule/flush")
async def flush_post_schedule() -> Dict[str, Any]:
    """Đăng các bài ở hàng chờ (quá 10 ngày lúc gen) khi đã tới hạn hẹn được."""
    global _post_flush_thread
    from src.tiktok_poster import flush_waiting

    if job_manager.is_running():
        raise HTTPException(status_code=409, detail="Job gen video đang chạy, đợi xong rồi đăng hàng chờ.")
    if _post_flush_thread and _post_flush_thread.is_alive():
        raise HTTPException(status_code=409, detail="Đang đăng hàng chờ.")
    _post_flush_thread = threading.Thread(target=flush_waiting, name="tiktok-post-flush", daemon=True)
    _post_flush_thread.start()
    return {"ok": True}


@app.get("/api/profile-ai-video/log")
async def get_profile_ai_video_log() -> Dict[str, Any]:
    """Trả về nội dung manifest JSON log hiện tại."""
    manifest_file = get_default_log_file_path()
    manifest_mgr = ProfileManifestManager(manifest_file)
    data = manifest_mgr.load()
    return {
        "manifest_path": str(manifest_file),
        "log": data,
        "total_logged": len(data.get("videos", {})),
    }


@app.websocket("/api/job/ws")
async def job_ws(websocket: WebSocket) -> None:
    """WebSocket: phát snapshot ngay và mỗi khi job_manager publish.

    Sử dụng thay cho SSE để tránh tự tạo nhiều kết nối liên tiếp khi job kết thúc.
    """
    await websocket.accept()
    loop = asyncio.get_running_loop()
    client = websocket.client
    logger.info("Job WebSocket connected: client=%s", client)
    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=64)
    state = {"active": True}

    def enqueue_snapshot(payload: Dict[str, Any]) -> None:
        if not state["active"]:
            return
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.debug("WS queue full; dropping snapshot")

    def listener(snapshot: JobSnapshot) -> None:
        if not state["active"]:
            return
        try:
            loop.call_soon_threadsafe(
                enqueue_snapshot, _serialize_snapshot(snapshot)
            )
        except RuntimeError:
            logger.debug("WS event loop closed; skip enqueue")

    job_manager.subscribe(listener)

    try:
        current_payload = _serialize_snapshot(job_manager.current)
        await websocket.send_text(json.dumps(current_payload, ensure_ascii=False))

        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=20)
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "ping"}))
                continue
            await websocket.send_text(json.dumps(payload, ensure_ascii=False))
    except WebSocketDisconnect:
        logger.info("Job WebSocket disconnected: client=%s", client)
    except Exception:
        current = job_manager.current
        logger.exception(
            "Job WebSocket send failed: client=%s job_id=%s status=%s",
            client,
            current.job_id,
            current.status,
        )
    finally:
        state["active"] = False
        job_manager.unsubscribe(listener)


class PickFilePayload(BaseModel):
    title: Optional[str] = "Chọn file ảnh"
    filter: Optional[str] = "Image Files|*.png;*.jpg;*.jpeg;*.webp;*.bmp|All Files|*.*"


@app.post("/api/pick-folder")
async def pick_folder() -> Dict[str, Any]:
    # Native dialogs block until the user closes them. Run outside FastAPI's
    # event-loop so the UI and other API calls remain responsive meanwhile.
    path = await asyncio.to_thread(_pick_folder_dialog)
    return {"path": path}


@app.post("/api/pick-file")
async def pick_file(payload: Optional[PickFilePayload] = None) -> Dict[str, Any]:
    title = (payload.title if payload and payload.title else "Chọn file ảnh")
    file_filter = (payload.filter if payload and payload.filter else "Image Files|*.png;*.jpg;*.jpeg;*.webp;*.bmp|All Files|*.*")
    path = await asyncio.to_thread(_pick_file_dialog, title=title, file_filter=file_filter)
    return {"path": path}


@app.post("/api/open-folder")
async def open_folder(payload: PathPayload) -> Dict[str, Any]:
    target = _validate_local_path(payload.path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Thư mục không tồn tại.")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Đường dẫn không phải thư mục.")
    ok = _open_path(target)
    return {"ok": ok, "path": str(target)}


@app.post("/api/reveal-file")
async def reveal_file(payload: PathPayload) -> Dict[str, Any]:
    target = _validate_local_path(payload.path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File không tồn tại.")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Đường dẫn không phải file.")
    ok = _reveal_file(target)
    return {"ok": ok, "path": str(target)}


@app.exception_handler(Exception)
async def unhandled_exception(_, exc: Exception) -> JSONResponse:  # type: ignore[no-untyped-def]
    logger.exception("unhandled error")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Lỗi máy chủ: {exc!s}"},
    )


__all__ = [
    "app",
    "job_manager",
    "ALLOWED_ORIGINS",
]
