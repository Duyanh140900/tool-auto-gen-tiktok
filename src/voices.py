"""
voices.py - Persist a list of TTS voices (LucyAI) and the active selection.

Storage: ~/tiktok-review-tool/voices.json — always writeable regardless of
where the bundled .app was launched from.

Schema:
  {
    "voices": [
      {"name": "Adam - US Male", "voice_id": "5r2MVjMfzwsSDzTpaLjbY9", "active": true},
      ...
    ]
  }

The active voice is mirrored into .env (LUCY_VOICE_ID=...) so the rest of
the pipeline keeps using settings.LUCY_VOICE_ID unchanged.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

from config import settings


VOICES_FILE: Path = Path.home() / "tiktok-review-tool" / "voices.json"


@dataclass
class Voice:
    name: str
    voice_id: str
    active: bool = False


class VoiceStore:
    """CRUD over a JSON list of voices. Single source of truth for the GUI."""

    def __init__(self, path: Path = VOICES_FILE):
        self.path = path
        self.voices: List[Voice] = []
        self._load()

    # ---------- Persistence ----------
    def _load(self):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.voices = [Voice(**v) for v in data.get("voices", [])]
            except Exception:
                self.voices = []

        # Backward compat: if file is empty / missing but .env has a voice,
        # seed the list with one default active voice.
        if not self.voices and settings.LUCY_VOICE_ID:
            self.voices = [
                Voice(name="Default", voice_id=settings.LUCY_VOICE_ID, active=True)
            ]
            self.save()
            return

        # Make sure exactly one voice is active (or none)
        actives = [v for v in self.voices if v.active]
        if len(actives) == 0 and self.voices:
            self.voices[0].active = True
            self.save()
        elif len(actives) > 1:
            for v in self.voices:
                v.active = False
            self.voices[0].active = True
            self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"voices": [asdict(v) for v in self.voices]}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---------- Helpers ----------
    @property
    def active(self) -> Optional[Voice]:
        for v in self.voices:
            if v.active:
                return v
        return None

    # ---------- Mutations ----------
    def add(self, name: str, voice_id: str) -> Voice:
        name = (name or "").strip()
        voice_id = (voice_id or "").strip()
        if not name or not voice_id:
            raise ValueError("Cần cả Tên voice và Voice ID.")
        # If this is the first voice, mark active.
        is_first = len(self.voices) == 0
        v = Voice(name=name, voice_id=voice_id, active=is_first)
        self.voices.append(v)
        self.save()
        return v

    def update(self, index: int, name: str, voice_id: str) -> Voice:
        if not (0 <= index < len(self.voices)):
            raise IndexError(f"Voice index {index} out of range")
        v = self.voices[index]
        v.name = (name or "").strip()
        v.voice_id = (voice_id or "").strip()
        if not v.name or not v.voice_id:
            raise ValueError("Cần cả Tên voice và Voice ID.")
        self.save()
        return v

    def remove(self, index: int) -> None:
        if not (0 <= index < len(self.voices)):
            raise IndexError(f"Voice index {index} out of range")
        was_active = self.voices[index].active
        del self.voices[index]
        if was_active and self.voices:
            self.voices[0].active = True
        self.save()

    def set_active(self, index: int) -> Voice:
        if not (0 <= index < len(self.voices)):
            raise IndexError(f"Voice index {index} out of range")
        for i, v in enumerate(self.voices):
            v.active = (i == index)
        self.save()
        return self.voices[index]


FREE_VOICES = [
    {"index": -1, "name": "Google TTS (Free)", "voice_id": "google-free", "active": False},
    {"index": -2, "name": "Edge TTS - Nữ Hoài My (Free)", "voice_id": "edge-vi-female", "active": False},
    {"index": -3, "name": "Edge TTS - Nam Nam Minh (Free)", "voice_id": "edge-vi-male", "active": False},
]


def list_voice_options(path: Path = VOICES_FILE) -> List[dict]:
    """Giọng free có sẵn + giọng đã lưu — danh sách cho UI web và bot Telegram."""
    store = VoiceStore(path)
    voices = [dict(v) for v in FREE_VOICES]
    for idx, v in enumerate(store.voices):
        voices.append({"index": idx, "name": v.name, "voice_id": v.voice_id, "active": v.active})
    return voices
