"""env_persistence.py

Quản lý cập nhật file .env cục bộ một cách an toàn.

Mục tiêu:
  - Cập nhật từng khóa cấu hình mà không phá các khóa khác do người dùng nhập tay.
  - Chấp nhận cả tên theo schema cũ (LUCY_*) và schema UI mới (ITERA102_*),
    đồng thời giữ hai bên đồng bộ để pipeline cũ vẫn dùng được.
  - Cung cấp ``apply_updates()`` trả về dict thay đổi thực sự để log/audit.

Đường dẫn:
  - Mặc định ``<PROJECT_ROOT>/.env``. Có thể truyền đường dẫn khác qua env
    ``TIKTOK_ENV_FILE`` (hữu ích cho test).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Tuple

from config import PROJECT_ROOT

DEFAULT_ENV_PATH = Path(os.environ.get("TIKTOK_ENV_FILE", PROJECT_ROOT / ".env"))

# Bảng map giữa khóa UI (ITERA102_*) và khóa pipeline nội bộ (LUCY_*).
# UI sử dụng tên Itera102; pipeline đang dùng LucyAI. Ta mirror cả hai chiều
# để khi UI lưu xuống, phần CLI/GUI vẫn thấy cấu hình mới ngay lập tức.
LEGACY_TO_UI: dict[str, str] = {
    "LUCY_API_KEY": "ITERA102_API_KEY",
    "LUCY_VOICE_ID": "ITERA102_VOICE_ID",
    "LUCY_BASE_URL": "ITERA102_BASE_URL",
    "LUCY_MODEL": "ITERA102_MODEL_ID",
    "LUCY_LANGUAGE": "ITERA102_LANGUAGE_CODE",
}

UI_TO_LEGACY: dict[str, str] = {v: k for k, v in LEGACY_TO_UI.items()}

# Khóa UI được phép cập nhật từ giao diện cùng bộ ép kiểu.
def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_str(value: str) -> str:
    return value


def _as_float(value: str) -> str:
    return str(float(value))


def _as_path(value: str) -> str:
    return str(Path(value).expanduser())


_CASTER: dict[str, Callable[[str], str]] = {
    "bool": lambda v: "true" if _parse_bool(v) else "false",
    "float": _as_float,
    "path": _as_path,
    "str": _as_str,
}

EDITABLE_KEYS: dict[str, Tuple[str, Callable[[str], str]]] = {
    "ITERA102_VOICE_ID": ("str", _as_str),
    "ITERA102_SPEED": ("float", _as_float),
    "ITERA102_STABILITY": ("float", _as_float),
    "ITERA102_SIMILARITY_BOOST": ("float", _as_float),
    "ITERA102_STYLE": ("float", _as_float),
    "ITERA102_USE_SPEAKER_BOOST": ("bool", _CASTER["bool"]),
    "EDGE_TTS_VOICE": ("str", _as_str),
    "EDGE_TTS_SPEED": ("str", _as_str),
    "FINAL_OUTPUT_DIR": ("path", _as_path),
    "CUSTOM_LOGO_PATH": ("str", _as_str),
    "CUSTOM_CARD_BG_PATH": ("str", _as_str),
    "CUSTOM_NHAY_PATH": ("str", _as_str),
    "CUSTOM_BLACK_BG_PATH": ("str", _as_str),
    "CUSTOM_STYLE1_LOGO_PATH": ("str", _as_str),
    "CUSTOM_STYLE1_CARD_BG_PATH": ("str", _as_str),
    "CUSTOM_STYLE1_NHAY_PATH": ("str", _as_str),
    "CUSTOM_STYLE1_BLACK_BG_PATH": ("str", _as_str),
    "CUSTOM_STYLE2_LOGO_PATH": ("str", _as_str),
    "CUSTOM_STYLE2_CARD_BG_PATH": ("str", _as_str),
    "CUSTOM_STYLE2_NHAY_PATH": ("str", _as_str),
    "CUSTOM_STYLE2_BLACK_BG_PATH": ("str", _as_str),
    "CUSTOM_STYLE3_LOGO_PATH": ("str", _as_str),
    "CUSTOM_STYLE3_CARD_BG_PATH": ("str", _as_str),
    "CUSTOM_STYLE3_NHAY_PATH": ("str", _as_str),
    "CUSTOM_STYLE3_BLACK_BG_PATH": ("str", _as_str),
}


@dataclass
class EnvUpdate:
    key: str
    raw: str
    cast: str


def _strip_inline_comment(value: str) -> str:
    """Bỏ phần comment nối sau giá trị (tách bởi khoảng trắng + ``#``)."""
    if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
        return value[1:-1]
    return value.split("  #", 1)[0].strip()


def load_env(path: Path = DEFAULT_ENV_PATH) -> dict[str, str]:
    """Đọc file .env hiện tại thành dict (không thực thi)."""
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = _strip_inline_comment(value.strip())
    return data


def save_env(path: Path, data: Mapping[str, str]) -> None:
    """Ghi đè file .env an toàn qua file tạm và atomicity replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    lines: list[str] = []
    seen: set[str] = set()

    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                lines.append(raw_line)
                continue
            k, _ = stripped.split("=", 1)
            k = k.strip()
            if k in data:
                lines.append(f"{k}={data[k]}")
                seen.add(k)
            else:
                lines.append(raw_line)

    for k, v in data.items():
        if k not in seen:
            lines.append(f"{k}={v}")

    temp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _coerce(key: str, raw_value: object) -> str | None:
    spec = EDITABLE_KEYS.get(key)
    if not spec:
        return None
    _, caster = spec
    try:
        return caster(str(raw_value))
    except Exception:
        return None


def apply_updates(
    updates: Mapping[str, object], path: Path = DEFAULT_ENV_PATH
) -> dict[str, EnvUpdate]:
    """Áp dụng các thay đổi từ UI vào file .env và cập nhật `os.environ`."""
    applied: dict[str, EnvUpdate] = {}
    if not updates:
        return applied

    current = load_env(path)
    dirty = False

    for raw_key, raw_val in updates.items():
        if raw_val is None:
            continue
        canonical_key = raw_key.upper()
        # Chấp nhận cả schema UI lẫn legacy
        target_keys = {canonical_key}
        if canonical_key in UI_TO_LEGACY:
            target_keys.add(UI_TO_LEGACY[canonical_key])
        if canonical_key in LEGACY_TO_UI:
            target_keys.add(LEGACY_TO_UI[canonical_key])

        for key in target_keys:
            cast_val = _coerce(key, raw_val)
            if cast_val is None:
                continue
            if current.get(key) != cast_val:
                current[key] = cast_val
                dirty = True
            os.environ[key] = cast_val
            applied[key] = EnvUpdate(key=key, raw=str(raw_val), cast=cast_val)

    if dirty:
        save_env(path, current)

    return applied


def build_ui_settings(settings) -> dict[str, object]:
    """Chuyển ``config.settings`` sang schema UI đang sử dụng (ITERA102_*)."""
    return {
        "output_dir": str(settings.OUTPUT_DIR),
        "final_output_dir": str(settings.FINAL_OUTPUT_DIR),
        "itera102_voice_id": os.environ.get("ITERA102_VOICE_ID", settings.LUCY_VOICE_ID),
        "itera102_provider": os.environ.get("ITERA102_PROVIDER", "lucy"),
        "itera102_model_id": os.environ.get("ITERA102_MODEL_ID", "eleven_multilingual_v2"),
        "itera102_language_code": os.environ.get("ITERA102_LANGUAGE_CODE", "vi"),
        "itera102_speed": float(os.environ.get("ITERA102_SPEED", "1.0")),
        "itera102_stability": float(os.environ.get("ITERA102_STABILITY", "0.5")),
        "itera102_similarity_boost": float(
            os.environ.get("ITERA102_SIMILARITY_BOOST", "0.75")
        ),
        "itera102_style": float(os.environ.get("ITERA102_STYLE", "0.0")),
        "itera102_use_speaker_boost": _parse_bool(
            os.environ.get("ITERA102_USE_SPEAKER_BOOST", "true")
        ),
        "edge_tts_voice": settings.EDGE_TTS_VOICE,
        "edge_tts_speed": str(settings.EDGE_TTS_SPEED),
        "custom_logo_path": os.environ.get("CUSTOM_STYLE1_LOGO_PATH", os.environ.get("CUSTOM_LOGO_PATH", settings.CUSTOM_STYLE1_LOGO_PATH)),
        "custom_card_bg_path": os.environ.get("CUSTOM_STYLE1_CARD_BG_PATH", os.environ.get("CUSTOM_CARD_BG_PATH", settings.CUSTOM_STYLE1_CARD_BG_PATH)),
        "custom_nhay_path": os.environ.get("CUSTOM_STYLE1_NHAY_PATH", os.environ.get("CUSTOM_NHAY_PATH", settings.CUSTOM_STYLE1_NHAY_PATH)),
        "custom_black_bg_path": os.environ.get("CUSTOM_STYLE1_BLACK_BG_PATH", os.environ.get("CUSTOM_BLACK_BG_PATH", settings.CUSTOM_STYLE1_BLACK_BG_PATH)),
        "custom_style1_logo_path": os.environ.get("CUSTOM_STYLE1_LOGO_PATH", os.environ.get("CUSTOM_LOGO_PATH", settings.CUSTOM_STYLE1_LOGO_PATH)),
        "custom_style1_card_bg_path": os.environ.get("CUSTOM_STYLE1_CARD_BG_PATH", os.environ.get("CUSTOM_CARD_BG_PATH", settings.CUSTOM_STYLE1_CARD_BG_PATH)),
        "custom_style1_nhay_path": os.environ.get("CUSTOM_STYLE1_NHAY_PATH", os.environ.get("CUSTOM_NHAY_PATH", settings.CUSTOM_STYLE1_NHAY_PATH)),
        "custom_style1_black_bg_path": os.environ.get("CUSTOM_STYLE1_BLACK_BG_PATH", os.environ.get("CUSTOM_BLACK_BG_PATH", settings.CUSTOM_STYLE1_BLACK_BG_PATH)),
        "custom_style2_logo_path": os.environ.get("CUSTOM_STYLE2_LOGO_PATH", settings.CUSTOM_STYLE2_LOGO_PATH),
        "custom_style2_card_bg_path": os.environ.get("CUSTOM_STYLE2_CARD_BG_PATH", settings.CUSTOM_STYLE2_CARD_BG_PATH),
        "custom_style2_nhay_path": os.environ.get("CUSTOM_STYLE2_NHAY_PATH", settings.CUSTOM_STYLE2_NHAY_PATH),
        "custom_style2_black_bg_path": os.environ.get("CUSTOM_STYLE2_BLACK_BG_PATH", settings.CUSTOM_STYLE2_BLACK_BG_PATH),
        "custom_style3_logo_path": os.environ.get("CUSTOM_STYLE3_LOGO_PATH", settings.CUSTOM_STYLE3_LOGO_PATH),
        "custom_style3_card_bg_path": os.environ.get("CUSTOM_STYLE3_CARD_BG_PATH", settings.CUSTOM_STYLE3_CARD_BG_PATH),
        "custom_style3_nhay_path": os.environ.get("CUSTOM_STYLE3_NHAY_PATH", settings.CUSTOM_STYLE3_NHAY_PATH),
        "custom_style3_black_bg_path": os.environ.get("CUSTOM_STYLE3_BLACK_BG_PATH", settings.CUSTOM_STYLE3_BLACK_BG_PATH),
        "itera102_api_key_configured": bool(
            os.environ.get("ITERA102_API_KEY", settings.LUCY_API_KEY)
        ),
        "llm_api_key_configured": bool(settings.LLM_API_KEY),
    }


def iter_env_lines(path: Path = DEFAULT_ENV_PATH) -> Iterable[str]:
    """Tiện ích đọc lại file .env từng dòng (chủ yếu cho debug)."""
    if not path.exists():
        return []
    return list(path.read_text(encoding="utf-8").splitlines())


__all__ = [
    "DEFAULT_ENV_PATH",
    "EDITABLE_KEYS",
    "LEGACY_TO_UI",
    "UI_TO_LEGACY",
    "EnvUpdate",
    "apply_updates",
    "build_ui_settings",
    "iter_env_lines",
]
