"""
config.py - Load configuration from .env file and provide settings.
"""

from pathlib import Path
from dotenv import load_dotenv
import os

# Project root
PROJECT_ROOT = Path(__file__).parent.resolve()

# Load .env file from project root
env_path = PROJECT_ROOT / ".env"
if not env_path.exists():
    env_path = PROJECT_ROOT / ".env.example"
load_dotenv(env_path)


class Settings:
    """Centralized settings loaded from .env"""

    # ---------- Paths ----------
    PROJECT_ROOT: Path = PROJECT_ROOT
    INPUT_DIR: Path = PROJECT_ROOT / "inputs"
    OUTPUT_DIR: Path = PROJECT_ROOT / "outputs"
    ASSETS_DIR: Path = PROJECT_ROOT / "assets"

    # ---------- TTS: Itera102 / ElevenLabs ----------
    ITERA102_API_KEY: str = os.getenv("ITERA102_API_KEY", "")
    ITERA102_VOICE_ID: str = os.getenv("ITERA102_VOICE_ID", "")
    ITERA102_BASE_URL: str = os.getenv("ITERA102_BASE_URL", "https://api.itera102.space")
    ITERA102_PROVIDER: str = os.getenv("ITERA102_PROVIDER", "elevenlabs")
    ITERA102_MODEL_ID: str = os.getenv("ITERA102_MODEL_ID", "eleven_v3")
    ITERA102_LANGUAGE_CODE: str = os.getenv("ITERA102_LANGUAGE_CODE", "vi")
    ITERA102_SPEED: float = float(os.getenv("ITERA102_SPEED", "1.2"))
    ITERA102_STABILITY: float = float(os.getenv("ITERA102_STABILITY", "0.5"))
    ITERA102_SIMILARITY_BOOST: float = float(os.getenv("ITERA102_SIMILARITY_BOOST", "0.75"))

    # Legacy TTS aliases (for backward compatibility)
    LUCY_API_KEY: str = os.getenv("LUCY_API_KEY", ITERA102_API_KEY)
    LUCY_VOICE_ID: str = os.getenv("LUCY_VOICE_ID", ITERA102_VOICE_ID)
    LUCY_BASE_URL: str = os.getenv("LUCY_BASE_URL", ITERA102_BASE_URL)

    # ---------- TTS: Edge TTS (fallback) ----------
    EDGE_TTS_VOICE: str = os.getenv("EDGE_TTS_VOICE", "vi-VN-NamMinhNeural")
    EDGE_TTS_SPEED: float = float(os.getenv("EDGE_TTS_SPEED", "1.15"))

    # ---------- LLM (Anthropic / OpenAI / 9Router) ----------
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "Coder")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "http://localhost:20128/v1")

    # ---------- Video ----------
    VIDEO_QUALITY: str = os.getenv("VIDEO_QUALITY", "high")
    AUDIO_BITRATE: str = os.getenv("AUDIO_BITRATE", "192k")

    # ---------- Custom Overlay Assets (Style 1) ----------
    CUSTOM_STYLE1_LOGO_PATH: str = os.getenv("CUSTOM_STYLE1_LOGO_PATH", os.getenv("CUSTOM_LOGO_PATH", ""))
    CUSTOM_STYLE1_CARD_BG_PATH: str = os.getenv("CUSTOM_STYLE1_CARD_BG_PATH", os.getenv("CUSTOM_CARD_BG_PATH", ""))
    CUSTOM_STYLE1_NHAY_PATH: str = os.getenv("CUSTOM_STYLE1_NHAY_PATH", os.getenv("CUSTOM_NHAY_PATH", ""))
    CUSTOM_STYLE1_BLACK_BG_PATH: str = os.getenv("CUSTOM_STYLE1_BLACK_BG_PATH", os.getenv("CUSTOM_BLACK_BG_PATH", ""))

    # ---------- Custom Overlay Assets (Style 2) ----------
    CUSTOM_STYLE2_LOGO_PATH: str = os.getenv("CUSTOM_STYLE2_LOGO_PATH", "")
    CUSTOM_STYLE2_CARD_BG_PATH: str = os.getenv("CUSTOM_STYLE2_CARD_BG_PATH", "")
    CUSTOM_STYLE2_NHAY_PATH: str = os.getenv("CUSTOM_STYLE2_NHAY_PATH", "")
    CUSTOM_STYLE2_BLACK_BG_PATH: str = os.getenv("CUSTOM_STYLE2_BLACK_BG_PATH", "")

    # ---------- Custom Overlay Assets (Style 3) ----------
    CUSTOM_STYLE3_LOGO_PATH: str = os.getenv("CUSTOM_STYLE3_LOGO_PATH", "")
    CUSTOM_STYLE3_CARD_BG_PATH: str = os.getenv("CUSTOM_STYLE3_CARD_BG_PATH", "")
    CUSTOM_STYLE3_NHAY_PATH: str = os.getenv("CUSTOM_STYLE3_NHAY_PATH", "")
    CUSTOM_STYLE3_BLACK_BG_PATH: str = os.getenv("CUSTOM_STYLE3_BLACK_BG_PATH", "")

    # Legacy fallback aliases
    CUSTOM_LOGO_PATH: str = os.getenv("CUSTOM_LOGO_PATH", "")
    CUSTOM_CARD_BG_PATH: str = os.getenv("CUSTOM_CARD_BG_PATH", "")
    CUSTOM_NHAY_PATH: str = os.getenv("CUSTOM_NHAY_PATH", "")
    CUSTOM_BLACK_BG_PATH: str = os.getenv("CUSTOM_BLACK_BG_PATH", "")

    # Output folders default to ~/tiktok-review-tool/ (user home, always writeable).
    _default_base = Path.home() / "tiktok-review-tool"
    OUTPUT_DIR: Path = Path(
        os.getenv("OUTPUT_DIR", str(_default_base / "outputs"))
    ).expanduser()
    FINAL_OUTPUT_DIR: Path = Path(
        os.getenv("FINAL_OUTPUT_DIR", str(_default_base / "final_videos"))
    ).expanduser()

    # ---------- TikTok Downloader & Cookies ----------
    TIKTOK_COOKIES_FILE: str = os.getenv("TIKTOK_COOKIES_FILE", "")

    # ---------- Pipeline ----------
    MAX_CONCURRENT: int = int(os.getenv("MAX_CONCURRENT", "1"))

    # ---------- CapCut (macOS) ----------
    CAPCUT_APP_PATH: str = os.getenv("CAPCUT_APP_PATH", "/Applications/CapCut.app")
    AUTO_OPEN_CAPCUT: bool = os.getenv("AUTO_OPEN_CAPCUT", "true").lower() == "true"
    CAPCUT_TEMPLATE_NAME: str = os.getenv("CAPCUT_TEMPLATE_NAME", "project1")
    CAPCUT_AUTO_EXPORT: bool = os.getenv("CAPCUT_AUTO_EXPORT", "false").lower() == "true"
    CAPCUT_AUTO_RELAUNCH: bool = os.getenv("CAPCUT_AUTO_RELAUNCH", "true").lower() == "true"
    CAPCUT_VIDEO_Y_OFFSET: float = float(os.getenv("CAPCUT_VIDEO_Y_OFFSET", "-0.42"))
    CAPCUT_VIDEO_SCALE: float = float(os.getenv("CAPCUT_VIDEO_SCALE", "0.95"))

    @classmethod
    def ensure_dirs(cls):
        cls.INPUT_DIR.mkdir(parents=True, exist_ok=True)
        cls.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        cls.FINAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        cls.ASSETS_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
