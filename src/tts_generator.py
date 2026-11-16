"""
tts_generator.py - Tổng hợp giọng nói từ text bằng https://api.itera102.space.

Provider duy nhất: itera102. Không có fallback. Khi thiếu cấu hình hoặc API
trả lỗi, hàm ``raise`` để pipeline nổi lỗi lên UI (không tự ý đổi giọng).

Schema API (từ ``endpoints/tts/*.yaml``):

    POST https://api.itera102.space/v1/text-to-speech/{voice_id}
        Headers:
            xi-api-key: <API_KEY>
            Content-Type: application/json
        Body:
            {
                "text": "...",
                "model_id": "eleven_multilingual_v2" | "speech-2.8-turbo" | ...,
                "provider": "elevenlabs" | "minimax" | "capcut",
                "language_code": "en" | "vi" | "English" | ...,
                "voice_settings": {
                    "stability": 0..1,
                    "similarity_boost": 0..1,
                    "style": 0..1,
                    "use_speaker_boost": true,
                    "speed": 0.7..1.2 (ElevenLabs) hoặc 0.5..2.0 (khác)
                },
                "export_transcript": false
            }
        Response 202:
            {"id": "...", "status": "pending"}

    GET https://api.itera102.space/v1/history/{id}
        Headers:
            xi-api-key: <API_KEY>
        Response 200:
            {"id": "...", "status": "pending|processing|completed|failed",
             "result": {"audio_url": "https://..."},
             "error": "..." | null,
             ...}

Audio tải về từ ``result.audio_url``.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiohttp
from dotenv import dotenv_values
from loguru import logger


# ---------------------------------------------------------------------------
# Exception định nghĩa lỗi hết credit / quota
# ---------------------------------------------------------------------------


class TTSCreditExhaustedError(RuntimeError):
    """Raise khi API tổng hợp giọng nói (Itera102, ElevenLabs, MiniMax...) báo hết credit, hết tiền hoặc vượt quota."""
    pass


def is_credit_exhausted_error(status_code: int = 0, error_body_or_msg: str = "") -> bool:
    """Kiểm tra phản hồi hoặc thông điệp lỗi có phải là lỗi hết credit / quota hay không."""
    if status_code in (402, 429):
        return True
    lower = str(error_body_or_msg or "").lower()
    keywords = [
        "credit",
        "credits",
        "quota",
        "balance",
        "insufficient",
        "payment required",
        "out of credit",
        "out of quota",
        "exceeded your current quota",
        "không đủ credit",
        "hết credit",
        "hết tiền",
        "hết lượt",
        "nạp thêm",
        "unpaid",
        "subscription",
    ]
    return any(kw in lower for kw in keywords)


# ---------------------------------------------------------------------------
# Cấu hình itera102
# ---------------------------------------------------------------------------


@dataclass
class Itera102Settings:
    base_url: str  # ví dụ https://api.itera102.space
    api_key: str
    voice_id: str
    model_id: str
    language_code: str
    provider: str
    speed: float
    stability: float
    similarity_boost: float
    style: float
    use_speaker_boost: bool
    export_transcript: bool
    request_timeout_sec: float
    poll_interval_sec: float
    poll_max_attempts: int
    download_timeout_sec: float
    stuck_resubmit_polls: int = 40  # task kẹt "processing" quá N lần poll thì submit task mới

    @classmethod
    def from_env(cls) -> "Itera102Settings":
        dotenv_config = _load_dotenv_values()
        base_url = (
            _env_or_dotenv("ITERA102_BASE_URL", dotenv_config)
            or _env_or_dotenv("LUCY_BASE_URL", dotenv_config)
            or "https://api.itera102.space"
        ).rstrip("/")
        api_key = (
            _env_or_dotenv("ITERA102_API_KEY", dotenv_config)
            or _env_or_dotenv("LUCY_API_KEY", dotenv_config)
            or ""
        ).strip()
        voice_id = (
            _voice_env_or_dotenv("ITERA102_VOICE_ID", dotenv_config)
            or _voice_env_or_dotenv("LUCY_VOICE_ID", dotenv_config)
            or ""
        ).strip()
        if is_placeholder_voice_id(voice_id):
            raise RuntimeError(
                "ITERA102_VOICE_ID chưa hợp lệ hoặc đang là placeholder/test voice. "
                "Hãy chọn voice thật trong Voice Manager hoặc dán voice id thật vào .env."
            )
        return cls(
            base_url=base_url,
            api_key=api_key,
            voice_id=voice_id,
            model_id=_env_or_dotenv("ITERA102_MODEL_ID", dotenv_config) or "eleven_multilingual_v2",
            language_code=_env_or_dotenv("ITERA102_LANGUAGE_CODE", dotenv_config) or "vi",
            provider=_env_or_dotenv("ITERA102_PROVIDER", dotenv_config) or "elevenlabs",
            speed=_env_float("ITERA102_SPEED", 1.15),
            stability=_env_float("ITERA102_STABILITY", 0.5),
            similarity_boost=_env_float("ITERA102_SIMILARITY_BOOST", 0.75),
            style=_env_float("ITERA102_STYLE", 0.0),
            use_speaker_boost=_env_bool("ITERA102_USE_SPEAKER_BOOST", True),
            export_transcript=_env_bool("ITERA102_EXPORT_TRANSCRIPT", False),
            request_timeout_sec=_env_float("ITERA102_REQUEST_TIMEOUT_SEC", 30),
            poll_interval_sec=_env_float("ITERA102_POLL_INTERVAL_SEC", 2.5),
            poll_max_attempts=int(_env_float("ITERA102_POLL_MAX_ATTEMPTS", 90)),
            download_timeout_sec=_env_float("ITERA102_DOWNLOAD_TIMEOUT_SEC", 120),
            stuck_resubmit_polls=int(_env_float("ITERA102_STUCK_RESUBMIT_POLLS", 40)),
        )


def _load_dotenv_values() -> dict[str, str]:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return {}
    return {key: value for key, value in dotenv_values(env_path).items() if value is not None}


def _env_or_dotenv(name: str, dotenv_config: dict[str, str]) -> str:
    return (os.getenv(name) or dotenv_config.get(name) or "").strip()


def _voice_env_or_dotenv(name: str, dotenv_config: dict[str, str]) -> str:
    env_value = (os.getenv(name) or "").strip()
    dotenv_value = (dotenv_config.get(name) or "").strip()
    if env_value and not is_placeholder_voice_id(env_value):
        return env_value
    if dotenv_value and not is_placeholder_voice_id(dotenv_value):
        if env_value and env_value != dotenv_value:
            logger.warning(
                "[tts_itera102] runtime {}={!r} is placeholder; using .env value {!r}",
                name,
                env_value,
                dotenv_value,
            )
        return dotenv_value
    return env_value or dotenv_value


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_placeholder_voice_id(voice_id: str) -> bool:
    """Detect voice ids used by docs/tests that should never hit provider API."""
    normalized = (voice_id or "").strip().lower()
    if not normalized:
        return True
    if is_free_voice_id(normalized):
        return False
    if normalized.startswith("paste_"):
        return True
    return normalized in {
        "test",
        "test-voice",
        "your_voice_id",
        "your_voice_id_here",
        "voice_id_cua_ban",
        "voice_id_của_bạn",
        "placeholder",
    }


def is_free_voice_id(voice_id: str) -> bool:
    """Kiểm tra voice_id có phải là giọng đọc miễn phí (Google TTS hoặc Edge TTS) hay không."""
    normalized = (voice_id or "").strip().lower()
    return normalized in {
        "google-free",
        "google-tts",
        "google-vi",
        "google-vi-standard",
        "gtts",
        "free",
        "free-google",
        "edge-free",
        "edge-vi-female",
        "edge-vi-male",
        "vi-vn-hoaimyneural",
        "vi-vn-namminhneural",
    } or normalized.startswith("free-") or normalized.startswith("edge-")


def _client_timeout(total: float) -> aiohttp.ClientTimeout:
    return aiohttp.ClientTimeout(total=total)


@dataclass
class TTSResult:
    provider: str  # "itera102"
    voice_id: str
    text: str
    audio_path: Path
    duration_sec: Optional[float] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Provider: itera102
# ---------------------------------------------------------------------------


async def tts_itera102(
    text: str,
    output_path: Path,
    *,
    speed: Optional[float] = None,
) -> TTSResult:
    """Gửi text tới ``POST /v1/text-to-speech/{voice_id}`` của itera102, đợi job
    hoàn tất qua ``GET /v1/history/{id}``, tải audio về ``output_path``.

    Không có fallback: thiếu config / API lỗi / voice chưa sẵn sàng đều raise.
    """
    cfg = Itera102Settings.from_env()
    if not cfg.api_key:
        raise RuntimeError(
            "Chưa cấu hình ITERA102_API_KEY trong .env. Không thể gọi "
            "https://api.itera102.space để tổng hợp giọng."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    submitted_text = text
    raw_speed = float(speed) if speed is not None else cfg.speed
    # itera102 giới hạn speed theo provider:
    # ElevenLabs: 0.7..1.2; MiniMax/CapCut: 0.5..2.0.
    if cfg.provider == "elevenlabs":
        effective_speed = max(0.7, min(1.2, raw_speed))
    else:
        effective_speed = max(0.5, min(2.0, raw_speed))
    if effective_speed != raw_speed:
        logger.warning(
            f"[tts_itera102] speed {raw_speed} -> {effective_speed} cho provider={cfg.provider}"
        )
    headers = {
        "xi-api-key": cfg.api_key,
        "Content-Type": "application/json",
    }
    tts_url = f"{cfg.base_url}/v1/text-to-speech/{cfg.voice_id}"
    history_url_tpl = f"{cfg.base_url}/v1/history/{{id}}"
    req_timeout = _client_timeout(cfg.request_timeout_sec)
    dl_timeout = _client_timeout(cfg.download_timeout_sec)

    submit_payload = {
        "text": submitted_text,
        "model_id": cfg.model_id,
        "provider": cfg.provider,
        "language_code": cfg.language_code,
        "voice_settings": {
            "stability": cfg.stability,
            "similarity_boost": cfg.similarity_boost,
            "style": cfg.style,
            "use_speaker_boost": cfg.use_speaker_boost,
            "speed": effective_speed,
        },
        "export_transcript": cfg.export_transcript,
    }

    emotion_tags = [
        token
        for token in (
            "[annoyed]",
            "[chuckles]",
            "[excited]",
            "[laughs]",
            "[whispers]",
            "[sighs]",
        )
        if token in submitted_text.lower()
    ]
    text_preview = submitted_text.replace("\r", " ").replace("\n", " ")[:160]
    logger.info(
        "[tts_itera102] submit config provider={} model={} language={} "
        "requested_speed={} effective_speed={} stability={} style={} "
        "text_chars={} emotion_tags={} text_preview={!r}",
        cfg.provider,
        cfg.model_id,
        cfg.language_code,
        raw_speed,
        effective_speed,
        cfg.stability,
        cfg.style,
        len(submitted_text),
        emotion_tags,
        text_preview,
    )

    async with aiohttp.ClientSession() as session:
        async def submit_task(attempt_no: int) -> str:
            """Submit một generation task và trả về task id."""
            async with session.post(
                tts_url, headers=headers, json=submit_payload, timeout=req_timeout
            ) as resp:
                body = await resp.text()
                if resp.status not in (200, 202):
                    if is_credit_exhausted_error(resp.status, body):
                        raise TTSCreditExhaustedError(
                            f"itera102 hết credit / quota (HTTP {resp.status}): {body[:400]}"
                        )
                    raise RuntimeError(
                        f"itera102 submit thất bại attempt={attempt_no} "
                        f"(HTTP {resp.status}): {body[:400]}"
                    )
                try:
                    submit_data = await resp.json() if body else {}
                except Exception:
                    submit_data = {}
            next_task_id = (submit_data or {}).get("id")
            if not next_task_id:
                raise RuntimeError(
                    f"itera102: response không có 'id' ở attempt={attempt_no}. "
                    f"Body: {body[:400]}"
                )
            logger.info(
                "[tts_itera102] submitted generation attempt={} task_id={} text_chars={}",
                attempt_no,
                next_task_id,
                len(submitted_text),
            )
            return str(next_task_id)

        # 1. Submit. Một số lỗi "Generation failed, please try again." là lỗi
        # transient từ provider; cho phép submit lại tối đa 3 lần với backoff.
        # Task kẹt "processing" quá ``stuck_resubmit_polls`` lần poll cũng được submit lại
        # (vẫn tiếp tục poll task cũ, task nào xong trước thì dùng task đó).
        max_generation_attempts = 3
        generation_attempt = 1
        task_id = await submit_task(generation_attempt)
        active_tasks: list[str] = [task_id]
        polls_on_latest = 0

        async def poll_task(tid: str, poll_no: int) -> Optional[dict]:
            try:
                async with session.get(
                    history_url_tpl.format(id=tid),
                    headers=headers,
                    timeout=req_timeout,
                ) as resp:
                    if resp.status != 200:
                        logger.debug(f"[tts_itera102] poll {poll_no} task_id={tid}: HTTP {resp.status}")
                        return None
                    return await resp.json()
            except Exception as exc:
                logger.debug(f"[tts_itera102] poll {poll_no} task_id={tid} lỗi: {exc!r}")
                return None

        # 2. Poll (kèm retry khi gặp "Generation failed" thoáng qua của ElevenLabs).
        audio_url: Optional[str] = None
        last_error: Optional[str] = None
        for attempt in range(cfg.poll_max_attempts):
            await asyncio.sleep(cfg.poll_interval_sec)
            polls_on_latest += 1
            resubmit_reason: Optional[str] = None
            for tid in list(reversed(active_tasks)):  # task mới nhất trước
                data = await poll_task(tid, attempt + 1)
                if data is None:
                    continue
                state = data.get("status")
                err_msg = data.get("error")
                logger.debug(
                    "[tts_itera102] poll={} task_id={} generation_attempt={} state={} error={!r}",
                    attempt + 1,
                    tid,
                    generation_attempt,
                    state,
                    err_msg,
                )
                if state == "completed":
                    audio_url = (data.get("result") or {}).get("audio_url")
                    task_id = tid
                    logger.info(
                        "[tts_itera102] completed task_id={} generation_attempt={} poll={}",
                        tid,
                        generation_attempt,
                        attempt + 1,
                    )
                    break
                if state == "failed":
                    last_error = str(err_msg) if err_msg else None
                    if is_credit_exhausted_error(0, str(err_msg)):
                        raise TTSCreditExhaustedError(
                            f"itera102 synthesis failed do hết credit / quota: task_id={tid} error={err_msg}"
                        )
                    active_tasks.remove(tid)
                    if active_tasks:
                        # Còn task khác đang chạy: bỏ task lỗi, chờ task còn lại.
                        logger.warning(f"[tts_itera102] task_id={tid} failed ({err_msg!r}), vẫn chờ task khác")
                        continue
                    # ElevenLabs hay trả "Generation failed, please try again"
                    # khi server quá tải; coi đây là transient và retry bằng cách
                    # submit lại task mới (giữ nguyên voice_id, model, speed).
                    is_generation_failed = bool(
                        err_msg and "generation failed" in str(err_msg).lower()
                    )
                    if is_generation_failed and generation_attempt < max_generation_attempts:
                        resubmit_reason = f"transient generation failure error={err_msg!r}"
                        break
                    if is_generation_failed:
                        raise RuntimeError(
                            "itera102 synthesis failed after "
                            f"{generation_attempt}/{max_generation_attempts} attempts: {err_msg}. "
                            "Provider đang báo lỗi generation; hãy thử lại sau hoặc rút ngắn script."
                        )
                    raise RuntimeError(
                        f"itera102 synthesis failed task_id={tid} state=failed error={err_msg}"
                    )
                if err_msg:
                    last_error = err_msg
            if audio_url:
                break

            if (
                resubmit_reason is None
                and cfg.stuck_resubmit_polls > 0
                and polls_on_latest >= cfg.stuck_resubmit_polls
                and generation_attempt < max_generation_attempts
            ):
                resubmit_reason = (
                    f"task kẹt processing sau {polls_on_latest} lần poll "
                    f"(~{polls_on_latest * cfg.poll_interval_sec:.0f}s)"
                )
                last_error = f"provider giữ task ở trạng thái processing quá lâu ({resubmit_reason})"

            if resubmit_reason:
                generation_attempt += 1
                backoff_sec = cfg.poll_interval_sec * generation_attempt
                logger.warning(
                    "[tts_itera102] {}; submit lại next_attempt={}/{} backoff={}s active_tasks={}",
                    resubmit_reason,
                    generation_attempt,
                    max_generation_attempts,
                    backoff_sec,
                    active_tasks,
                )
                await asyncio.sleep(backoff_sec)
                try:
                    new_tid = await submit_task(generation_attempt)
                    active_tasks.append(new_tid)
                    task_id = new_tid
                    polls_on_latest = 0
                except TTSCreditExhaustedError:
                    raise
                except Exception as exc2:
                    logger.warning(
                        "[tts_itera102] retry submit failed attempt={}/{} error={!r}",
                        generation_attempt,
                        max_generation_attempts,
                        exc2,
                    )
                    last_error = str(exc2)
                    if not active_tasks:
                        raise RuntimeError(f"itera102 submit lại thất bại: {exc2}") from exc2

        if not audio_url:
            raise RuntimeError(
                f"itera102: timed out sau {cfg.poll_max_attempts} lần poll "
                f"(~{cfg.poll_max_attempts * cfg.poll_interval_sec:.0f}s), task vẫn chưa xong. "
                f"generation_attempt={generation_attempt}/{max_generation_attempts}, tasks={active_tasks}. "
                f"Last error: {last_error}"
            )

        # 3. Download audio
        async with session.get(audio_url, timeout=dl_timeout) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f"itera102: tải audio thất bại (HTTP {resp.status}) từ {audio_url}"
                )
            output_path.write_bytes(await resp.read())

    return TTSResult(
        provider="itera102",
        voice_id=cfg.voice_id,
        text=text,
        audio_path=output_path,
    )


# ---------------------------------------------------------------------------
# Provider: Google TTS (gTTS Fallback)
# ---------------------------------------------------------------------------


def split_text_for_google_tts(text: str, max_chars: int = 150) -> list[str]:
    """Làm sạch các tag biểu cảm (vd: [excited], [laughs]...) và cắt text thành các đoạn <= max_chars ký tự."""
    clean = re.sub(r"\[[a-zA-Z0-9_\-\s]+\]", "", text).strip()
    clean = re.sub(r"\s+", " ", clean)
    if not clean:
        return []
    if len(clean) <= max_chars:
        return [clean]

    sentences = re.split(r"(?<=[.!?,\n;:])\s+", clean)
    chunks: list[str] = []
    current = ""
    for s in sentences:
        if not s:
            continue
        if len(current) + len(s) + 1 <= max_chars:
            current = f"{current} {s}".strip()
        else:
            if current:
                chunks.append(current)
            if len(s) > max_chars:
                words = s.split(" ")
                sub = ""
                for w in words:
                    if len(sub) + len(w) + 1 <= max_chars:
                        sub = f"{sub} {w}".strip()
                    else:
                        if sub:
                            chunks.append(sub)
                        sub = w
                if sub:
                    chunks.append(sub)
                current = ""
            else:
                current = s
    if current:
        chunks.append(current)
    return [c for c in chunks if c.strip()]


async def tts_google(
    text: str,
    output_path: Path,
    *,
    speed: Optional[float] = None,
    lang: str = "vi",
) -> TTSResult:
    """Tổng hợp giọng nói tiếng Việt bằng Google Translate TTS endpoint, tự động ghép và chỉnh tốc độ qua FFmpeg."""
    chunks = split_text_for_google_tts(text)
    if not chunks:
        raise ValueError("Nội dung text rỗng, không thể gọi Google TTS.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="gtts_fall_"))
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    chunk_files: list[Path] = []
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            for idx, chunk in enumerate(chunks):
                url = (
                    "https://translate.google.com/translate_tts?ie=UTF-8&q="
                    f"{urllib.parse.quote(chunk)}&tl={lang}&client=tw-ob"
                )
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(f"Google TTS lỗi (HTTP {resp.status}): {body[:200]}")
                    raw_data = await resp.read()
                    part_file = temp_dir / f"part_{idx:03d}.mp3"
                    part_file.write_bytes(raw_data)
                    chunk_files.append(part_file)

        from src.downloader import get_ffmpeg_path

        ffmpeg = get_ffmpeg_path()
        concat_txt = temp_dir / "concat.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for p in chunk_files:
                safe = str(p.resolve()).replace("'", "'\\''")
                f.write(f"file '{safe}'\n")

        merged_raw = temp_dir / "merged_raw.mp3"
        concat_cmd = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
            "-c",
            "copy",
            str(merged_raw),
        ]
        proc = await asyncio.create_subprocess_exec(
            *concat_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Google TTS concat error: {stderr.decode().strip()[-300:]}")

        atempo = max(0.5, min(2.0, float(speed))) if speed is not None else 1.15
        is_mp3 = output_path.suffix.lower() == ".mp3"
        encoder = "libmp3lame" if is_mp3 else "aac"
        final_cmd = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(merged_raw),
            "-filter:a",
            f"atempo={atempo:.3f}",
            "-c:a",
            encoder,
            "-b:a",
            "192k",
            str(output_path),
        ]
        proc2 = await asyncio.create_subprocess_exec(
            *final_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr2 = await proc2.communicate()
        if proc2.returncode != 0:
            raise RuntimeError(f"Google TTS audio speed filter error: {stderr2.decode().strip()[-300:]}")

        logger.info(f"[tts_google] synthesized successfully -> {output_path} (speed={atempo:.2f})")
        return TTSResult(
            provider="google",
            voice_id="google-vi-standard",
            text=text,
            audio_path=output_path,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Provider: Edge TTS (Free Microsoft Neural Voice)
# ---------------------------------------------------------------------------


async def tts_edge(
    text: str,
    output_path: Path,
    *,
    voice: str = "vi-VN-HoaiMyNeural",
    speed: Optional[float] = None,
) -> TTSResult:
    """Tổng hợp giọng nói miễn phí chất lượng cao bằng Microsoft Edge TTS."""
    import edge_tts

    clean = re.sub(r"\[[a-zA-Z0-9_\-\s]+\]", "", text).strip()
    clean = re.sub(r"\s+", " ", clean)
    if not clean:
        raise ValueError("Nội dung text rỗng, không thể gọi Edge TTS.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="edge_tts_"))
    try:
        sp = float(speed) if speed is not None else 1.15
        if sp >= 1.0:
            rate_str = f"+{int((sp - 1.0) * 100)}%"
        else:
            rate_str = f"-{int((1.0 - sp) * 100)}%"

        temp_mp3 = temp_dir / "edge_raw.mp3"
        comm = edge_tts.Communicate(clean, voice=voice, rate=rate_str)
        await comm.save(str(temp_mp3))

        # Re-encode to destination if necessary (e.g., m4a / aac)
        from src.downloader import get_ffmpeg_path

        ffmpeg = get_ffmpeg_path()
        is_mp3 = output_path.suffix.lower() == ".mp3"
        encoder = "libmp3lame" if is_mp3 else "aac"
        cmd = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(temp_mp3),
            "-c:a",
            encoder,
            "-b:a",
            "192k",
            str(output_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Edge TTS reencode error: {stderr.decode().strip()[-300:]}")

        logger.info(f"[tts_edge] synthesized successfully ({voice}) -> {output_path}")
        return TTSResult(
            provider="edge_tts",
            voice_id=voice,
            text=text,
            audio_path=output_path,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Unified entrypoint
# ---------------------------------------------------------------------------


async def synthesize(
    text: str,
    output_path: Path,
    *,
    voice_id: Optional[str] = None,
    speed: Optional[float] = None,
    allow_fallback: bool = False,
) -> TTSResult:
    """Tổng hợp giọng nói.
    - Nếu voice_id là giọng free (Google TTS hoặc Edge TTS), gọi trực tiếp provider miễn phí.
    - Nếu là giọng Itera102, gọi Itera102 và tự động fallback sang Google TTS / Edge TTS nếu gặp lỗi (402, timeout...).

    Args:
        text: Script TikTok.
        output_path: Đường dẫn ghi audio (mp3/m4a/wav).
        voice_id: Voice id do UI truyền xuống (override ``ITERA102_VOICE_ID`` hoặc "google-free", "edge-free"...).
        speed: Override tốc độ đọc.
        allow_fallback: Bật tự động fallback sang Google TTS khi itera102 lỗi.
    """
    normalized_vid = (voice_id or "").strip().lower()

    # 1. Trực tiếp chọn giọng miễn phí Google TTS
    if normalized_vid in {"google-free", "google-tts", "google-vi", "google-vi-standard", "gtts", "free-google"}:
        logger.info(f"TTS via Google TTS Free -> {output_path}")
        return await tts_google(text, output_path, speed=speed)

    # 2. Trực tiếp chọn giọng miễn phí Microsoft Edge TTS
    if normalized_vid in {
        "edge-free",
        "free",
        "edge-vi-female",
        "vi-vn-hoaimyneural",
        "free-edge",
    }:
        logger.info(f"TTS via Edge TTS Free (Hoài My - Nữ) -> {output_path}")
        return await tts_edge(text, output_path, voice="vi-VN-HoaiMyNeural", speed=speed)

    if normalized_vid in {"edge-vi-male", "vi-vn-namminhneural"}:
        logger.info(f"TTS via Edge TTS Free (Nam Minh - Nam) -> {output_path}")
        return await tts_edge(text, output_path, voice="vi-VN-NamMinhNeural", speed=speed)

    # 3. Mặc định: Itera102 với fallback Google TTS
    logger.info(f"TTS via itera102 voice_id={voice_id or 'env'} -> {output_path}")

    async def _call_itera() -> TTSResult:
        if voice_id:
            prev_value = os.environ.get("ITERA102_VOICE_ID")
            os.environ["ITERA102_VOICE_ID"] = voice_id
            try:
                return await tts_itera102(text, output_path, speed=speed)
            finally:
                if prev_value is None:
                    os.environ.pop("ITERA102_VOICE_ID", None)
                else:
                    os.environ["ITERA102_VOICE_ID"] = prev_value
        return await tts_itera102(text, output_path, speed=speed)

    try:
        return await _call_itera()
    except TTSCreditExhaustedError:
        # Lỗi hết credit không bao giờ fallback mà raise thẳng để dừng luồng
        raise
    except Exception as exc:
        if not allow_fallback:
            logger.error(f"TTS giọng được chọn ({voice_id or 'mặc định'}) gặp lỗi: {exc!r}. Không fallback sang giọng khác.")
            raise
        logger.warning(
            f"Itera102 TTS gặp lỗi ({exc!r}). Đang thử fallback sang Google TTS theo yêu cầu..."
        )
        try:
            return await tts_google(text, output_path, speed=speed)
        except Exception as google_exc:
            logger.error(f"Fallback Google TTS cũng thất bại: {google_exc!r}")
            raise RuntimeError(
                f"TTS thất bại trên cả Itera102 ({exc}) lẫn Google TTS ({google_exc})"
            ) from exc


async def synthesize_batch(
    items: list[tuple[str, Path]],
    *,
    voice_id: Optional[str] = None,
    speed: Optional[float] = None,
) -> list[TTSResult]:
    """items = [(text, output_path), ...]."""
    tasks = [synthesize(t, p, voice_id=voice_id, speed=speed) for t, p in items]
    return await asyncio.gather(*tasks, return_exceptions=False)


async def synthesize_per_sentence(
    sentences: list[str],
    output_dir: Path,
    *,
    filename_prefix: str = "voice_part",
    voice_id: Optional[str] = None,
    speed: Optional[float] = None,
) -> list[TTSResult]:
    """Tạo một file audio mỗi câu, chạy song song."""
    output_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for i, sentence in enumerate(sentences):
        out_path = output_dir / f"{filename_prefix}_{i+1:02d}.mp3"
        items.append((sentence, out_path))
    return await synthesize_batch(items, voice_id=voice_id, speed=speed)


async def concatenate_audios(
    audio_paths: list[Path],
    output_path: Path,
) -> Path:
    """Ghép nhiều audio thành một track bằng FFmpeg (re-encode AAC)."""
    if not audio_paths:
        raise ValueError("audio_paths is empty")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    is_mp3 = output_path.suffix.lower() == ".mp3"
    encoder = "libmp3lame" if is_mp3 else "aac"
    bitrate = "192k"
    from src.downloader import get_ffmpeg_path
    ffmpeg = get_ffmpeg_path()

    if len(audio_paths) == 1:
        cmd = [
            ffmpeg, "-y", "-loglevel", "error",
            "-i", str(audio_paths[0]),
            "-c:a", encoder, "-b:a", bitrate,
            str(output_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg reencode failed: {stderr.decode().strip()[-300:]}")
        return output_path

    list_file = output_path.with_suffix(".concat.txt")
    try:
        with open(list_file, "w", encoding="utf-8") as f:
            for p in audio_paths:
                safe = str(p.resolve()).replace("'", "'\\''")
                f.write(f"file '{safe}'\n")

        cmd = [
            ffmpeg, "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c:a", encoder, "-b:a", bitrate,
            str(output_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg concat failed: {stderr.decode().strip()[-300:]}"
            )
    finally:
        list_file.unlink(missing_ok=True)
    return output_path
