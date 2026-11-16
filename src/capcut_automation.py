"""
capcut_automation.py - Open CapCut and stage files for manual fine-tuning.

CapCut doesn't expose a stable programmatic editing API on macOS, so this
module does the practical thing:

  1. Launch CapCut Desktop
  2. Reveal the final video in Finder so the user can drag-drop into CapCut
  3. (Optional) Try a best-effort AppleScript to import the file via the
     menu bar — this is fragile and gracefully degrades.

The end goal is: after the tool finishes, CapCut is open with the final
video right there, ready for the user to add captions / effects / trim.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger

from config import settings


@dataclass
class CapCutResult:
    capcut_opened: bool
    file_revealed: bool
    notes: list[str]


def _is_macos() -> bool:
    import platform
    return platform.system() == "Darwin"


def _run_osascript(script: str) -> tuple[bool, str]:
    """Run an AppleScript, return (success, output)."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip()
    except FileNotFoundError:
        return False, "osascript not found"
    except subprocess.TimeoutExpired:
        return False, "osascript timed out"


async def open_capcut() -> bool:
    """Launch CapCut Desktop. Returns True if a CapCut process is running."""
    if _is_macos():
        app_path = settings.CAPCUT_APP_PATH
        if not Path(app_path).exists():
            # Fallback to common CapCut paths
            for alt in ("/Applications/CapCut.app", "/Applications/CapCut/CapCut.app"):
                if Path(alt).exists():
                    app_path = alt
                    break
            else:
                logger.warning(f"CapCut.app not found at {settings.CAPCUT_APP_PATH}")
                # Still try via Spotlight
                ok, _ = _run_osascript('tell application "CapCut" to activate')
                return ok

        logger.info(f"Opening CapCut at {app_path}")
        proc = await asyncio.create_subprocess_exec(
            "open", "-a", app_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        # Give it a moment to launch
        await asyncio.sleep(2)

        # Confirm it actually launched
        ok, _ = _run_osascript('tell application "System Events" to (name of processes) contains "CapCut"')
        return ok
    else:
        # Windows / Linux fallback
        logger.warning("CapCut automation is macOS-only. On other platforms, "
                       "you'll need to open CapCut manually.")
        return False


async def reveal_in_finder(file_path: Path) -> bool:
    """Open Finder (or Explorer) at the given file."""
    file_path = Path(file_path)
    if not file_path.exists():
        logger.warning(f"reveal_in_finder: file not found: {file_path}")
        return False

    if _is_macos():
        proc = await asyncio.create_subprocess_exec(
            "open", "-R", str(file_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        return True
    else:
        # Windows
        subprocess.Popen(f'explorer /select,"{file_path}"')
        return True


async def try_import_into_capcut(video_path: Path) -> bool:
    """
    Best-effort: try to import the video into CapCut via AppleScript.
    This clicks through menus ("File > Import..."). Very fragile — if the
    CapCut version doesn't match, we silently fall back.
    """
    if not _is_macos():
        return False

    video_path = Path(video_path).resolve()
    if not video_path.exists():
        return False

    # Make sure CapCut is frontmost
    _run_osascript('tell application "CapCut" to activate')
    await asyncio.sleep(1)

    # AppleScript: tell CapCut to import the file via menu bar.
    # This relies on CapCut's menu structure being unchanged.
    script = f'''
    tell application "System Events"
        tell process "CapCut"
            try
                click menu item "Import..." of menu "File" of menu bar 1
                delay 0.5
                keystroke "G" using {{command down, shift down}}
                delay 0.3
                keystroke "{video_path}"
                delay 0.3
                key code 36
                delay 0.5
                return "imported"
            on error errMsg
                return "failed: " & errMsg
            end try
        end tell
    end tell
    '''
    ok, output = _run_osascript(script)
    logger.info(f"CapCut import attempt: {output}")
    return ok and "imported" in output


async def stage_for_capcut(video_path: Path) -> CapCutResult:
    """
    Open CapCut and stage the video for manual fine-tuning.

    Args:
        video_path: The final video file ready for editing

    Returns:
        CapCutResult with what worked
    """
    notes: list[str] = []
    capcut_opened = False
    file_revealed = False

    if settings.AUTO_OPEN_CAPCUT:
        capcut_opened = await open_capcut()
        if capcut_opened:
            notes.append("CapCut opened")
        else:
            notes.append("CapCut could not be opened automatically — please launch it manually")
    else:
        notes.append("AUTO_OPEN_CAPCUT is disabled")

    file_revealed = await reveal_in_finder(video_path)
    if file_revealed:
        notes.append(f"Finder opened at: {video_path}")

    return CapCutResult(
        capcut_opened=capcut_opened,
        file_revealed=file_revealed,
        notes=notes,
    )