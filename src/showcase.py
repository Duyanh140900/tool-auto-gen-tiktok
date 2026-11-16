"""showcase.py

Tự động thêm sản phẩm gắn trong video TikTok nguồn vào "trang trưng bày"
(Showcase) ngay sau khi gen xong video. Chuyển từ tool ``tiktok_showcase.py``.

Luồng trên điện thoại Android (uiautomator2, giống thao tác tay):
  mở link video -> bấm thẻ sản phẩm (danh sách "Liên kết") -> bấm tên sản phẩm
  -> bấm mũi tên "Lên" -> bấm "Thêm vào trang trưng bày"

``ShowcaseWorker`` chạy trên luồng nền riêng với hàng đợi: job gen video gọi
``submit()`` khi một item xong, worker xử lý lần lượt trong lúc video tiếp
theo vẫn render. Điện thoại chỉ điều khiển được tuần tự nên chỉ có 1 worker.

Yêu cầu: ``pip install uiautomator2`` + ``python -m uiautomator2 init``, điện
thoại bật Gỡ lỗi USB và đã đăng nhập TikTok tài khoản creator. Nhiều thiết bị
thì đặt ``SHOWCASE_DEVICE_SERIAL`` trong .env.
"""
from __future__ import annotations

import csv
import logging
import os
import queue
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("tiktok.showcase")

# ---------- Cấu hình ----------
TIKTOK_PACKAGES = ["com.ss.android.ugc.trill", "com.zhiliaoapp.musically"]
# Nhịp giống người dùng thật (giây, ngẫu nhiên trong khoảng). Đổi nghỉ giữa 2 link bằng
# SHOWCASE_DELAY_SECONDS trong .env, vd "20-40".
DELAY_BETWEEN_LINKS = (8, 15)    # nghỉ giữa 2 link (thời gian render video đã được tính vào)
DELAY_BETWEEN_PRODUCTS = (3, 6)
STEP_PAUSE = (0.8, 1.8)          # nghỉ trước mỗi lần chạm
WATCH_VIDEO = (2, 4)             # "xem" video một lúc trước khi mở giỏ hàng
STEP_TIMEOUT = 10                # giây chờ mỗi bước
VIDEO_LOAD_WAIT = 6

# Selector dò trên app TikTok (OPPO, Android 17, 11/2026). App đổi giao diện thì sửa ở đây.
TAG_LAYOUT = ".*:id/feed_multi_tag_layout"   # thẻ sản phẩm trên video
TAG_EXPAND_DESC = "Xuống"                    # mũi tên mở danh sách "Liên kết"
LINK_SHEET_TEXT = "Liên kết"                 # tiêu đề danh sách sản phẩm
LINK_TITLE_ID = ".*:id/title"                # tên sản phẩm trong danh sách
UP_ARROW_DESC = "Lên"                        # mũi tên mở bảng hoa hồng
# Nút thêm: desc " Thêm vào trang trưng bày"; đã có: " disabled,Đã thêm vào\xa0trang trưng bày"
ADD_BUTTON_DESC = r"\s*Thêm vào[\s ]+trang trưng bày.*"
ALREADY_ADDED_DESC = r".*Đã thêm vào[\s ]+trang trưng bày.*"
# --------------------------------

# Trạng thái từng sản phẩm (giữ nguyên như tool gốc / ket_qua.csv)
OK_STATUSES = {"thanh_cong", "da_co", "thu"}
TERMINAL_STATUSES = {"done", "error", "cancelled"}


class ShowcaseError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Thao tác trên điện thoại ----------


def connect(serial: Optional[str] = None) -> Tuple[Any, str]:
    """Kết nối điện thoại qua adb. Trả về (device, package TikTok)."""
    try:
        import uiautomator2 as u2
    except ImportError as exc:
        raise ShowcaseError(
            "Chưa cài uiautomator2. Chạy: pip install uiautomator2 && python -m uiautomator2 init"
        ) from exc

    serial = serial or os.environ.get("SHOWCASE_DEVICE_SERIAL") or None
    try:
        d = u2.connect(serial)  # None = thiết bị USB đầu tiên mà adb thấy
        installed = d.shell("pm list packages").output
    except Exception as exc:
        raise ShowcaseError(f"Không kết nối được điện thoại qua adb: {exc}") from exc
    for pkg in TIKTOK_PACKAGES:
        if f"package:{pkg}" in installed:
            return d, pkg
    raise ShowcaseError("Không tìm thấy app TikTok trên thiết bị.")


def check_device(serial: Optional[str] = None) -> Dict[str, Any]:
    """Kiểm tra nhanh điện thoại cho nút "Kiểm tra điện thoại" trên UI."""
    try:
        d, pkg = connect(serial)
        info = d.device_info or {}
        return {
            "ok": True,
            "serial": info.get("serial") or serial,
            "model": info.get("model"),
            "package": pkg,
        }
    except ShowcaseError as exc:
        return {"ok": False, "error": str(exc)}


def delay_range(env_name: str, default: Tuple[float, float]) -> Tuple[float, float]:
    """Đọc khoảng nghỉ "a-b" (giây) từ .env, sai định dạng thì dùng mặc định."""
    raw = os.environ.get(env_name, "").strip()
    try:
        low, high = (float(x) for x in raw.split("-", 1))
        return (min(low, high), max(low, high))
    except ValueError:
        return default


def _pause(span: Tuple[float, float] = STEP_PAUSE) -> None:
    time.sleep(random.uniform(*span))


def _tap(obj) -> None:
    """Nghỉ một chút rồi chạm vào điểm ngẫu nhiên trên nút (không luôn chạm chính giữa)."""
    _pause()
    obj.click(offset=(random.uniform(0.3, 0.7), random.uniform(0.35, 0.65)))


def open_link(d, pkg, url):
    d.app_stop(pkg)
    d.shell(f'am start -a android.intent.action.VIEW -d "{url}" {pkg}')
    time.sleep(VIDEO_LOAD_WAIT)
    _pause(WATCH_VIDEO)


def open_link_sheet(d):
    """Mở danh sách 'Liên kết' của video. Trả về list tên sản phẩm."""
    tag = d(resourceIdMatches=TAG_LAYOUT)
    if not tag.wait(timeout=STEP_TIMEOUT):
        return None
    creator = d(resourceIdMatches=LINK_TITLE_ID)
    creator_name = creator.get_text() if creator.exists else None

    expand = tag.child(description=TAG_EXPAND_DESC)
    _tap(expand if expand.exists else tag)
    if not d(text=LINK_SHEET_TEXT).wait(timeout=STEP_TIMEOUT):
        return []  # 1 sản phẩm: có thể đã vào thẳng trang sản phẩm
    _pause()  # "đọc" danh sách sản phẩm
    titles = d(resourceIdMatches=LINK_TITLE_ID)  # UiObject không duyệt bằng for được
    names = [titles[i].get_text() for i in range(titles.count)]
    return [n for n in names if n and n != creator_name]


def add_current_product(d, dry):
    """Đang ở trang sản phẩm: mở bảng hoa hồng và bấm thêm. Trả về (trạng thái, ghi chú)."""
    up = d(description=UP_ARROW_DESC)
    if not up.wait(timeout=STEP_TIMEOUT):
        return "loi", "không thấy mũi tên 'Lên' (sản phẩm không có affiliate?)"
    _pause()  # "xem" trang sản phẩm
    _tap(up)

    btn = d(descriptionMatches=ADD_BUTTON_DESC)
    already = d(descriptionMatches=ALREADY_ADDED_DESC)
    deadline = time.time() + STEP_TIMEOUT
    while True:
        if already.exists:
            return "da_co", ""
        if btn.exists:
            break
        if time.time() > deadline:
            return "loi", "không thấy nút 'Thêm vào trang trưng bày'"
        time.sleep(0.5)
    if dry:
        return "thu", "đã thấy nút thêm (chạy thử, không bấm)"
    _pause()
    _tap(btn)
    # Bấm xong nút đổi thành "Khám phá sản phẩm dành cho bạn"
    if btn.wait_gone(timeout=STEP_TIMEOUT):
        return "thanh_cong", ""
    return "loi", "đã bấm nhưng nút không đổi, cần kiểm tra lại"


def process_link(d, pkg, url, dry):
    """Trả về list (tên sản phẩm, trạng thái, ghi chú)."""
    open_link(d, pkg, url)
    names = open_link_sheet(d)
    if names is None:
        return [("", "loi", "video không gắn sản phẩm / không mở được video")]
    if not names:  # vào thẳng trang sản phẩm
        return [("", *add_current_product(d, dry))]

    results = []
    for i, name in enumerate(names):
        if i > 0:  # mở lại video cho chắc thay vì bấm Back nhiều lần
            time.sleep(random.uniform(*DELAY_BETWEEN_PRODUCTS))
            open_link(d, pkg, url)
            open_link_sheet(d)
        item = d(resourceIdMatches=LINK_TITLE_ID, text=name)
        if not item.exists:
            results.append((name, "loi", "không thấy sản phẩm trong danh sách"))
            continue
        _tap(item)
        clean_name = name.replace("￼", "").strip()  # bỏ ký tự icon ￼ trong tên
        results.append((clean_name, *add_current_product(d, dry)))
    return results


# ---------- Log CSV (cùng định dạng ket_qua.csv của tool gốc) ----------


def get_default_csv_log_path() -> Path:
    from config import settings

    output_dir = Path(getattr(settings, "FINAL_OUTPUT_DIR", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / "showcase_log.csv"


def append_csv_log(log_path: Path, url: str, results: List[Dict[str, str]]) -> None:
    try:
        new_file = not log_path.exists()
        with log_path.open("a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if new_file:
                writer.writerow(["thoi_gian", "link", "san_pham", "trang_thai", "ghi_chu"])
            now = datetime.now().isoformat(timespec="seconds")
            for r in results:
                writer.writerow([now, url, r["product"], r["status"], r["note"]])
    except Exception as exc:
        logger.warning(f"Không ghi được showcase log CSV ({log_path}): {exc}")


# ---------- Worker nền ----------

ShowcaseListener = Callable[[int, Dict[str, Any]], None]


class ShowcaseWorker:
    """Hàng đợi thêm sản phẩm vào Showcase, chạy song song với job gen video.

    ``on_update(index, showcase_state)`` được gọi mỗi khi trạng thái của một
    item đổi; ``showcase_state`` có dạng::

        {"status": "queued|running|done|error|cancelled", "dry": bool,
         "message": str, "results": [{"product", "status", "note"}], "updated_at": str}
    """

    _STOP = object()

    def __init__(
        self,
        on_update: ShowcaseListener,
        *,
        dry: bool = False,
        mock: bool = False,
        cancel_event: Optional[threading.Event] = None,
        delay_between_links: Optional[Tuple[float, float]] = None,
        csv_log_path: Optional[Path] = None,
        serial: Optional[str] = None,
    ) -> None:
        self._on_update = on_update
        self._dry = dry
        self._mock = mock
        self._cancel = cancel_event or threading.Event()
        self._delay = delay_between_links or delay_range("SHOWCASE_DELAY_SECONDS", DELAY_BETWEEN_LINKS)
        self._csv_log_path = csv_log_path
        self._serial = serial
        self._queue: "queue.Queue[Any]" = queue.Queue()
        self._submitted: set = set()
        self._device: Optional[Tuple[Any, str]] = None
        self._last_link_at: Optional[float] = None
        self._thread = threading.Thread(target=self._run, name="tiktok-showcase", daemon=True)
        self._thread.start()

    def submit(self, index: int, url: str) -> bool:
        """Đưa link video nguồn vào hàng đợi. Bỏ qua nếu item đã được gửi."""
        if index in self._submitted or not url:
            return False
        self._submitted.add(index)
        self._emit(index, "queued", "Chờ thêm sản phẩm vào Showcase")
        self._queue.put((index, url))
        return True

    def finish(self, timeout: Optional[float] = None) -> None:
        """Chờ xử lý hết hàng đợi (dừng sớm nếu job bị hủy)."""
        self._queue.put(self._STOP)
        self._thread.join(timeout)

    # -------- Internals --------
    def _emit(self, index: int, status: str, message: str, results: Optional[List[Dict[str, str]]] = None) -> None:
        try:
            self._on_update(index, {
                "status": status,
                "dry": self._dry,
                "message": message,
                "results": results or [],
                "updated_at": _now_iso(),
            })
        except Exception:  # pragma: no cover - listener chỉ log
            logger.exception("showcase listener failed")

    def _wait_between_links(self) -> bool:
        """Nghỉ giữa 2 link; thời gian render video đã trôi qua được tính vào."""
        if self._last_link_at is None or self._mock:
            return not self._cancel.is_set()
        target = self._last_link_at + random.uniform(*self._delay)
        while time.time() < target:
            if self._cancel.wait(min(0.5, target - time.time())):
                return False
        return not self._cancel.is_set()

    def _process(self, url: str) -> List[Dict[str, str]]:
        if self._mock:
            return [{"product": "Mock product", "status": "thu", "note": "mock, không điều khiển điện thoại"}]
        if self._device is None:
            self._device = connect(self._serial)
        d, pkg = self._device
        return [
            {"product": name, "status": status, "note": note}
            for name, status, note in process_link(d, pkg, url, self._dry)
        ]

    def _run(self) -> None:
        while True:
            task = self._queue.get()
            if task is self._STOP:
                return
            index, url = task
            if not self._wait_between_links():
                self._emit(index, "cancelled", "Job đã hủy, bỏ qua thêm Showcase")
                continue
            self._emit(index, "running", "Đang thêm sản phẩm vào Showcase trên điện thoại")
            try:
                results = self._process(url)
            except ShowcaseError as exc:
                self._device = None  # thử kết nối lại ở link sau
                results = [{"product": "", "status": "loi", "note": str(exc)}]
            except Exception as exc:
                logger.exception(f"showcase failed for {url}")
                self._device = None
                results = [{"product": "", "status": "loi", "note": repr(exc)}]
            self._last_link_at = time.time()

            if self._csv_log_path and not self._mock:
                append_csv_log(self._csv_log_path, url, results)
            ok = all(r["status"] in OK_STATUSES for r in results)
            counts = ", ".join(
                f"{sum(1 for r in results if r['status'] == s)} {s}"
                for s in ("thanh_cong", "da_co", "thu", "loi")
                if any(r["status"] == s for r in results)
            )
            self._emit(index, "done" if ok else "error", counts, results)


__all__ = [
    "ShowcaseError",
    "ShowcaseWorker",
    "check_device",
    "connect",
    "get_default_csv_log_path",
    "process_link",
]
