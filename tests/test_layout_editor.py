"""Unit tests for layout_editor, montage_editor, and video_editor with lower-half overlays (Style 1, 2, 3)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import layout_editor, montage_editor, video_editor


class LayoutEditorTests(unittest.TestCase):
    def test_get_public_assets_validates_existence(self) -> None:
        assets = layout_editor.get_public_assets()
        self.assertTrue(assets.black_bg.exists())
        self.assertTrue(assets.card_bg.exists())
        self.assertTrue(assets.logo.exists())
        self.assertTrue(assets.nhay.exists())
        self.assertEqual(assets.style, "style1")

    def test_get_public_assets_style2(self) -> None:
        assets = layout_editor.get_public_assets(style="style2")
        self.assertTrue(assets.black_bg.exists())
        self.assertTrue(assets.card_bg.exists())
        self.assertTrue(assets.logo.exists())
        self.assertIsNone(assets.nhay)
        self.assertEqual(assets.style, "style2")

    def test_get_public_assets_style3(self) -> None:
        assets = layout_editor.get_public_assets(style="style3")
        self.assertTrue(assets.black_bg.exists())
        self.assertTrue(assets.card_bg.exists())
        self.assertEqual(assets.style, "style3")

    def test_get_public_assets_with_custom_paths(self) -> None:
        default_assets = layout_editor.get_public_assets()
        # Custom logo and card_bg pointing to valid files
        custom = layout_editor.get_public_assets(
            custom_logo=default_assets.logo,
            custom_card_bg=default_assets.card_bg,
        )
        self.assertEqual(custom.logo, default_assets.logo)
        self.assertEqual(custom.card_bg, default_assets.card_bg)

    def test_get_public_assets_raises_file_not_found(self) -> None:
        with TemporaryDirectory() as tmpdir:
            empty_path = Path(tmpdir)
            with self.assertRaises(FileNotFoundError):
                layout_editor.get_public_assets(empty_path)

    def test_prepare_script_text_and_escape(self) -> None:
        raw = "Đi học, đi làm hay mang đi cà phê đều ra vibe rất gọn gàng. % 100: giá tốt!"
        lines, font_size = layout_editor.prepare_script_text(raw)
        self.assertGreater(len(lines), 0)
        self.assertGreaterEqual(font_size, 30)

        escaped = layout_editor.escape_drawtext_text(raw)
        self.assertIn("\\%", escaped)
        self.assertIn("\\:", escaped)

    def test_prepare_style3_script_text(self) -> None:
        raw = "PHÔ MAI QUE KÉO SỢI SIÊU ĐẪM\n---\nĂn cực cuốn, vỏ giòn rụm bên trong ngập ngụa phô mai"
        h_segs, h_size, q_lines, q_size = layout_editor.prepare_style3_script_text(raw)
        self.assertGreater(len(h_segs), 0)
        self.assertGreater(len(q_lines), 0)
        self.assertGreaterEqual(h_size, 30)
        self.assertGreaterEqual(q_size, 20)

    def test_build_complex_filter_graph_contains_expected_filters(self) -> None:
        assets = layout_editor.get_public_assets()
        text = "XIN CHÀO TIKTOK REVIEW DÒNG THỨ HAI"
        fg, meta = layout_editor.build_complex_filter_graph(
            text=text,
            assets=assets,
            video_input_idx=0,
            black_bg_idx=1,
            card_bg_idx=2,
            logo_idx=3,
            nhay_idx=4,
            video_shift_ratio=0.3333,
        )
        self.assertIn("[0:v]scale=1166:2074", fg)
        self.assertIn("[card_mask]", fg)
        self.assertIn("overlay=100:1000[stage3]", fg)
        self.assertIn("drawtext=fontfile=", fg)
        self.assertIn("[outv]", fg)
        self.assertEqual(meta["style"], "style1")

    def test_build_complex_filter_graph_style2_no_nhay(self) -> None:
        assets = layout_editor.get_public_assets(style="style2")
        text = "XIN CHÀO STYLE 2"
        fg, meta = layout_editor.build_complex_filter_graph(
            text=text,
            assets=assets,
            video_input_idx=0,
            black_bg_idx=1,
            card_bg_idx=2,
            logo_idx=3,
            nhay_idx=None,
        )
        self.assertNotIn("nhay", fg)
        self.assertIn("crop=408:171:46:148", fg)
        self.assertIn("overlay=409:1019[stage4]", fg)
        self.assertIn("[outv]", fg)
        self.assertEqual(meta["style"], "style2")

    def test_build_complex_filter_graph_style3(self) -> None:
        assets = layout_editor.get_public_assets(style="style3")
        text = "TIÊU ĐỀ STYLE 3\n---\nTrích dẫn đánh giá cực kỳ hấp dẫn"
        fg, meta = layout_editor.build_complex_filter_graph(
            text=text,
            assets=assets,
            video_input_idx=0,
            black_bg_idx=1,
            card_bg_idx=2,
            video_shift_ratio=0.3333,
        )
        self.assertIn("overlay=0:800[stage_bg]", fg)
        self.assertIn("141414", fg)  # Dark charcoal headline color
        self.assertIn("BA3846", fg)  # Pink accent quote color
        self.assertIn("[outv]", fg)
        self.assertEqual(meta["style"], "style3")

    def test_compute_video_geometry(self) -> None:
        zoomed_w, zoomed_h, center_x, overlay_y = layout_editor.compute_video_geometry(
            video_scale=1.08, video_shift_ratio=0.3333
        )
        self.assertEqual(zoomed_w, 1166)
        self.assertEqual(zoomed_h, 2074)
        self.assertEqual(center_x, -43)
        self.assertEqual(overlay_y, -768)

    def test_invalid_ratio_raises_value_error(self) -> None:
        assets = layout_editor.get_public_assets()
        with self.assertRaises(ValueError) as ctx:
            layout_editor.build_complex_filter_graph(
                text="TEST",
                assets=assets,
                video_shift_ratio=1.5,
            )
        self.assertIn("0.0 and 1.0", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
