"""
capcut_editor.py - Edit CapCut draft JSON directly.

This module replaces audio, video, and text content in a CapCut project
(.capcut draft format) by editing the draft_info.json file. This is
much more reliable than UI automation (PyAutoGUI), but you must close
CapCut before editing — CapCut rewrites the file on close, which would
overwrite our changes.

The approach:
  1. Make a copy of the source project folder (don't touch the original).
  2. Update draft_info.json in the copy:
     - Replace audio material (track type=audio)
     - Replace video material on a configurable track index
     - Adjust video speed so duration matches audio duration
     - Update text segments (text content + timing split across N parts)
     - Move video into the upper-half frame area
  3. Update root_meta_info.json so CapCut picks up the new project.
  4. Open the new project in CapCut for the user to verify & export.

Schema reference: gist by renezander030 (capcut draft_content.json schema)
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from loguru import logger

from config import settings


# ---------------------------------------------------------------------------
# Discovery & utilities
# ---------------------------------------------------------------------------

DEFAULT_CAPCUT_ROOT = Path.home() / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"


def find_template_project(name: str = "project1") -> Path:
    """Find the source template project folder."""
    candidate = DEFAULT_CAPCUT_ROOT / name
    if candidate.exists():
        return candidate
    raise FileNotFoundError(
        f"Template project '{name}' not found at {candidate}. "
        f"Set CAPCUT_TEMPLATE_PROJECT in .env to the right path."
    )


def list_projects() -> list[Path]:
    """List all draft project folders."""
    if not DEFAULT_CAPCUT_ROOT.exists():
        return []
    return sorted(p for p in DEFAULT_CAPCUT_ROOT.iterdir() if p.is_dir())


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: dict):
    """Save with indentation + trailing newline so CapCut accepts it."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _new_id() -> str:
    """Generate a fresh UUID (uppercase, matching CapCut's style)."""
    return str(uuid.uuid4()).upper()


def _copy_project(src: Path, dst_name: Optional[str] = None) -> Path:
    """Copy a CapCut project folder to a new name (suffix _N)."""
    if dst_name is None:
        # auto-suffix to avoid overwriting
        base = src.name
        i = 1
        while (src.parent / f"{base}_copy{i}").exists():
            i += 1
        dst_name = f"{base}_copy{i}"
    dst = src.parent / dst_name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst


def _stage_video_in_project(
    new_project: Path,
    src_video: Path,
) -> Path:
    """
    Copy the new video into the CapCut project's local Videos/ folder and
    return the new absolute path. We do this because CapCut sometimes
    refuses to introspect videos that live outside the project tree (sets
    duration=0 and refuses to play them). With the file inside the project,
    CapCut treats it as a normal local media.
    """
    videos_dir = new_project / "Videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    dst = videos_dir / src_video.name
    shutil.copy2(src_video, dst)
    return dst


# ---------------------------------------------------------------------------
# Edit operations
# ---------------------------------------------------------------------------

@dataclass
class CapCutEditResult:
    project_path: Path
    draft_info_path: Path
    video_replaced: bool = False
    audio_replaced: bool = False
    text_updated: bool = False
    video_positioned: bool = False
    duration_adjusted: bool = False
    notes: list[str] = field(default_factory=list)


def replace_audio(
    draft: dict,
    audio_path: Path,
    duration_us: int,
) -> bool:
    """
    Replace the audio material on the first audio track.
    Updates: materials.audios[0].path + .name + .duration
    Updates: tracks[type=audio][0].segments[0].target_timerange.duration + source_timerange.duration
    """
    if "audios" not in draft.get("materials", {}) or not draft["materials"]["audios"]:
        logger.warning("No audio material in template — skipping audio replace")
        return False

    audio_mat = draft["materials"]["audios"][0]
    audio_mat["path"] = str(audio_path.resolve())
    audio_mat["name"] = audio_path.name
    audio_mat["duration"] = duration_us

    # Find audio track
    audio_track = next((t for t in draft.get("tracks", []) if t.get("type") == "audio"), None)
    if not audio_track or not audio_track.get("segments"):
        return False

    seg = audio_track["segments"][0]
    seg["target_timerange"] = {"start": 0, "duration": duration_us}
    seg["source_timerange"] = {"start": 0, "duration": duration_us}

    # Update draft total duration
    draft["duration"] = duration_us
    return True


def remove_audio_track(draft: dict) -> bool:
    """
    Remove the audio track entirely (and any audio materials referenced by it).
    Used when the merged video file already contains the ADAM1 voice — we don't
    want a second audio track playing at the same time.
    """
    before = len(draft.get("tracks", []))
    draft["tracks"] = [t for t in draft.get("tracks", []) if t.get("type") != "audio"]
    removed = before - len(draft["tracks"])
    if removed:
        logger.info(f"removed {removed} audio track(s)")
    return bool(removed)


def find_combo_group_segment_ids(draft: dict) -> set[str]:
    """
    Return the set of segment IDs that belong to the template's "combo group"
    (group_container.groups[*].group_members). These are the decoration/
    overlay/frame tracks that should be kept and stretched to match the new
    main video duration, rather than being replaced.

    Returns an empty set if no group is defined (in which case the caller can
    fall back to extending every segment).
    """
    gc = draft.get("group_container") or {}
    if not isinstance(gc, dict):
        return set()
    groups = gc.get("groups") or []
    ids: set[str] = set()
    for g in groups:
        for member in g.get("group_members", []) or []:
            ids.add(member)
    return ids


def extend_combo_group_segments(
    draft: dict,
    new_duration_us: int,
    segment_ids: set[str],
) -> tuple[int, list[str]]:
    """
    Stretch only the segments whose IDs are in `segment_ids` (typically the
    template's combo group decoration tracks) to fill `new_duration_us`.
    Returns (count_extended, list_of_track_indices_updated).

    For each segment:
      - target_timerange.duration = new_duration_us
      - target_timerange.start = 0  (snap to beginning)
      - speed = source_duration / target_duration  (so content still plays
        at its natural rate across the whole timeline)
    """
    if not segment_ids:
        return 0, []

    count = 0
    tracks_updated: list[int] = []
    for ti, track in enumerate(draft.get("tracks", [])):
        for seg in track.get("segments", []):
            if seg.get("id") not in segment_ids:
                continue
            seg["target_timerange"] = {"start": 0, "duration": new_duration_us}
            src = seg.get("source_timerange") or {}
            source_dur = src.get("duration") or new_duration_us
            if source_dur > 0 and new_duration_us > 0:
                seg["speed"] = round(source_dur / new_duration_us, 6)
            count += 1
            if ti not in tracks_updated:
                tracks_updated.append(ti)
    return count, tracks_updated


def _find_main_video_track_index(draft: dict) -> int:
    """
    Return the index of the main content video track. By convention the
    first video track (track index 0) holds the main content; the remaining
    tracks are decoration / overlay / frame members of combo group A.
    """
    for i, t in enumerate(draft.get("tracks", [])):
        if t.get("type") == "video":
            return i
    return 0


def replace_main_video(
    draft: dict,
    video_path: Path,
    video_duration_us: int,
    audio_duration_us: int,
    track_index: Optional[int] = None,
) -> Tuple[bool, int]:
    """
    Replace the main video material and adjust speed so it matches the audio duration.
    Returns (replaced, track_index_used).
    """
    if track_index is None:
        track_index = _find_main_video_track_index(draft)

    video_track = draft["tracks"][track_index]
    if video_track.get("type") != "video" or not video_track.get("segments"):
        return False, track_index

    seg = video_track["segments"][0]
    mat_id = seg.get("material_id")
    video_mat = next(
        (m for m in draft.get("materials", {}).get("videos", []) if m.get("id") == mat_id),
        None,
    )
    if video_mat is None:
        return False, track_index

    video_mat["path"] = str(video_path.resolve())
    video_mat["name"] = video_path.name
    video_mat["duration"] = video_duration_us

    # Adjust target duration to match audio duration
    seg["target_timerange"] = {"start": 0, "duration": audio_duration_us}
    # Source duration = full video duration (no trim)
    seg["source_timerange"] = {"start": 0, "duration": video_duration_us}

    # Speed = source_dur / target_dur — slows down or speeds up to fit audio
    if audio_duration_us > 0 and video_duration_us > 0:
        speed = video_duration_us / audio_duration_us
        seg["speed"] = round(speed, 6)

    return True, track_index


def position_video_upper_half(
    draft: dict,
    track_index: int,
    y_offset: float = -0.42,
    scale: float = 0.95,
) -> bool:
    """
    Move the video on the given track to the upper half of the canvas.
    Coordinates are normalized (-1 to +1). y_offset=-0.42 puts it in the upper
    half; scale=0.95 keeps it from filling more than its frame.

    The user said the frame occupies the upper half; we scale to fit and center
    horizontally. Adjust y_offset and scale per template if needed.
    """
    try:
        seg = draft["tracks"][track_index]["segments"][0]
    except (IndexError, KeyError):
        return False

    clip = seg.setdefault("clip", {})
    transform = clip.setdefault("transform", {"x": 0.0, "y": 0.0})
    transform["x"] = 0.0  # horizontal center
    transform["y"] = y_offset  # negative y = upward in CapCut convention

    scale_obj = clip.setdefault("scale", {"x": 1.0, "y": 1.0})
    scale_obj["x"] = scale
    scale_obj["y"] = scale

    return True


def _split_text_into_segments(text: str, num_segments: int) -> List[str]:
    """
    Split a script into N parts, balanced by sentence/word count.
    Tries to break on sentence boundaries first, then on commas.
    """
    text = text.strip()
    if num_segments <= 1 or not text:
        return [text]

    # Try to split on sentence-ending punctuation
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) >= num_segments:
        # Distribute sentences evenly into N groups
        groups: List[List[str]] = [[] for _ in range(num_segments)]
        for i, sent in enumerate(sentences):
            groups[i * num_segments // len(sentences)].append(sent)
        return [" ".join(g) for g in groups if g]

    # Fall back: split by commas evenly
    if "," in text:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if len(parts) >= num_segments:
            groups = [[] for _ in range(num_segments)]
            for i, p in enumerate(parts):
                groups[i * num_segments // len(parts)].append(p)
            return [", ".join(g) for g in groups if g]

    # Last resort: word-balanced split
    words = text.split()
    chunk_size = len(words) // num_segments
    result = []
    for i in range(num_segments):
        start = i * chunk_size
        end = (i + 1) * chunk_size if i < num_segments - 1 else len(words)
        result.append(" ".join(words[start:end]))
    return result


def update_text_segments(
    draft: dict,
    texts: List[str],
    audio_duration_us: int,
    custom_durations_us: Optional[List[int]] = None,
) -> bool:
    """
    Replace the content of each text segment on the text track, distributing
    timing across the audio duration.

    Args:
        custom_durations_us: If provided, use these exact durations for each
                             text segment (1:1 with the texts). Otherwise the
                             total duration is split across segments based on
                             char count (legacy behavior).
    """
    text_tracks = [t for t in draft.get("tracks", []) if t.get("type") == "text"]
    if not text_tracks:
        return False

    text_track = text_tracks[0]
    segments = text_track.get("segments", [])
    if not segments:
        return False

    # Pad/truncate texts to match segment count
    while len(texts) < len(segments):
        texts.append("")
    texts = texts[: len(segments)]

    # If caller supplied exact per-sentence durations, use them and ignore the
    # char-count fallback. The durations are laid back-to-back starting at 0.
    if custom_durations_us is not None:
        durs = list(custom_durations_us[: len(texts)])
        while len(durs) < len(texts):
            durs.append(1_000_000)
    else:
        # Char-balanced distribution across the total audio duration
        total_chars = sum(len(t) for t in texts) or 1
        durs = [int(audio_duration_us * (len(t) / total_chars)) for t in texts]
        # Ensure at least 1s per segment
        durs = [max(d, 1_000_000) for d in durs]
        # Cap so total doesn't exceed audio_duration_us
        if sum(durs) > audio_duration_us:
            scale = audio_duration_us / sum(durs)
            durs = [max(int(d * scale), 1_000_000) for d in durs]

    cursor = 0
    for seg, new_text, duration in zip(segments, texts, durs):
        seg["target_timerange"] = {"start": cursor, "duration": duration}
        cursor += duration

        # Update the text material
        mat_id = seg.get("material_id")
        text_mat = next(
            (m for m in draft.get("materials", {}).get("texts", []) if m.get("id") == mat_id),
            None,
        )
        if text_mat is None:
            continue
        # Preserve existing styling by reading the content JSON, swapping "text"
        try:
            content_str = text_mat.get("content", "{}")
            content = json.loads(content_str)
        except Exception:
            content = {}
        content["text"] = new_text
        content.setdefault(
            "styles",
            [{"range": [0, len(new_text)],
              "fill": {"content": {"solid": {"color": [1, 1, 1]}}}}],
        )
        content.setdefault("layer_weight", 1)
        content.setdefault("effect", [])
        text_mat["content"] = json.dumps(content, ensure_ascii=False)

    return True


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

def edit_template(
    template_project: Path,
    new_video_path: Path,
    new_audio_path: Optional[Path],
    video_duration_sec: float,
    audio_duration_sec: float,
    script_text: str,
    *,
    copy_to_name: Optional[str] = None,
    auto_split_text: bool = True,
    video_y_offset: float = -0.42,
    video_scale: float = 0.95,
    use_merged_video: bool = True,
    sentences: Optional[List[str]] = None,
    sentence_durations_us: Optional[List[int]] = None,
) -> CapCutEditResult:
    """
    Edit a copy of the CapCut template project with new media + text.

    Four sequential steps, each independent and minimal:
      1. Copy the project folder (template is left untouched).
      2. Replace the main video material path.
      3. Replace the 3 text segment contents with the (split) sentences.
      4. Stretch every segment in combo group A to match the new video length.

    No other fields (transform, scale, speed, source_timerange, audio tracks,
    extra_material_refs) are touched.
    """
    result = CapCutEditResult(
        project_path=Path(),
        draft_info_path=Path(),
    )

    # ---------- Step 1: copy template project ----------
    new_project = _copy_project(template_project, copy_to_name)
    result.project_path = new_project
    result.draft_info_path = new_project / "draft_info.json"
    result.notes.append(f"Step 1: copied project → {new_project.name}")

    # ---------- Step 1b: copy video into the project folder ----------
    # CapCut refuses to introspect videos outside the project tree
    # (sets duration=0, refuses to play). Keep the file local.
    staged_video = _stage_video_in_project(new_project, new_video_path)
    new_video_str = str(staged_video.resolve())
    result.notes.append(f"Step 1b: staged video at {staged_video.relative_to(new_project)}")

    # ---------- Step 2: load draft ----------
    draft = _load_json(result.draft_info_path)

    new_duration_us = int(video_duration_sec * 1_000_000)

    # ---------- Step 3: replace main video (Track 0, the first video track) ----------
    main_track_idx = _find_main_video_track_index(draft)
    if main_track_idx is None or main_track_idx >= len(draft["tracks"]):
        result.notes.append("WARNING: no video track found in template")
    else:
        main_seg = draft["tracks"][main_track_idx]["segments"][0]
        main_mat_id = main_seg.get("material_id")
        replaced = False
        for v in draft.get("materials", {}).get("videos", []):
            if v.get("id") == main_mat_id:
                v["path"] = new_video_str
                v["duration"] = new_duration_us
                replaced = True
                break
        # Also stretch the main video segment to the new duration so it
        # doesn't keep the template's old (longer) target_timerange.
        main_seg["target_timerange"] = {
            "start": 0,
            "duration": new_duration_us,
        }
        result.video_replaced = replaced
        if replaced:
            result.notes.append(
                f"Step 2: replaced main video (track #{main_track_idx}) → "
                f"{new_video_path.name}, duration={video_duration_sec:.1f}s, "
                f"target_timerange set to {video_duration_sec:.1f}s"
            )
        else:
            result.notes.append("WARNING: main video material not found in template")

    # ---------- Step 4: replace text segments (3 items) ----------
    text_track = next(
        (t for t in draft.get("tracks", []) if t.get("type") == "text"), None
    )
    if text_track and text_track.get("segments"):
        num_segments = len(text_track["segments"])
        if sentences is not None:
            texts = list(sentences)
        elif auto_split_text:
            texts = _split_text_into_segments(script_text, num_segments)
        else:
            texts = [script_text] + [""] * (num_segments - 1)
        while len(texts) < num_segments:
            texts.append("")
        texts = texts[:num_segments]

        updated_count = 0
        for seg, new_text in zip(text_track["segments"], texts):
            mat_id = seg.get("material_id")
            t_mat = next(
                (m for m in draft.get("materials", {}).get("texts", [])
                 if m.get("id") == mat_id),
                None,
            )
            if t_mat is None:
                continue
            try:
                content = json.loads(t_mat.get("content", "{}"))
            except Exception:
                content = {}
            content["text"] = new_text
            content.setdefault(
                "styles",
                [{"range": [0, len(new_text)],
                  "fill": {"content": {"solid": {"color": [1, 1, 1]}}}}],
            )
            content.setdefault("layer_weight", 1)
            content.setdefault("effect", [])
            t_mat["content"] = json.dumps(content, ensure_ascii=False)
            updated_count += 1
        result.text_updated = updated_count > 0
        if result.text_updated:
            preview = " | ".join(t[:30] + ("…" if len(t) > 30 else "") for t in texts)
            result.notes.append(f"Step 3: updated {updated_count} text segment(s): {preview}")
    else:
        result.notes.append("WARNING: no text track in template")

    # ---------- Step 5: extend combo group A to match new duration ----------
    combo_ids = find_combo_group_segment_ids(draft)
    if combo_ids:
        extended = 0
        tracks_idx: list[int] = []
        for ti, track in enumerate(draft.get("tracks", [])):
            for seg in track.get("segments", []):
                if seg.get("id") in combo_ids:
                    seg["target_timerange"] = {
                        "start": 0,
                        "duration": new_duration_us,
                    }
                    extended += 1
                    if ti not in tracks_idx:
                        tracks_idx.append(ti)
        result.duration_adjusted = True
        result.notes.append(
            f"Step 4: extended combo group A — {extended} segments on tracks "
            f"{tracks_idx} → {video_duration_sec:.1f}s"
        )
    else:
        result.notes.append("WARNING: no combo group A found in template")

    # ---------- Step 6: update total draft duration ----------
    draft["duration"] = new_duration_us

    # ---------- Step 7: save ----------
    _save_json(result.draft_info_path, draft)
    result.notes.append(f"Saved: {result.draft_info_path.name}")

    # Also save to the Timeline subfolder (CapCut reads from there too).
    timeline_files = list(new_project.glob("Timelines/*/draft_info.json"))
    for tf in timeline_files:
        tl_draft = _load_json(tf)
        # Mirror the same edits onto the timeline copy.
        for ti, track in enumerate(tl_draft.get("tracks", [])):
            for seg in track.get("segments", []):
                if seg.get("id") in combo_ids:
                    seg["target_timerange"] = {
                        "start": 0,
                        "duration": new_duration_us,
                    }
                if ti == main_track_idx and seg.get("material_id") == main_mat_id:
                    seg["target_timerange"] = {
                        "start": 0,
                        "duration": new_duration_us,
                    }
        # Replace main video path + duration
        for v in tl_draft.get("materials", {}).get("videos", []):
            if v.get("id") == main_mat_id:
                v["path"] = new_video_str
                v["duration"] = new_duration_us
                break
        # Update texts
        tl_text_track = next(
            (t for t in tl_draft.get("tracks", []) if t.get("type") == "text"), None
        )
        if tl_text_track and tl_text_track.get("segments"):
            for seg, new_text in zip(tl_text_track["segments"], texts):
                mat_id = seg.get("material_id")
                t_mat = next(
                    (m for m in tl_draft.get("materials", {}).get("texts", [])
                     if m.get("id") == mat_id),
                    None,
                )
                if t_mat is None:
                    continue
                try:
                    content = json.loads(t_mat.get("content", "{}"))
                except Exception:
                    content = {}
                content["text"] = new_text
                content.setdefault("layer_weight", 1)
                content.setdefault("effect", [])
                t_mat["content"] = json.dumps(content, ensure_ascii=False)
        tl_draft["duration"] = new_duration_us
        _save_json(tf, tl_draft)
    if timeline_files:
        result.notes.append(f"Mirrored edits to {len(timeline_files)} Timeline file(s)")

    # ---------- Step 8: register in CapCut library ----------
    root_meta = DEFAULT_CAPCUT_ROOT / "root_meta_info.json"
    if root_meta.exists():
        try:
            meta = _load_json(root_meta)
            store = meta.get("all_draft_store", [])
            new_id = str(uuid.uuid4())
            store.append({
                "cloud_draft_cover": False,
                "cloud_draft_sync": False,
                "draft_cloud_last_action_download": False,
                "draft_cloud_purchase_info": "",
                "draft_cloud_template_id": "",
                "draft_cloud_tutorial_info": "",
                "draft_cloud_videocut_purchase_info": "",
                "draft_cover": str(new_project / "draft_cover.jpg"),
                "draft_fold_path": str(new_project),
                "draft_id": new_id,
                "draft_is_ai_shorts": False,
                "draft_is_cloud_temp_draft": False,
                "draft_is_invisible": False,
                "draft_is_pippit_draft": False,
                "draft_is_web_article_video": False,
                "draft_json_file": str(result.draft_info_path),
                "draft_name": new_project.name,
                "draft_new_version": "",
                "draft_root_path": str(DEFAULT_CAPCUT_ROOT),
                "draft_timeline_materials_size": 0,
                "draft_type": "",
                "draft_web_article_video_enter_from": "",
                "pippit_avatar_url": "",
                "pippit_extra_info": "",
                "pippit_id": "",
                "pippit_user_name": "",
                "streaming_edit_draft_ready": True,
                "tm_draft_cloud_completed": "",
                "tm_draft_cloud_entry_id": -1,
                "tm_draft_cloud_modified": int(time.time() * 1_000_000),
                "tm_draft_cloud_parent_entry_id": -1,
                "tm_draft_cloud_space_id": -1,
                "tm_draft_cloud_user_id": -1,
                "tm_draft_create": int(time.time() * 1_000_000),
                "tm_draft_removed": 0,
                "tm_duration": new_duration_us,
            })
            meta["draft_ids"] = len(store)
            _save_json(root_meta, meta)
            result.notes.append(f"Registered '{new_project.name}' in CapCut library")
        except Exception as e:
            result.notes.append(f"WARNING: Failed to update root_meta_info.json: {e}")

    return result


# ---------------------------------------------------------------------------
# Open + Export
# ---------------------------------------------------------------------------

def open_project_in_capcut(project_path: Path) -> bool:
    """Open CapCut and navigate to the given project folder."""
    # Use AppleScript: tell CapCut to open the project
    script = f'''
    tell application "CapCut" to activate
    delay 1
    tell application "System Events"
        tell process "CapCut"
            try
                keystroke "o" using {{command down}}
                delay 0.5
                keystroke "{project_path}"
                delay 0.3
                key code 36
                delay 0.5
                return "opened"
            on error errMsg
                return "failed: " & errMsg
            end try
        end tell
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15,
        )
        logger.info(f"CapCut open result: {result.stdout.strip()}")
        return "opened" in result.stdout
    except Exception as e:
        logger.warning(f"open_project_in_capcut failed: {e}")
        return False


def quit_capcut() -> bool:
    """Force-quit CapCut. Used after editing the project JSON so CapCut
    reloads from disk on next launch (it caches the project in RAM)."""
    script = '''
    tell application "CapCut"
        quit
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except Exception as e:
        logger.warning(f"quit_capcut failed: {e}")
        return False


def reopen_project_fresh(project_path: Path) -> bool:
    """
    Quit CapCut entirely, relaunch it, and open the given project.

    Required because CapCut loads the draft JSON into memory on project
    open and never reloads from disk — so any external edit to the JSON
    (like ours) is invisible until the user restarts CapCut and reopens
    the project.
    """
    import time
    logger.info("Restarting CapCut to reload project JSON from disk...")
    quit_capcut()
    time.sleep(3)  # wait for CapCut to fully quit
    # Reopen CapCut
    try:
        subprocess.Popen(["open", "-a", "CapCut"])
    except Exception as e:
        logger.warning(f"Failed to relaunch CapCut: {e}")
        return False
    time.sleep(5)  # let CapCut boot
    return open_project_in_capcut(project_path)


def trigger_export(output_dir: Optional[Path] = None) -> bool:
    """
    Trigger CapCut's export dialog via Cmd+E.
    Note: the user must complete the export dialog (format, save path).
    """
    script = '''
    tell application "CapCut" to activate
    delay 0.5
    tell application "System Events"
        keystroke "e" using {command down}
    end tell
    '''
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
        return True
    except Exception as e:
        logger.warning(f"trigger_export failed: {e}")
        return False