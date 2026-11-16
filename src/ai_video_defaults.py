"""ai_video_defaults.py

Lưu thông số form của trang /ai-video ở phía backend (file JSON), để các
nguồn chạy không có trình duyệt — như bot Telegram — dùng đúng setting đang
chọn trên giao diện. Trang /ai-video ghi file này mỗi khi form thay đổi.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("tiktok.ai_video_defaults")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULTS_FILE = Path(
    os.environ.get("AI_VIDEO_DEFAULTS_FILE", PROJECT_ROOT / ".ai_video_defaults.json")
)

STYLES = ("style1", "style2", "style3")

FALLBACK: Dict[str, Any] = {
    "video_shift_ratio": 0.3333,
    "video_scale": 1.08,
    "voice_id": "google-free",
    "style": "style1",
    "auto_showcase": False,
    "showcase_dry": False,
    "auto_post": False,
    "post_dry": False,
    "post_delete_after": False,
    "script_theme": "",
}

_lock = threading.Lock()


def _num(value: Any, fallback: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return fallback
    return v if lo <= v <= hi else fallback


def normalize(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ép kiểu + chặn giá trị lỗi, giống handleSubmit của trang /ai-video."""
    raw = raw or {}
    out = dict(FALLBACK)
    out["video_shift_ratio"] = _num(raw.get("video_shift_ratio"), FALLBACK["video_shift_ratio"], 0.0, 1.0)
    out["video_scale"] = _num(raw.get("video_scale"), FALLBACK["video_scale"], 0.1, 3.0)
    voice = str(raw.get("voice_id") or "").strip()
    out["voice_id"] = voice or FALLBACK["voice_id"]
    style = raw.get("style")
    out["style"] = style if style in STYLES else FALLBACK["style"]
    for key in ("auto_showcase", "showcase_dry", "auto_post", "post_dry", "post_delete_after"):
        out[key] = bool(raw.get(key, FALLBACK[key]))
    out["script_theme"] = str(raw.get("script_theme") or "").strip()[:300]
    return out


def load(path: Optional[Path] = None) -> Dict[str, Any]:
    target = path or DEFAULTS_FILE
    with _lock:
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return normalize(None)
        except Exception as exc:
            logger.warning(f"Không đọc được {target}: {exc}")
            return normalize(None)
    return normalize(data if isinstance(data, dict) else None)


def save(raw: Dict[str, Any], path: Optional[Path] = None) -> Dict[str, Any]:
    target = path or DEFAULTS_FILE
    data = normalize(raw)
    with _lock:
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    return data


def build_batch_kwargs(
    urls: List[str],
    defaults: Dict[str, Any],
    themes: Optional[List[Optional[str]]] = None,
    scales: Optional[List[Optional[float]]] = None,
    shifts: Optional[List[Optional[float]]] = None,
    post_ats: Optional[List[Optional[str]]] = None,
) -> Dict[str, Any]:
    """Tham số cho ``JobManager.create_batch`` — y như nút Chạy của /ai-video.

    ``themes[i]`` là chủ đề riêng của link i (None = theo chủ đề mặc định của setting).
    ``shifts[i]`` là tỷ lệ kéo video (Y-offset) riêng, ``scales[i]`` là scale riêng (None = theo setting); ``post_ats[i]`` là giờ đăng hẹn riêng dạng
    ISO ``YYYY-MM-DDTHH:MM`` (None = slot tự động).
    """
    d = normalize(defaults)
    voice = None if d["voice_id"] == "default" else d["voice_id"]
    items = []
    for i, u in enumerate(urls):
        item: Dict[str, Any] = {
            "url": u,
            "video_shift_ratio": d["video_shift_ratio"],
            "video_scale": d["video_scale"],
            "voice_id": voice,
            "style": d["style"],
        }
        shift = shifts[i] if shifts and i < len(shifts) else None
        if shift is not None:
            item["video_shift_ratio"] = _num(shift, d["video_shift_ratio"], 0.0, 1.0)
        scale = scales[i] if scales and i < len(scales) else None
        if scale is not None:
            item["video_scale"] = _num(scale, d["video_scale"], 0.1, 3.0)
        post_at = post_ats[i] if post_ats and i < len(post_ats) else None
        if post_at:
            item["post_at"] = post_at
        theme = (themes[i] if themes and i < len(themes) else None) or ""
        if theme.strip():
            item["script_theme"] = theme.strip()[:300]
        items.append(item)
    return {
        "items_payload": items,
        "default_voice_id": voice,
        "default_style": d["style"],
        "auto_showcase": d["auto_showcase"],
        "showcase_dry": d["showcase_dry"],
        "auto_post": d["auto_post"],
        "post_dry": d["post_dry"],
        "post_delete_after": d["post_delete_after"],
        "default_script_theme": d["script_theme"] or None,
    }


def describe(defaults: Dict[str, Any]) -> str:
    d = normalize(defaults)
    onoff = lambda b: "bật" if b else "tắt"  # noqa: E731
    lines = [
        f"Style: {d['style']}",
        f"Giọng: {d['voice_id']}",
        f"Shift: {d['video_shift_ratio']} · Scale: {d['video_scale']}",
        f"Chủ đề: {d['script_theme'] or '(AI tự chọn)'}",
        f"Showcase: {onoff(d['auto_showcase'])}" + (" (chạy thử)" if d["showcase_dry"] else ""),
        f"Đăng hẹn giờ: {onoff(d['auto_post'])}" + (" (chạy thử)" if d["post_dry"] else "")
        + (" · xóa sau khi hẹn" if d["post_delete_after"] else ""),
    ]
    return "\n".join(lines)
