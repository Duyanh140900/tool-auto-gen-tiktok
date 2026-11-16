"""profile_crawler.py

Cào danh sách video từ trang cá nhân TikTok và quản lý file JSON log/manifest
để tự động bỏ qua video đã hoàn thành và lưu thông tin sản phẩm/kết quả.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yt_dlp
from config import settings

logger = logging.getLogger("tiktok.profile_crawler")

# Job gen video và luồng Showcase cùng ghi manifest -> tuần tự hóa read-modify-write.
_MANIFEST_WRITE_LOCK = threading.RLock()


class _YtDlpLogger:
    """Chuyển log của yt-dlp vào logger của tool (thay vì chỉ in ra stderr)."""

    def __init__(self, errors: Optional[List[str]] = None) -> None:
        self.errors = errors if errors is not None else []
        self._log = logging.getLogger("tiktok.yt_dlp")

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug] "):
            self._log.debug(msg)

    def info(self, msg: str) -> None:
        self._log.debug(msg)

    def warning(self, msg: str) -> None:
        self._log.warning(msg)

    def error(self, msg: str) -> None:
        self._log.error(msg)
        clean = re.sub(r"^ERROR:\s*", "", str(msg)).strip()
        if clean and clean not in self.errors:
            self.errors.append(clean)


def _looks_like_bot_challenge(html: str) -> bool:
    """TikTok trả trang WAF/captcha (rất ngắn, có SlardarWAF) thay vì HTML profile."""
    return len(html) < 5000 and ("SlardarWAF" in html or "slardar_us_waf" in html or "captcha" in html.lower())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_profile_url(raw_url: str) -> str:
    """Chuẩn hóa link profile TikTok về dạng chuẩn https://www.tiktok.com/@username."""
    cleaned = (raw_url or "").strip()
    if not cleaned:
        raise ValueError("Link profile TikTok không được để trống.")

    if cleaned.startswith("tiktokuser:"):
        return cleaned

    # Xử lý trường hợp nhập username trực tiếp: "@username" hoặc "username"
    if not cleaned.startswith("http://") and not cleaned.startswith("https://"):
        user = cleaned if cleaned.startswith("@") else f"@{cleaned}"
        return f"https://www.tiktok.com/{user}"

    # Bỏ query params và trailing slash
    match = re.search(r"https?://(?:www\.)?tiktok\.com/(@[A-Za-z0-9_.-]+)", cleaned, re.IGNORECASE)
    if match:
        user = match.group(1)
        return f"https://www.tiktok.com/{user}"

    return cleaned.split("?")[0].rstrip("/")


def normalize_video_url(url: str, video_id: Optional[str] = None) -> str:
    """Chuẩn hóa link video TikTok về dạng canonical."""
    clean = (url or "").strip().split("?")[0].rstrip("/")
    if video_id and not clean.startswith("http"):
        return f"https://www.tiktok.com/video/{video_id}"
    return clean


def extract_video_id(url: str) -> Optional[str]:
    """Trích xuất ID video từ link TikTok."""
    if not url:
        return None
    match = re.search(r"/video/(\d+)", url)
    if match:
        return match.group(1)
    match_id = re.search(r"(\d{15,22})", url)
    if match_id:
        return match_id.group(1)
    return None


def get_default_log_file_path() -> Path:
    """Trả về đường dẫn file manifest JSON log mặc định trong thư mục output."""
    output_dir = Path(getattr(settings, "FINAL_OUTPUT_DIR", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / "profile_ai_video_log.json"


def resolve_tiktok_sec_uid(
    profile_url: str,
    sample_video_url: Optional[str] = None,
    cookie_file: Optional[str] = None,
    reasons: Optional[List[str]] = None,
) -> Optional[str]:
    """Cố gắng tìm secUid của creator TikTok khi yt-dlp profile extractor bị lỗi.

    1. Quét HTML trang profile qua HTTP request với User-Agent browser để tìm mẫu secUid.
    2. Nếu không tìm được và có sample_video_url, dùng yt-dlp trích xuất video đó để lấy channel_id.
    ``reasons`` (nếu truyền) sẽ được thêm lý do thất bại của từng cách để báo lỗi rõ ràng.
    """
    reasons = reasons if reasons is not None else []
    canonical_profile = normalize_profile_url(profile_url)
    if canonical_profile.startswith("tiktokuser:"):
        return canonical_profile.replace("tiktokuser:", "").strip()

    # Cách 1: Request trang web profile trực tiếp tìm secUid
    try:
        import urllib.request
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.tiktok.com/",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        req = urllib.request.Request(canonical_profile, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as response:
            html = response.read().decode("utf-8", errors="ignore")
            # Tìm mẫu secUid thông dụng của TikTok (bắt đầu bằng MS4wLj)
            match = re.search(r'["\']secUid["\']\s*:\s*["\'](MS4wLj[a-zA-Z0-9_\-]+)["\']', html)
            if match:
                sec_uid = match.group(1)
                logger.info(f"Đã trích xuất secUid từ HTML của profile: {sec_uid}")
                return sec_uid
            # Tìm kiếm trực tiếp mẫu chuỗi Base64 đặc trưng của secUid
            match_generic = re.search(r'(MS4wLjABAAAA[a-zA-Z0-9_\-]{40,80})', html)
            if match_generic:
                sec_uid = match_generic.group(1)
                logger.info(f"Đã trích xuất secUid regex từ HTML của profile: {sec_uid}")
                return sec_uid
            if _looks_like_bot_challenge(html):
                msg = (f"TikTok trả về trang chống bot (WAF, {len(html)} bytes) thay vì trang profile "
                       f"nên không tìm được secUid")
            else:
                msg = f"HTML trang profile ({len(html)} bytes) không chứa secUid"
            logger.warning(msg)
            reasons.append(msg)
    except Exception as exc:
        msg = f"Không tải được trang profile để tìm secUid: {exc}"
        logger.warning(msg)
        reasons.append(msg)

    # Cách 2: Trích xuất channel_id từ video mẫu nếu có
    if sample_video_url:
        try:
            ydl_video_opts: Dict[str, Any] = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
                "ignoreerrors": True,
            }
            if cookie_file and Path(cookie_file).exists():
                ydl_video_opts["cookiefile"] = cookie_file
            with yt_dlp.YoutubeDL(ydl_video_opts) as ydl:
                vid_info = ydl.extract_info(sample_video_url, download=False)
                if vid_info:
                    sec_uid = vid_info.get("channel_id")
                    if sec_uid and (str(sec_uid).startswith("MS4wLj") or len(str(sec_uid)) > 25):
                        logger.info(f"Đã trích xuất secUid từ video mẫu ({sample_video_url}): {sec_uid}")
                        return str(sec_uid)
            msg = f"Video mẫu {sample_video_url} không trả về channel_id hợp lệ"
            logger.warning(msg)
            reasons.append(msg)
        except Exception as exc:
            msg = f"Không lấy được channel_id từ video mẫu {sample_video_url}: {exc}"
            logger.warning(msg)
            reasons.append(msg)
    else:
        reasons.append("Chưa có video mẫu nào của profile trong manifest để dò secUid")

    return None


def crawl_tiktok_profile(
    profile_url: str,
    max_videos: Optional[int] = None,
    sample_video_url: Optional[str] = None,
    sec_uid: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Cào toàn bộ danh sách video từ profile TikTok bằng yt-dlp.

    Sử dụng extract_flat="in_playlist" kèm headers giả lập browser hiện đại
    để bypass anti-bot và trích xuất playlist đầy đủ.
    Nếu trích xuất URL hồ sơ bị lỗi (ví dụ Unable to extract secondary user ID),
    tự động giải mã secUid để gọi playlist qua kênh tiktokuser:channel_id.
    """
    canonical_profile = normalize_profile_url(profile_url)
    target_crawl_url = canonical_profile
    active_sec_uid = sec_uid
    if sec_uid:
        target_crawl_url = f"tiktokuser:{sec_uid}"
    elif canonical_profile.startswith("tiktokuser:"):
        target_crawl_url = canonical_profile
        active_sec_uid = canonical_profile.split(":", 1)[1].strip()

    logger.info(f"Bắt đầu crawl profile TikTok: {canonical_profile} (target={target_crawl_url})")

    custom_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.tiktok.com/",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    ytdlp_errors: List[str] = []
    ydl_opts: Dict[str, Any] = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "http_headers": custom_headers,
        "logger": _YtDlpLogger(ytdlp_errors),
    }

    cookie_file = str(getattr(settings, "TIKTOK_COOKIES_FILE", "")).strip()
    if cookie_file and Path(cookie_file).exists():
        ydl_opts["cookiefile"] = cookie_file
    elif cookie_file:
        logger.warning(f"TIKTOK_COOKIES_FILE={cookie_file} không tồn tại, crawl không dùng cookies")
    logger.debug(f"yt-dlp {getattr(yt_dlp.version, '__version__', '?')}, cookies={'có' if 'cookiefile' in ydl_opts else 'không'}")

    if max_videos and max_videos > 0:
        ydl_opts["playlist_items"] = f"1:{max_videos}"

    info = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_crawl_url, download=False)
    except Exception as exc:
        logger.warning(f"Lần crawl đầu thất bại cho {target_crawl_url}: {exc}. Thử lại với extract_flat=True...")
        try:
            ydl_opts["extract_flat"] = True
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_crawl_url, download=False)
        except Exception as retry_exc:
            logger.warning(f"yt-dlp extract profile với URL {target_crawl_url} thất bại: {retry_exc}")
            ytdlp_errors.append(str(retry_exc))

    sec_uid_reasons: List[str] = []
    # Nếu chưa có danh sách video và target_crawl_url chưa phải là tiktokuser:
    if (not info or not info.get("entries")) and not target_crawl_url.startswith("tiktokuser:"):
        found_sec_uid = resolve_tiktok_sec_uid(
            canonical_profile,
            sample_video_url=sample_video_url,
            cookie_file=ydl_opts.get("cookiefile"),
            reasons=sec_uid_reasons,
        )
        if found_sec_uid:
            active_sec_uid = found_sec_uid
            alt_url = f"tiktokuser:{found_sec_uid}"
            logger.info(f"Thử crawl lại bằng kênh trực tiếp secUid: {alt_url}")
            try:
                ydl_opts["extract_flat"] = "in_playlist"
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(alt_url, download=False)
            except Exception as sec_exc:
                logger.warning(f"Crawl với {alt_url} thất bại: {sec_exc}")
                ytdlp_errors.append(str(sec_exc))

    entries = (info or {}).get("entries") or []
    if not entries and (ytdlp_errors or sec_uid_reasons):
        # Không lấy được video: nêu rõ lý do để UI/log hiển thị thay vì "không tìm thấy video".
        reasons = [f"yt-dlp: {e}" for e in ytdlp_errors] + sec_uid_reasons
        detail = "; ".join(dict.fromkeys(reasons))
        logger.error(f"Crawl profile {canonical_profile} thất bại: {detail}")
        raise RuntimeError(f"Crawl profile thất bại: {detail}")
    if not info:
        return []
    videos: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()

    for entry in entries:
        if not entry or not isinstance(entry, dict):
            continue

        raw_id = str(entry.get("id") or "")
        url = entry.get("url") or ""
        webpage_url = entry.get("webpage_url") or ""
        title = entry.get("title") or ""

        target_url = webpage_url or url
        if not target_url:
            continue

        video_id = extract_video_id(target_url) or raw_id or extract_video_id(url)
        if not video_id:
            continue

        if video_id in seen_ids:
            continue
        seen_ids.add(video_id)

        canonical_video_url = normalize_video_url(target_url, video_id)

        v_entry: Dict[str, Any] = {
            "id": video_id,
            "url": canonical_video_url,
            "title": title,
            "profile_url": canonical_profile,
        }
        if active_sec_uid:
            v_entry["sec_uid"] = active_sec_uid
        videos.append(v_entry)

    logger.info(f"Crawl thành công {len(videos)} video từ profile {canonical_profile}")
    return videos


class ProfileManifestManager:
    """Quản lý đọc / ghi file JSON log của các video từ profile."""

    def __init__(self, log_path: Optional[Union[Path, str]] = None) -> None:
        self.log_path = Path(log_path) if log_path else get_default_log_file_path()

    def load(self) -> Dict[str, Any]:
        """Đọc và trả về toàn bộ dữ liệu manifest JSON."""
        return self._read_data()

    @staticmethod
    def _extract_username(url: str) -> Optional[str]:
        if not url:
            return None
        match = re.search(r"@([a-zA-Z0-9_\.\-]+)", url)
        if match:
            return match.group(1).lower()
        return None

    def get_profile_sec_uid(self, profile_url: str) -> Optional[str]:
        """Lấy sec_uid đã lưu trong manifest cho profile này nếu có."""
        data = self._read_data()
        profiles_map = data.get("profiles", {})
        canonical_profile = normalize_profile_url(profile_url)
        prof = profiles_map.get(canonical_profile)
        if prof and isinstance(prof, dict) and prof.get("sec_uid"):
            return str(prof["sec_uid"]).strip()
        username = self._extract_username(canonical_profile)
        if username:
            for p_url, p_data in profiles_map.items():
                if isinstance(p_data, dict) and self._extract_username(p_url) == username:
                    if p_data.get("sec_uid"):
                        return str(p_data["sec_uid"]).strip()
        return None

    def save_profile_sec_uid(self, profile_url: str, sec_uid: str) -> None:
        """Lưu sec_uid vào manifest cho profile."""
        if not sec_uid:
            return
        data = self._read_data()
        profiles_map = data.get("profiles", {})
        canonical_profile = normalize_profile_url(profile_url)
        prof = profiles_map.setdefault(canonical_profile, {})
        prof["sec_uid"] = sec_uid
        data["profiles"] = profiles_map
        self._write_data(data)

    def get_sample_video_url(self, profile_url: str) -> Optional[str]:
        """Tìm 1 URL video mẫu đã biết của creator này trong manifest để phân giải secUid."""
        data = self._read_data()
        videos_map = data.get("videos", {})
        canonical_profile = normalize_profile_url(profile_url)
        username = self._extract_username(canonical_profile)

        for url, item in videos_map.items():
            if not isinstance(item, dict):
                continue
            v_prof = item.get("profile_url") or ""
            v_url = item.get("url") or url
            if v_prof and normalize_profile_url(v_prof) == canonical_profile:
                return v_url
            if username and f"@{username}/" in v_url.lower():
                return v_url
        return None

    def get_videos_for_profile(self, profile_url: str) -> List[Dict[str, Any]]:
        """Lấy toàn bộ danh sách video đã được lưu trong manifest log thuộc profile này.

        Hỗ trợ match theo profile_url chuẩn hóa hoặc username (@username).
        Trả về danh sách dict theo cấu trúc giống như output của crawl_tiktok_profile.
        """
        data = self._read_data()
        videos_map: Dict[str, Any] = data.get("videos", {})
        canonical_profile = normalize_profile_url(profile_url)
        username = self._extract_username(canonical_profile)

        results: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()

        for raw_key, item in videos_map.items():
            if not isinstance(item, dict):
                continue
            item_prof = item.get("profile_url") or ""
            item_url = item.get("url") or raw_key

            matches = False
            if item_prof and normalize_profile_url(item_prof) == canonical_profile:
                matches = True
            elif username:
                if self._extract_username(item_prof) == username:
                    matches = True
                elif f"@{username}/" in item_url.lower() or f"@{username}" in item_url.lower():
                    matches = True
            elif not item_prof and len(videos_map) > 0 and len(data.get("profiles", {})) <= 1:
                matches = True

            if matches:
                v_id = item.get("video_id") or extract_video_id(item_url) or raw_key
                if v_id in seen_ids:
                    continue
                seen_ids.add(v_id)
                results.append({
                    "id": v_id,
                    "url": item_url,
                    "title": item.get("title") or "",
                    "profile_url": item_prof or canonical_profile,
                })

        return results

    def _read_data(self) -> Dict[str, Any]:
        if not self.log_path.exists():
            return {"profiles": {}, "videos": {}}
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return {"profiles": {}, "videos": {}}
                if "videos" not in data or not isinstance(data["videos"], dict):
                    data["videos"] = {}
                if "profiles" not in data or not isinstance(data["profiles"], dict):
                    data["profiles"] = {}
                return data
        except Exception as exc:
            logger.warning(f"Không thể đọc file log JSON ({self.log_path}): {exc}")
            return {"profiles": {}, "videos": {}}

    def _write_data(self, data: Dict[str, Any]) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.log_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            temp_path.replace(self.log_path)
        except Exception as exc:
            logger.error(f"Không thể ghi file log JSON ({self.log_path}): {exc}")

    def filter_runnable_videos(
        self,
        crawled_videos: Any,
        profile_url: Any = "",
        force_rerun_all: bool = False,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Phân loại danh sách video crawl:

        1. to_run: video chưa có trong manifest hoặc có status != 'done' (status == 'error', 'pending', etc.)
        2. skipped_done: video đã có status == 'done' (trừ khi force_rerun_all=True)
        3. rerun_failed: video đã có trong log nhưng trước đó bị lỗi ('error')

        Đồng thời ghi nhận profile_url và danh sách video vào manifest với trạng thái ban đầu.
        Tự động nhận diện nếu đối số bị truyền ngược (profile_url, crawled_videos)
        để tránh lỗi AttributeError: 'list' object has no attribute 'strip'.
        """
        if isinstance(crawled_videos, str) and isinstance(profile_url, list):
            profile_url, crawled_videos = crawled_videos, profile_url
        elif not isinstance(crawled_videos, list):
            crawled_videos = []

        data = self._read_data()
        videos_map: Dict[str, Any] = data.get("videos", {})
        profiles_map: Dict[str, Any] = data.get("profiles", {})

        canonical_profile = normalize_profile_url(profile_url)
        now_str = _now_iso()

        to_run: List[Dict[str, Any]] = []
        skipped_done: List[Dict[str, Any]] = []
        rerun_failed: List[Dict[str, Any]] = []

        for item in crawled_videos:
            url = item.get("url") or ""
            video_id = item.get("id") or extract_video_id(url) or url
            title = item.get("title") or ""

            existing = videos_map.get(url) or (videos_map.get(video_id) if video_id else None)

            if existing and existing.get("status") == "done" and not force_rerun_all:
                skipped_done.append(item)
            elif existing and existing.get("status") == "error":
                rerun_failed.append(item)
                to_run.append(item)
            else:
                # Video mới hoàn toàn hoặc chưa hoàn thành hoặc force_rerun_all
                to_run.append(item)
                # Khởi tạo bản ghi ban đầu nếu chưa có
                if not existing:
                    videos_map[url] = {
                        "video_id": video_id,
                        "url": url,
                        "profile_url": canonical_profile,
                        "title": title,
                        "product_name": None,
                        "file_name": None,
                        "final_video_path": None,
                        "status": "pending",
                        "error": None,
                        "created_at": now_str,
                        "updated_at": now_str,
                    }

        # Cập nhật thông tin profile (giữ lại các trường bổ sung như sec_uid)
        prof_entry = profiles_map.setdefault(canonical_profile, {})
        sec_uid_val = prof_entry.get("sec_uid")
        for item in crawled_videos:
            if not sec_uid_val and item.get("sec_uid"):
                sec_uid_val = item["sec_uid"]
                break

        prof_entry["last_crawled_at"] = now_str
        if len(crawled_videos) > 0 or "total_crawled" not in prof_entry:
            prof_entry["total_crawled"] = len(crawled_videos)
        prof_entry["runnable_count"] = len(to_run)
        prof_entry["done_count"] = len(skipped_done)
        prof_entry["error_count"] = len(rerun_failed)
        if sec_uid_val:
            prof_entry["sec_uid"] = sec_uid_val

        data["videos"] = videos_map
        data["profiles"] = profiles_map
        self._write_data(data)

        return to_run, skipped_done, rerun_failed

    def update_video_status(
        self,
        url: str,
        status: str,
        title: Optional[str] = None,
        product_name: Optional[str] = None,
        file_name: Optional[str] = None,
        final_video_path: Optional[str] = None,
        error: Optional[str] = None,
        profile_url: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Cập nhật tiến trình/kết quả xử lý của một video vào manifest JSON."""
        with _MANIFEST_WRITE_LOCK:
            self._update_video_status_locked(
                url, status, title, product_name, file_name, final_video_path, error, profile_url
            )

    def update_showcase_status(self, url: str, showcase: Dict[str, Any]) -> None:
        """Lưu kết quả thêm sản phẩm vào Showcase của video (ghi từ luồng showcase)."""
        with _MANIFEST_WRITE_LOCK:
            data = self._read_data()
            videos_map: Dict[str, Any] = data.get("videos", {})
            video_id = extract_video_id(url) or url
            record = videos_map.get(url) or videos_map.get(video_id)
            if record is None:
                record = {"video_id": video_id, "url": url, "created_at": _now_iso()}
            record["showcase"] = showcase
            videos_map[url] = record
            data["videos"] = videos_map
            self._write_data(data)

    def _update_video_status_locked(
        self,
        url: str,
        status: str,
        title: Optional[str],
        product_name: Optional[str],
        file_name: Optional[str],
        final_video_path: Optional[str],
        error: Optional[str],
        profile_url: Optional[str],
    ) -> None:
        data = self._read_data()
        videos_map: Dict[str, Any] = data.get("videos", {})

        video_id = extract_video_id(url) or url
        now_str = _now_iso()

        existing = videos_map.get(url) or videos_map.get(video_id) or {}

        # Tự động suy ra file_name nếu có final_video_path
        computed_file_name = file_name or existing.get("file_name")
        if not computed_file_name and final_video_path:
            try:
                computed_file_name = Path(final_video_path).name
            except Exception:
                pass

        record: Dict[str, Any] = {
            "video_id": video_id,
            "url": url,
            "profile_url": profile_url or existing.get("profile_url"),
            "title": title or existing.get("title") or "",
            "product_name": product_name or existing.get("product_name"),
            "file_name": computed_file_name,
            "final_video_path": final_video_path or existing.get("final_video_path"),
            "status": status,
            "error": error if status == "error" else None,
            "created_at": existing.get("created_at") or now_str,
            "updated_at": now_str,
        }
        if existing.get("showcase"):
            record["showcase"] = existing["showcase"]

        videos_map[url] = record
        data["videos"] = videos_map
        self._write_data(data)
