"""telegram_bot.py

Bot Telegram: gửi link TikTok vào chat là backend tự chạy quy trình của trang
/ai-video với đúng thông số đang chọn trên giao diện (src/ai_video_defaults.py).

- Long polling ``getUpdates`` bằng ``requests`` trên luồng nền, khởi động cùng
  FastAPI (src/web/app.py) khi có ``TELEGRAM_BOT_TOKEN``.
- Chỉ nhận lệnh từ chat id trong ``TELEGRAM_ALLOWED_CHAT_IDS``; chat lạ được báo
  lại chat id của mình để thêm vào .env.
- JobManager chỉ chạy 1 job một lúc: link gửi lúc đang bận được xếp hàng, rảnh
  thì gom tất cả link đang chờ thành 1 batch.

Lệnh: /start, /status, /settings (menu nút bấm để đổi setting), /queue, /clear, /cancel.
Setting đổi trên bot ghi chung file với trang /ai-video, nên 2 bên luôn khớp.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import requests

from src import ai_video_defaults

logger = logging.getLogger("tiktok.telegram_bot")

API_BASE = "https://api.telegram.org"
POLL_TIMEOUT_SEC = 30
DISPATCH_INTERVAL_SEC = 3.0
MAX_UPLOAD_BYTES = 49 * 1024 * 1024  # giới hạn sendVideo của Bot API là 50MB

TIKTOK_URL_RE = re.compile(
    r"https?://(?:[a-z0-9-]+\.)*tiktok\.com/[^\s<>\"']+", re.IGNORECASE
)
DONE_STATUSES = {"done", "completed", "success"}
FAIL_STATUSES = {"error", "failed"}
JOB_TERMINAL = {"done", "error", "cancelled"}

STYLE_LABELS = {"style1": "Style 1 (Tone Đỏ)", "style2": "Style 2 (Tone Xanh)", "style3": "Style 3 (Tone Hồng)"}
TOGGLE_FIELDS = {
    "auto_showcase": "Showcase",
    "showcase_dry": "Showcase chạy thử",
    "auto_post": "Đăng hẹn giờ",
    "post_dry": "Đăng chạy thử",
    "post_delete_after": "Xóa video sau khi hẹn",
}
INPUT_PROMPTS = {
    "script_theme": "Gửi chủ đề kịch bản AI (vd: Black Friday). Gửi - để AI tự chọn.",
    "video_shift_ratio": "Gửi Shift (số 0 – 1, mặc định 0.3333).",
    "video_scale": "Gửi Scale (số 0.1 – 3, mặc định 1.08).",
}


def extract_tiktok_urls(text: str) -> List[str]:
    """Lấy các link TikTok trong tin nhắn, bỏ trùng, giữ thứ tự."""
    seen: List[str] = []
    for match in TIKTOK_URL_RE.findall(text or ""):
        url = match.rstrip(").,;!?]")
        if url not in seen:
            seen.append(url)
    return seen


THEME_SEPARATORS = " \t-–—:|>»→=,"
THEME_QUOTES = "\"'“”‘’«»`"


_FIELD_SPLIT = re.compile(r"\s+[-–—|]\s+|\s*\|\s*")
_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$")
_TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2})|[hH](\d{2})?)$")
_NUMBER_RE = re.compile(r"^(\d+(?:[.,]\d+)?)[xX]?$")
_PLACEHOLDERS = {"_", "*"}  # bỏ qua một ô số (dùng mặc định)
POST_MINUTE_STEP = 5  # ô chọn phút của TikTok Studio theo bước 5 phút
POST_DEFAULT_HOUR = 8  # chỉ có ngày, không có giờ -> 08:00


@dataclass
class ParsedLink:
    url: str
    theme: Optional[str] = None
    shift: Optional[float] = None  # tỷ lệ kéo video (Y-offset) 0–1
    scale: Optional[float] = None
    post_at: Optional[datetime] = None
    warnings: List[str] = field(default_factory=list)


def _build_post_at(
    day: Optional[Tuple[int, int, Optional[int]]],
    clock: Optional[Tuple[int, int]],
    now: datetime,
) -> datetime:
    """Ghép ngày/giờ người dùng gửi. Thiếu ngày -> hôm nay (qua giờ rồi thì ngày mai); thiếu giờ -> 08:00."""
    from src.post_schedule import MIN_LEAD

    hour, minute = clock if clock else (POST_DEFAULT_HOUR, 0)
    minute -= minute % POST_MINUTE_STEP
    if day is None:
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return candidate if candidate >= now + MIN_LEAD else candidate + timedelta(days=1)
    d, m, y = day
    if y is not None:
        year = y + 2000 if y < 100 else y
        return datetime(year, m, d, hour, minute)
    candidate = datetime(now.year, m, d, hour, minute)
    return candidate if candidate.date() >= now.date() else datetime(now.year + 1, m, d, hour, minute)


def parse_link_options(text: str, now: Optional[datetime] = None) -> List[ParsedLink]:
    """Mỗi dòng ``link - chủ đề - Y-offset - scale - giờ - ngày`` (các phần sau link đều tùy chọn).

    Các phần cách nhau bằng `` - `` (có khoảng trắng hai bên) hoặc ``|``. Ngày ``20/11`` hoặc
    ``20/11/2026`` và giờ ``18:30`` / ``18h30`` / ``18h`` nhận dạng theo dạng viết (đứng trước/sau nhau đều được).
    Số thuần xếp theo vị trí: một số = Y-offset (0–1); hai số = Y-offset rồi scale (0.1–3). Dùng ``_`` để bỏ
    qua một ô (vd ``_ - 1.2`` chỉ đặt scale). Phần còn lại ghép thành chủ đề.
    Chữ đứng trước link (vd lời mời của nút Share TikTok) bị bỏ qua.
    """
    now = now or datetime.now()
    result: List[ParsedLink] = []
    seen: Set[str] = set()
    for line in (text or "").splitlines():
        matches = list(TIKTOK_URL_RE.finditer(line))
        if not matches:
            continue
        tail = line[matches[-1].end():].strip(THEME_SEPARATORS).strip()
        parts = [p.strip() for p in _FIELD_SPLIT.split(tail)] if tail else []
        parts = [p for p in parts if p]
        warnings: List[str] = []
        numbers: List[str] = []  # số thuần/placeholder, thu từ phải sang trái
        day: Optional[Tuple[int, int, Optional[int]]] = None
        clock: Optional[Tuple[int, int]] = None
        while parts:
            last = parts[-1]
            if day is None and (dm := _DATE_RE.match(last)):
                d, m = int(dm.group(1)), int(dm.group(2))
                y = int(dm.group(3)) if dm.group(3) else None
                try:
                    datetime(2024 if y is None else (y + 2000 if y < 100 else y), m, d)  # 2024 nhuận: cho 29/02
                except ValueError:
                    warnings.append(f"Ngày đăng '{last}' không hợp lệ")
                else:
                    day = (d, m, y)
            elif clock is None and (tm := _TIME_RE.match(last)):
                hh = int(tm.group(1))
                mm = int(tm.group(2) or tm.group(3) or 0)
                if hh > 23 or mm > 59:
                    warnings.append(f"Giờ đăng '{last}' không hợp lệ")
                else:
                    clock = (hh, mm)
            elif len(numbers) < 2 and (_NUMBER_RE.match(last) or last in _PLACEHOLDERS):
                numbers.append(last)
            else:
                break
            parts.pop()
        shift: Optional[float] = None
        scale: Optional[float] = None
        for slot_name, raw_num, lo, hi in zip(("Y-offset", "Scale"), reversed(numbers), (0.0, 0.1), (1.0, 3.0)):
            if raw_num in _PLACEHOLDERS:
                continue
            value = float(_NUMBER_RE.match(raw_num).group(1).replace(",", "."))
            if not lo <= value <= hi:
                warnings.append(f"{slot_name} '{raw_num}' ngoài khoảng {lo:g} – {hi:g}, dùng giá trị mặc định")
            elif slot_name == "Y-offset":
                shift = value
            else:
                scale = value
        theme_raw = " - ".join(parts).strip().strip(THEME_QUOTES).strip()
        theme = None if theme_raw in ("", "-") else theme_raw[:300]
        post_at = _build_post_at(day, clock, now) if (day or clock) else None
        for m_url in matches:
            url = m_url.group(0).rstrip(").,;!?]")
            if url not in seen:
                seen.add(url)
                result.append(ParsedLink(url, theme, shift, scale, post_at, list(warnings)))
    return result


def parse_links_with_themes(text: str) -> List[Tuple[str, Optional[str]]]:
    """Tương thích cũ: ``link - chủ đề`` -> (link, chủ đề riêng); không ghi chủ đề -> (link, None)."""
    return [(p.url, p.theme) for p in parse_link_options(text)]


def parse_chat_ids(raw: str) -> Set[int]:
    ids: Set[int] = set()
    for part in re.split(r"[,\s;]+", raw or ""):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            logger.warning(f"TELEGRAM_ALLOWED_CHAT_IDS có giá trị không hợp lệ: {part!r}")
    return ids


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class QueuedLink:
    url: str
    chat_id: int
    theme: Optional[str] = None  # chủ đề riêng gửi kèm link; None = theo setting
    shift: Optional[float] = None  # Y-offset riêng; None = theo setting
    scale: Optional[float] = None  # scale riêng; None = theo setting
    post_at: Optional[datetime] = None  # giờ đăng hẹn riêng; None = slot tự động 08/12/18/22h


class TelegramBot:
    def __init__(
        self,
        token: str,
        job_manager: Any,
        allowed_chat_ids: Set[int],
        *,
        send_video: bool = False,
        defaults_loader: Callable[[], Dict[str, Any]] = ai_video_defaults.load,
        defaults_saver: Callable[[Dict[str, Any]], Dict[str, Any]] = ai_video_defaults.save,
        voices_loader: Optional[Callable[[], List[Dict[str, Any]]]] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.token = token
        self.job_manager = job_manager
        self.allowed_chat_ids = allowed_chat_ids
        self.send_video = send_video
        self.defaults_loader = defaults_loader
        self.defaults_saver = defaults_saver
        self.voices_loader = voices_loader or _load_voices
        self._pending_input: Dict[int, str] = {}  # chat_id -> field đang chờ nhập
        self.http = session or requests.Session()

        self._lock = threading.RLock()  # hàng chờ link
        self._job_lock = threading.Lock()  # trạng thái job đang theo dõi
        self._stop = threading.Event()
        self._queue: List[QueuedLink] = []
        self._offset: Optional[int] = None
        self._threads: List[threading.Thread] = []

        # Job do bot tạo đang theo dõi
        self._job_id: Optional[str] = None
        self._job_chats: Dict[int, int] = {}  # item index -> chat_id
        self._notified: Set[int] = set()  # item index đã báo kết quả
        self._last_snapshot: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self.job_manager.subscribe(self._on_job_update)
        for name, target in (("tg-poll", self._poll_loop), ("tg-dispatch", self._dispatch_loop)):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        logger.info(
            f"Telegram bot đã chạy (chat được phép: {sorted(self.allowed_chat_ids) or 'chưa cấu hình'})"
        )

    def stop(self) -> None:
        self._stop.set()
        try:
            self.job_manager.unsubscribe(self._on_job_update)
        except Exception:
            pass

    # ------------------------------------------------------------ Telegram API
    def _api(self, method: str, timeout: float = 15, **params: Any) -> Any:
        url = f"{API_BASE}/bot{self.token}/{method}"
        resp = self.http.post(url, timeout=timeout, **params)
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} lỗi: {data.get('description')}")
        return data.get("result")

    def send(self, chat_id: int, text: str, markup: Optional[Dict[str, Any]] = None) -> None:
        payload: Dict[str, Any] = {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True}
        if markup:
            payload["reply_markup"] = markup
        try:
            self._api("sendMessage", json=payload)
        except Exception as exc:
            logger.warning(f"Gửi tin Telegram thất bại: {exc}")

    def edit(self, chat_id: int, message_id: int, text: str, markup: Optional[Dict[str, Any]] = None) -> None:
        payload: Dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text[:4000]}
        if markup:
            payload["reply_markup"] = markup
        try:
            self._api("editMessageText", json=payload)
        except Exception as exc:
            if "not modified" not in str(exc):
                logger.warning(f"Sửa tin Telegram thất bại: {exc}")

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            self._api("answerCallbackQuery", json={"callback_query_id": callback_id, "text": text[:200]})
        except Exception as exc:
            logger.debug(f"answerCallbackQuery lỗi: {exc}")

    def _send_video_file(self, chat_id: int, path: Path, caption: str) -> bool:
        try:
            if not path.is_file() or path.stat().st_size > MAX_UPLOAD_BYTES:
                return False
            with path.open("rb") as fh:
                self._api(
                    "sendVideo",
                    timeout=300,
                    data={"chat_id": chat_id, "caption": caption[:1000], "supports_streaming": "true"},
                    files={"video": (path.name, fh, "video/mp4")},
                )
            return True
        except Exception as exc:
            logger.warning(f"Gửi video Telegram thất bại: {exc}")
            return False

    # ------------------------------------------------------------ polling
    def _poll_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                params: Dict[str, Any] = {"timeout": POLL_TIMEOUT_SEC, "allowed_updates": ["message", "callback_query"]}
                if self._offset is not None:
                    params["offset"] = self._offset
                updates = self._api("getUpdates", timeout=POLL_TIMEOUT_SEC + 10, json=params) or []
                backoff = 1.0
                for update in updates:
                    self._offset = int(update["update_id"]) + 1
                    try:
                        self.handle_update(update)
                    except Exception:
                        logger.exception("Xử lý update Telegram lỗi")
            except Exception as exc:
                logger.warning(f"getUpdates lỗi: {exc} (thử lại sau {backoff:.0f}s)")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 60.0)

    def handle_update(self, update: Dict[str, Any]) -> None:
        if update.get("callback_query"):
            self._handle_callback(update["callback_query"])
            return
        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        text = message.get("text") or message.get("caption") or ""
        if chat_id is None:
            return
        if chat_id not in self.allowed_chat_ids:
            self.send(
                chat_id,
                f"Chat này chưa được phép dùng bot.\nChat ID: {chat_id}\n"
                "Thêm vào TELEGRAM_ALLOWED_CHAT_IDS trong .env rồi khởi động lại backend.",
            )
            return

        command = text.strip().split(maxsplit=1)[0].split("@")[0].lower() if text.strip() else ""
        if command in ("/start", "/help"):
            self.send(
                chat_id,
                "Gửi link TikTok (1 hoặc nhiều link) để chạy AI Video với setting đang chọn ở trang /ai-video.\n"
                "Mỗi dòng 1 link, có thể ghi kèm (đều tùy chọn, cách nhau bằng dấu gạch có khoảng trắng):\n"
                "link - chủ đề - Y-offset - scale - giờ - ngày\n"
                "vd: https://vt.tiktok.com/abc/ - Black Friday - 0.4 - 1.1 - 18:30 - 20/11\n"
                "• Y-offset (tỷ lệ kéo video): số 0–1 · scale: số 0.1–3 · giờ: 18:30 hoặc 18h30 (làm tròn xuống bội số 5 phút) · ngày: 20/11 hoặc 20/11/2026\n"
                "• Chỉ ghi 1 số thì đó là Y-offset; muốn chỉ đặt scale thì ghi _ - 1.2 (dấu _ = giữ mặc định).\n"
                "• Chỉ có giờ -> hôm nay (qua rồi thì ngày mai); chỉ có ngày -> 08:00. Không ghi thì theo /settings và slot tự động.\n"
                "• Giờ/ngày đăng chỉ có tác dụng khi bật 'Đăng hẹn giờ' trong /settings.\n\n"
                "/settings – xem & đổi setting (style, giọng, chủ đề, showcase, đăng…)\n"
                "/status – tiến độ job\n/queue – link đang chờ\n/clear – xóa hàng chờ\n/cancel – hủy nhập setting",
            )
            return
        if command in ("/settings", "/config"):
            with self._lock:
                self._pending_input.pop(chat_id, None)
            self.send(chat_id, self._settings_text(), self._settings_keyboard())
            return
        if command == "/cancel":
            with self._lock:
                had = self._pending_input.pop(chat_id, None)
            self.send(chat_id, "Đã hủy nhập setting." if had else "Không có gì để hủy.")
            return

        with self._lock:
            pending = self._pending_input.get(chat_id) if not command.startswith("/") else None
        if pending:
            self._handle_setting_input(chat_id, pending, text)
            return
        if command == "/status":
            self.send(chat_id, self._status_text())
            return
        if command == "/queue":
            with self._lock:
                urls = [q.url for q in self._queue]
            self.send(chat_id, "Hàng chờ trống." if not urls else f"{len(urls)} link đang chờ:\n" + "\n".join(urls))
            return
        if command == "/clear":
            with self._lock:
                n = len(self._queue)
                self._queue.clear()
            self.send(chat_id, f"Đã xóa {n} link khỏi hàng chờ.")
            return

        links = parse_link_options(text)
        if not links:
            self.send(chat_id, "Không thấy link TikTok nào trong tin nhắn.")
            return
        with self._lock:
            queued = {q.url: q for q in self._queue}
            for link in links:
                if link.url in queued:  # gửi lại link đang chờ kèm thông tin mới -> cập nhật phần được gửi
                    q = queued[link.url]
                    q.theme = link.theme or q.theme
                    q.shift = link.shift if link.shift is not None else q.shift
                    q.scale = link.scale if link.scale is not None else q.scale
                    q.post_at = link.post_at or q.post_at
                else:
                    self._queue.append(QueuedLink(link.url, chat_id, link.theme, link.shift, link.scale, link.post_at))
        with self._job_lock:
            tracking = self._job_id is not None
        busy = tracking or self.job_manager.is_running()
        note = "Đang có job chạy, sẽ chạy khi xong." if busy else "Sắp bắt đầu."
        defaults = self.defaults_loader()
        default_theme = defaults.get("script_theme") or "AI tự chọn"
        default_shift = defaults.get("video_shift_ratio")
        default_scale = defaults.get("video_scale")
        lines = [f"Đã nhận {len(links)} link. {note}"]
        has_post_at = False
        for i, link in enumerate(links, start=1):
            shift_txt = f"{link.shift}" if link.shift is not None else f"mặc định ({default_shift})"
            scale_txt = f"{link.scale}" if link.scale is not None else f"mặc định ({default_scale})"
            if link.post_at:
                has_post_at = True
                post_txt = f"{link.post_at:%H:%M %d/%m/%Y}"
            else:
                post_txt = "slot tự động (08/12/18/22h)"
            theme_txt = link.theme or f"mặc định ({default_theme})"
            lines.append(f"{i}. {link.url}\n   Chủ đề: {theme_txt}\n   Y-offset: {shift_txt} · Scale: {scale_txt}\n   Đăng: {post_txt}")
            lines.extend(f"   ⚠ {w}" for w in link.warnings)
        if has_post_at and not defaults.get("auto_post"):
            lines.append("⚠ 'Đăng hẹn giờ' đang tắt trong /settings nên giờ/ngày đăng sẽ không được dùng.")
        self.send(chat_id, "\n".join(lines))

    # ------------------------------------------------------------ settings menu
    def _safe_voices(self) -> List[Dict[str, Any]]:
        try:
            return list(self.voices_loader())
        except Exception as exc:
            logger.warning(f"Không đọc được danh sách giọng: {exc}")
            return []

    def _voice_name(self, voice_id: str) -> str:
        if voice_id == "default":
            return "Mặc định (.env)"
        for v in self._safe_voices():
            if v.get("voice_id") == voice_id:
                return str(v.get("name") or voice_id)
        return voice_id

    def _settings_text(self) -> str:
        d = self.defaults_loader()
        text = ai_video_defaults.describe(d).replace(
            f"Giọng: {d['voice_id']}", f"Giọng: {self._voice_name(d['voice_id'])}"
        )
        return "⚙️ Setting AI Video (dùng chung với trang /ai-video):\n" + text

    def _settings_keyboard(self) -> Dict[str, Any]:
        d = self.defaults_loader()
        on = lambda key: "✅" if d[key] else "⬜"  # noqa: E731
        btn = lambda text, data: {"text": text, "callback_data": data}  # noqa: E731
        return {"inline_keyboard": [
            [btn(f"🎨 {STYLE_LABELS.get(d['style'], d['style'])}", "cfg:menu:style"),
             btn(f"🎙 {self._voice_name(d['voice_id'])[:28]}", "cfg:menu:voice")],
            [btn("✏️ Chủ đề", "cfg:ask:script_theme"),
             btn(f"↕ Shift {d['video_shift_ratio']}", "cfg:ask:video_shift_ratio"),
             btn(f"🔍 Scale {d['video_scale']}", "cfg:ask:video_scale")],
            [btn(f"{on('auto_showcase')} Showcase", "cfg:t:auto_showcase"),
             btn(f"{on('showcase_dry')} Showcase chạy thử", "cfg:t:showcase_dry")],
            [btn(f"{on('auto_post')} Đăng hẹn giờ", "cfg:t:auto_post"),
             btn(f"{on('post_dry')} Đăng chạy thử", "cfg:t:post_dry")],
            [btn(f"{on('post_delete_after')} Xóa video sau khi hẹn", "cfg:t:post_delete_after")],
            [btn("🔄 Làm mới", "cfg:menu:main")],
        ]}

    def _style_keyboard(self) -> Dict[str, Any]:
        cur = self.defaults_loader()["style"]
        rows = [[{"text": ("● " if k == cur else "") + v, "callback_data": f"cfg:style:{k}"}]
                for k, v in STYLE_LABELS.items()]
        rows.append([{"text": "« Quay lại", "callback_data": "cfg:menu:main"}])
        return {"inline_keyboard": rows}

    def _voice_keyboard(self) -> Dict[str, Any]:
        cur = self.defaults_loader()["voice_id"]
        rows = []
        # callback_data tối đa 64 byte: gửi số thứ tự thay vì voice_id
        for i, v in enumerate(self._safe_voices()[:40]):
            mark = "● " if v.get("voice_id") == cur else ""
            label = f"{mark}{v.get('name') or v.get('voice_id')}"[:60]
            rows.append([{"text": label, "callback_data": f"cfg:voice:{i}"}])
        rows.append([{"text": "« Quay lại", "callback_data": "cfg:menu:main"}])
        return {"inline_keyboard": rows}

    def _update_defaults(self, **changes: Any) -> Dict[str, Any]:
        with self._lock:
            d = dict(self.defaults_loader())
            d.update(changes)
            return self.defaults_saver(d)

    def _handle_callback(self, cb: Dict[str, Any]) -> None:
        msg = cb.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        message_id = msg.get("message_id")
        data = str(cb.get("data") or "")
        cb_id = str(cb.get("id") or "")
        if chat_id not in self.allowed_chat_ids:
            self.answer_callback(cb_id, "Chat này chưa được phép dùng bot.")
            return
        parts = data.split(":", 2)
        if len(parts) != 3 or parts[0] != "cfg":
            self.answer_callback(cb_id)
            return
        _, action, arg = parts
        toast = ""
        if action == "menu" and arg == "style":
            self.answer_callback(cb_id)
            self.edit(chat_id, message_id, "Chọn style:", self._style_keyboard())
            return
        if action == "menu" and arg == "voice":
            self.answer_callback(cb_id)
            self.edit(chat_id, message_id, "Chọn giọng đọc:", self._voice_keyboard())
            return
        if action == "style" and arg in STYLE_LABELS:
            self._update_defaults(style=arg)
            toast = f"Style: {STYLE_LABELS[arg]}"
        elif action == "voice":
            voices = self._safe_voices()
            try:
                voice = voices[int(arg)]
            except (ValueError, IndexError):
                self.answer_callback(cb_id, "Danh sách giọng đã đổi, mở lại /settings.")
                return
            self._update_defaults(voice_id=voice["voice_id"])
            toast = f"Giọng: {voice.get('name') or voice['voice_id']}"
        elif action == "t" and arg in TOGGLE_FIELDS:
            d = self._update_defaults(**{arg: not self.defaults_loader()[arg]})
            toast = f"{TOGGLE_FIELDS[arg]}: {'bật' if d[arg] else 'tắt'}"
        elif action == "ask" and arg in INPUT_PROMPTS:
            with self._lock:
                self._pending_input[chat_id] = arg
            self.answer_callback(cb_id)
            self.send(chat_id, INPUT_PROMPTS[arg] + "\n(/cancel để hủy)")
            return
        self.answer_callback(cb_id, toast)
        self.edit(chat_id, message_id, self._settings_text(), self._settings_keyboard())

    def _handle_setting_input(self, chat_id: int, field: str, text: str) -> None:
        raw = text.strip()
        if field == "script_theme":
            value: Any = "" if raw in ("-", "") else raw[:300]
        else:
            lo, hi = (0.0, 1.0) if field == "video_shift_ratio" else (0.1, 3.0)
            try:
                value = float(raw.replace(",", "."))
            except ValueError:
                self.send(chat_id, f"Cần nhập số từ {lo} đến {hi}. Thử lại hoặc /cancel.")
                return
            if not lo <= value <= hi:
                self.send(chat_id, f"Giá trị phải từ {lo} đến {hi}. Thử lại hoặc /cancel.")
                return
        with self._lock:
            self._pending_input.pop(chat_id, None)
        self._update_defaults(**{field: value})
        self.send(chat_id, "Đã lưu.\n" + self._settings_text(), self._settings_keyboard())

    # ------------------------------------------------------------ dispatch
    # Thứ tự lock: listener của JobManager chạy khi JobManager đang giữ lock của
    # nó, nên ở đây KHÔNG gọi JobManager khi đang giữ self._lock / self._job_lock.
    def _dispatch_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.dispatch_once()
            except Exception:
                logger.exception("Telegram dispatch lỗi")
            self._stop.wait(DISPATCH_INTERVAL_SEC)

    def dispatch_once(self) -> None:
        """Báo kết quả job đã xong; rảnh thì gom hàng chờ thành batch mới."""
        current = self.job_manager.current
        running = self.job_manager.is_running()
        current_dict = current.to_dict()

        with self._job_lock:
            job_id = self._job_id
            last = self._last_snapshot
        if job_id is not None:
            if current_dict["job_id"] == job_id:
                if running or current_dict["status"] not in JOB_TERMINAL:
                    return  # vẫn đang chạy
                finished: Optional[Dict[str, Any]] = current_dict
            else:
                finished = last
            self._finish_job(finished)

        if running:
            return
        with self._lock:
            batch = list(self._queue)
        if not batch:
            return
        defaults = self.defaults_loader()
        kwargs = ai_video_defaults.build_batch_kwargs(
            [q.url for q in batch],
            defaults,
            themes=[q.theme for q in batch],
            shifts=[q.shift for q in batch],
            scales=[q.scale for q in batch],
            post_ats=[q.post_at.isoformat(timespec="minutes") if q.post_at else None for q in batch],
        )
        try:
            snapshot = self.job_manager.create_batch(kwargs.pop("items_payload"), **kwargs)
        except RuntimeError:
            return  # job khác vừa chạy, đợi vòng sau
        except Exception as exc:
            self._drop_from_queue(batch)
            for chat in {q.chat_id for q in batch}:
                self.send(chat, f"Không khởi tạo được job: {exc}")
            return
        self._drop_from_queue(batch)
        snap_dict = snapshot.to_dict()
        with self._job_lock:
            self._job_id = snap_dict["job_id"]
            self._job_chats = {it["index"]: q.chat_id for it, q in zip(snap_dict["items"], batch)}
            self._notified = set()
            self._last_snapshot = snap_dict

        summary = ai_video_defaults.describe(defaults)
        for chat in sorted({q.chat_id for q in batch}):
            n = sum(1 for q in batch if q.chat_id == chat)
            self.send(chat, f"Bắt đầu AI Video cho {n} link.\n{summary}")

    def _drop_from_queue(self, batch: List[QueuedLink]) -> None:
        ids = {id(q) for q in batch}
        with self._lock:
            self._queue = [q for q in self._queue if id(q) not in ids]

    def _on_job_update(self, snapshot: Any) -> None:
        """Listener của JobManager (chạy trên luồng job): báo từng video xong/lỗi."""
        with self._job_lock:
            if self._job_id is None or getattr(snapshot, "job_id", None) != self._job_id:
                return
            self._last_snapshot = snapshot.to_dict()
            ready = []
            for it in self._last_snapshot["items"]:
                if it["index"] in self._notified:
                    continue
                if it.get("status") in DONE_STATUSES | FAIL_STATUSES:
                    self._notified.add(it["index"])
                    chat = self._job_chats.get(it["index"])
                    if chat is not None:
                        ready.append((chat, it))
        for chat, it in ready:
            threading.Thread(target=self._notify_item, args=(chat, it), daemon=True).start()

    def _notify_item(self, chat: int, item: Dict[str, Any]) -> None:
        if item.get("status") in DONE_STATUSES:
            path = item.get("final_video_path")
            caption = f"✅ Xong video #{item['index']}\n{item['url']}"
            if path and self.send_video and self._send_video_file(chat, Path(path), caption):
                return
            self.send(chat, caption + (f"\nFile: {path}" if path else ""))
        else:
            self.send(chat, f"❌ Lỗi video #{item['index']}\n{item['url']}\n{item.get('error') or ''}".strip())

    def _finish_job(self, snapshot: Optional[Dict[str, Any]]) -> None:
        with self._job_lock:
            chats = set(self._job_chats.values())
            self._job_id = None
            self._job_chats = {}
            self._notified = set()
            self._last_snapshot = None
        items = (snapshot or {}).get("items") or []
        ok = sum(1 for it in items if it.get("status") in DONE_STATUSES)
        fail = len(items) - ok
        status = (snapshot or {}).get("status", "?")
        for chat in chats:
            self.send(chat, f"Job kết thúc ({status}): {ok} thành công, {fail} lỗi/chưa xong.")

    def _status_text(self) -> str:
        snap = self.job_manager.current
        with self._lock:
            waiting = len(self._queue)
        if not self.job_manager.is_running():
            return f"Không có job đang chạy. Hàng chờ: {waiting} link."
        lines = [f"Job {snap.status}:"]
        for it in snap.items:
            lines.append(f"#{it.index} {it.status} – {it.url}")
        lines.append(f"Hàng chờ: {waiting} link.")
        return "\n".join(lines)


def _load_voices() -> List[Dict[str, Any]]:
    from src.voices import list_voice_options

    return list_voice_options()


_bot: Optional[TelegramBot] = None


def start_from_env(job_manager: Any) -> Optional[TelegramBot]:
    """Khởi động bot nếu .env có TELEGRAM_BOT_TOKEN (gọi lúc FastAPI startup)."""
    global _bot
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or _bot is not None:
        return _bot
    allowed = parse_chat_ids(os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", ""))
    if not allowed:
        logger.warning(
            "TELEGRAM_ALLOWED_CHAT_IDS trống: bot sẽ không chạy job nào, chỉ trả lời chat id. "
            "Nhắn bot để lấy chat id rồi thêm vào .env."
        )
    _bot = TelegramBot(
        token,
        job_manager,
        allowed,
        send_video=_env_bool("TELEGRAM_SEND_VIDEO", False),
    )
    _bot.start()
    return _bot


def stop() -> None:
    global _bot
    if _bot is not None:
        _bot.stop()
        _bot = None


__all__ = ["TelegramBot", "extract_tiktok_urls", "parse_chat_ids", "parse_link_options", "parse_links_with_themes", "start_from_env", "stop"]
