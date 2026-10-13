"""Real Pillow reference-image checks. No network, credentials or USB access."""
import base64
import io
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, features

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import ai_images as images
import bridge


def encoded(image, format="PNG", **options):
    output = io.BytesIO()
    image.save(output, format, **options)
    return output.getvalue()


def unpack(result):
    prefix = "data:image/jpeg;base64,"
    if not result["dataUrl"].startswith(prefix):
        raise AssertionError("Not a normalized JPEG data URL")
    raw = base64.b64decode(result["dataUrl"][len(prefix):], validate=True)
    image = Image.open(io.BytesIO(raw))
    image.load()
    return image, raw


class ReferenceImageChecks(unittest.TestCase):
    def test_transparency_flattens_to_white_in_real_jpeg(self):
        source = Image.new("RGBA", (32, 16), (0, 0, 0, 0))
        source.paste((255, 0, 0, 128), (16, 0, 32, 16))
        result = images.normalize(encoded(source))
        normalized, _ = unpack(result)
        self.assertEqual(normalized.mode, "RGB")
        self.assertTrue(all(channel >= 245 for channel in normalized.getpixel((4, 8))))
        red, green, blue = normalized.getpixel((26, 8))
        self.assertGreater(red, 245)
        self.assertTrue(120 <= green <= 135)
        self.assertTrue(120 <= blue <= 135)

    def test_exif_orientation_applied_and_exif_gps_icc_stripped(self):
        source = Image.new("RGB", (40, 20), "red")
        source.paste("blue", (20, 0, 40, 20))
        exif = Image.Exif()
        exif[274] = 6  # Rotate 90 degrees clockwise when displayed.
        exif[270] = "private-source-description"
        exif[34853] = {1: "N", 2: (22.0, 30.0, 0.0), 3: "E", 4: (114.0, 0.0, 0.0)}
        raw = encoded(source, "JPEG", exif=exif, icc_profile=b"private-icc-profile")
        original = Image.open(io.BytesIO(raw))
        self.assertTrue(original.getexif().get_ifd(34853))
        result = images.normalize(raw, "/private/source/folder/image.jpg")
        normalized, normalized_raw = unpack(result)
        self.assertEqual((result["width"], result["height"]), (20, 40))
        self.assertEqual(normalized.size, (20, 40))
        self.assertEqual(len(normalized.getexif()), 0)
        self.assertNotIn("icc_profile", normalized.info)
        self.assertNotIn(b"private-source-description", normalized_raw)
        self.assertNotIn(b"private-icc-profile", normalized_raw)
        self.assertGreater(normalized.getpixel((10, 5))[0], 200)
        self.assertGreater(normalized.getpixel((10, 35))[2], 200)

    def test_resize_preserves_aspect_ratio_and_longest_side_limit(self):
        result = images.normalize(encoded(Image.new("RGB", (2560, 1280), "#24DDFC")))
        normalized, raw = unpack(result)
        self.assertEqual(normalized.size, (1280, 640))
        self.assertEqual((result["width"], result["height"]), normalized.size)
        self.assertLessEqual(len(raw), 400 * 1024)

    def test_high_entropy_image_is_recompressed_under_output_budget(self):
        random_bytes = random.Random(917).randbytes(1400 * 1400 * 3)
        source = Image.frombytes("RGB", (1400, 1400), random_bytes)
        raw = encoded(source)
        self.assertGreater(len(raw), images.MAX_IMAGE_BYTES)
        result = images.normalize(raw)
        normalized, normalized_raw = unpack(result)
        self.assertLessEqual(len(normalized_raw), 400 * 1024)
        self.assertLessEqual(max(normalized.size), 1280)
        self.assertNotEqual(normalized.getpixel((10, 10)), normalized.getpixel((20, 20)))

    def test_png_jpeg_webp_are_decoded_by_pillow_and_reencoded_jpeg(self):
        formats = ["PNG", "JPEG"]
        if features.check("webp"):
            formats.append("WEBP")
        else:
            self.fail("This packaged Pillow runtime must support WebP reference images")
        for format in formats:
            with self.subTest(format=format):
                raw = encoded(Image.new("RGB", (24, 12), "#24DDFC"), format)
                result = images.normalize(raw)
                normalized, _ = unpack(result)
                self.assertEqual(normalized.format, "JPEG")
                self.assertEqual(normalized.size, (24, 12))
                self.assertGreater(normalized.getpixel((12, 6))[1], 200)

    def test_animated_gif_uses_only_first_frame(self):
        first = Image.new("RGB", (24, 12), "red")
        second = Image.new("RGB", (24, 12), "blue")
        raw = encoded(first, "GIF", save_all=True, append_images=[second], duration=40, loop=0)
        original = Image.open(io.BytesIO(raw))
        self.assertEqual(original.n_frames, 2)
        result = images.normalize(raw)
        normalized, _ = unpack(result)
        self.assertEqual(getattr(normalized, "n_frames", 1), 1)
        red, green, blue = normalized.getpixel((12, 6))
        self.assertGreater(red, 240)
        self.assertLess(blue, 20)

    def test_corrupt_unrecognized_empty_and_unsupported_images_rejected(self):
        bmp = encoded(Image.new("RGB", (4, 4), "white"), "BMP")
        for raw in (b"", b"not an image", b"\xff\xd8\xff\xe0broken", bmp, "not bytes", bytearray(b"bytes")):
            with self.subTest(type=type(raw).__name__):
                with self.assertRaises(images.ImageError):
                    images.normalize(raw)

    def test_source_bytes_limit_is_checked_before_decoder(self):
        raw = b"x" * (images.MAX_SOURCE_BYTES + 1)
        with patch.object(images.Image, "open", side_effect=AssertionError("oversize was decoded")):
            with self.assertRaises(images.ImageError) as context:
                images.normalize(raw)
        self.assertIn("20 MB", str(context.exception))

    def test_source_pixel_limit_is_checked_before_decompression(self):
        # A real monochrome PNG needs only about 4 MiB uncompressed while its
        # declared pixel count crosses the 32 Mi-pixel input cap.
        raw = encoded(Image.new("1", (8192, 4097), 0))
        self.assertLess(len(raw), images.MAX_SOURCE_BYTES)
        with self.assertRaises(images.ImageError) as context:
            images.normalize(raw)
        self.assertIn("分辨率过大", str(context.exception))

    def test_pillow_decompression_bomb_warning_is_a_rejection(self):
        raw = encoded(Image.new("RGB", (16, 16), "white"))
        with patch.object(Image, "MAX_IMAGE_PIXELS", 100):
            with self.assertRaises(images.ImageError):
                images.normalize(raw)

    def test_payload_rejects_remote_file_svg_bad_base64_and_oversize(self):
        for url in ("https://example.com/photo.jpg", "file:///private/photo.jpg",
                    "data:image/svg+xml;base64,PHN2Zz4=", "data:image/png;base64,eA==",
                    "data:image/jpeg;base64,!!!!", "data:image/jpeg;base64,eA==\n",
                    "data:image/jpeg;base64," + "A" * 560000):
            with self.subTest(prefix=url[:32]):
                with self.assertRaises(images.ImageError):
                    images.from_payload([{"dataUrl": url}])
        encoded_oversize = "data:image/jpeg;base64," + base64.b64encode(b"x" * (images.MAX_IMAGE_BYTES + 1)).decode()
        with self.assertRaises(images.ImageError):
            images.from_payload([{"dataUrl": encoded_oversize}])

    def test_payload_image_number_and_structure_are_bounded(self):
        self.assertEqual(images.from_payload(None), [])
        self.assertEqual(images.from_payload([]), [])
        for value in ([{}] * 4, "image", {}, [None], [{"dataUrl": None}]):
            with self.assertRaises(images.ImageError):
                images.from_payload(value)
        result = images.normalize(encoded(Image.new("RGB", (8, 8), "white")))
        self.assertEqual(len(images.from_payload([result] * 3)), 3)

    def test_frontend_metadata_and_dimensions_are_discarded(self):
        safe = images.normalize(encoded(Image.new("RGB", (8, 6), "white")), "image.jpg")
        safe.update({"width": 2 ** 60, "height": -5, "path": "/private/credentials", "exif": "private-meta"})
        result = images.from_payload([safe])[0]
        self.assertEqual((result["width"], result["height"]), (8, 6))
        self.assertEqual(set(result), {"name", "dataUrl", "width", "height"})
        self.assertNotIn("private", json.dumps(result))

    def test_normalize_stays_in_memory_and_source_is_unchanged(self):
        raw = encoded(Image.new("RGBA", (8, 6), (255, 0, 0, 128)))
        snapshot = bytes(raw)
        with patch.object(Path, "open", side_effect=AssertionError("normalize accessed filesystem")), \
             patch.object(Path, "write_bytes", side_effect=AssertionError("normalize wrote a file")), \
             patch.object(Path, "write_text", side_effect=AssertionError("normalize wrote a file")):
            result = images.normalize(raw)
        self.assertEqual(raw, snapshot)
        self.assertEqual((result["width"], result["height"]), (8, 6))

    def test_paths_expose_only_basename_and_preserve_original_files(self):
        with tempfile.TemporaryDirectory(prefix="studio-private-image-") as tmp:
            directory = Path(tmp) / "private-folder"
            directory.mkdir()
            source = directory / "参考图.png"
            raw = encoded(Image.new("RGBA", (8, 6), (255, 0, 0, 128)))
            source.write_bytes(raw)
            before_mtime = source.stat().st_mtime_ns
            before_files = set(Path(tmp).rglob("*"))
            result = images.from_paths([str(source)])
            self.assertEqual(result["images"][0]["name"], "参考图.png")
            self.assertNotIn("private-folder", json.dumps(result))
            self.assertNotIn(tmp, json.dumps(result))
            self.assertEqual(source.read_bytes(), raw)
            self.assertEqual(source.stat().st_mtime_ns, before_mtime)
            self.assertEqual(set(Path(tmp).rglob("*")), before_files)

    def test_paths_reject_nonabsolute_missing_directories_and_overlimits(self):
        for paths in (None, [], ["relative.png"], [None], ["/private/not-existing-reference.jpg"], ["/private/tmp"],
                      ["/private/file.jpg"] * 4):
            with self.assertRaises(images.ImageError):
                images.from_paths(paths)
        with tempfile.TemporaryDirectory() as tmp:
            oversized = Path(tmp) / "large.jpg"
            with oversized.open("wb") as stream:
                stream.truncate(images.MAX_SOURCE_BYTES + 1)
            with self.assertRaises(images.ImageError):
                images.from_paths([str(oversized)])

    def test_bridge_preparation_never_queries_device_or_creates_state(self):
        class NoDeviceAccess(dict):
            def __getitem__(self, key):
                raise AssertionError("Image preparation accessed device/CLI: " + str(key))

        with tempfile.TemporaryDirectory(prefix="studio-image-bridge-") as tmp:
            directory = Path(tmp)
            source = directory / "picture.png"
            source.write_bytes(encoded(Image.new("RGB", (8, 6), "#24DDFC")))
            state = directory / "app-state"
            events = []
            backend = bridge.Bridge(state, directory, cli=NoDeviceAccess(), cli_version="offline", event_sink=events.append)
            result = backend.prepareAIImages({"paths": [str(source)]})
            self.assertEqual(len(result["images"]), 1)
            self.assertFalse(state.exists())
            self.assertEqual(events, [])
            with self.assertRaises(bridge.BridgeError) as context:
                backend.prepareAIImages({"paths": ["relative.jpg"]})
            self.assertEqual(context.exception.code, "ai_image_invalid")
            self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
