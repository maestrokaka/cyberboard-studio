#!/usr/bin/env python3
"""Render public built-in JSON as full-timing, exact-RGB GitHub GIF previews.

Reads only data/preset-catalog.json, its public data/designs entries, and the
public front-view key geometry. It never opens a user workspace, key, or USB.
Requires Pillow. Example: python scripts/build-preset-gifs.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, __version__ as PILLOW_VERSION


ROOT = Path(__file__).resolve().parents[1]
SIZE = (640, 400)
BACKGROUND = (15, 18, 21)
SHELL = (23, 27, 32)
BORDER = (46, 52, 60)
KEY_FACE = (8, 10, 12)
OFF = (0, 0, 0)
HEX = re.compile(r"#[0-9A-Fa-f]{6}\Z")
RESERVED = {57, 61, 74, 78, 82, 83, 84}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def rgb(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ValueError(f"Invalid RGB value: {value!r}")
    return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))


def key_geometry():
    """Keep the real key gaps and separate all three LEDs under Space."""
    geometry = load(ROOT / "data/photos/key-photo-layout.json")["views"]["front"]
    indices = {key["index"] for key in geometry}
    if len(geometry) != 83 or indices != set(range(90)) - RESERVED:
        raise ValueError("Expected 83 physical LEDs and seven reserved indices")
    # Public photo annotations become a flat schematic, not a hardware model.
    left, top, scale = 41.0, 154.0, 0.496
    result = []
    for key in geometry:
        quad = key["quad"]
        x0 = min(point[0] for point in quad)
        x1 = max(point[0] for point in quad)
        y0 = min(point[1] for point in quad)
        y1 = max(point[1] for point in quad)
        u, v = key["lamp_uv"]
        box = tuple(round(value) for value in (
            left + (x0 - 274) * scale,
            top + (y0 - 405) * scale,
            left + (x1 - 274) * scale,
            top + (y1 - 405) * scale,
        ))
        cx = round(left + (x0 + u * (x1 - x0) - 274) * scale)
        # Center the LED patch inside each flat key outline for legibility.
        cy = round(top + ((y0 + y1) / 2 - 405) * scale)
        half_width = 10 if key["index"] in (79, 80, 81) else min(12, (box[2] - box[0] - 8) // 2)
        led_box = (cx - half_width, cy - 6, cx + half_width, cy + 6)
        result.append((key["index"], box, led_box))
    return result


def render(top_frame, key_frame, geometry) -> Image.Image:
    # Build an exact local GIF palette, then draw by explicit color index.
    # Image.quantize(palette=...) can approximate close RGBs through its cache;
    # direct indices avoid even that small, unnecessary color change.
    colors = sorted({BACKGROUND, SHELL, BORDER, KEY_FACE, OFF}
                    | {rgb(value) for value in top_frame + key_frame})
    if len(colors) > 256:
        raise ValueError(f"Frame has {len(colors)} colors; GIF allows 256. Use an explicit quantization workflow.")
    indices = {color: index for index, color in enumerate(colors)}
    image = Image.new("P", SIZE, indices[BACKGROUND])
    padded = colors + [colors[0]] * (256 - len(colors))
    image.putpalette([channel for color in padded for channel in color])
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24, 18, 615, 127), radius=10, fill=indices[SHELL], outline=indices[BORDER], width=1)
    draw.rounded_rectangle((33, 26, 606, 118), radius=5, fill=indices[OFF])
    for index, value in enumerate(top_frame):
        x, y = 41 + index % 40 * 14, 38 + index // 40 * 14
        draw.rectangle((x, y, x + 11, y + 11), fill=indices[rgb(value)])
    draw.rounded_rectangle((24, 142, 615, 375), radius=10, fill=indices[SHELL], outline=indices[BORDER], width=1)
    outlined = set()
    for index, box, led_box in geometry:
        if box not in outlined:
            draw.rounded_rectangle((box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1),
                                   radius=3, fill=indices[KEY_FACE], outline=indices[BORDER], width=1)
            outlined.add(box)
        draw.rounded_rectangle(led_box, radius=2, fill=indices[rgb(key_frame[index])])
    decoded = image.convert("RGB")
    for index, value in enumerate(top_frame):
        if decoded.getpixel((46 + index % 40 * 14, 43 + index // 40 * 14)) != rgb(value):
            raise AssertionError("Top LED schematic did not preserve a source RGB")
    for index, _, box in geometry:
        if decoded.getpixel(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)) != rgb(key_frame[index]):
            raise AssertionError("Key LED schematic did not preserve a source RGB")
    return image


def validate_design(design):
    frames, keys = design["frames"], design["keyframes"]
    count = len(frames)
    if not 1 <= count <= 255 or design["frame_count"] != count or len(keys) != count:
        raise ValueError("Invalid frame count")
    duration = design["speed_ms"]
    if type(duration) is not int or duration < 10 or duration % 10:
        raise ValueError("Exact GIF timing requires a positive multiple of 10 ms")
    for top, key in zip(frames, keys):
        if len(top) != 200 or len(key) != 90:
            raise ValueError("Expected 200 top LEDs and 90 key entries")
        for value in top + key:
            rgb(value)
        if any(rgb(key[index]) != OFF for index in RESERVED):
            raise ValueError("Reserved key entries must remain black")


def verify_gif(path: Path, images, duration: int):
    expected = [sha256(frame.convert("RGB").tobytes()) for frame in images]
    ticks, decoded, timeline = 0, 0, []
    with Image.open(path) as image:
        if image.size != SIZE or image.info.get("loop") != 0:
            raise AssertionError("GIF must use fixed dimensions and loop forever")
        for frame_index in range(image.n_frames):
            image.seek(frame_index)
            frame_duration = image.info.get("duration", 0)
            if not frame_duration or frame_duration % duration:
                raise AssertionError("GIF lost the source frame timing")
            digest = sha256(image.convert("RGB").tobytes())
            repeats = frame_duration // duration
            if expected[ticks : ticks + repeats] != [digest] * repeats:
                raise AssertionError(f"Decoded GIF differs from source at tick {ticks}")
            timeline.append(frame_duration)
            ticks += repeats
            decoded += 1
    if ticks != len(images) or sum(timeline) != len(images) * duration:
        raise AssertionError("GIF omitted source ticks")
    return decoded, timeline


def build(entry, output: Path, geometry, check_only: bool):
    filename = entry["file"]
    if Path(filename).name != filename or not filename.endswith(".design.json"):
        raise ValueError("Preset catalog must contain simple .design.json filenames")
    source = ROOT / "data/designs" / filename
    design = load(source)
    validate_design(design)
    slug = filename.removesuffix(".design.json")
    destination = output / f"{slug}.gif"
    images = [render(top, keys, geometry)
              for top, keys in zip(design["frames"], design["keyframes"])]
    speed = design["speed_ms"]
    if not check_only:
        images[0].save(destination, save_all=True, append_images=images[1:],
                       duration=[speed] * len(images), loop=0, optimize=False,
                       disposal=1, comment=b"Cyberboard Studio | original RGB and complete original timing | schematic, not hardware color calibration")
    decoded, timeline = verify_gif(destination, images, speed)
    row = {
        "id": design["id"], "name": design["name"],
        "source": f"data/designs/{filename}", "source_sha256": sha256(source.read_bytes()),
        "gif": destination.name, "gif_sha256": sha256(destination.read_bytes()),
        "bytes": destination.stat().st_size, "dimensions": list(SIZE),
        "source_frames": len(images), "decoded_frames": decoded,
        "source_frame_ms": speed, "total_duration_ms": sum(timeline),
        "loop": 0, "rgb_quantization": "none; every decoded frame matches original RGB schematic exactly",
        "timing_check": "every source tick matched; identical GIF frames may be merged without dropping duration",
    }
    print(f"{destination.name}: {decoded}/{len(images)} decoded/source frames, {sum(timeline)} ms, {row['bytes']:,} bytes, exact RGB", flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/previews")
    parser.add_argument("--only", nargs="+", help="Explicit filename slugs from the public preset catalog")
    parser.add_argument("--check-only", action="store_true", help="Verify existing GIFs without overwriting them")
    args = parser.parse_args()
    catalog_path = ROOT / "data/preset-catalog.json"
    catalog = load(catalog_path)
    if catalog.get("schema_version") != 1:
        raise ValueError("Unsupported preset catalog schema")
    works = catalog["works"]
    if args.only:
        wanted = set(args.only)
        works = [entry for entry in works if entry["file"].removesuffix(".design.json") in wanted]
        if len(works) != len(wanted):
            raise ValueError("Every requested slug must occur exactly once in the main preset catalog")
    if not works:
        raise ValueError("No presets selected")
    output = args.output.resolve()
    if not args.check_only:
        output.mkdir(parents=True, exist_ok=True)
    geometry = key_geometry()
    previews = [build(entry, output, geometry, args.check_only) for entry in works]
    if len({row["id"] for row in previews}) != len(previews):
        raise ValueError("Duplicate preset IDs")
    manifest = {
        "schema_version": 1,
        "renderer": "scripts/build-preset-gifs.py", "pillow_version": PILLOW_VERSION,
        "rendering": "40 x 5 top LEDs plus 83 physical key LED positions, including three Space LEDs; flat schematic, no gain, glow, white cores, or recoloring",
        "geometry_source": "data/photos/key-photo-layout.json",
        "geometry_sha256": sha256((ROOT / "data/photos/key-photo-layout.json").read_bytes()),
        "display_limit": "Screen RGB preview; not a physical color or brightness calibration",
        "previews": previews,
    }
    if args.check_only:
        current = load(output / "manifest.json")
        if current != manifest:
            raise AssertionError("Manifest differs from current public sources or verified GIFs")
    else:
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
