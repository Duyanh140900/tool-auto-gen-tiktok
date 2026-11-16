"""post_schedule.py

Sổ lịch đăng bài hẹn giờ TikTok: cố định 4 video/ngày vào 08:00, 12:00, 18:00,
22:00. Mỗi video mới lấy slot kế tiếp sau slot muộn nhất đã hẹn; hết giờ trong
ngày thì sang 08:00 ngày hôm sau.

Mốc "đang hẹn đến đâu" lấy từ màn Posts của TikTok Studio (bài có nhãn đồng hồ
hẹn giờ), tool đọc mỗi lần chạy -> ``studio_last_slot``. Các slot tool hẹn sau lần
đọc đó (sổ lịch) được cộng thêm để không đè slot.

Ràng buộc của TikTok Studio:
  - Giờ hẹn phải cách hiện tại ít nhất ``MIN_LEAD`` (15 phút) -> slot đã trôi
    qua thì nhảy tới slot hợp lệ gần nhất.
  - Chỉ hẹn trước tối đa ``POST_SCHEDULE_MAX_DAYS`` ngày (mặc định 30) -> video
    có slot vượt quá thì nằm ở hàng chờ (``waiting``) cho tới khi tới hạn.

Sổ lịch lưu ở ``<FINAL_OUTPUT_DIR>/post_schedule.json``::

    {"studio_last_slot": "2026-11-03T22:00" | null, "studio_checked_at": "...",
     "posts": [{"slot", "status", "source_url", "video_path", "product", "short_name", ...}]}
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("tiktok.post_schedule")

SLOT_TIMES = [time(8, 0), time(12, 0), time(18, 0), time(22, 0)]
MIN_LEAD = timedelta(minutes=15)

# Trạng thái bài trong sổ: scheduled = đã hẹn trên TikTok (giữ slot), unverified = đã bấm
# Schedule nhưng chưa xác nhận được (vẫn giữ slot để không hẹn trùng giờ),
# waiting = chờ tới hạn, error = lỗi trước khi bấm Schedule.
SLOT_TAKEN_STATUSES = {"scheduled", "unverified"}

_LOCK = threading.RLock()


def max_days_ahead() -> int:
    try:
        return int(os.environ.get("POST_SCHEDULE_MAX_DAYS", "30"))
    except ValueError:
        return 30


def next_slot_after(last_slot: Optional[datetime], now: datetime) -> datetime:
    """Slot đăng kế tiếp sau ``last_slot`` và cách ``now`` ít nhất ``MIN_LEAD``."""
    earliest = now + MIN_LEAD
    start = last_slot if last_slot and last_slot >= earliest else None
    day = (start or earliest).date()
    while True:
        for t in SLOT_TIMES:
            candidate = datetime.combine(day, t)
            if start is not None and candidate <= start:
                continue
            if candidate < earliest:
                continue
            return candidate
        day += timedelta(days=1)


def within_horizon(slot: datetime, now: datetime) -> bool:
    return slot <= now + timedelta(days=max_days_ahead())


def get_default_schedule_path() -> Path:
    from config import settings

    output_dir = Path(getattr(settings, "FINAL_OUTPUT_DIR", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / "post_schedule.json"


class PostSchedule:
    """Đọc/ghi sổ lịch đăng (an toàn giữa các luồng)."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else get_default_schedule_path()

    # -------- IO --------
    def load(self) -> Dict[str, Any]:
        with _LOCK:
            empty = {"studio_last_slot": None, "studio_checked_at": None, "posts": []}
            if not self.path.exists():
                return empty
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning(f"Không đọc được sổ lịch đăng ({self.path}): {exc}")
                return empty
            for key, value in empty.items():
                data.setdefault(key, value)
            return data

    def _save(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # -------- Mốc lịch --------
    def last_slot(self) -> Optional[datetime]:
        """Slot muộn nhất: lần đọc TikTok Studio gần nhất + slot tool hẹn sau lần đọc đó.

        Bài hẹn giờ riêng (``custom_slot``) không tính, để không đẩy các slot tự động ra sau mốc đó.
        """
        data = self.load()
        checked_at = data.get("studio_checked_at") or ""
        slots = [
            datetime.fromisoformat(p["slot"])
            for p in data["posts"]
            if p.get("status") in SLOT_TAKEN_STATUSES and p.get("slot") and not p.get("custom_slot")
            and (p.get("updated_at") or "") >= checked_at
        ]
        if data.get("studio_last_slot"):
            slots.append(datetime.fromisoformat(data["studio_last_slot"]))
        return max(slots) if slots else None

    def set_studio_last_slot(self, value: Optional[datetime], checked_at: Optional[datetime] = None) -> None:
        """Lưu mốc hẹn muộn nhất vừa đọc từ màn Posts của TikTok Studio."""
        with _LOCK:
            data = self.load()
            data["studio_last_slot"] = value.isoformat(timespec="minutes") if value else None
            data["studio_checked_at"] = (checked_at or datetime.now()).isoformat(timespec="seconds")
            self._save(data)

    def next_slot(self, now: Optional[datetime] = None) -> datetime:
        return next_slot_after(self.last_slot(), now or datetime.now())

    # -------- Bài đăng --------
    def upsert(self, record: Dict[str, Any]) -> None:
        """Thêm/cập nhật bài theo ``video_path``."""
        with _LOCK:
            data = self.load()
            posts: List[Dict[str, Any]] = data["posts"]
            for i, p in enumerate(posts):
                if p.get("video_path") == record.get("video_path"):
                    posts[i] = {**p, **record}
                    break
            else:
                posts.append(record)
            self._save(data)

    def find(self, video_path: str) -> Optional[Dict[str, Any]]:
        return next((p for p in self.load()["posts"] if p.get("video_path") == video_path), None)

    def waiting(self) -> List[Dict[str, Any]]:
        return [p for p in self.load()["posts"] if p.get("status") == "waiting"]

    def summary(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        now = now or datetime.now()
        data = self.load()
        last = self.last_slot()
        nxt = next_slot_after(last, now)
        posts = data["posts"]
        return {
            "path": str(self.path),
            "studio_last_slot": data.get("studio_last_slot"),
            "studio_checked_at": data.get("studio_checked_at"),
            "last_slot": last.isoformat(timespec="minutes") if last else None,
            "next_slot": nxt.isoformat(timespec="minutes"),
            "next_slot_within_horizon": within_horizon(nxt, now),
            "max_days_ahead": max_days_ahead(),
            "scheduled_count": sum(1 for p in posts if p.get("status") == "scheduled"),
            "waiting_count": sum(1 for p in posts if p.get("status") == "waiting"),
            "error_count": sum(1 for p in posts if p.get("status") == "error"),
        }


__all__ = ["PostSchedule", "SLOT_TIMES", "next_slot_after", "within_horizon", "get_default_schedule_path"]
