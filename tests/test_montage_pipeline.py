from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import montage_editor
from src.montage_pipeline import validate_montage_inputs


class MontagePipelineTests(unittest.TestCase):
    def test_validate_montage_inputs_requires_two_urls_and_script(self) -> None:
        with self.assertRaisesRegex(ValueError, "ít nhất 2"):
            validate_montage_inputs(["https://example.com/a"], "script")

        with self.assertRaisesRegex(ValueError, "Script TTS"):
            validate_montage_inputs(["https://example.com/a", "https://example.com/b"], "  ")

        urls, script = validate_montage_inputs(
            [" https://example.com/a ", "", "https://example.com/b"],
            "  xin chào  ",
        )
        self.assertEqual(urls, ["https://example.com/a", "https://example.com/b"])
        self.assertEqual(script, "xin chào")

    def test_build_clip_plan_is_deterministic_and_preserves_order(self) -> None:
        durations = {
            "a.mp4": 8.0,
            "b.mp4": 9.0,
            "c.mp4": 7.0,
        }

        def fake_duration(path: Path) -> float:
            return durations[path.name]

        sources = [Path("a.mp4"), Path("b.mp4"), Path("c.mp4")]
        with patch.object(montage_editor, "ffprobe_duration", side_effect=fake_duration):
            first = montage_editor.build_clip_plan(sources, target_duration=13.0, seed=99)
            second = montage_editor.build_clip_plan(sources, target_duration=13.0, seed=99)

        self.assertEqual(first, second)
        self.assertGreaterEqual(sum(clip.duration for clip in first), 12.9)
        self.assertEqual([clip.source_index for clip in first[:3]], [1, 2, 3])
        for clip in first:
            self.assertGreaterEqual(clip.duration, 0.5)
            self.assertLessEqual(clip.duration, 4.0)
            self.assertLessEqual(clip.start + clip.duration, clip.source_duration + 0.05)

    def test_build_clip_plan_rejects_too_few_sources(self) -> None:
        with self.assertRaisesRegex(ValueError, "tối thiểu 2"):
            montage_editor.build_clip_plan([Path("a.mp4")], target_duration=5.0, seed=1)


if __name__ == "__main__":
    unittest.main()
