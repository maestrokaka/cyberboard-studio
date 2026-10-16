#!/usr/bin/env python3
"""Offline GIF regressions: fixed palette, static photo detail and tick integrity."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("preset_gifs", ROOT / "scripts/build-preset-gifs.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PhotoGifTests(unittest.TestCase):
    def fixture(self, directory):
        # A detailed static body with one lamp that returns to its initial color.
        # The return must not incorrectly classify that lamp as always static.
        colors = [(255, 0, 0), (0, 255, 0), (255, 0, 0), (255, 0, 0)]
        records = []
        for tick, color in enumerate(colors):
            frame = Image.new("RGB", (32, 18))
            frame.putdata([(20 + x * 3, 25 + y * 5, 30 + x + y)
                           for y in range(18) for x in range(32)])
            frame.putpixel((12, 8), color)
            file = f"frame-{tick:04d}.png"
            frame.save(directory / file)
            records.append({"file": file, "tick": tick})
        design = {"palette": ["#FF0000", "#00FF00"],
                  "frames": [["#FF0000"]], "keyframes": [["#00FF00"]]}
        return {"width": 32, "height": 18, "frames": records}, design

    def test_static_body_fixed_and_returning_lamp_dynamic(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest, design = self.fixture(directory)
            images, palette, reserved, details = module.quantize_frames(directory, manifest, design)
            self.assertEqual(len(palette), 768)
            self.assertEqual(details["dynamic_pixels"], 1)
            self.assertEqual(details["static_photo_pixels"], 32 * 18 - 1)
            self.assertEqual(details["dynamic_dither"], "none")
            self.assertIn((255, 0, 0), reserved)
            self.assertIn((0, 255, 0), reserved)
            first, second = images[0].convert("RGB"), images[1].convert("RGB")
            self.assertEqual(first.getpixel((12, 8)), (255, 0, 0))
            self.assertEqual(second.getpixel((12, 8)), (0, 255, 0))
            self.assertEqual(ImageChops.difference(first, second).getbbox(), (12, 8, 13, 9))
            self.assertEqual(images[0].tobytes(), images[2].tobytes())
            module.static_pixel_check(directory, manifest, images)
            path = directory / "test.gif"
            decoded, timeline = module.save_gif(path, images, palette, 20)
            self.assertLessEqual(decoded, len(images))  # Identical ticks may merge.
            self.assertEqual(sum(timeline), 80)
            module.verify_palette(path, palette)
            # The decoder must reject either missing timing or wrong RGB.
            with self.assertRaises(AssertionError):
                module.verify_gif(path, images[:-1], 20)
            wrong = [frame.copy() for frame in images]
            wrong[1].putpixel((0, 0), 0 if wrong[1].getpixel((0, 0)) else 1)
            with self.assertRaises(AssertionError):
                module.verify_gif(path, wrong, 20)
            with self.assertRaises(AssertionError):
                module.verify_palette(path, bytes(reversed(palette)))

    def test_full_lcm_timing_and_reserved_entries(self):
        design = {"frame_count": 2, "speed_ms": 20,
                  "frames": [["#000000"] * 200 for _ in range(2)],
                  "keyframes": [["#000000"] * 90 for _ in range(3)]}
        module.validate_design(design)  # Unequal streams are a full LCM loop.
        broken = copy.deepcopy(design)
        broken["keyframes"][1][83] = "#FF0000"
        with self.assertRaises(ValueError):
            module.validate_design(broken)
        broken = copy.deepcopy(design)
        broken["speed_ms"] = 25
        with self.assertRaises(ValueError):
            module.validate_design(broken)  # Never silently round GIF timing.

    def test_public_paths_reject_local_and_traversal(self):
        for value in ("/Users/private/key", "../key", "web/../../key", "C:\\private\\key"):
            with self.assertRaises(ValueError):
                module.public_path(value)
        self.assertEqual(module.public_path("web/preview-engine.js"), ROOT / "web/preview-engine.js")


if __name__ == "__main__":
    unittest.main(verbosity=2)
