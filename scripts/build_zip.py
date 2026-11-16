"""Package the restored repository into a single, safe-to-distribute zip.

The script always rebuilds from ``ROOT`` and writes ``DEST``. It excludes:

  * secrets: ``.env``, ``frontend/.env``, anything matching ``*.env``
    (except ``.env.example``/``frontend/.env.example``)
  * generated dependencies: ``.venv``, ``frontend/node_modules``, ``frontend/.next``
  * heavy binaries that previously broke GitHub's 100 MB limit
  * Python/Next caches, logs, OS junk (``Thumbs.db``, ``.DS_Store``)

Only sources needed to bootstrap ``scripts\\dev_all.cmd install`` + ``dev_all.cmd``
are packaged.
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT.parent / "tiktok-review-tool-restore.zip"

EXCLUDE_DIRS = {
    ".git",
    ".tiktok_browser_profile",  # phiên đăng nhập TikTok Studio
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".next",
    ".turbo",
    ".cache",
    ".vercel",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "out",
    "tmp",
    "temp",
    "logs",
    "outputs",
    "final_videos",
    "downloads",
    "dist",
    "build",
    "recovery",
    "frontend/node_modules",
    "frontend/.next",
    "frontend/.turbo",
    "frontend/.cache",
    "frontend/.vercel",
    "frontend/dist",
    "frontend/out",
    "frontend/.next-dev",
    "scripts/__pycache__",
}

EXCLUDE_FILES = {
    # Heavy binaries
    "ffmpeg.exe",
    "ffplay.exe",
    "ffprobe.exe",
    "ffmpeg",
    "ffplay",
    "ffprobe",
    # Phiên đăng nhập / setting cục bộ
    "cookies.txt",
    ".ai_video_defaults.json",
    # OS junk
    ".DS_Store",
    "Thumbs.db",
    # Lockfiles that drag in absolute paths (optional, will regenerate)
    "frontend/.next-lock.yaml",
}

EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".log", ".tsbuildinfo")

# Allow-list cho file .env: chỉ giữ example, mọi file env khác đều bị loại.
ENV_FILE_PATTERN = ".env"


def is_env_file(path: Path) -> bool:
    if path.name == ".env":
        return True
    if path.name.startswith(".env.") and path.name not in {".env.example"}:
        return True
    if path.parent.name == "frontend" and path.name == ".env":
        return True
    if path.parent.name == "frontend" and path.name.startswith(".env.") and path.name not in {
        "frontend/.env.example"
    }:
        return True
    return False


def is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    for ex in EXCLUDE_DIRS:
        if ex in parts:
            return True
    if path.name in EXCLUDE_FILES:
        return True
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    if is_env_file(path):
        return True
    return False


def should_include(path: Path) -> bool:
    if not path.is_file():
        return False
    if is_excluded(path):
        return False
    return True


def main() -> None:
    if DEST.exists():
        DEST.unlink()
    included: list[Path] = []
    skipped: list[tuple[Path, str]] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.name == ".env":
            skipped.append((path, "env"))
            continue
        if path.name.startswith(".env.") and path.name != ".env.example":
            skipped.append((path, "env"))
            continue
        if path.parent.name == "frontend" and path.name == ".env":
            skipped.append((path, "env"))
            continue
        if (
            path.parent.name == "frontend"
            and path.name.startswith(".env.")
            and path.name != ".env.example"
        ):
            skipped.append((path, "env"))
            continue
        if is_excluded(path):
            skipped.append((path, "rule"))
            continue
        included.append(path)

    with zipfile.ZipFile(DEST, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in included:
            arcname = path.relative_to(ROOT.parent)
            zf.write(path, arcname)

    env_files = [p for p, reason in skipped if reason == "env"]
    other_skipped = [p for p, reason in skipped if reason != "env"]
    print(f"Wrote {len(included)} files to {DEST}")
    print(f"ZIP size: {DEST.stat().st_size} bytes")
    if env_files:
        print(f"Excluded {len(env_files)} env files:")
        for p in env_files:
            print(f"  - {p.relative_to(ROOT)}")
    if other_skipped:
        print(f"Excluded {len(other_skipped)} other files (rules/caches/binaries).")

    # Phụ trợ: audit nhanh để chắc chắn không mang secret.
    secrets_found: list[str] = []
    with zipfile.ZipFile(DEST, "r") as zf:
        for info in zf.infolist():
            name = Path(info.filename).name
            if name == ".env" or name.startswith(".env."):
                if name != ".env.example":
                    secrets_found.append(info.filename)
    if secrets_found:
        raise SystemExit(
            f"REFUSE: zip vẫn chứa file env: {secrets_found}"
        )


if __name__ == "__main__":
    main()
