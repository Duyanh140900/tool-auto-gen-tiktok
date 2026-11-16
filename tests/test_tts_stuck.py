"""tests/test_tts_stuck.py - itera102 task kẹt 'processing' phải được submit lại (không gọi API thật)."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from src import tts_generator as tg


def _settings(**over):
    base = dict(
        base_url="https://tts.test", api_key="k", voice_id="v", model_id="m", language_code="vi",
        provider="elevenlabs", speed=1.0, stability=0.5, similarity_boost=0.75, style=0.0,
        use_speaker_boost=True, export_transcript=False, request_timeout_sec=5, poll_interval_sec=0.01,
        poll_max_attempts=30, download_timeout_sec=5, stuck_resubmit_polls=5,
    )
    base.update(over)
    return tg.Itera102Settings(**base)


class _Resp:
    def __init__(self, status=200, payload=None, body=b""):
        self.status = status
        self._payload = payload
        self._body = body

    async def text(self):
        return json.dumps(self._payload) if self._payload is not None else ""

    async def json(self):
        return self._payload

    async def read(self):
        return self._body


class _Ctx:
    def __init__(self, resp):
        self.resp = resp

    async def __aenter__(self):
        return self.resp

    async def __aexit__(self, *a):
        return False


class FakeSession:
    """status_fn(task_id, poll_count) -> dict trạng thái trả về cho GET /v1/history/{id}."""

    def __init__(self, status_fn):
        self.status_fn = status_fn
        self.submitted = []
        self.polls = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def post(self, url, **kw):
        tid = f"t{len(self.submitted) + 1}"
        self.submitted.append(tid)
        return _Ctx(_Resp(payload={"id": tid}))

    def get(self, url, **kw):
        if "/v1/history/" in url:
            tid = url.rsplit("/", 1)[-1]
            self.polls[tid] = self.polls.get(tid, 0) + 1
            return _Ctx(_Resp(payload=self.status_fn(tid, self.polls[tid])))
        return _Ctx(_Resp(body=b"mp3-bytes"))


PROCESSING = {"status": "processing", "error": None}


def _completed(tid):
    return {"status": "completed", "result": {"audio_url": f"https://cdn.test/{tid}.mp3"}}


class ItEra102StuckTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, session, **over):
        with TemporaryDirectory() as tmp, \
                patch.object(tg.Itera102Settings, "from_env", return_value=_settings(**over)), \
                patch.object(tg.aiohttp, "ClientSession", return_value=session), \
                patch.object(tg.asyncio, "sleep", new=AsyncMock()):
            out = Path(tmp) / "voice.mp3"
            res = await tg.tts_itera102("xin chào", out)
            self.assertEqual(out.read_bytes(), b"mp3-bytes")
            return res

    async def test_resubmits_when_task_stuck_and_uses_new_task(self):
        session = FakeSession(lambda tid, n: _completed(tid) if tid == "t2" and n >= 2 else PROCESSING)
        await self._run(session)
        self.assertEqual(session.submitted, ["t1", "t2"])
        self.assertEqual(session.polls["t1"], 6)  # vẫn poll task cũ song song (task mới được poll trước)

    async def test_old_task_finishing_late_is_still_used(self):
        session = FakeSession(lambda tid, n: _completed(tid) if tid == "t1" and n >= 7 else PROCESSING)
        await self._run(session)
        self.assertEqual(session.submitted, ["t1", "t2"])

    async def test_normal_fast_task_not_resubmitted(self):
        session = FakeSession(lambda tid, n: _completed(tid) if n >= 3 else PROCESSING)
        await self._run(session)
        self.assertEqual(session.submitted, ["t1"])

    async def test_times_out_with_clear_error_after_max_attempts(self):
        session = FakeSession(lambda tid, n: PROCESSING)
        with self.assertRaises(RuntimeError) as ctx:
            await self._run(session, poll_max_attempts=20)
        self.assertEqual(session.submitted, ["t1", "t2", "t3"])  # tối đa 3 lần submit
        self.assertIn("timed out", str(ctx.exception))
        self.assertIn("processing quá lâu", str(ctx.exception))

    async def test_stuck_resubmit_can_be_disabled(self):
        session = FakeSession(lambda tid, n: _completed(tid) if n >= 12 else PROCESSING)
        await self._run(session, stuck_resubmit_polls=0)
        self.assertEqual(session.submitted, ["t1"])

    async def test_generation_failed_still_resubmits(self):
        def status(tid, n):
            if tid == "t1":
                return {"status": "failed", "error": "Generation failed, please try again."}
            return _completed(tid)
        session = FakeSession(status)
        await self._run(session)
        self.assertEqual(session.submitted, ["t1", "t2"])


if __name__ == "__main__":
    unittest.main()
