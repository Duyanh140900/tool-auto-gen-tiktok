"""Bot Telegram: nhận link -> chạy batch /ai-video với setting đã lưu."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from src import ai_video_defaults
from datetime import datetime

from src.telegram_bot import TelegramBot, extract_tiktok_urls, parse_chat_ids, parse_link_options, parse_links_with_themes
from src.web.job_manager import BatchItem, JobSnapshot


class FakeJobManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.current = JobSnapshot(job_id="idle", created_at="", status="idle")
        self.running = False
        self.calls: List[Dict[str, Any]] = []
        self.listeners: List[Any] = []

    def subscribe(self, fn: Any) -> None:
        self.listeners.append(fn)

    def unsubscribe(self, fn: Any) -> None:
        self.listeners.remove(fn)

    def is_running(self) -> bool:
        return self.running

    def create_batch(self, items: List[Dict[str, Any]], **kwargs: Any) -> JobSnapshot:
        if self.running:
            raise RuntimeError("busy")
        self.calls.append({"items": items, **kwargs})
        self.current = JobSnapshot(
            job_id=f"job{len(self.calls)}",
            created_at="",
            status="running",
            items=[BatchItem(index=i + 1, url=it["url"]) for i, it in enumerate(items)],
        )
        self.running = True
        return self.current

    def publish(self) -> None:
        with self._lock:  # giống JobManager thật: listener chạy khi đang giữ lock
            for fn in self.listeners:
                fn(self.current)


def make_bot(jm: FakeJobManager, defaults: Dict[str, Any]) -> tuple[TelegramBot, List[tuple]]:
    sent: List[tuple] = []
    bot = TelegramBot("t", jm, {42}, defaults_loader=lambda: defaults)
    bot.send = lambda chat, text, markup=None: sent.append((chat, text))  # type: ignore[method-assign]
    jm.subscribe(bot._on_job_update)
    return bot, sent


def msg(chat_id: int, text: str) -> Dict[str, Any]:
    return {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": text}}


class HelperTests(unittest.TestCase):
    def test_extract_urls(self) -> None:
        text = "xem https://vt.tiktok.com/ZSabc/ và https://www.tiktok.com/@a/video/123?x=1, https://vt.tiktok.com/ZSabc/"
        self.assertEqual(
            extract_tiktok_urls(text),
            ["https://vt.tiktok.com/ZSabc/", "https://www.tiktok.com/@a/video/123?x=1"],
        )
        self.assertEqual(extract_tiktok_urls("https://youtube.com/x"), [])

    def test_parse_link_options_full_line(self) -> None:
        now = datetime(2026, 11, 16, 10, 0)
        [p] = parse_link_options("https://vt.tiktok.com/ZSabc/ - Black Friday - 0.4 - 1.1 - 18:32 - 20/11", now)
        self.assertEqual(p.url, "https://vt.tiktok.com/ZSabc/")
        self.assertEqual(p.theme, "Black Friday")
        self.assertEqual((p.shift, p.scale), (0.4, 1.1))
        self.assertEqual(p.post_at, datetime(2026, 11, 20, 18, 30))  # phút làm tròn xuống bội số 5
        self.assertEqual(p.warnings, [])

    def test_parse_link_options_optional_and_unordered(self) -> None:
        now = datetime(2026, 11, 16, 10, 0)
        link = "https://vt.tiktok.com/ZSabc/"
        self.assertEqual(parse_link_options(link, now)[0].post_at, None)
        self.assertEqual(parse_link_options(f"{link} - Tết", now)[0].theme, "Tết")
        only_shift = parse_link_options(f"{link} - 0,45", now)[0]  # một số = Y-offset
        self.assertEqual((only_shift.theme, only_shift.shift, only_shift.scale, only_shift.post_at), (None, 0.45, None, None))
        only_scale = parse_link_options(f"{link} - _ - 1,25", now)[0]  # _ bỏ qua Y-offset
        self.assertEqual((only_scale.shift, only_scale.scale), (None, 1.25))
        mixed = parse_link_options(f"{link} - Tết - 18:30 - 0.3 - 1.2", now)[0]  # giờ đứng trước/sau số đều được
        self.assertEqual((mixed.theme, mixed.shift, mixed.scale), ("Tết", 0.3, 1.2))
        # giờ + ngày không cần chủ đề/scale, thứ tự bất kỳ
        p = parse_link_options(f"{link} - 20/11/2026 - 9h30", now)[0]
        self.assertEqual((p.theme, p.post_at), (None, datetime(2026, 11, 20, 9, 30)))
        # chủ đề có dấu gạch bên trong vẫn giữ nguyên
        p = parse_link_options(f"{link} - Combo 2 - 1 giá - 0.5 - 1.2", now)[0]
        self.assertEqual((p.theme, p.shift, p.scale), ("Combo 2 - 1 giá", 0.5, 1.2))

    def test_parse_link_options_time_and_date_defaults(self) -> None:
        now = datetime(2026, 11, 16, 10, 0)
        link = "https://vt.tiktok.com/ZSabc/"
        self.assertEqual(parse_link_options(f"{link} - 18h", now)[0].post_at, datetime(2026, 11, 16, 18, 0))
        self.assertEqual(parse_link_options(f"{link} - 08:00", now)[0].post_at, datetime(2026, 11, 17, 8, 0))  # qua giờ -> mai
        self.assertEqual(parse_link_options(f"{link} - 20/11", now)[0].post_at, datetime(2026, 11, 20, 8, 0))  # chỉ ngày -> 08:00
        self.assertEqual(parse_link_options(f"{link} - 05/01 - 9:00", now)[0].post_at, datetime(2027, 1, 5, 9, 0))  # ngày đã qua -> năm sau

    def test_parse_link_options_invalid_values_warn(self) -> None:
        now = datetime(2026, 11, 16, 10, 0)
        link = "https://vt.tiktok.com/ZSabc/"
        p = parse_link_options(f"{link} - 0.4 - 9 - 31/02", now)[0]  # scale 9 ngoài khoảng, ngày không có thật
        self.assertEqual(len(p.warnings), 1 + 1)
        self.assertEqual((p.shift, p.scale), (0.4, None))
        self.assertIsNone(p.post_at)
        self.assertEqual(parse_link_options(f"{link} - 25:00", now)[0].warnings, ["Giờ đăng '25:00' không hợp lệ"])

    def test_parse_links_with_themes_still_works(self) -> None:
        self.assertEqual(
            parse_links_with_themes("https://vt.tiktok.com/ZSabc/ - Black Friday\nhttps://vt.tiktok.com/ZSdef/"),
            [("https://vt.tiktok.com/ZSabc/", "Black Friday"), ("https://vt.tiktok.com/ZSdef/", None)],
        )

    def test_batch_kwargs_per_link_scale_and_post_at(self) -> None:
        kw = ai_video_defaults.build_batch_kwargs(
            ["u1", "u2"], {}, shifts=[0.5, None], scales=[1.3, None], post_ats=["2026-11-20T18:30", None]
        )
        first, second = kw["items_payload"]
        self.assertEqual((first["video_shift_ratio"], first["video_scale"], first["post_at"]), (0.5, 1.3, "2026-11-20T18:30"))
        self.assertEqual((second["video_shift_ratio"], second["video_scale"]), (0.3333, 1.08))  # theo setting
        self.assertNotIn("post_at", second)

    def test_parse_chat_ids(self) -> None:
        self.assertEqual(parse_chat_ids("1, -100200 ;x"), {1, -100200})

    def test_defaults_roundtrip_and_batch_kwargs(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "defaults.json"
            self.assertEqual(ai_video_defaults.load(path)["style"], "style1")
            ai_video_defaults.save(
                {"style": "style3", "voice_id": "default", "video_scale": 9, "auto_post": True, "script_theme": " Tết "},
                path,
            )
            loaded = ai_video_defaults.load(path)
        kw = ai_video_defaults.build_batch_kwargs(["u1"], loaded)
        self.assertEqual(kw["default_style"], "style3")
        self.assertIsNone(kw["default_voice_id"])  # "default" = giọng mặc định .env
        self.assertEqual(kw["items_payload"][0]["video_scale"], 1.08)  # ngoài khoảng -> mặc định
        self.assertTrue(kw["auto_post"])
        self.assertEqual(kw["default_script_theme"], "Tết")


class BotFlowTests(unittest.TestCase):
    def test_rejects_unknown_chat(self) -> None:
        jm = FakeJobManager()
        bot, sent = make_bot(jm, {})
        bot.handle_update(msg(7, "https://vt.tiktok.com/abc/"))
        bot.dispatch_once()
        self.assertEqual(jm.calls, [])
        self.assertIn("7", sent[0][1])

    def test_link_runs_batch_with_saved_settings_and_reports(self) -> None:
        jm = FakeJobManager()
        bot, sent = make_bot(jm, {"style": "style2", "voice_id": "v1", "auto_showcase": True})
        bot.handle_update(msg(42, "https://vt.tiktok.com/a/ https://vt.tiktok.com/b/"))
        bot.dispatch_once()

        self.assertEqual(len(jm.calls), 1)
        call = jm.calls[0]
        self.assertEqual([it["url"] for it in call["items"]], ["https://vt.tiktok.com/a/", "https://vt.tiktok.com/b/"])
        self.assertEqual(call["default_style"], "style2")
        self.assertEqual(call["default_voice_id"], "v1")
        self.assertTrue(call["auto_showcase"])

        # link gửi khi đang bận thì xếp hàng, không tạo job mới
        bot.handle_update(msg(42, "https://vt.tiktok.com/c/"))
        bot.dispatch_once()
        self.assertEqual(len(jm.calls), 1)

        # item 1 xong -> báo ngay (listener chạy dưới lock JobManager, không deadlock)
        jm.current.items[0].status = "done"
        jm.current.items[0].final_video_path = "D:/out/a.mp4"
        jm.publish()
        jm.current.items[1].status = "error"
        jm.current.items[1].error = "boom"
        jm.current.status = "error"
        jm.running = False
        jm.publish()
        for t in threading.enumerate():
            if t is not threading.current_thread() and t.daemon:
                t.join(timeout=2)

        bot.dispatch_once()  # báo kết thúc + chạy link đang chờ
        texts = "\n".join(t for _, t in sent)
        self.assertIn("Xong video #1", texts)
        self.assertIn("D:/out/a.mp4", texts)
        self.assertIn("boom", texts)
        self.assertIn("1 thành công, 1 lỗi", texts)
        self.assertEqual(len(jm.calls), 2)
        self.assertEqual(jm.calls[1]["items"][0]["url"], "https://vt.tiktok.com/c/")

    def test_per_link_theme_overrides_default(self) -> None:
        jm = FakeJobManager()
        bot, sent = make_bot(jm, {"script_theme": "Quà tặng"})
        bot.handle_update(msg(42, (
            "Xem https://vt.tiktok.com/a/ - \"Black Friday\"\n"
            "https://vt.tiktok.com/b/\n"
            "https://vt.tiktok.com/c/ – Quà 20/11"
        )))
        self.assertIn("Chủ đề: mặc định (Quà tặng)", sent[-1][1])
        self.assertIn("Chủ đề: Black Friday", sent[-1][1])
        bot.dispatch_once()
        call = jm.calls[0]
        self.assertEqual([it.get("script_theme") for it in call["items"]], ["Black Friday", None, "Quà 20/11"])
        self.assertEqual(call["default_script_theme"], "Quà tặng")  # link không ghi chủ đề dùng mặc định

    def test_resending_queued_link_with_theme_updates_it(self) -> None:
        jm = FakeJobManager()
        jm.running = True
        bot, _ = make_bot(jm, {})
        bot.handle_update(msg(42, "https://vt.tiktok.com/a/"))
        bot.handle_update(msg(42, "https://vt.tiktok.com/a/ - Tết"))
        self.assertEqual([(q.url, q.theme) for q in bot._queue], [("https://vt.tiktok.com/a/", "Tết")])

    def test_queue_kept_when_ui_job_running(self) -> None:
        jm = FakeJobManager()
        jm.running = True
        bot, _ = make_bot(jm, {})
        bot.handle_update(msg(42, "https://vt.tiktok.com/a/"))
        bot.dispatch_once()
        self.assertEqual(jm.calls, [])
        jm.running = False
        bot.dispatch_once()
        self.assertEqual(len(jm.calls), 1)


class SettingsMenuTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "d.json"
        self.jm = FakeJobManager()
        self.voices = [{"name": "Google", "voice_id": "google-free"}, {"name": "Adam", "voice_id": "adam-id"}]
        self.bot = TelegramBot(
            "t", self.jm, {42},
            defaults_loader=lambda: ai_video_defaults.load(path),
            defaults_saver=lambda d: ai_video_defaults.save(d, path),
            voices_loader=lambda: self.voices,
        )
        self.sent: List[tuple] = []
        self.edits: List[tuple] = []
        self.bot.send = lambda chat, text, markup=None: self.sent.append((chat, text, markup))  # type: ignore
        self.bot.edit = lambda chat, mid, text, markup=None: self.edits.append((text, markup))  # type: ignore
        self.bot.answer_callback = lambda cb_id, text="": None  # type: ignore

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def click(self, data: str, chat: int = 42) -> None:
        self.bot.handle_update({"update_id": 2, "callback_query": {
            "id": "c", "data": data, "message": {"chat": {"id": chat}, "message_id": 5}}})

    def test_settings_shows_keyboard(self) -> None:
        self.bot.handle_update(msg(42, "/settings"))
        _, text, markup = self.sent[-1]
        self.assertIn("Style 1", str(markup))
        self.assertIn("Giọng: Google", text)
        for row in markup["inline_keyboard"]:
            for b in row:
                self.assertLessEqual(len(b["callback_data"].encode()), 64)

    def test_buttons_change_settings_used_by_next_batch(self) -> None:
        self.click("cfg:style:style3")
        self.click("cfg:voice:1")
        self.click("cfg:t:auto_post")
        d = self.bot.defaults_loader()
        self.assertEqual((d["style"], d["voice_id"], d["auto_post"]), ("style3", "adam-id", True))
        self.assertIn("Giọng: Adam", self.edits[-1][0])

        self.bot.handle_update(msg(42, "https://vt.tiktok.com/a/"))
        self.bot.dispatch_once()
        call = self.jm.calls[0]
        self.assertEqual((call["default_style"], call["default_voice_id"], call["auto_post"]), ("style3", "adam-id", True))

    def test_text_input_for_theme_and_scale(self) -> None:
        self.click("cfg:ask:script_theme")
        self.bot.handle_update(msg(42, "Black Friday"))
        self.assertEqual(self.bot.defaults_loader()["script_theme"], "Black Friday")

        self.click("cfg:ask:video_scale")
        self.bot.handle_update(msg(42, "9"))  # ngoài khoảng: hỏi lại, chưa lưu
        self.assertEqual(self.bot.defaults_loader()["video_scale"], 1.08)
        self.bot.handle_update(msg(42, "1,2"))
        self.assertEqual(self.bot.defaults_loader()["video_scale"], 1.2)

        # hết chờ nhập: link lại được xếp hàng bình thường
        self.bot.handle_update(msg(42, "https://vt.tiktok.com/a/"))
        self.assertEqual(len(self.bot._queue), 1)

    def test_unknown_chat_cannot_change(self) -> None:
        self.click("cfg:t:auto_post", chat=7)
        self.assertFalse(self.bot.defaults_loader()["auto_post"])


class ApiTests(unittest.TestCase):
    def test_defaults_endpoint(self) -> None:
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from src.web.app import app

        with tempfile.TemporaryDirectory() as d, patch.object(
            ai_video_defaults, "DEFAULTS_FILE", Path(d) / "x.json"
        ):
            client = TestClient(app)
            r = client.post("/api/ai-video/defaults", json={"style": "style2", "voice_id": "abc"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(client.get("/api/ai-video/defaults").json()["voice_id"], "abc")


if __name__ == "__main__":
    unittest.main()
