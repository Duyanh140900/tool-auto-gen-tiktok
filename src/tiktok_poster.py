"""tiktok_poster.py

Đăng video hẹn giờ lên TikTok Studio web (Playwright) và gắn giỏ hàng sản phẩm
vừa thêm vào Showcase, với tên sản phẩm ngắn gọn hài hước do 9router đặt.

Luồng (giống thao tác tay, selector dò trên TikTok Studio 11/2026):
  1. Màn Posts (tiktokstudio/content): đọc các bài đang hẹn giờ (nhãn đồng hồ)
     -> mốc muộn nhất -> slot kế tiếp (8h/12h/18h/22h).
  2. Trang video nguồn: đọc sản phẩm gắn trong video (keyword + product_id).
  3. Trang upload: chọn file -> chờ "Uploaded" -> nhập caption + hashtag
     -> Add link -> Products -> Next -> tìm theo Product ID trong Showcase -> chọn
     -> Next -> đổi "Product name" thành tên ngắn -> Add
     -> When to post: Schedule -> chọn ngày + giờ -> đọc lại 2 ô -> bấm Schedule.
  4. Đọc lại màn Posts để xác nhận slot vừa hẹn đã có.

Trình duyệt dùng hồ sơ riêng (``.tiktok_browser_profile``): lần đầu cửa sổ Chrome
mở ra trang đăng nhập, bạn tự đăng nhập tay, tool chờ rồi chạy tiếp; các lần sau
giữ phiên đăng nhập.

Cài: ``pip install playwright`` (dùng Chrome có sẵn; không có Chrome thì thêm
``python -m playwright install chromium``).

Khi tool bấm sai (TikTok đổi giao diện): mỗi lần lỗi tool lưu ảnh + HTML vào
``<FINAL_OUTPUT_DIR>/post_dump/`` để chỉnh selector ở phần cấu hình bên dưới.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import random
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.post_schedule import MIN_LEAD, PostSchedule, next_slot_after, within_horizon

logger = logging.getLogger("tiktok.poster")

# ---------- Cấu hình ----------
STUDIO_UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=webapp"
STUDIO_CONTENT_URL = "https://www.tiktok.com/tiktokstudio/content"
LOGIN_WAIT = 300           # giây chờ bạn đăng nhập tay lần đầu
UPLOAD_TIMEOUT = 300       # giây chờ video tải lên xong
STEP_TIMEOUT = 15_000      # ms chờ mỗi bước
PRODUCT_NAME_MAX = 30      # TikTok giới hạn tên sản phẩm hiển thị trên giỏ hàng
# Nhịp giống người dùng thật (giây, ngẫu nhiên trong khoảng). Mặc định không nghỉ giữa 2 bài;
# muốn nghỉ thì đặt POST_DELAY_SECONDS trong .env, vd "60-120".
DELAY_BETWEEN_POSTS = (0, 0)      # nghỉ giữa 2 bài
STEP_PAUSE = (1.2, 3.0)           # nghỉ giữa các bước (bấm nút, mở hộp thoại)
READ_PAUSE = (3.0, 6.0)           # "xem" video/màn hình sau khi tải lên, trước khi bấm Schedule
TYPE_DELAY = (0.06, 0.18)         # giữa 2 ký tự khi gõ

# Selector TikTok Studio (dò 11/2026, giao diện tiếng Anh; có kèm chữ tiếng Việt).
FILE_INPUT = 'input[type="file"]'
CAPTION_EDITOR = ".public-DraftEditor-content"
UPLOADED_TEXT = re.compile(r"Uploaded|Đã tải lên", re.I)
POPUP_DISMISS = re.compile(r"^(Got it|Đã hiểu)$", re.I)
ANCHOR_SECTION = ".anchor-entry-container"            # khu "Add link"
ADD_TEXT = re.compile(r"^(Add|Thêm)$", re.I)
NEXT_TEXT = re.compile(r"^(Next|Tiếp|Tiếp theo)$", re.I)
PRODUCT_ROW = "tr.product-tb-row"                     # dòng trong bảng Showcase products
PRODUCT_RADIO = ".TUXRadioStandalone"
SCHEDULE_LABEL = ".schedule-radio-container label"
SCHEDULE_TEXT = re.compile(r"^(Schedule|Lên lịch)$", re.I)
SCHEDULE_RADIO = "input[value=schedule]"
SCHEDULE_BOX = ".scheduled-container"                 # chứa ô giờ (HH:MM) và ô ngày (YYYY-MM-DD)
SCHEDULE_TITLE = ".scheduled-container .title-v2"     # bấm vào để đóng ô chọn giờ
HOUR_OPTION = "span.tiktok-timepicker-left"
MINUTE_OPTION = "span.tiktok-timepicker-right"
CALENDAR = ".calendar-wrapper"
CALENDAR_ARROW = "span.arrow"                         # [0] tháng trước, [1] tháng sau
CALENDAR_DAY = "span.day.valid"
SUBMIT_BUTTON = 'button[data-e2e="post_video_button"]'
# Hộp "Continue to post?" khi TikTok chưa kiểm tra xong video -> bấm "Post now" (vẫn là hẹn giờ)
CONTINUE_POST_TEXT = re.compile(r"Continue to post|Tiếp tục đăng", re.I)
POST_NOW_TEXT = re.compile(r"^(Post now|Đăng ngay)$", re.I)
SCHEDULED_BADGE = ".icon-label"                       # nhãn đồng hồ của bài đang hẹn ở màn Posts
# Ngày giờ ở màn Posts, vd "Nov 3, 10:00 PM", "Nov 3, 2027, 10:00 PM",
# bài vừa hẹn: "Nov 4, 8:00 AM (GMT+7) Bangkok"; giao diện tiếng Việt: "5 tháng 11, 10:00 CH"
STUDIO_DATE_JS = (
    r"/^([A-Za-z]{3,9}\.? \d{1,2}|\d{1,2} tháng \d{1,2})(, \d{4})?, \d{1,2}:\d{2}(\s?([AP]M|SA|CH))?"
    r"( \(GMT[^)]*\).*)?$/"
)
# --------------------------------

_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_BROWSER_LOCK = threading.Lock()  # chỉ 1 phiên trình duyệt dùng hồ sơ đăng nhập


class PostError(RuntimeError):
    pass


class UnverifiedPostError(PostError):
    """Đã bấm Schedule nhưng chưa thấy bài ở màn Posts: coi như slot đã dùng, giữ lại file video."""


def delay_range(env_name: str, default: tuple) -> tuple:
    """Đọc khoảng nghỉ "a-b" (giây) từ .env, sai định dạng thì dùng mặc định."""
    raw = os.environ.get(env_name, "").strip()
    try:
        low, high = (float(x) for x in raw.split("-", 1))
        return (min(low, high), max(low, high))
    except ValueError:
        return default


def _profile_dir() -> Path:
    from config import PROJECT_ROOT

    return PROJECT_ROOT / ".tiktok_browser_profile"


def _dump_dir() -> Path:
    from config import settings

    return Path(getattr(settings, "FINAL_OUTPUT_DIR", "output")) / "post_dump"


def _fold(text: str) -> str:
    """Bỏ dấu + chữ thường để so tên sản phẩm (khoá/khóa, Đ/đ...)."""
    text = unicodedata.normalize("NFD", (text or "").replace("￼", "")).replace("đ", "d").replace("Đ", "D")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text).strip().lower()


def parse_studio_datetime(text: str, now: datetime) -> datetime:
    """'Nov 3, 10:00 PM' / '3 tháng 11, 10:00 CH' -> datetime. Không có năm thì lấy năm gần ``now``."""
    vi = re.match(
        r"^(\d{1,2}) tháng (\d{1,2})(?:, (\d{4}))?, (\d{1,2}):(\d{2})\s?(SA|CH)?(?: \(GMT[^)]*\).*)?$", text.strip()
    )
    if vi:  # SA = sáng (AM), CH = chiều (PM)
        mer = {"SA": "AM", "CH": "PM"}.get(vi.group(6) or "", "")
        month_name = _MONTHS[int(vi.group(2)) - 1].capitalize()
        year = f", {vi.group(3)}" if vi.group(3) else ""
        text = f"{month_name} {vi.group(1)}{year}, {vi.group(4)}:{vi.group(5)}" + (f" {mer}" if mer else "")
    m = re.match(
        r"^([A-Za-z]{3})[A-Za-z]*\.? (\d{1,2})(?:, (\d{4}))?, (\d{1,2}):(\d{2})\s?([AP]M)?(?: \(GMT[^)]*\).*)?$",
        text.strip(),
    )
    if not m or m.group(1).lower() not in _MONTHS:
        raise PostError(f"Không hiểu định dạng ngày giờ ở TikTok Studio: {text!r}")
    month = _MONTHS.index(m.group(1).lower()) + 1
    hour, minute = int(m.group(4)), int(m.group(5))
    if m.group(6):
        hour = hour % 12 + (12 if m.group(6).upper() == "PM" else 0)
    if m.group(3):
        return datetime(int(m.group(3)), month, int(m.group(2)), hour, minute)
    value = datetime(now.year, month, int(m.group(2)), hour, minute)
    if value < now - timedelta(days=180):  # vd đang tháng 12, lịch hẹn tháng 1 năm sau
        value = value.replace(year=now.year + 1)
    return value


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip()


def is_duplicate_caption(caption: str, studio_captions: List[str]) -> bool:
    """Bài đã có trên TikTok? So tối đa 50 ký tự đầu của caption (bỏ khác biệt khoảng trắng)."""
    mine = _squash(caption)
    for other in map(_squash, studio_captions):
        n = min(50, len(mine), len(other))
        if n >= 15 and mine[:n] == other[:n]:
            return True
    return False


def caption_from_filename(video_path: str) -> str:
    """Tên file video = caption + hashtag (pipeline cắt ở 120 ký tự) -> bỏ hashtag cuối bị cắt dở."""
    stem = Path(video_path).stem.strip()
    parts = stem.split()
    if len(stem) >= 115 and len(parts) > 1 and parts[-1].startswith("#"):
        parts = parts[:-1]
    return " ".join(parts)


def move_to_trash(path: str) -> None:
    """Chuyển file vào Thùng rác (khôi phục được), không xóa vĩnh viễn."""
    from send2trash import send2trash

    send2trash(str(Path(path)))


def choose_anchor(anchors: List[Dict[str, str]], product_name: str) -> Optional[Dict[str, str]]:
    """Chọn sản phẩm gắn trong video nguồn khớp tên Showcase; video 1 sản phẩm thì lấy luôn."""
    want = _fold(product_name)
    if want:
        for a in anchors:
            got = _fold(a.get("keyword", ""))
            if got and (got == want or got in want or want in got):
                return a
    return anchors[0] if len(anchors) == 1 else None


# ---------- Tên sản phẩm ngắn (9router) ----------

SHORT_NAME_SYSTEM = (
    "Bạn đặt tên hiển thị cho giỏ hàng sản phẩm trên video TikTok bán hàng tiếng Việt. "
    "Tên chỉ gồm 2 tiếng (tối đa 3), ngắn gọn, hài hước, bắt tai, vẫn đoán được là sản phẩm gì, "
    "vd: 'Gương Thần', 'Ủi Thần Tốc', 'Tất Thơm'. "
    "Không emoji, không dấu ngoặc kép, không hashtag. Chỉ trả về đúng cái tên."
)


def _fallback_short_name(product_name: str) -> str:
    words = re.sub(r"[\[\]\(\)【】|,.\-–_/]+", " ", product_name).split()
    return " ".join(words[:2])[:PRODUCT_NAME_MAX] or "Siêu phẩm"


def clean_short_name(raw: str, product_name: str) -> str:
    name = (raw or "").strip().splitlines()[0] if (raw or "").strip() else ""
    name = re.sub(r"^(tên|name)\s*:\s*", "", name, flags=re.I)
    name = name.strip(" \"'“”‘’`*.#")
    if not name:
        return _fallback_short_name(product_name)
    return name[:PRODUCT_NAME_MAX].strip()


ANCHOR_PICK_SYSTEM = (
    "Bạn chọn đúng sản phẩm đang được review trong một video TikTok bán hàng. "
    "Cho tên sản phẩm AI nhận diện từ video, caption và danh sách sản phẩm được gắn trong video nguồn (đánh số). "
    "Trả về DUY NHẤT số thứ tự của sản phẩm khớp nhất. "
    "Nếu không chắc chắn hoặc có từ 2 sản phẩm khớp ngang nhau thì trả về 0."
)


def parse_anchor_choice(raw: str, count: int) -> Optional[int]:
    """Số thứ tự (1..count) LLM trả về -> index 0-based; 0 / lạ -> None."""
    m = re.search(r"\d+", raw or "")
    if not m:
        return None
    n = int(m.group())
    return n - 1 if 1 <= n <= count else None


def pick_anchor_llm(anchors: List[Dict[str, str]], product_hint: str, caption: str = "") -> Optional[Dict[str, str]]:
    """Video nguồn gắn nhiều sản phẩm mà không có tên Showcase: nhờ LLM chọn theo tên AI nhận diện."""
    from src.script_generator import call_llm

    if not anchors or not (product_hint or caption):
        return None
    lines = [f"{i}. {a.get('title') or a.get('keyword')}" for i, a in enumerate(anchors, start=1)]
    prompt = f"Sản phẩm trong video: {product_hint or '(không rõ)'}"
    if caption:
        prompt += f"\nCaption video: {caption}"
    prompt += "\nSản phẩm gắn trong video nguồn:\n" + "\n".join(lines)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            raw = pool.submit(
                lambda: asyncio.run(call_llm(prompt, system_message=ANCHOR_PICK_SYSTEM, max_tokens=10))
            ).result(timeout=120)
    except Exception as exc:
        logger.warning(f"9router không chọn được sản phẩm: {exc}")
        return None
    idx = parse_anchor_choice(raw, len(anchors))
    logger.info(f"AI chọn sản phẩm {raw!r} cho '{product_hint}' trong {len(anchors)} sản phẩm")
    return anchors[idx] if idx is not None else None


def make_short_name(product_name: str, caption: str = "") -> str:
    """Nhờ LLM (9router, cấu hình LLM_* trong .env) đặt tên ~2 từ hài hước."""
    from src.script_generator import call_llm

    prompt = f"Sản phẩm: {product_name}"
    if caption:
        prompt += f"\nCaption video: {caption}"
    try:
        # Luồng riêng: luồng đăng bài đang có event loop của Playwright nên không asyncio.run được
        with ThreadPoolExecutor(max_workers=1) as pool:
            raw = pool.submit(
                lambda: asyncio.run(call_llm(prompt, system_message=SHORT_NAME_SYSTEM, max_tokens=50))
            ).result(timeout=120)
    except Exception as exc:
        logger.warning(f"9router không đặt được tên ngắn, dùng tên rút gọn: {exc}")
        raw = ""
    return clean_short_name(raw, product_name)


def _parse_post_at(value: Optional[str]) -> Optional[datetime]:
    """Giờ đăng hẹn riêng (ISO) -> datetime; rỗng/sai định dạng -> None (dùng slot tự động)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


# ---------- Điều khiển TikTok Studio ----------


@dataclass
class PostTask:
    index: int
    video_path: str
    caption: str
    product_name: str  # tên sản phẩm trên Showcase (điện thoại), dùng để chọn đúng sản phẩm của video
    source_url: str = ""
    product_hint: str = ""  # tên sản phẩm AI nhận diện (kịch bản), dùng khi không có tên Showcase
    post_at: Optional[str] = None  # giờ đăng hẹn riêng ISO "YYYY-MM-DDTHH:MM"; None = slot tự động


class StudioSession:
    """Một phiên Chrome (Playwright) đã đăng nhập TikTok, dùng lại cho nhiều bài."""

    def __init__(self, on_status: Optional[Callable[[str], None]] = None) -> None:
        self.on_status = on_status or (lambda msg: None)  # worker đổi theo từng bài
        self._owns_lock = False
        self._pw = None
        self._context = None
        self.page = None

    def open(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise PostError("Chưa cài Playwright. Chạy: pip install playwright") from exc
        if not _BROWSER_LOCK.acquire(blocking=False):
            raise PostError("Trình duyệt đăng bài đang được dùng bởi tác vụ khác.")
        self._owns_lock = True
        try:
            self._pw = sync_playwright().start()
            kwargs = dict(
                user_data_dir=str(_profile_dir()),
                headless=False,
                no_viewport=True,  # dùng đúng kích thước cửa sổ như người dùng
                # Selector dò trên giao diện tiếng Anh; hồ sơ đồng bộ Google mang tiếng Việt về -> ép tiếng Anh
                locale="en-US",
                args=["--lang=en-US", "--window-size=1400,950", "--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],  # bỏ thanh "Chrome đang bị phần mềm tự động điều khiển"
            )
            try:
                self._context = self._pw.chromium.launch_persistent_context(channel="chrome", **kwargs)
            except Exception:
                self._context = self._pw.chromium.launch_persistent_context(**kwargs)
            self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
            self.page.set_default_timeout(STEP_TIMEOUT)
        except Exception as exc:
            self.close()
            raise PostError(f"Không mở được Chrome đăng bài (đóng cửa sổ Chrome của tool nếu đang mở): {exc}") from exc

    def close(self) -> None:
        for closer in (lambda: self._context and self._context.close(), lambda: self._pw and self._pw.stop()):
            try:
                closer()
            except Exception:
                pass
        self._context = self._pw = self.page = None
        if self._owns_lock:
            self._owns_lock = False
            _BROWSER_LOCK.release()

    def dump(self, name: str, page: Any = None) -> Optional[str]:
        page = page or self.page
        if not page:
            return None
        try:
            folder = _dump_dir()
            folder.mkdir(parents=True, exist_ok=True)
            stem = folder / f"{datetime.now():%Y%m%d_%H%M%S}_{name}"
            page.screenshot(path=f"{stem}.png", full_page=True)
            Path(f"{stem}.html").write_text(page.content(), encoding="utf-8")
            return f"{stem}.png"
        except Exception as exc:
            logger.warning(f"Không lưu được dump TikTok Studio: {exc}")
            return None

    # -------- Thao tác kiểu người dùng thật --------
    def _pause(self, span: tuple = STEP_PAUSE) -> None:
        self.page.wait_for_timeout(int(random.uniform(*span) * 1000))

    def _click(self, locator: Any) -> None:
        """Di chuột tới một điểm ngẫu nhiên trên phần tử rồi bấm, thay vì bấm tức thì."""
        locator.scroll_into_view_if_needed()
        self._pause((0.4, 1.0))
        box = locator.bounding_box()
        if not box:
            locator.click()
            return
        x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
        y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
        self.page.mouse.move(x, y, steps=random.randint(12, 30))
        self._pause((0.15, 0.5))
        self.page.mouse.click(x, y, delay=random.randint(50, 140))

    def _hover(self, locator: Any) -> None:
        """Rê chuột qua phần tử (dùng trước các ô chỉ bấm được bằng JS)."""
        box = locator.bounding_box()
        if box:
            self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=random.randint(8, 20))
        self._pause((0.3, 0.8))

    def _type(self, text: str) -> None:
        """Gõ từng ký tự với nhịp ngẫu nhiên, thỉnh thoảng ngừng lâu hơn sau dấu cách."""
        for ch in text:
            self.page.keyboard.type(ch)
            span = (0.25, 0.6) if ch == " " and random.random() < 0.15 else TYPE_DELAY
            self.page.wait_for_timeout(int(random.uniform(*span) * 1000))

    def _goto(self, page: Any, url: str) -> None:
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("load", timeout=30_000)
        except Exception:
            pass

    def _wait_logged_in(self, page: Any, ready_selector: str, url: str) -> None:
        """Chờ trang sẵn sàng; nếu bị đẩy sang trang đăng nhập thì chờ bạn đăng nhập tay."""
        deadline = time.time() + LOGIN_WAIT
        notified = False
        while True:
            if url.split("?")[0] in page.url:
                try:
                    page.locator(ready_selector).first.wait_for(state="attached", timeout=5_000)
                    return
                except Exception:
                    pass
            else:
                page.wait_for_timeout(2000)
            if time.time() > deadline:
                raise PostError("Hết thời gian chờ đăng nhập TikTok trên cửa sổ Chrome.")
            if "login" in page.url:
                if not notified:
                    self.on_status("Chờ bạn đăng nhập TikTok trên cửa sổ Chrome vừa mở")
                    notified = True
            elif url.split("?")[0] not in page.url:
                self._goto(page, url)

    # -------- Màn Posts: đang hẹn đến đâu --------
    def read_posts(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Đọc màn Posts: mọi bài đang hẹn (cuộn tới khi gặp bài đã đăng) + các bài đã đăng gần nhất.

        Trả về [{"when": datetime, "scheduled": bool, "caption": str}].
        """
        now = now or datetime.now()
        page = self._context.new_page()
        page.set_default_timeout(STEP_TIMEOUT)
        js_leaves = f"""[...document.querySelectorAll('*')]
            .filter(e => e.children.length === 0 && {STUDIO_DATE_JS}.test(e.textContent.trim()))"""
        # Caption: dòng đầu của hàng (bỏ thời lượng "00:25" và chính dòng ngày giờ)
        js_rows = rf"""() => {js_leaves}.map(e => {{
            const date = e.textContent.trim();
            let row = e.parentElement;
            for (let i = 0; i < 8 && row && !/(^|\n)\d\d:\d\d(\n|$)/.test(row.innerText); i++) row = row.parentElement;
            const lines = row ? row.innerText.split('\n').map(l => l.trim()).filter(Boolean) : [];
            const caption = lines.find(l => l !== date && !/^\d\d:\d\d$/.test(l)) || '';
            return [date, !!e.closest('{SCHEDULED_BADGE}'), caption];
        }})"""
        try:
            self._goto(page, STUDIO_CONTENT_URL)
            self._wait_logged_in(page, "body", STUDIO_CONTENT_URL)
            try:
                page.wait_for_function(f"() => {js_leaves}.length > 0", timeout=30_000)
            except Exception:
                raise PostError("Không đọc được danh sách bài ở màn Posts của TikTok Studio")
            # Danh sách ảo: cuộn xuống thì các dòng trên cùng bị gỡ khỏi trang -> gộp qua mọi lần cuộn
            seen: Dict[tuple, None] = {}
            for _ in range(60):  # mỗi lần cuộn tải thêm ~20 bài
                visible = page.evaluate(js_rows)
                before = len(seen)
                for row in visible:
                    seen.setdefault(tuple(row), None)
                if not visible[-1][1] or (len(seen) == before and _ > 0):
                    break  # bài cuối đang thấy là bài đã đăng (đã qua hết bài hẹn giờ), hoặc hết bài mới
                page.evaluate(f"() => {{ const r = {js_leaves}; r[r.length - 1].scrollIntoView(); }}")
                page.wait_for_timeout(2000)
            rows = list(seen)
            return [
                {"when": parse_studio_datetime(date, now), "scheduled": scheduled, "caption": caption}
                for date, scheduled, caption in rows
            ]
        except PostError as exc:
            shot = self.dump("posts", page)
            raise PostError(f"{exc}" + (f" (ảnh: {shot})" if shot else "")) from exc
        finally:
            page.close()

    def read_scheduled_slots(self, now: Optional[datetime] = None) -> List[datetime]:
        return [p["when"] for p in self.read_posts(now) if p["scheduled"]]

    def read_last_scheduled(self) -> Optional[datetime]:
        slots = self.read_scheduled_slots()
        return max(slots) if slots else None

    # -------- Trang video nguồn: sản phẩm gắn trong video --------
    def fetch_anchors(self, source_url: str) -> List[Dict[str, str]]:
        """[{keyword, product_id, title}] của các sản phẩm gắn trong video nguồn."""
        page = self._context.new_page()
        try:
            raw = ""
            for _ in range(3):
                try:
                    self._goto(page, source_url)
                    page.wait_for_timeout(3000)
                    raw = page.evaluate(
                        "() => (document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__')||{}).textContent || ''"
                    )
                    if raw:
                        break
                except Exception:
                    page.wait_for_timeout(2000)
            data = json.loads(raw) if raw else {}
            item = (
                data.get("__DEFAULT_SCOPE__", {}).get("webapp.video-detail", {})
                .get("itemInfo", {}).get("itemStruct", {})
            )
            anchors: List[Dict[str, str]] = []
            for anchor in item.get("anchors") or []:
                try:
                    extras = json.loads(anchor.get("extra") or "[]")
                except ValueError:
                    continue
                for ex in extras if isinstance(extras, list) else [extras]:
                    inner = ex.get("extra") if isinstance(ex, dict) else None
                    if isinstance(inner, str):
                        try:
                            inner = json.loads(inner)
                        except ValueError:
                            inner = None
                    product_id = str((inner or {}).get("product_id") or ex.get("id") or "")
                    if product_id:
                        anchors.append({
                            "keyword": ex.get("keyword") or "",
                            "product_id": product_id,
                            "title": (inner or {}).get("title") or ex.get("keyword") or "",
                        })
            return anchors
        finally:
            page.close()

    # -------- Trang upload --------
    def _dismiss_popups(self) -> None:
        btn = self.page.get_by_role("button", name=POPUP_DISMISS)
        for i in range(btn.count()):
            try:
                if btn.nth(i).is_visible():
                    btn.nth(i).click()
            except Exception:
                pass

    def _open_upload_page(self) -> None:
        self._goto(self.page, STUDIO_UPLOAD_URL)
        self._wait_logged_in(self.page, FILE_INPUT, STUDIO_UPLOAD_URL)

    def _upload(self, video_path: str) -> None:
        self.page.locator(FILE_INPUT).first.set_input_files(video_path)
        self.page.get_by_text(UPLOADED_TEXT).first.wait_for(timeout=UPLOAD_TIMEOUT * 1000)
        self._pause(READ_PAUSE)
        self._dismiss_popups()

    def _set_caption(self, caption: str) -> None:
        """Thay mô tả TikTok tự điền (tên file) bằng caption; đọc lại, sai thì làm lại.

        Lần đầu gõ từng chữ như người. TikTok có thể vẽ lại ô mô tả (Draft.js) giữa chừng
        làm con trỏ nhảy về đầu -> các lần sau chèn cả caption trong 1 lần.
        """
        editor = self.page.locator(CAPTION_EDITOR).first
        squash = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731
        self._pause(READ_PAUSE)
        for attempt in range(3):
            self._click(editor)
            for _ in range(5):
                if not editor.inner_text().strip():
                    break
                editor.evaluate(
                    """el => { const r = document.createRange(); r.selectNodeContents(el);
                    const s = getSelection(); s.removeAllRanges(); s.addRange(r); }"""
                )
                self.page.keyboard.press("Backspace")
                self.page.wait_for_timeout(300)
            if editor.inner_text().strip():
                continue
            if attempt == 0:
                self._type(caption)
            else:
                self.page.keyboard.insert_text(caption)
            self.page.wait_for_timeout(1500)  # chờ gợi ý hashtag hiện rồi đóng
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(500)
            if squash(editor.inner_text()) == squash(caption):
                return
        raise PostError(f"Caption sau khi điền không khớp: {editor.inner_text()[:120]!r}")

    def _visible_dialog(self) -> Any:
        dialog = self.page.get_by_role("dialog").last
        dialog.wait_for(state="visible")
        return dialog

    def _attach_product(self, product_id: str, short_name: str) -> None:
        page = self.page
        section = page.locator(ANCHOR_SECTION).first
        section.scroll_into_view_if_needed()
        self._pause()
        self._click(section.get_by_text(ADD_TEXT).first)

        dialog = self._visible_dialog()  # "Add link" -> Link type: Products
        self._pause()
        self._click(dialog.get_by_role("button", name=NEXT_TEXT))

        self._pause()
        dialog = self._visible_dialog()  # "Add product links" -> bảng Showcase products
        search = dialog.locator("input[type=text]").first
        self._click(search)
        self._type(product_id)
        self._pause((0.4, 1.0))
        search.press("Enter")
        row = dialog.locator(PRODUCT_ROW).filter(has_text=product_id).first
        try:
            row.wait_for(state="visible", timeout=STEP_TIMEOUT)
        except Exception:
            raise PostError(f"Không thấy sản phẩm {product_id} trong Showcase products")
        self._pause()  # "đọc" kết quả tìm kiếm
        self._click(row.locator(PRODUCT_RADIO).first)
        if not row.locator("input[type=radio]").first.is_checked():
            raise PostError("Không chọn được sản phẩm trong bảng Showcase")
        self._pause()
        self._click(dialog.get_by_role("button", name=NEXT_TEXT))

        self._pause()
        dialog = self._visible_dialog()  # "Product name will appear on your video"
        name_input = dialog.locator("input[type=text]").first
        self._click(name_input)
        page.keyboard.press("Control+A")
        self._pause((0.3, 0.8))
        self._type(short_name)
        if name_input.input_value() != short_name:
            raise PostError(f"Không điền được tên sản phẩm: {name_input.input_value()!r}")
        self._pause()
        self._click(dialog.get_by_role("button", name=ADD_TEXT))
        dialog.wait_for(state="hidden", timeout=STEP_TIMEOUT)
        if short_name not in section.inner_text():
            raise PostError("Đã bấm Add nhưng giỏ hàng chưa hiện trong mục Add link")

    def _pick_schedule(self, slot: datetime) -> None:
        page = self.page
        self._pause()
        self._click(page.locator(SCHEDULE_LABEL).filter(has_text=SCHEDULE_TEXT).first)
        self._pause()
        if not page.locator(SCHEDULE_RADIO).first.is_checked():
            raise PostError("Không chọn được chế độ Schedule")

        inputs = page.locator(f"{SCHEDULE_BOX} input[type=text]")
        time_input = date_input = None
        for i in range(inputs.count()):
            value = inputs.nth(i).input_value()
            if re.match(r"^\d{1,2}:\d{2}$", value):
                time_input = inputs.nth(i)
            elif re.match(r"^\d{4}-\d{2}-\d{2}$", value):
                date_input = inputs.nth(i)
        if time_input is None or date_input is None:
            raise PostError("Không thấy ô ngày/giờ hẹn")

        # Ngày: mở lịch, chuyển tháng theo tiêu đề "November / 2026", bấm đúng số ngày
        self._click(date_input)
        self._pause()
        calendar = page.locator(CALENDAR).first
        for _ in range(14):
            header = calendar.inner_text().split("\n")[0]
            year = int(re.search(r"\d{4}", header).group())
            month = next(
                (i for i, m in enumerate(_MONTHS, 1) if m in header.lower()),
                int((re.search(r"(\d{1,2})\s*/", header) or re.search(r"(\d{1,2})", header)).group(1)),
            )
            if (year, month) == (slot.year, slot.month):
                break
            forward = (year, month) < (slot.year, slot.month)
            arrow = calendar.locator(CALENDAR_ARROW).nth(1 if forward else 0)
            self._hover(arrow)
            arrow.evaluate("e => e.click()")
            self._pause((0.5, 1.2))
        days = calendar.locator(CALENDAR_DAY).filter(has_text=re.compile(rf"^{slot.day}$"))
        if not days.count():
            raise PostError(f"Ngày {slot:%d/%m} chưa cho hẹn trên TikTok Studio")
        # Lịch hiện cả vài ngày của tháng trước/sau: ngày nhỏ lấy ô đầu, ngày lớn lấy ô cuối
        day = days.first if slot.day < 15 else days.nth(days.count() - 1)
        self._hover(day)
        day.evaluate("e => e.click()")
        self._pause()

        # Giờ: cột trái là giờ, cột phải là phút; click bằng JS vì cột đang cuộn mượt
        self._click(time_input)
        self._pause()
        page.locator(HOUR_OPTION).filter(has_text=re.compile(rf"^{slot:%H}$")).first.evaluate("e => e.click()")
        self._pause((0.8, 1.6))
        page.locator(MINUTE_OPTION).filter(has_text=re.compile(rf"^{slot:%M}$")).first.evaluate("e => e.click()")
        self._pause((0.8, 1.6))
        self._click(page.locator(SCHEDULE_TITLE).first)  # đóng ô chọn giờ
        self._pause()

        # Kiểm tra lại: sai ngày/giờ thì dừng, KHÔNG đăng
        got = f"{date_input.input_value()} {time_input.input_value()}"
        want = slot.strftime("%Y-%m-%d %H:%M")
        if got != want:
            raise PostError(f"Chọn lịch sai: muốn {want}, ô đang là {got}")

    def _submit_and_verify(self, slot: datetime) -> None:
        button = self.page.locator(SUBMIT_BUTTON).first
        if not SCHEDULE_TEXT.match(button.inner_text().strip()):
            raise PostError(f"Nút đăng đang là {button.inner_text()!r}, không phải Schedule")
        self._pause(READ_PAUSE)  # xem lại bài trước khi bấm
        self._click(button)
        # Từ đây bài có thể đã được hẹn: lỗi gì cũng báo "chưa xác nhận" để slot không bị dùng lại
        try:
            deadline = time.time() + 60
            while "tiktokstudio/content" not in self.page.url:
                if time.time() > deadline:
                    raise UnverifiedPostError("Đã bấm Schedule nhưng TikTok Studio không chuyển sang màn Posts")
                confirm = self.page.get_by_role("dialog").filter(has_text=CONTINUE_POST_TEXT)
                if confirm.count() and confirm.first.is_visible():
                    self.on_status("TikTok chưa kiểm tra xong video, bấm Post now để tiếp tục hẹn giờ")
                    self._pause()
                    self._click(confirm.first.get_by_role("button", name=POST_NOW_TEXT))
                self.page.wait_for_timeout(1000)
            self.page.wait_for_timeout(3000)
            for _ in range(2):  # bài mới đôi khi hiện chậm vài giây
                if slot in self.read_scheduled_slots():
                    return
                self.page.wait_for_timeout(5000)
            raise UnverifiedPostError(f"Đã bấm Schedule nhưng chưa thấy bài hẹn {slot:%H:%M %d/%m} ở màn Posts")
        except UnverifiedPostError:
            raise
        except Exception as exc:
            raise UnverifiedPostError(f"Đã bấm Schedule nhưng không kiểm tra lại được: {exc}") from exc

    def schedule_post(
        self, task: PostTask, anchor: Dict[str, str], short_name: str, slot: datetime, dry: bool
    ) -> str:
        """Đăng 1 video hẹn giờ. Trả về ghi chú; lỗi thì raise PostError (kèm file dump)."""
        try:
            self._open_upload_page()
            self.on_status("Đang tải video lên TikTok Studio")
            self._upload(task.video_path)
            self._set_caption(task.caption)
            self.on_status(f"Đang gắn giỏ hàng: {short_name}")
            self._attach_product(anchor["product_id"], short_name)
            self.on_status(f"Đang hẹn giờ {slot:%H:%M %d/%m}")
            self._pick_schedule(slot)
            if dry:
                return "chạy thử: đã điền đủ, không bấm Schedule"
            self._submit_and_verify(slot)
            return ""
        except PostError as exc:
            shot = self.dump(f"item{task.index}")
            raise type(exc)(f"{exc}" + (f" (ảnh: {shot})" if shot else "")) from exc
        except Exception as exc:
            shot = self.dump(f"item{task.index}")
            raise PostError(f"{type(exc).__name__}: {exc}" + (f" (ảnh: {shot})" if shot else "")) from exc


def check_studio_schedule(schedule: Optional[PostSchedule] = None) -> Dict[str, Any]:
    """Mở TikTok Studio, đọc mốc hẹn muộn nhất ở màn Posts và lưu vào sổ lịch."""
    schedule = schedule or PostSchedule()
    session = StudioSession()
    session.open()
    try:
        schedule.set_studio_last_slot(session.read_last_scheduled())
    finally:
        session.close()
    return schedule.summary()


# ---------- Worker nền ----------

PostListener = Callable[[int, Dict[str, Any]], None]
TERMINAL_POST_STATUSES = {"scheduled", "unverified", "waiting", "error", "cancelled", "thu"}


class PostWorker:
    """Hàng đợi đăng hẹn giờ, chạy sau bước Showcase của từng video.

    ``on_update(index, post_state)`` với ``post_state``::

        {"status": "queued|running|scheduled|waiting|thu|error|cancelled",
         "slot": "2026-11-05T08:00", "short_name", "product", "message", "dry"}
    """

    _STOP = object()

    def __init__(
        self,
        on_update: PostListener,
        *,
        dry: bool = False,
        mock: bool = False,
        cancel_event: Optional[threading.Event] = None,
        schedule: Optional[PostSchedule] = None,
        session_factory: Callable[..., StudioSession] = StudioSession,
        short_namer: Callable[[str, str], str] = make_short_name,
        anchor_picker: Callable[..., Optional[Dict[str, str]]] = pick_anchor_llm,
        delete_after: bool = False,
        trasher: Callable[[str], None] = move_to_trash,
    ) -> None:
        self._on_update = on_update
        self._delete_after = delete_after  # hẹn xong thì chuyển file video vào Thùng rác
        self._trasher = trasher
        self._dry = dry
        self._mock = mock
        self._cancel = cancel_event or threading.Event()
        self._schedule = schedule or PostSchedule()
        self._session_factory = session_factory
        self._short_namer = short_namer
        self._anchor_picker = anchor_picker
        self._session: Optional[StudioSession] = None
        self._studio_checked = False
        self._studio_captions: List[str] = []  # caption các bài đang có ở màn Posts (chống đăng trùng)
        self._last_run_slot: Optional[datetime] = None  # slot đã dùng trong lần chạy này (kể cả chạy thử)
        self._next_post_at: Optional[float] = None  # chưa tới lúc này thì nghỉ trước khi đăng bài kế tiếp
        self._used_studio = False  # bài vừa xử lý có thao tác trên TikTok Studio không
        self._submitted: set = set()
        self._queue: "queue.Queue[Any]" = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="tiktok-poster", daemon=True)
        self._thread.start()

    def submit(self, task: PostTask) -> bool:
        if task.index in self._submitted:
            return False
        self._submitted.add(task.index)
        self._emit(task, "queued", "Chờ đăng hẹn giờ")
        self._queue.put(task)
        return True

    def finish(self, timeout: Optional[float] = None) -> None:
        self._queue.put(self._STOP)
        self._thread.join(timeout)

    # -------- Internals --------
    def _emit(self, task: PostTask, status: str, message: str, **extra: Any) -> None:
        state = {"status": status, "message": message, "dry": self._dry, "product": task.product_name, **extra}
        try:
            self._on_update(task.index, state)
        except Exception:  # pragma: no cover
            logger.exception("post listener failed")

    def _record(self, task: PostTask, **fields: Any) -> None:
        if self._dry or self._mock:
            return
        self._schedule.upsert({
            "video_path": task.video_path,
            "source_url": task.source_url,
            "caption": task.caption,
            "product": task.product_name,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            **fields,
        })

    def _run(self) -> None:
        try:
            while True:
                task = self._queue.get()
                if task is self._STOP:
                    return
                if self._cancel.is_set():
                    self._emit(task, "cancelled", "Job đã hủy, bỏ qua đăng bài")
                    continue
                self._process(task)
                if self._used_studio:  # khoảng nghỉ tính từ lúc xong bài này
                    self._used_studio = False
                    gap = random.uniform(*delay_range("POST_DELAY_SECONDS", DELAY_BETWEEN_POSTS))
                    self._next_post_at = time.time() + gap
        finally:
            if self._session:
                self._session.close()

    def _next_slot(self, now: datetime) -> datetime:
        last = [s for s in (self._schedule.last_slot(), self._last_run_slot) if s]
        return next_slot_after(max(last) if last else None, now)

    def _fail(self, task: PostTask, message: str, **extra: Any) -> None:
        self._record(task, status="error", error=message, **{k: v for k, v in extra.items() if k == "short_name"})
        self._emit(task, "error", message, **extra)

    def _trash_video(self, task: PostTask) -> str:
        """Hẹn xong thì chuyển video vào Thùng rác. Trả về ghi chú thêm vào thông báo."""
        if not self._delete_after or self._dry or self._mock:
            return ""
        try:
            self._trasher(task.video_path)
        except Exception as exc:
            logger.warning(f"Không chuyển được video vào Thùng rác ({task.video_path}): {exc}")
            return f", chưa xóa được video: {exc}"
        self._record(task, deleted=True)
        return ", đã chuyển video vào Thùng rác"

    def _wait_before_next_post(self, task: PostTask) -> bool:
        """Nghỉ giữa 2 bài như người thật. Chỉ nghỉ khi còn bài để đăng, không nghỉ sau bài cuối
        (để job kết thúc ngay). Trả về False nếu job bị hủy trong lúc nghỉ."""
        if self._next_post_at is not None:
            remaining = self._next_post_at - time.time()
            if remaining > 0:
                self._emit(task, "running", f"Nghỉ {remaining:.0f} giây trước bài tiếp theo cho giống người thật")
                if self._cancel.wait(remaining):
                    self._emit(task, "cancelled", "Job đã hủy, bỏ qua đăng bài")
                    return False
        self._used_studio = True
        return True

    def _process(self, task: PostTask) -> None:
        if not task.video_path or (not self._mock and not Path(task.video_path).exists()):
            self._emit(task, "error", f"Không thấy file video: {task.video_path}")
            return
        done = self._schedule.find(task.video_path) if not (self._dry or self._mock) else None
        if done and done.get("status") == "scheduled":
            note = self._trash_video(task)
            self._emit(task, "scheduled", "Đã hẹn từ trước" + note, slot=done.get("slot"), short_name=done.get("short_name"))
            return

        if self._mock:
            custom = _parse_post_at(task.post_at)
            slot = custom or self._next_slot(datetime.now())
            if custom is None:
                self._last_run_slot = slot
            short_name = self._short_namer(task.product_name or "Sản phẩm", task.caption)
            self._emit(task, "thu", "mock, không mở TikTok Studio", slot=slot.isoformat(timespec="minutes"), short_name=short_name)
            return

        if not self._wait_before_next_post(task):
            return
        try:
            if self._session is None:
                session = self._session_factory()
                session.open()
                self._session = session
            self._session.on_status = lambda msg: self._emit(task, "running", msg)

            if not self._studio_checked:
                self._emit(task, "running", "Đang kiểm tra lịch đã hẹn trên TikTok Studio")
                posts = self._session.read_posts()
                scheduled = [p["when"] for p in posts if p["scheduled"]]
                self._schedule.set_studio_last_slot(max(scheduled) if scheduled else None, checked_at=datetime.now())
                self._studio_captions = [p["caption"] for p in posts]
                self._studio_checked = True

            if is_duplicate_caption(task.caption, self._studio_captions):
                prev = self._schedule.find(task.video_path) or {}
                if prev.get("status") == "unverified" and not self._dry:
                    # Lần trước bấm Schedule nhưng chưa xác nhận được; giờ đã thấy bài trên Studio
                    self._record(task, status="scheduled", error=None)
                    note = self._trash_video(task)
                    self._emit(task, "scheduled", "Đã xác nhận bài hẹn trên TikTok Studio" + note,
                               slot=prev.get("slot"), short_name=prev.get("short_name"))
                    return
                self._fail(task, "Bài trùng caption đã có trên TikTok Studio, bỏ qua (không xóa video)")
                return

            now = datetime.now()
            custom = _parse_post_at(task.post_at)
            if custom is not None:
                if custom < now + MIN_LEAD:
                    self._fail(task, f"Giờ đăng {custom:%H:%M %d/%m/%Y} đã qua hoặc cách hiện tại dưới {int(MIN_LEAD.total_seconds() // 60)} phút, bỏ qua đăng bài (không xóa video)")
                    return
                slot = custom
            else:
                slot = self._next_slot(now)
            slot_str = slot.isoformat(timespec="minutes")
            if not within_horizon(slot, now):
                self._record(task, status="waiting", **({"slot": slot_str, "custom_slot": True} if custom is not None else {}))
                self._emit(task, "waiting", f"Slot {slot:%H:%M %d/%m} quá {self._schedule_days()} ngày, chờ tới hạn rồi bấm 'Đăng hàng chờ'")
                return

            self._emit(task, "running", "Đang đọc sản phẩm của video nguồn", slot=slot_str)
            anchors = self._session.fetch_anchors(task.source_url)
            anchor = choose_anchor(anchors, task.product_name)
            if anchor is None and len(anchors) > 1 and (task.product_hint or task.caption):
                # Không có/không khớp tên Showcase (vd không cắm điện thoại): nhờ AI chọn theo tên nhận diện
                self._emit(task, "running", f"Video nguồn gắn {len(anchors)} sản phẩm, nhờ AI chọn", slot=slot_str)
                anchor = self._anchor_picker(anchors, task.product_hint, task.caption)
            if anchor is None:
                detail = task.product_name or task.product_hint or "không có tên"
                if len(anchors) > 1:
                    detail += f"; video nguồn gắn {len(anchors)} sản phẩm, AI không chọn chắc được"
                elif not anchors:
                    detail += "; không đọc được sản phẩm nào trong video nguồn"
                self._fail(task, f"Không xác định được sản phẩm của video nguồn để gắn giỏ hàng ({detail})", slot=slot_str)
                return

            self._emit(task, "running", "Đang đặt tên giỏ hàng (9router)", slot=slot_str)
            short_name = self._short_namer(anchor["title"], task.caption)
            self._session.on_status = lambda msg: self._emit(task, "running", msg, slot=slot_str, short_name=short_name)
            note = self._session.schedule_post(task, anchor, short_name, slot, self._dry)
        except UnverifiedPostError as exc:
            if custom is None:
                self._last_run_slot = slot
            self._studio_captions.append(task.caption)
            self._record(task, status="unverified", slot=slot_str, short_name=short_name, error=str(exc), custom_slot=custom is not None)
            self._emit(task, "unverified", f"{exc}. Đã giữ slot này, không xóa video", slot=slot_str, short_name=short_name)
            return
        except Exception as exc:
            if not isinstance(exc, PostError):
                logger.exception(f"post failed for {task.video_path}")
                if self._session:
                    self._session.close()
                self._session = None
            self._fail(task, str(exc), **({"slot": slot_str, "short_name": short_name} if "short_name" in locals() else {}))
            return

        if custom is None:
            self._last_run_slot = slot
        self._studio_captions.append(task.caption)
        status = "thu" if self._dry else "scheduled"
        self._record(task, status=status, slot=slot_str, short_name=short_name, product_id=anchor["product_id"], error=None, custom_slot=custom is not None)
        note = (note or f"Đã hẹn {slot:%H:%M %d/%m}") + self._trash_video(task)
        self._emit(task, status, note, slot=slot_str, short_name=short_name)

    @staticmethod
    def _schedule_days() -> int:
        from src.post_schedule import max_days_ahead

        return max_days_ahead()


def flush_waiting(on_update: Optional[PostListener] = None, dry: bool = False) -> List[Dict[str, Any]]:
    """Đăng các bài đang ở hàng chờ (``waiting``) khi slot đã lọt vào khoảng hẹn được."""
    schedule = PostSchedule()
    results: List[Dict[str, Any]] = []

    def collect(index: int, state: Dict[str, Any]) -> None:
        if state["status"] in TERMINAL_POST_STATUSES:
            results.append({"index": index, **state})
        if on_update:
            on_update(index, state)

    worker = PostWorker(collect, dry=dry, schedule=schedule)
    for i, post in enumerate(schedule.waiting(), start=1):
        worker.submit(PostTask(
            index=i,
            video_path=post["video_path"],
            caption=post.get("caption", ""),
            product_name=post.get("product", ""),
            source_url=post.get("source_url", ""),
            post_at=post.get("slot") if post.get("custom_slot") else None,
        ))
    worker.finish()
    return results


def build_caption(script: Optional[Dict[str, Any]], fallback: str = "") -> str:
    script = script or {}
    caption = (script.get("caption") or fallback or "").strip()
    tags = [t if t.startswith("#") else f"#{t}" for t in (script.get("hashtags") or []) if t]
    return " ".join([caption, *tags]).strip()


def pick_product_name(showcase: Optional[Dict[str, Any]]) -> str:
    """Lấy tên sản phẩm vừa thêm vào Showcase (ưu tiên thêm thành công / đã có)."""
    results = (showcase or {}).get("results") or []
    for wanted in (("thanh_cong", "da_co"), ("thu",)):
        for r in results:
            if r.get("status") in wanted and r.get("product"):
                return r["product"]
    return ""


__all__ = [
    "PostError",
    "PostTask",
    "PostWorker",
    "StudioSession",
    "build_caption",
    "caption_from_filename",
    "check_studio_schedule",
    "choose_anchor",
    "parse_anchor_choice",
    "pick_anchor_llm",
    "clean_short_name",
    "flush_waiting",
    "is_duplicate_caption",
    "move_to_trash",
    "make_short_name",
    "parse_studio_datetime",
    "pick_product_name",
]
