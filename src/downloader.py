"""
downloader.py - Download TikTok videos without watermark using yt-dlp.

yt-dlp supports TikTok's internal API which returns unwatermarked video URLs
when given a public share link. We wrap yt-dlp with our conventions:
- Output filename: <index>_<safe_product_name>.mp4
- Stored in: outputs/<index>_<product>/source_video.mp4
- Metadata (title/uploader) extracted for product naming
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
import html
from typing import Any, Dict, List, Optional

from loguru import logger
import requests
import yt_dlp

from config import settings


# ---------------------------------------------------------------------------
# External binaries (ffmpeg, ffprobe) — locate in bundle or system PATH
# ---------------------------------------------------------------------------

def _find_binary(name: str) -> str:
    """Find ffmpeg/ffprobe. Order:
    1. PyInstaller bundle: sys._MEIPASS/binaries/<name>
    2. Same dir as the bundled Python (sometimes)
    3. System PATH (shutil.which)
    Raises FileNotFoundError if not found.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for candidate in [
            Path(meipass) / "binaries" / name,
            Path(meipass) / name,
        ]:
            if candidate.exists() and candidate.is_file():
                return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(
        f"{name} not found. Install via 'brew install ffmpeg' "
        f"(macOS) or place {name} in PATH."
    )


def get_ffmpeg_path() -> str:
    return _find_binary("ffmpeg")


def get_ffprobe_path() -> str:
    return _find_binary("ffprobe")


def has_video_stream(file_path: Path) -> bool:
    """Check if media file has at least one valid video stream."""
    if not file_path.exists() or file_path.stat().st_size == 0:
        return False
    try:
        ffprobe = get_ffprobe_path()
        check = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return bool(check.stdout.strip())
    except Exception as e:
        logger.warning(f"ffprobe check failed for {file_path}: {e}")
        return False


# ---------------------------------------------------------------------------
# yt-dlp — use the Python API in-process (no subprocess).
# ---------------------------------------------------------------------------

def _get_cookie_file_path() -> Optional[str]:
    """Return verified path to cookies file if configured and exists."""
    cookie_setting = getattr(settings, "TIKTOK_COOKIES_FILE", "")
    if cookie_setting:
        p = Path(cookie_setting).expanduser()
        if p.exists() and p.is_file():
            return str(p)
        logger.warning(f"TIKTOK_COOKIES_FILE được cấu hình ({cookie_setting}) nhưng file không tồn tại.")
    return None


def _extract_hashtags_from_text(text: str) -> List[str]:
    """Extract hashtag list from text (e.g. '#review #kemchongnang')."""
    if not text:
        return []
    tags = re.findall(r"#[A-Za-z0-9_À-ỹ]+", text)
    seen = set()
    unique_tags = []
    for t in tags:
        t_clean = t.strip()
        if t_clean and t_clean.lower() not in seen:
            seen.add(t_clean.lower())
            unique_tags.append(t_clean)
    return unique_tags


def _yt_dlp_metadata(url: str) -> dict:
    """Fetch video metadata via yt-dlp without downloading. Raises on failure."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    cookie_file = _get_cookie_file_path()
    if cookie_file:
        opts["cookiefile"] = cookie_file
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        raw_tags = info.get("tags") or []
        caption = info.get("description") or info.get("title") or ""
        tags_from_text = _extract_hashtags_from_text(caption)
        combined_tags = []
        seen = set()
        for t in list(raw_tags) + tags_from_text:
            tag_str = f"#{t.lstrip('#')}" if not t.startswith("#") else t
            if tag_str.lower() not in seen:
                seen.add(tag_str.lower())
                combined_tags.append(tag_str)
        return {
            "title": info.get("title") or "",
            "description": caption,
            "caption": caption,
            "uploader": info.get("uploader") or info.get("creator") or "",
            "duration": info.get("duration"),
            "hashtags": combined_tags,
            "raw_info": info,
        }


def _yt_dlp_download(url: str, out_path: Path) -> None:
    """Download video via yt-dlp with no-watermark preference, fallback to best."""
    opts_template = {
        "outtmpl": str(out_path),
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
    }
    cookie_file = _get_cookie_file_path()
    if cookie_file:
        opts_template["cookiefile"] = cookie_file

    # Try no-watermark first
    opts = {**opts_template, "format": "best[ext=mp4][vcodec!*=av01][watermark=0]/best[ext=mp4][vcodec!*=av01]/best[ext=mp4]/best"}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        if out_path.exists() and out_path.stat().st_size > 0:
            return
    except Exception as e:
        logger.debug(f"yt-dlp no-watermark strategy failed: {e}")
    # Fallback: any best format
    opts = {**opts_template, "format": "best"}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])


@dataclass
class VideoInfo:
    """Metadata for one downloaded video"""
    url: str
    index: int
    product_name: str
    video_path: Path
    title: Optional[str] = None
    uploader: Optional[str] = None
    duration: Optional[float] = None
    caption: Optional[str] = None
    hashtags: Optional[List[str]] = None
    error: Optional[str] = None
    used_strategy: Optional[str] = None


# ---------- yt-dlp helpers ----------

def check_yt_dlp() -> bool:
    """Check if yt-dlp is importable and working."""
    try:
        import yt_dlp  # noqa: F401
        return True
    except Exception:
        return False


def sanitize_filename(name: str, max_length: int = 50) -> str:
    """Make a string safe to use as a filename. Strips diacritics for ASCII safety."""
    # Strip emojis
    name = re.sub(r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U00002700-\U000027BF]", "", name)
    # Strip Vietnamese + common diacritics → ASCII
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Normalize whitespace
    name = re.sub(r"\s+", "_", name.strip())
    # Remove unsafe chars
    name = re.sub(r"[<>:\"/\\|?*]", "", name)
    # Strip leading/trailing dots and underscores
    name = name.strip("._")
    if len(name) > max_length:
        name = name[:max_length].rstrip("._")
    return name or "video"


# ---------------------------------------------------------------------------
# TikVid.io — Primary no-watermark download provider
# ---------------------------------------------------------------------------
# Reverse engineered AJAX search API:
# Endpoint: POST https://tikvid.io/api/ajaxSearch
# Body: q=<tiktok_url>&lang=en
# Headers: Origin: https://tikvid.io, Referer: https://tikvid.io/en, X-Requested-With: XMLHttpRequest
# Response JSON: {"status": "ok", "data": "<html fragment with download anchors>"}

TIKVID_SEARCH_ENDPOINT = "https://tikvid.io/api/ajaxSearch"
TIKVID_BASE_URL = "https://tikvid.io/en"
TIKVID_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://tikvid.io",
    "Referer": "https://tikvid.io/en",
    "X-Requested-With": "XMLHttpRequest",
}


def _extract_tikvid_media_urls(html_content: str) -> List[Dict[str, Any]]:
    """Trích xuất các liên kết tải video MP4 từ HTML response của TikVid."""
    candidates = []

    # 1. Tìm các button download link thẻ <a>
    link_pattern = re.compile(
        r'<a\s+[^>]*href=["\'](?P<href>[^"\']+)["\'][^>]*>(?P<text>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    for match in link_pattern.finditer(html_content):
        href = html.unescape(match.group("href").strip())
        text_content = re.sub(r"<[^>]+>", "", match.group("text")).strip()

        # Bỏ qua javascript/hash/audio/mp3 links
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        text_lower = text_content.lower()
        if "mp3" in text_lower or "audio" in text_lower or ".mp3" in href.lower():
            continue

        # Ưu tiên nút download MP4 / video
        is_mp4 = (
            "mp4" in text_lower
            or "video" in text_lower
            or "download" in text_lower
            or "snapcdn" in href
            or "tiktokcdn" in href
        )
        if is_mp4:
            candidates.append({"url": href, "text": text_content})

    # 2. Tìm thẻ <source src="..." /> nếu có
    source_pattern = re.compile(
        r'<source\s+[^>]*src=["\'](?P<src>[^"\']+)["\']',
        re.IGNORECASE,
    )
    for match in source_pattern.finditer(html_content):
        src = html.unescape(match.group("src").strip())
        if src and not any(c["url"] == src for c in candidates):
            candidates.append({"url": src, "text": "Direct Video Source"})

    return candidates


def _download_via_tikvid(url: str, out_path: Path) -> dict:
    """
    Download TikTok video directly from TikVid.io without watermark.

    Returns metadata dictionary or raises RuntimeError on failure.
    """
    session = requests.Session()
    session.headers.update(TIKVID_HEADERS)

    # Gửi request search tới TikVid endpoint
    try:
        resp = session.post(
            TIKVID_SEARCH_ENDPOINT,
            data={"q": url, "lang": "en"},
            timeout=25,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"TikVid search request failed: {e}")

    if data.get("status") != "ok" or not data.get("data"):
        msg = data.get("msg") or data.get("message") or "Invalid response format"
        raise RuntimeError(f"TikVid returned non-ok status: {msg}")

    html_content = data["data"]
    candidates = _extract_tikvid_media_urls(html_content)
    if not candidates:
        raise RuntimeError("TikVid returned no valid video download links in HTML response")

    # Thử tải lần lượt qua các download candidates
    last_err = ""
    for cand in candidates:
        cand_url = cand["url"]
        out_path.unlink(missing_ok=True)
        try:
            download_headers = {
                "User-Agent": TIKVID_HEADERS["User-Agent"],
                "Referer": "https://tikvid.io/",
            }
            with session.get(cand_url, headers=download_headers, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(out_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)

            if out_path.exists() and out_path.stat().st_size > 0:
                if has_video_stream(out_path):
                    logger.info(
                        f"TikVid tải thành công qua URL candidate '{cand['text']}' "
                        f"({out_path.stat().st_size} bytes)"
                    )
                    return {"source": "tikvid", "cand_url": cand_url, "size": out_path.stat().st_size}
                else:
                    logger.warning(f"TikVid link '{cand['text']}' trả về audio-only file. Đang thử link khác...")
                    out_path.unlink(missing_ok=True)
                    last_err = f"candidate '{cand['text']}': audio-only (no video stream)"
        except Exception as e:
            last_err = f"candidate '{cand['text']}': {e}"
            out_path.unlink(missing_ok=True)

    raise RuntimeError(f"TikVid all download candidates failed: {last_err}")


# ---------------------------------------------------------------------------
# TikWM API — Secondary fallback download path
# ---------------------------------------------------------------------------
# Free public API at https://www.tikwm.com/api/ that returns direct
# no-watermark MP4 URLs for TikTok videos. Works where yt-dlp's internal
# extractor fails (especially on region/age-restricted clips).
# Endpoint: POST https://www.tikwm.com/api/  body: url=<tiktok_url>
# Response: { "code": 0, "data": { "play": "<mp4 url no-watermark>", ... } }

TIKWM_ENDPOINT = "https://www.tikwm.com/api/"
TIKWM_MIN_INTERVAL_SEC = 1.1
TIKWM_MAX_ATTEMPTS = 3
_tikwm_request_lock = threading.Lock()
_tikwm_last_request_at = 0.0


def _fetch_tikwm_metadata(url: str) -> dict:
    """Fetch TikWM metadata with process-wide throttling and rate-limit retry."""
    global _tikwm_last_request_at
    last_error = ""
    for attempt in range(1, TIKWM_MAX_ATTEMPTS + 1):
        with _tikwm_request_lock:
            wait_sec = max(0.0, TIKWM_MIN_INTERVAL_SEC - (time.monotonic() - _tikwm_last_request_at))
            if wait_sec:
                logger.info(
                    "TikWM throttle url={} wait_sec={:.2f} attempt={}/{}",
                    url,
                    wait_sec,
                    attempt,
                    TIKWM_MAX_ATTEMPTS,
                )
                time.sleep(wait_sec)
            try:
                resp = requests.post(
                    TIKWM_ENDPOINT,
                    data={"url": url},
                    timeout=20,
                    headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                                            "Chrome/131.0.0.0 Safari/537.36"},
                )
            except Exception as e:
                _tikwm_last_request_at = time.monotonic()
                raise RuntimeError(f"TikWM request failed: {e}") from e
            _tikwm_last_request_at = time.monotonic()

        if resp.status_code != 200:
            raise RuntimeError(f"TikWM HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"TikWM JSON parse failed: {e}") from e

        if data.get("code") == 0 and "data" in data:
            logger.info("TikWM metadata resolved url={} attempt={}", url, attempt)
            return data["data"]

        last_error = f"TikWM returned error: {data}"
        message = str(data.get("msg", "")).lower()
        is_rate_limited = "limit" in message or "request/second" in message or "too many" in message
        if not is_rate_limited or attempt >= TIKWM_MAX_ATTEMPTS:
            break
        backoff_sec = TIKWM_MIN_INTERVAL_SEC * attempt
        logger.warning(
            "TikWM rate limited url={} attempt={}/{}; retry in {:.2f}s: {}",
            url,
            attempt,
            TIKWM_MAX_ATTEMPTS,
            backoff_sec,
            data.get("msg"),
        )
        time.sleep(backoff_sec)

    raise RuntimeError(last_error)


def _download_via_tikwm(url: str, out_path: Path, payload: Optional[dict] = None) -> dict:
    """Download TikWM MP4, reusing an already resolved payload when available."""
    if payload is None:
        payload = _fetch_tikwm_metadata(url)
        logger.info("TikWM download resolved a fresh payload url={}", url)
    else:
        logger.info("TikWM download reusing metadata payload url={}", url)
    play_url = payload.get("play") or payload.get("hdplay")
    if not play_url:
        raise RuntimeError(f"TikWM returned no play URL. keys={list(payload.keys())}")

    # Download the actual MP4
    try:
        with requests.get(play_url, stream=True, timeout=60,
                          headers={"User-Agent": "Mozilla/5.0"}) as r:
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
    except Exception as e:
        raise RuntimeError(f"TikWM video download failed: {e}")

    return payload


# ---------------------------------------------------------------------------
# yt-dlp fallback
# ---------------------------------------------------------------------------

def _download_via_ytdlp(url: str, out_path: Path) -> bool:
    """
    Use yt-dlp Python API to download. Tries multiple format strategies sequentially.
    Crucial: Validates video stream on each attempt and moves to next format if
    download produced an audio-only file.
    """
    format_strategies = [
        "best[ext=mp4][vcodec!=none]/bestvideo[ext=mp4]+bestaudio/best[vcodec!=none]",
        "best[vcodec^=hev][ext=mp4]/best[ext=mp4]/best",
        "bestvideo+bestaudio/best",
        "best",
    ]
    cookie_file = _get_cookie_file_path()
    last_err = ""

    for fmt in format_strategies:
        out_path.unlink(missing_ok=True)
        try:
            opts = {
                "outtmpl": str(out_path),
                "quiet": True,
                "no_warnings": True,
                "format": fmt,
                "merge_output_format": "mp4",
                "http_headers": {"Accept-Language": "en-US,en;q=0.9"},
            }
            if cookie_file:
                opts["cookiefile"] = cookie_file

            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            if out_path.exists() and out_path.stat().st_size > 0:
                # Kiểm tra video stream ngay trong từng format strategy
                if has_video_stream(out_path):
                    logger.info(f"yt-dlp tải thành công với format '{fmt}' -> {out_path} ({out_path.stat().st_size} bytes)")
                    return True
                else:
                    logger.warning(f"yt-dlp format '{fmt}' trả về file audio-only không có video stream. Đang thử format tiếp theo...")
                    out_path.unlink(missing_ok=True)
                    last_err = f"format {fmt}: audio-only file (no video stream)"
        except Exception as e:
            last_err = f"format {fmt}: {str(e)[-300:]}"
            out_path.unlink(missing_ok=True)

    raise RuntimeError(f"yt-dlp all strategies failed: {last_err}")


async def fetch_video_metadata(url: str) -> dict:
    """Fetch video metadata via yt-dlp Python API with fallback to TikWM API."""
    try:
        return await asyncio.to_thread(_yt_dlp_metadata, url)
    except Exception as e:
        logger.debug(f"yt-dlp metadata extraction failed ({e}), trying TikWM API fallback...")
        try:
            tikwm_data = await asyncio.to_thread(_fetch_tikwm_metadata, url)
            author = tikwm_data.get("author") or {}
            uploader = author.get("nickname") or author.get("unique_id")
            title_caption = tikwm_data.get("title") or ""
            hashtags = _extract_hashtags_from_text(title_caption)
            return {
                "title": title_caption,
                "description": title_caption,
                "caption": title_caption,
                "uploader": uploader,
                "duration": tikwm_data.get("duration"),
                "hashtags": hashtags,
                "raw_tikwm": tikwm_data,
            }
        except Exception as tikwm_err:
            raise RuntimeError(f"Metadata fetch failed (yt-dlp: {e}; tikwm: {tikwm_err})")


async def download_one(
    url: str,
    index: int,
    product_name_hint: Optional[str] = None,
) -> VideoInfo:
    """
    Download a single TikTok video without watermark.

    Args:
        url: TikTok share URL (e.g. https://www.tiktok.com/@user/video/123)
        index: Numeric index for ordering (used in output folder name)
        product_name_hint: Optional human-readable product name to use as folder name

    Returns:
        VideoInfo with path and metadata
    """
    safe_name = sanitize_filename(product_name_hint or "video")
    out_dir = settings.OUTPUT_DIR / f"{index:02d}_{safe_name}"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / "source_video.mp4"

    # Try to fetch metadata first to get the actual title (for product naming).
    # Keep the TikWM payload so the download step does not immediately hit the
    # same rate-limited API a second time.
    title = None
    uploader = None
    duration = None
    caption = None
    hashtags = None
    tikwm_payload: Optional[dict] = None
    try:
        meta = await fetch_video_metadata(url)
        title = meta.get("title") or meta.get("description")
        caption = meta.get("caption") or meta.get("description") or title
        uploader = meta.get("uploader") or meta.get("creator")
        duration = meta.get("duration")
        hashtags = meta.get("hashtags") or []
        raw_tikwm = meta.get("raw_tikwm")
        if isinstance(raw_tikwm, dict):
            tikwm_payload = raw_tikwm
            logger.info("[{}] metadata source=tikwm; payload will be reused", index)
        else:
            logger.info("[{}] metadata source=yt-dlp", index)
    except Exception as e:
        logger.warning(f"[{index}] metadata fetch failed (will still try download): {e}")

    # Use hint if provided, otherwise derive from title
    final_name = sanitize_filename(product_name_hint or title or f"video_{index}")

    # Rename folder if product name was derived after initial creation
    if final_name != safe_name:
        new_out_dir = settings.OUTPUT_DIR / f"{index:02d}_{final_name}"
        if not new_out_dir.exists():
            out_dir.rename(new_out_dir)
            out_dir = new_out_dir
            out_path = out_dir / "source_video.mp4"

    # Try multiple strategies. Order matters — TikWM works where yt-dlp
    # can't extract the no-watermark source.
    last_err: str = ""
    used_strategy: str = ""
    for label, runner in (
        ("tikvid", lambda: _download_via_tikvid(url, out_path)),
        ("tikwm-api", lambda: _download_via_tikwm(url, out_path, tikwm_payload)),
        ("yt-dlp", lambda: _download_via_ytdlp(url, out_path)),
    ):
        out_path.unlink(missing_ok=True)
        logger.info(f"[{index}] attempt '{label}': {url}")
        try:
            res = await asyncio.to_thread(runner)
            ok = bool(res)
            # If TikWM returned metadata and title was empty, retrieve it
            if label == "tikwm-api" and isinstance(res, dict) and not title:
                title = res.get("title") or title
                author_obj = res.get("author") or {}
                if not uploader:
                    uploader = author_obj.get("nickname") or author_obj.get("unique_id")
        except Exception as e:
            ok = False
            last_err = f"{label}: {e}"

        if not ok or not out_path.exists():
            last_err = last_err or f"{label}: download did not produce a file"
            logger.warning(f"[{index}] '{label}' failed: {last_err[:200]}")
            continue

        # Hard requirement: file MUST contain a video stream. Audio-only is
        # treated as a hard failure (per requirement: never fall back to
        # audio-only, never auto-generate placeholders).
        if not has_video_stream(out_path):
            logger.warning(
                f"[{index}] '{label}' downloaded but file has no video stream — "
                f"TikTok only served audio. Trying next strategy."
            )
            last_err = f"{label}: audio-only file (no video stream)"
            out_path.unlink(missing_ok=True)
            continue

        used_strategy = label
        break
    else:
        # All strategies failed. Surface a clear, actionable error.
        err_msg = (
            f"Could not download a no-watermark video from this URL. "
            f"Last error: {last_err}. "
            f"The video may be region-locked, age-restricted, or the URL invalid. "
            f"If the URL is reachable in a browser, try configuring TIKTOK_COOKIES_FILE in .env."
        )
        logger.error(f"[{index}] {err_msg}")
        return VideoInfo(
            url=url,
            index=index,
            product_name=final_name,
            video_path=out_path,
            title=title,
            uploader=uploader,
            duration=duration,
            caption=caption,
            hashtags=hashtags or [],
            error=err_msg,
        )

    # Refresh duration from the actual file (the metadata estimate can be wrong)
    try:
        ffprobe = get_ffprobe_path()
        check = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(out_path)],
            capture_output=True, text=True, timeout=15,
        )
        duration = float(json.loads(check.stdout)["format"]["duration"])
    except Exception:
        pass

    logger.info(f"[{index}] OK ({used_strategy}) -> {out_path}")
    return VideoInfo(
        url=url,
        index=index,
        product_name=final_name,
        video_path=out_path,
        title=title,
        uploader=uploader,
        duration=duration,
        caption=caption,
        hashtags=hashtags or [],
        used_strategy=used_strategy,
    )


async def download_batch(
    urls: List[str],
    product_names: Optional[List[str]] = None,
) -> List[VideoInfo]:
    """
    Download multiple TikTok videos in parallel.

    Args:
        urls: List of TikTok share URLs
        product_names: Optional list of product name hints (parallel to urls)

    Returns:
        List of VideoInfo, one per URL (in order)
    """
    if product_names is None:
        product_names = [None] * len(urls)
    if len(product_names) < len(urls):
        product_names += [None] * (len(urls) - len(product_names))

    tasks = [
        download_one(url, i + 1, name)
        for i, (url, name) in enumerate(zip(urls, product_names))
    ]
    return await asyncio.gather(*tasks)


# ---------- CLI entrypoint ----------

async def _main():
    """Run from command line: python -m src.downloader <url1> <url2> ..."""
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m src.downloader <tiktok_url1> [url2 ...]")
        sys.exit(1)
    if not check_yt_dlp():
        print("ERROR: yt-dlp not found. Install with: pip install yt-dlp")
        sys.exit(1)
    urls = sys.argv[1:]
    results = await download_batch(urls)
    print("\n=== Results ===")
    for r in results:
        status = "OK" if not r.error else f"FAIL: {r.error}"
        print(f"[{r.index}] {r.product_name}: {status} -> {r.video_path}")


if __name__ == "__main__":
    asyncio.run(_main())
