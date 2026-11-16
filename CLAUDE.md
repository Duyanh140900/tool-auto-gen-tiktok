# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout note

The project root is the inner `tiktok-review-tool/` directory (the outer one is just a wrapper). It is a git repo, but `.venv/`, `.tiktok_browser_profile/`, `outputs/`, logs and `frontend/node_modules` live inside it — exclude them when searching/globbing (they contain tens of thousands of files). The README is written in Vietnamese; many comments and UI strings are too.

## Commands

Windows is the primary dev platform (`scripts\dev_all.cmd`); `requirements.txt`/`.spec` carry macOS leftovers (`requirements-macos.txt`, Homebrew ffmpeg path in `TikTokReviewTool.spec`).

```cmd
scripts\dev_all.cmd install     # pip install -r requirements.txt + npm install in frontend/
scripts\dev_all.cmd             # backend (FastAPI :8000) + frontend (Next.js :3000); kills anything on those ports first
scripts\dev_all.cmd backend     # only backend   (also: frontend, stop)
```

Equivalent manual commands:

```bash
python -m uvicorn src.web.app:app --host 127.0.0.1 --port 8000   # backend
cd frontend && npm run dev                                       # frontend (proxies /api/* to :8000, override with NEXT_PUBLIC_API_TARGET)
cd frontend && npm run lint                                      # only frontend check; there is no frontend test suite
python main.py                                                   # legacy PyQt6 desktop GUI
python main.py --from-file inputs/urls.txt -c 2                  # CLI batch (also accepts inline URLs, --hints, --scripts)
python -m pytest tests                                           # all backend tests
python -m pytest tests/test_web_api.py::test_name -x             # single test
```

Requires `ffmpeg`/`ffprobe` on PATH (repo also ships `ffmpeg.exe` etc. in the root). Config comes from `.env` (copy `.env.example`); `config.py` falls back to `.env.example` if `.env` is missing and exposes a single `settings` object.

## Architecture

Pipeline: TikTok URL → download (no watermark) → LLM script + banner title → TTS voice-over → FFmpeg 9:16 render (video on top half, text card on bottom) → file named `<Caption>_<Hashtags>.mp4` → optionally Showcase add (Android) and scheduled post (TikTok Studio).

Three layers:

1. **Frontend** (`frontend/`, Next.js 15 App Router + Tailwind 4 + Radix). Each workflow is a route under `src/app/*` (`ai-video`, `auto-gen-video`, `montage`, `profile-ai-video`, `test-render`, `review`) that renders a screen from `src/components/workflow/`. `src/lib/api.ts` is the REST client; `src/hooks/use-job-events.ts` + `lib/job-events.ts` consume the job WebSocket for live progress.

2. **Web backend** (`src/web/`). `app.py` defines all `/api/*` routes (batch, auto-gen, montage, test-render, profile-ai-video, post-schedule/backlog, settings, defaults, folder pickers, `/api/job/ws`). `job_manager.py` holds `JobManager`, a single-active-job runner: it owns `JobSnapshot`/`BatchItem`, pause/resume/cancel, runs jobs on background threads, and publishes progress snapshots to subscribers (the WebSocket). Request models accept `mode_pipeline` of `"live"` or `"mock"`; mock paths (`_run_mock*`) simulate jobs without calling external APIs.

3. **Core pipeline** (`src/`, framework-agnostic, shared with the CLI/PyQt GUI):
   - `pipeline.py` — `process_one` / `process_batch` orchestrate per-item state (`ItemState`) through downloading → scripting → tts → merging, reporting via a progress callback.
   - `downloader.py` (yt-dlp with TikWM API fallback; optional `TIKTOK_COOKIES_FILE`), `profile_crawler.py` (crawl a creator profile for links), `script_generator.py` (LLM via OpenAI-compatible endpoint, e.g. local 9Router, or Anthropic; emotion tags for ElevenLabs v3), `tts_generator.py` + `voices.py` (Itera102/ElevenLabs with Edge TTS free fallback), `video_editor.py` / `layout_editor.py` (FFmpeg layout/banner rendering), `montage_pipeline.py` / `montage_editor.py` (multi-clip montage), `media_services.py` (thin async wrappers used by the web layer), `test_render_service.py` (5s silent layout preview).
   - Automation add-ons: `showcase.py` (Android phone via uiautomator2), `tiktok_poster.py` + `post_schedule.py` (Playwright driving TikTok Studio with persistent profile in `.tiktok_browser_profile/`; fixed slots 08/12/18/22h; ledger at `<FINAL_OUTPUT_DIR>/post_schedule.json`), `telegram_bot.py` (starts with the backend; sends link → runs AI Video using settings saved in `.ai_video_defaults.json`). Each message line is `link - chủ đề - Y-offset - scale - giờ - ngày` (all after the link optional; parsed by `parse_link_options`; bare numbers are positional — one number = Y-offset, two = Y-offset then scale, `_` skips one); they go into the item's `video_shift_ratio` / `video_scale`, and giờ/ngày become `BatchItem.post_at` → `PostTask.post_at`, which overrides the automatic 08/12/18/22h slot in `PostWorker` (those "custom_slot" posts are excluded from `PostSchedule.last_slot()`).
   - `env_persistence.py` writes settings changed in the UI back to `.env`; `ai_video_defaults.py` persists the /ai-video form defaults.
   - `capcut_*.py` / `gui.py` are the older desktop (CapCut/PyQt) path, not used by the web UI.

Tests in `tests/` are plain pytest, mostly mocking network/FFmpeg; `test_web_api*.py` use FastAPI `TestClient` (the Telegram bot deliberately skips startup under test). `scripts/` mostly holds one-off patch/fix scripts and logs, plus `build_zip.py` for packaging a distributable zip.

## Gotchas

- `.env`, `cookies.txt`, `.tiktok_browser_profile/` and `.ai_video_defaults.json` hold API keys / login sessions; they are in `.gitignore` and must never be committed, packaged or echoed.
- Ubuntu server deployment lives in `deploy/` (`install-ubuntu.sh`, `tiktok-login.sh`, `systemd/`); Chrome for TikTok Studio runs `headless=False` inside Xvfb `:99`, and the backend must run with `TZ` set to the posting timezone (slot times are naive local time).
- Frontend needs Node >= 20 (Node 18 fails to build).
