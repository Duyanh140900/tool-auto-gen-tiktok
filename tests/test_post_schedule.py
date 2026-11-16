"""Test lịch đăng hẹn giờ 4 slot/ngày và worker đăng TikTok Studio."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.post_schedule import PostSchedule, next_slot_after, within_horizon
from src.tiktok_poster import (
    PostError,
    PostTask,
    PostWorker,
    UnverifiedPostError,
    build_caption,
    caption_from_filename,
    choose_anchor,
    is_duplicate_caption,
    clean_short_name,
    parse_anchor_choice,
    parse_studio_datetime,
    pick_product_name,
)

MULTI_ANCHORS = [
    {"keyword": "Combo Kem tay", "product_id": "m1", "title": "Combo Kem Dưỡng Da Tay Và Bọt Rửa Mặt"},
    {"keyword": "Combo Mat na", "product_id": "m2", "title": "Combo Bọt Rửa Mặt Và Mặt Nạ Dưỡng Da"},
    {"keyword": "Combo 2 Sua", "product_id": "m3", "title": "Combo 2 Sữa Rửa Mặt Tơ Tằm"},
]


class NextSlotTests(unittest.TestCase):
    def test_follows_last_slot_through_the_day_and_rolls_over(self):
        now = datetime(2026, 11, 2, 9, 0)
        self.assertEqual(next_slot_after(datetime(2026, 11, 5, 8), now), datetime(2026, 11, 5, 12))
        self.assertEqual(next_slot_after(datetime(2026, 11, 5, 12), now), datetime(2026, 11, 5, 18))
        self.assertEqual(next_slot_after(datetime(2026, 11, 5, 18), now), datetime(2026, 11, 5, 22))
        self.assertEqual(next_slot_after(datetime(2026, 11, 5, 22), now), datetime(2026, 11, 6, 8))

    def test_no_history_uses_next_slot_from_now(self):
        self.assertEqual(next_slot_after(None, datetime(2026, 11, 2, 9, 0)), datetime(2026, 11, 2, 12))
        self.assertEqual(next_slot_after(None, datetime(2026, 11, 2, 23, 0)), datetime(2026, 11, 3, 8))

    def test_past_last_slot_or_too_close_is_skipped(self):
        now = datetime(2026, 11, 2, 11, 50)  # 12:00 cách < 15 phút
        self.assertEqual(next_slot_after(datetime(2026, 10, 30, 22), now), datetime(2026, 11, 2, 18))
        self.assertEqual(next_slot_after(None, now), datetime(2026, 11, 2, 18))

    def test_horizon_is_thirty_days_by_default(self):
        now = datetime(2026, 11, 2, 23, 0)
        self.assertTrue(within_horizon(datetime(2026, 12, 2, 22), now))
        self.assertFalse(within_horizon(datetime(2026, 12, 3, 8), now))


class PostScheduleLedgerTests(unittest.TestCase):
    def test_last_slot_is_studio_mark_plus_posts_after_the_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            sched = PostSchedule(Path(tmp) / "s.json")
            self.assertIsNone(sched.last_slot())
            # bài hẹn trước lần đọc Studio: Studio đã tính rồi (có thể đã bị xóa tay) -> bỏ qua
            sched.upsert({"video_path": "old.mp4", "status": "scheduled", "slot": "2026-11-20T08:00",
                          "updated_at": "2026-11-01T10:00:00"})
            sched.set_studio_last_slot(datetime(2026, 11, 3, 22), checked_at=datetime(2026, 11, 2, 9))
            self.assertEqual(sched.last_slot(), datetime(2026, 11, 3, 22))
            sched.upsert({"video_path": "a.mp4", "status": "scheduled", "slot": "2026-11-04T08:00",
                          "updated_at": "2026-11-02T09:05:00"})
            sched.upsert({"video_path": "b.mp4", "status": "error", "slot": "2026-11-09T08:00",
                          "updated_at": "2026-11-02T09:06:00"})
            self.assertEqual(sched.last_slot(), datetime(2026, 11, 4, 8))
            summary = sched.summary(now=datetime(2026, 11, 2, 9))
            self.assertEqual(summary["next_slot"], "2026-11-04T12:00")
            self.assertEqual(summary["studio_last_slot"], "2026-11-03T22:00")


class HelperTests(unittest.TestCase):
    def test_clean_short_name(self):
        self.assertEqual(clean_short_name('Tên: "Chảo Thần"\nxyz', "Chảo chống dính"), "Chảo Thần")
        self.assertEqual(clean_short_name("", "Nồi chiên không dầu 5L"), "Nồi chiên")
        self.assertLessEqual(len(clean_short_name("x" * 80, "p")), 30)

    def test_caption_and_product_pick(self):
        self.assertEqual(build_caption({"caption": "Mê quá", "hashtags": ["#a", "b"]}), "Mê quá #a #b")
        showcase = {"results": [{"product": "A", "status": "loi"}, {"product": "B", "status": "da_co"}]}
        self.assertEqual(pick_product_name(showcase), "B")
        self.assertEqual(pick_product_name({"results": [{"product": "", "status": "thanh_cong"}]}), "")

    def test_parse_studio_datetime(self):
        now = datetime(2026, 11, 2, 23, 0)
        self.assertEqual(parse_studio_datetime("Nov 3, 10:00 PM", now), datetime(2026, 11, 3, 22))
        self.assertEqual(parse_studio_datetime("Nov 3, 8:00 AM", now), datetime(2026, 11, 3, 8))
        self.assertEqual(parse_studio_datetime("Nov 3, 12:00 PM", now), datetime(2026, 11, 3, 12))
        self.assertEqual(parse_studio_datetime("Nov 4, 8:00 AM (GMT+7) Bangkok", now), datetime(2026, 11, 4, 8))
        self.assertEqual(parse_studio_datetime("5 tháng 11, 10:00 CH", now), datetime(2026, 11, 5, 22))
        self.assertEqual(parse_studio_datetime("5 tháng 11, 8:00 SA", now), datetime(2026, 11, 5, 8))
        self.assertEqual(parse_studio_datetime("6 tháng 11, 12:00 CH (GMT+7) Bangkok", now), datetime(2026, 11, 6, 12))
        self.assertEqual(parse_studio_datetime("Jan 2, 12:00 AM", datetime(2026, 12, 20)), datetime(2027, 1, 2, 0))
        self.assertEqual(parse_studio_datetime("Nov 3, 2027, 6:00 PM", now), datetime(2027, 11, 3, 18))
        with self.assertRaises(PostError):
            parse_studio_datetime("3 thg 11, 22:00", now)

    def test_parse_anchor_choice(self):
        self.assertEqual(parse_anchor_choice("2", 3), 1)
        self.assertEqual(parse_anchor_choice("Sản phẩm số 3.", 3), 2)
        self.assertIsNone(parse_anchor_choice("0", 3))
        self.assertIsNone(parse_anchor_choice("4", 3))
        self.assertIsNone(parse_anchor_choice("không chắc", 3))

    def test_choose_anchor_matches_showcase_name_ignoring_accents(self):
        anchors = [
            {"keyword": "Tất basic", "product_id": "1", "title": "COMBO 7 Tất"},
            {"keyword": "Móc khoá trái tim", "product_id": "2", "title": "Móc trang trí túi"},
        ]
        self.assertEqual(choose_anchor(anchors, "Móc khóa trái tim")["product_id"], "2")
        self.assertIsNone(choose_anchor(anchors, ""))
        self.assertEqual(choose_anchor(anchors[:1], "")["product_id"], "1")  # video 1 sản phẩm


class FakeSession:
    instances = []
    studio_last = None
    studio_captions = []

    def __init__(self):
        self.on_status = lambda msg: None
        self.calls = []
        self.closed = False
        self.reads = 0
        FakeSession.instances.append(self)

    def open(self):
        pass

    def close(self):
        self.closed = True

    def read_posts(self):
        self.reads += 1
        posts = [{"when": datetime(2026, 11, 1, 8), "scheduled": False, "caption": c} for c in FakeSession.studio_captions]
        if FakeSession.studio_last:
            posts.insert(0, {"when": FakeSession.studio_last, "scheduled": True, "caption": "bài đang hẹn"})
        return posts

    def fetch_anchors(self, source_url):
        if source_url == "none":
            return []
        if source_url == "multi":
            return list(MULTI_ANCHORS)
        return [{"keyword": source_url.upper(), "product_id": f"id-{source_url}", "title": f"Tên đầy đủ {source_url}"}]

    def schedule_post(self, task, anchor, short_name, slot, dry):
        self.on_status("Đang tải video lên TikTok Studio")
        if anchor["product_id"] == "id-hong":
            raise PostError("Không thấy sản phẩm trong Showcase products")
        if anchor["product_id"] == "id-mo":
            raise UnverifiedPostError("Đã bấm Schedule nhưng chưa thấy bài hẹn")
        self.calls.append((task.index, anchor["product_id"], short_name, slot, dry))
        return ""


class PostWorkerTests(unittest.TestCase):
    def setUp(self):
        FakeSession.instances.clear()
        FakeSession.studio_last = None
        FakeSession.studio_captions = []
        self.trashed = []
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.schedule = PostSchedule(self.dir / "s.json")
        self.videos = []
        for i in range(3):
            p = self.dir / f"v{i}.mp4"
            p.write_bytes(b"x")
            self.videos.append(str(p))

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, tasks, now, dry=False, delete_after=False, anchor_picker=None):
        updates = []
        with patch("src.tiktok_poster.datetime") as dt, patch("src.tiktok_poster.DELAY_BETWEEN_POSTS", (0, 0)):
            dt.now.return_value = now
            dt.fromisoformat.side_effect = datetime.fromisoformat
            worker = PostWorker(
                lambda i, s: updates.append((i, dict(s))),
                dry=dry,
                schedule=self.schedule,
                session_factory=FakeSession,
                short_namer=lambda name, caption: f"{name.split()[-1]} vui",
                delete_after=delete_after,
                trasher=self.trashed.append,
                anchor_picker=anchor_picker or (lambda anchors, hint, caption: None),
            )
            for t in tasks:
                worker.submit(t)
            worker.finish(timeout=10)
        return updates

    def test_continues_after_last_slot_read_from_studio(self):
        FakeSession.studio_last = datetime(2026, 11, 3, 22)
        tasks = [PostTask(i + 1, v, f"caption video số {i}", f"p{i}", source_url=f"p{i}") for i, v in enumerate(self.videos)]
        updates = self._run(tasks, datetime(2026, 11, 2, 23))

        session = FakeSession.instances[0]
        self.assertEqual(session.reads, 1)  # đọc Studio 1 lần mỗi lượt chạy
        self.assertEqual([c[3] for c in session.calls], [
            datetime(2026, 11, 4, 8), datetime(2026, 11, 4, 12), datetime(2026, 11, 4, 18),
        ])
        self.assertEqual(session.calls[0][1:3], ("id-p0", "p0 vui"))
        self.assertEqual(self.schedule.last_slot(), datetime(2026, 11, 4, 18))
        self.assertTrue(session.closed)
        final = {i: s["status"] for i, s in updates if s["status"] not in {"running", "queued"}}
        self.assertEqual(final, {1: "scheduled", 2: "scheduled", 3: "scheduled"})
        self.assertTrue(any(i == 2 and s["status"] == "running" and "tải video" in s["message"] for i, s in updates))

    def test_beyond_horizon_goes_to_waiting(self):
        FakeSession.studio_last = datetime(2026, 12, 2, 22)
        updates = self._run([PostTask(1, self.videos[0], "cap", "p", source_url="p")], datetime(2026, 11, 2, 23))
        self.assertEqual(updates[-1][1]["status"], "waiting")
        self.assertEqual(len(self.schedule.waiting()), 1)
        self.assertEqual(FakeSession.instances[0].calls, [])

    def test_custom_post_at_is_used_and_does_not_shift_auto_slots(self):
        tasks = [
            PostTask(1, self.videos[0], "caption riêng giờ", "p0", source_url="p0", post_at="2026-11-20T18:30"),
            PostTask(2, self.videos[1], "caption slot tự động", "p1", source_url="p1"),
        ]
        updates = self._run(tasks, datetime(2026, 11, 2, 9))
        session = FakeSession.instances[0]
        self.assertEqual([c[3] for c in session.calls], [datetime(2026, 11, 20, 18, 30), datetime(2026, 11, 2, 12)])
        final = {i: s for i, s in updates if s["status"] == "scheduled"}
        self.assertEqual(final[1]["slot"], "2026-11-20T18:30")
        self.assertEqual(final[2]["slot"], "2026-11-02T12:00")  # slot tự động không bị đẩy ra sau giờ riêng
        self.assertEqual(self.schedule.last_slot(), datetime(2026, 11, 2, 12))
        self.assertTrue(self.schedule.find(self.videos[0])["custom_slot"])

    def test_custom_post_at_in_the_past_fails_without_consuming_slot(self):
        tasks = [
            PostTask(1, self.videos[0], "caption giờ đã qua", "p0", source_url="p0", post_at="2026-11-02T09:05"),
            PostTask(2, self.videos[1], "caption bình thường", "p1", source_url="p1"),
        ]
        updates = self._run(tasks, datetime(2026, 11, 2, 9))
        final = {i: s for i, s in updates if s["status"] in {"scheduled", "error"}}
        self.assertEqual(final[1]["status"], "error")
        self.assertIn("đã qua", final[1]["message"])
        self.assertEqual(final[2]["slot"], "2026-11-02T12:00")

    def test_custom_post_at_beyond_horizon_waits_and_keeps_its_slot(self):
        updates = self._run(
            [PostTask(1, self.videos[0], "cap", "p", source_url="p", post_at="2027-03-01T08:00")], datetime(2026, 11, 2, 9)
        )
        self.assertEqual(updates[-1][1]["status"], "waiting")
        [waiting] = self.schedule.waiting()
        self.assertEqual((waiting["slot"], waiting["custom_slot"]), ("2027-03-01T08:00", True))

    def test_errors_do_not_consume_slot(self):
        tasks = [
            PostTask(1, self.videos[0], "cap", "hong", source_url="hong"),
            PostTask(2, self.videos[1], "cap", "", source_url="none"),
            PostTask(3, self.videos[2], "cap", "ok", source_url="ok"),
        ]
        updates = self._run(tasks, datetime(2026, 11, 2, 9))
        final = {i: s for i, s in updates if s["status"] in {"scheduled", "error"}}
        self.assertEqual(final[1]["status"], "error")
        self.assertIn("sản phẩm của video nguồn", final[2]["message"])
        self.assertEqual(final[3]["slot"], "2026-11-02T12:00")

    def test_multi_product_source_without_showcase_name_asks_ai(self):
        asked = []

        def picker(anchors, hint, caption):
            asked.append((len(anchors), hint))
            return anchors[1]

        task = PostTask(1, self.videos[0], "cap", "", source_url="multi", product_hint="Sữa rửa mặt + Mặt nạ")
        updates = self._run([task], datetime(2026, 11, 2, 9), anchor_picker=picker)
        self.assertEqual(asked, [(3, "Sữa rửa mặt + Mặt nạ")])
        self.assertEqual(FakeSession.instances[0].calls[0][1], "m2")
        final = [s for i, s in updates if s["status"] in {"scheduled", "error"}]
        self.assertEqual(final[-1]["status"], "scheduled")

    def test_multi_product_source_ai_unsure_fails_without_posting(self):
        task = PostTask(1, self.videos[0], "cap", "", source_url="multi", product_hint="Set quà")
        updates = self._run([task], datetime(2026, 11, 2, 9))
        final = [s for i, s in updates if s["status"] in {"scheduled", "error"}]
        self.assertEqual(final[-1]["status"], "error")
        self.assertIn("gắn 3 sản phẩm", final[-1]["message"])
        self.assertEqual(FakeSession.instances[0].calls, [])

    def test_dry_run_does_not_write_ledger_but_advances_slots(self):
        tasks = [PostTask(i + 1, v, f"caption video số {i}", "p", source_url="p") for i, v in enumerate(self.videos[:2])]
        updates = self._run(tasks, datetime(2026, 11, 2, 9), dry=True)
        calls = FakeSession.instances[0].calls
        self.assertEqual([c[3] for c in calls], [datetime(2026, 11, 2, 12), datetime(2026, 11, 2, 18)])
        self.assertTrue(all(c[4] for c in calls))
        self.assertEqual(updates[-1][1]["status"], "thu")
        self.assertEqual(self.schedule.waiting(), [])
        self.assertIsNone(self.schedule.find(self.videos[0]))

    def test_already_scheduled_video_is_not_posted_twice(self):
        self.schedule.upsert({"video_path": self.videos[0], "status": "scheduled", "slot": "2026-11-03T08:00"})
        updates = self._run([PostTask(1, self.videos[0], "cap", "p", source_url="p")], datetime(2026, 11, 2, 9))
        self.assertEqual(updates[-1][1]["message"], "Đã hẹn từ trước")
        self.assertEqual(FakeSession.instances, [])


    def test_delete_after_trashes_only_scheduled_videos(self):
        tasks = [
            PostTask(1, self.videos[0], "cap 1", "ok", source_url="ok"),
            PostTask(2, self.videos[1], "cap 2", "hong", source_url="hong"),
        ]
        updates = self._run(tasks, datetime(2026, 11, 2, 9), delete_after=True)
        self.assertEqual(self.trashed, [self.videos[0]])
        self.assertIn("Thùng rác", [s for i, s in updates if i == 1][-1]["message"])
        self.assertTrue(self.schedule.find(self.videos[0])["deleted"])

    def test_delete_after_also_trashes_video_scheduled_earlier(self):
        self.schedule.upsert({"video_path": self.videos[0], "status": "scheduled", "slot": "2026-11-04T08:00"})
        self._run([PostTask(1, self.videos[0], "cap", "p", source_url="p")], datetime(2026, 11, 2, 9), delete_after=True)
        self.assertEqual(self.trashed, [self.videos[0]])

    def test_unverified_post_keeps_slot_and_file(self):
        tasks = [
            PostTask(1, self.videos[0], "caption video mờ ám số một", "mo", source_url="mo"),
            PostTask(2, self.videos[1], "caption video bình thường số hai", "ok", source_url="ok"),
        ]
        updates = self._run(tasks, datetime(2026, 11, 2, 9), delete_after=True)
        final = {i: s for i, s in updates if s["status"] in {"scheduled", "unverified"}}
        self.assertEqual(final[1]["status"], "unverified")
        self.assertEqual(final[1]["slot"], "2026-11-02T12:00")
        self.assertEqual(final[2]["slot"], "2026-11-02T18:00")  # không hẹn trùng 12:00
        self.assertEqual(self.trashed, [self.videos[1]])  # bài chưa xác nhận giữ lại file
        self.assertEqual(self.schedule.find(self.videos[0])["status"], "unverified")
        self.assertEqual(self.schedule.last_slot(), datetime(2026, 11, 2, 18))

    def test_unverified_post_found_on_studio_next_run_is_confirmed(self):
        caption = "caption bài lần trước chưa xác nhận được"
        self.schedule.upsert({"video_path": self.videos[0], "status": "unverified", "slot": "2026-11-05T08:00",
                              "short_name": "Balo Lười"})
        FakeSession.studio_captions = [caption]
        updates = self._run([PostTask(1, self.videos[0], caption, "p", source_url="p")], datetime(2026, 11, 3, 9), delete_after=True)
        self.assertEqual(updates[-1][1]["status"], "scheduled")
        self.assertEqual(updates[-1][1]["slot"], "2026-11-05T08:00")
        self.assertEqual(self.schedule.find(self.videos[0])["status"], "scheduled")
        self.assertEqual(self.trashed, [self.videos[0]])
        self.assertEqual(FakeSession.instances[0].calls, [])

    def test_no_pause_after_last_post_but_pause_between_posts(self):
        import time as _time

        waits = []
        cancel = __import__("threading").Event()
        cancel.wait = lambda t=None: waits.append(t) or False
        with patch("src.tiktok_poster.datetime") as dt, patch("src.tiktok_poster.DELAY_BETWEEN_POSTS", (100, 100)):
            dt.now.return_value = datetime(2026, 11, 2, 9)
            worker = PostWorker(
                lambda i, s: None, schedule=self.schedule, session_factory=FakeSession,
                short_namer=lambda name, caption: "x", cancel_event=cancel,
            )
            worker.submit(PostTask(1, self.videos[0], "caption bài thứ nhất nè", "p", source_url="p"))
            worker.submit(PostTask(2, self.videos[1], "caption bài thứ hai nè", "p", source_url="p"))
            started = _time.time()
            worker.finish(timeout=10)
        self.assertLess(_time.time() - started, 5)  # không treo 100 giây sau bài cuối
        self.assertEqual(len(waits), 1)  # chỉ nghỉ 1 lần, giữa bài 1 và bài 2
        self.assertGreater(waits[0], 90)
        self.assertEqual(len(FakeSession.instances[0].calls), 2)

    def test_dry_run_never_trashes(self):
        self._run([PostTask(1, self.videos[0], "cap", "p", source_url="p")], datetime(2026, 11, 2, 9), dry=True, delete_after=True)
        self.assertEqual(self.trashed, [])

    def test_caption_already_on_studio_is_skipped_and_kept(self):
        FakeSession.studio_captions = ["Cứ ngỡ là xà bông thường, ai ngờ cứu cái lưng mụn ngoạn mục vãi chưởng! #panoxyl"]
        task = PostTask(1, self.videos[0], "Cứ ngỡ là xà bông thường, ai ngờ cứu cái lưng mụn ngoạn mục  vãi chưởng! #x", "p", source_url="p")
        updates = self._run([task], datetime(2026, 11, 2, 9), delete_after=True)
        self.assertEqual(updates[-1][1]["status"], "error")
        self.assertIn("trùng", updates[-1][1]["message"])
        self.assertEqual(FakeSession.instances[0].calls, [])
        self.assertEqual(self.trashed, [])


class BacklogHelperTests(unittest.TestCase):
    def test_delay_range_from_env(self):
        from src.showcase import delay_range as showcase_delay_range
        from src.tiktok_poster import delay_range

        with patch.dict("os.environ", {"POST_DELAY_SECONDS": "120-60", "SHOWCASE_DELAY_SECONDS": "abc"}):
            self.assertEqual(delay_range("POST_DELAY_SECONDS", (1, 2)), (60.0, 120.0))
            self.assertEqual(showcase_delay_range("SHOWCASE_DELAY_SECONDS", (40, 90)), (40, 90))
        with patch.dict("os.environ", {}, clear=False):
            self.assertEqual(delay_range("KHONG_CO_BIEN_NAY", (90, 180)), (90, 180))

    def test_caption_from_filename_drops_cut_hashtag(self):
        long_name = "Tưởng mua cái móc khóa trang trí ai ngờ rước luôn bảo bối dặm son siêu kín đáo! Quá êm luôn mấy bà ơi. #mockhoaguong #ke.mp4"
        self.assertEqual(
            caption_from_filename(rf"D:\x\{long_name}"),
            "Tưởng mua cái móc khóa trang trí ai ngờ rước luôn bảo bối dặm son siêu kín đáo! Quá êm luôn mấy bà ơi. #mockhoaguong",
        )
        self.assertEqual(caption_from_filename("Ngắn gọn #a #b.mp4"), "Ngắn gọn #a #b")

    def test_is_duplicate_caption(self):
        self.assertTrue(is_duplicate_caption("Mua nhầm đồ  kiểng ai ngờ", ["x", "Mua nhầm đồ kiểng ai ngờ gió mạnh #a"]))
        self.assertFalse(is_duplicate_caption("Ngắn", ["Ngắn"]))
        self.assertFalse(is_duplicate_caption("", ["", "x"]))

    def test_list_post_backlog_keeps_done_videos_with_files(self):
        import json

        from src.web.job_manager import list_post_backlog

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            keep, gone, posted = tmp / "keep #a.mp4", tmp / "gone.mp4", tmp / "posted.mp4"
            keep.write_bytes(b"x")
            posted.write_bytes(b"x")
            manifest = tmp / "log.json"
            manifest.write_text(json.dumps({"videos": {
                "u1": {"url": "u1", "status": "done", "final_video_path": str(keep), "created_at": "2",
                       "showcase": {"status": "done", "results": [{"product": "SP", "status": "da_co"}]}},
                "u2": {"url": "u2", "status": "done", "final_video_path": str(gone), "created_at": "1"},
                "u3": {"url": "u3", "status": "pending", "final_video_path": str(keep), "created_at": "3"},
                "u4": {"url": "u4", "status": "done", "final_video_path": str(posted), "created_at": "4"},
            }}), encoding="utf-8")
            sched = PostSchedule(tmp / "s.json")
            sched.upsert({"video_path": str(posted), "status": "scheduled", "deleted": True})
            with patch("src.post_schedule.get_default_schedule_path", return_value=tmp / "s.json"):
                items = list_post_backlog(manifest)
        self.assertEqual([it.url for it in items], ["u1"])
        self.assertEqual(items[0].script["caption"], "keep #a")
        self.assertEqual(items[0].showcase["status"], "done")


class JobManagerPostTests(unittest.TestCase):
    def test_mock_job_runs_showcase_then_post(self):
        from src.web.job_manager import JobManager

        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.tiktok_poster.PostSchedule", return_value=PostSchedule(Path(tmp) / "s.json")
        ):
            mgr = JobManager()
            with patch("src.web.job_manager.time.sleep"):
                mgr.create_batch(
                    [{"url": "https://www.tiktok.com/@a/video/1"}],
                    mode="mock",
                    log_file_path=str(Path(tmp) / "log.json"),
                    auto_post=True,
                    auto_showcase=True,
                )
                mgr._thread.join(timeout=10)

            item = mgr.current.items[0]
            self.assertEqual(item.showcase["status"], "done")
            self.assertEqual(item.post["status"], "thu")
            self.assertEqual(item.post["short_name"], "Mock vui")
            self.assertEqual(item.post["product"], "Mock product")

    def _run_mock_job(self, **flags):
        from src.web.job_manager import JobManager

        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.tiktok_poster.PostSchedule", return_value=PostSchedule(Path(tmp) / "s.json")
        ):
            mgr = JobManager()
            with patch("src.web.job_manager.time.sleep"):
                mgr.create_batch(
                    [{"url": "https://www.tiktok.com/@a/video/1"}, {"url": "https://www.tiktok.com/@a/video/2"}],
                    mode="mock",
                    log_file_path=str(Path(tmp) / "log.json"),
                    **flags,
                )
                mgr._thread.join(timeout=10)
            return mgr.current.items

    def test_post_without_showcase_skips_phone_step(self):
        with patch("src.showcase.ShowcaseWorker", side_effect=AssertionError("không được mở Showcase")):
            items = self._run_mock_job(auto_post=True, auto_showcase=False)
        for item in items:
            self.assertIsNone(item.showcase)
            self.assertEqual(item.post["status"], "thu")

    def test_post_and_showcase_both_on_still_chains(self):
        items = self._run_mock_job(auto_post=True, auto_showcase=True)
        self.assertEqual([it.showcase["status"] for it in items], ["done", "done"])
        self.assertEqual([it.post["status"] for it in items], ["thu", "thu"])

    def test_api_requests_accept_post_flags(self):
        from src.web.app import AutoGenRequest, ProfileAiVideoRequest

        self.assertTrue(ProfileAiVideoRequest(profile_url="@a", auto_post=True, post_dry=True).post_dry)
        self.assertFalse(AutoGenRequest(mode="review", items=[{"url": "u"}]).auto_post)


if __name__ == "__main__":
    unittest.main()
