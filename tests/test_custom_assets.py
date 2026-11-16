import unittest
import os
from tempfile import TemporaryDirectory
from pathlib import Path
from PIL import Image
from src.layout_editor import get_public_assets, build_complex_filter_graph
from src.env_persistence import build_ui_settings, apply_updates, save_env, load_env
from config import settings

class CustomAssetsTests(unittest.TestCase):
    def test_custom_assets_override_and_fallback(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            
            # create custom dummy image
            custom_logo = tmp / "custom_logo.png"
            img = Image.new("RGBA", (200, 200), (255, 0, 0, 255))
            img.save(custom_logo)
            
            # 1. Custom logo passed as param
            assets = get_public_assets(custom_logo=str(custom_logo))
            self.assertEqual(Path(assets.logo).resolve(), custom_logo.resolve())
            self.assertTrue(Path(assets.card_bg).exists())
            self.assertTrue(Path(assets.nhay).exists())
            
            # 2. Custom logo via environment variable style1
            os.environ["CUSTOM_STYLE1_LOGO_PATH"] = str(custom_logo)
            try:
                assets_env = get_public_assets(style="style1")
                self.assertEqual(Path(assets_env.logo).resolve(), custom_logo.resolve())
            finally:
                del os.environ["CUSTOM_STYLE1_LOGO_PATH"]

    def test_style2_and_style3_custom_assets(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            
            logo1 = tmp / "logo1.png"
            logo2 = tmp / "logo2.png"
            bg3 = tmp / "bg3.png"
            Image.new("RGBA", (100, 100), (255, 0, 0, 255)).save(logo1)
            Image.new("RGBA", (100, 100), (0, 255, 0, 255)).save(logo2)
            Image.new("RGBA", (100, 100), (255, 192, 203, 255)).save(bg3)
            
            os.environ["CUSTOM_STYLE1_LOGO_PATH"] = str(logo1)
            os.environ["CUSTOM_STYLE2_LOGO_PATH"] = str(logo2)
            os.environ["CUSTOM_STYLE3_CARD_BG_PATH"] = str(bg3)
            try:
                assets_s1 = get_public_assets(style="style1")
                assets_s2 = get_public_assets(style="style2")
                assets_s3 = get_public_assets(style="style3")
                
                self.assertEqual(Path(assets_s1.logo).resolve(), logo1.resolve())
                self.assertEqual(Path(assets_s2.logo).resolve(), logo2.resolve())
                self.assertEqual(Path(assets_s3.card_bg).resolve(), bg3.resolve())
            finally:
                del os.environ["CUSTOM_STYLE1_LOGO_PATH"]
                del os.environ["CUSTOM_STYLE2_LOGO_PATH"]
                del os.environ["CUSTOM_STYLE3_CARD_BG_PATH"]
                
    def test_env_persistence_style_assets(self):
        with TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("CUSTOM_STYLE1_LOGO_PATH=dummy1.png\n", encoding="utf-8")
            
            updates = {
                "CUSTOM_STYLE1_LOGO_PATH": "path/to/style1/logo.png",
                "CUSTOM_STYLE2_LOGO_PATH": "path/to/style2/logo.png",
                "CUSTOM_STYLE2_CARD_BG_PATH": "path/to/style2/bg.jpg",
                "CUSTOM_STYLE3_CARD_BG_PATH": "path/to/style3/bg.png",
            }
            # Snapshot environment before testing
            old_s1 = os.environ.get("CUSTOM_STYLE1_LOGO_PATH")
            old_s2 = os.environ.get("CUSTOM_STYLE2_LOGO_PATH")
            old_s2_bg = os.environ.get("CUSTOM_STYLE2_CARD_BG_PATH")
            old_s3_bg = os.environ.get("CUSTOM_STYLE3_CARD_BG_PATH")
            try:
                res = apply_updates(updates, path=env_file)
                self.assertEqual(len(res), 4)
                
                loaded = load_env(env_file)
                self.assertEqual(loaded.get("CUSTOM_STYLE1_LOGO_PATH"), "path/to/style1/logo.png")
                self.assertEqual(loaded.get("CUSTOM_STYLE2_LOGO_PATH"), "path/to/style2/logo.png")
                self.assertEqual(loaded.get("CUSTOM_STYLE2_CARD_BG_PATH"), "path/to/style2/bg.jpg")
                self.assertEqual(loaded.get("CUSTOM_STYLE3_CARD_BG_PATH"), "path/to/style3/bg.png")
            finally:
                for k, v in [
                    ("CUSTOM_STYLE1_LOGO_PATH", old_s1),
                    ("CUSTOM_STYLE2_LOGO_PATH", old_s2),
                    ("CUSTOM_STYLE2_CARD_BG_PATH", old_s2_bg),
                    ("CUSTOM_STYLE3_CARD_BG_PATH", old_s3_bg),
                ]:
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    def test_build_complex_filter_graph_with_custom_logo(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            custom_logo = tmp / "my_brand_logo.png"
            img = Image.new("RGBA", (300, 150), (0, 255, 0, 255))
            img.save(custom_logo)
            
            assets = get_public_assets(custom_logo=str(custom_logo))
            self.assertEqual(Path(assets.logo).resolve(), custom_logo.resolve())
            fg, meta = build_complex_filter_graph(
                text="TEST LINE 1 LINE 2",
                assets=assets,
                video_scale=1.08,
                video_shift_ratio=0.3333,
            )
            self.assertIn("[3:v]", fg)

if __name__ == "__main__":
    unittest.main()
