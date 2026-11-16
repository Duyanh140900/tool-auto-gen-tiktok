"""log_setup.py - Ghi log backend ra file trong thư mục ``logs/`` để dễ debug về sau.

- ``logs/backend.log``: toàn bộ log của tool (logger ``tiktok.*`` mức DEBUG, loguru của
  pipeline/script_generator, lỗi uvicorn và yt-dlp) kèm traceback đầy đủ.
- Xoay vòng mỗi nửa đêm, giữ 14 ngày (``backend.log.2026-11-05``...).
- Đổi thư mục bằng biến môi trường ``TIKTOK_LOG_DIR``; đổi số ngày giữ bằng ``TIKTOK_LOG_KEEP_DAYS``.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

from loguru import logger as loguru_logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

_file_handler: Optional[logging.Handler] = None
_loguru_sink_id: Optional[int] = None


def default_log_dir() -> Path:
    raw = os.environ.get("TIKTOK_LOG_DIR", "").strip()
    return Path(raw).expanduser() if raw else PROJECT_ROOT / "logs"


def _file_log_disabled() -> bool:
    if os.environ.get("TIKTOK_FILE_LOG", "1").strip().lower() in {"0", "false", "no", "off"}:
        return True
    argv0 = (sys.argv[0] if sys.argv else "").replace("\\", "/").lower()
    return "unittest" in argv0 or "pytest" in argv0


def setup_file_logging(log_dir: Optional[Path] = None) -> Path:
    """Gắn file handler (idempotent). Trả về đường dẫn file log."""
    global _file_handler, _loguru_sink_id

    target_dir = Path(log_dir) if log_dir else default_log_dir()
    log_file = target_dir / "backend.log"
    if log_dir is None and _file_log_disabled():
        # Chạy test (py -m unittest) hoặc TIKTOK_FILE_LOG=0: không ghi vào log thật
        return log_file
    if _file_handler is not None:
        return Path(getattr(_file_handler, "baseFilename", log_file))

    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        keep_days = max(1, int(os.environ.get("TIKTOK_LOG_KEEP_DAYS", "14")))
    except ValueError:
        keep_days = 14

    handler = TimedRotatingFileHandler(
        log_file, when="midnight", backupCount=keep_days, encoding="utf-8", delay=True
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))

    # Console giữ nguyên mức cũ (INFO); file nhận DEBUG của các logger tiktok.*
    root = logging.getLogger()
    for h in root.handlers:
        if h.level == logging.NOTSET:
            h.setLevel(root.level or logging.INFO)

    tiktok_logger = logging.getLogger("tiktok")
    tiktok_logger.setLevel(logging.DEBUG)
    tiktok_logger.addHandler(handler)
    # uvicorn.error: lỗi server/startup. Không gắn uvicorn.access để file đỡ rác.
    logging.getLogger("uvicorn.error").addHandler(handler)

    # loguru (pipeline, script_generator, tts...) ghi chung vào cùng handler
    def _loguru_to_file(message) -> None:
        record = message.record
        exc = record["exception"]
        log_record = logging.LogRecord(
            name=f"tiktok.{record['name']}",
            level=record["level"].no,
            pathname=record["file"].path,
            lineno=record["line"],
            msg=record["message"],
            args=None,
            exc_info=(exc.type, exc.value, exc.traceback) if exc else None,
        )
        log_record.created = record["time"].timestamp()
        handler.handle(log_record)

    _loguru_sink_id = loguru_logger.add(_loguru_to_file, level="DEBUG", backtrace=False, diagnose=False)
    _file_handler = handler
    logging.getLogger("tiktok.log_setup").info(f"File log: {log_file}")
    return log_file


def teardown_file_logging() -> None:
    """Gỡ handler (dùng cho test)."""
    global _file_handler, _loguru_sink_id
    if _file_handler is None:
        return
    logging.getLogger("tiktok").removeHandler(_file_handler)
    logging.getLogger("uvicorn.error").removeHandler(_file_handler)
    if _loguru_sink_id is not None:
        try:
            loguru_logger.remove(_loguru_sink_id)
        except ValueError:
            pass
    _file_handler.close()
    _file_handler = None
    _loguru_sink_id = None
