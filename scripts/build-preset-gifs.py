#!/usr/bin/env python3
"""Build full-speed GIFs with the App's public keyboard-photo preview.

Only public preset/photo/preview resources are read. Node renders RGB PNGs under
ignored build/. One fixed palette is used per GIF. Full-cycle static photo pixels
share one deterministic dithered base; changing lamps are quantized without dither.
GIF RGB is quantized: this is a screen preview, not physical color calibration.
Requires Pillow, Node and offline @napi-rs/canvas. Example:
python scripts/build-preset-gifs.py --only neon-rift --output build/photo-gif-trial
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from PIL import Image, ImageChops, __version__ as PILLOW_VERSION

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "scripts/render-preset-photo-frames.cjs"
HEX = re.compile(r"#[0-9A-Fa-f]{6}\Z")
RESERVED = {57, 61, 74, 78, 82, 83, 84}
OFF, BACKGROUND = (0, 0, 0), (15, 18, 21)
PALETTE_METHOD = "fixed-256-static-photo128-dynamic95-feature32-static-dither-v4"
HASH_FIELDS = {
    "engineSha256": "web/preview-engine.js",
    "adapterSha256": "scripts/render-preset-photo-frames.cjs",
    "modelSha256": "web/studio-model.js",
    "dataSha256": "web/data.js",
    "calibrationSha256": "data/photos/photo-calibration.json",
    "keyCalibrationSha256": "data/photos/key-photo-layout.json",
}

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def rgb(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ValueError(f"Invalid RGB value: {value!r}")
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))

def public_path(value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or Path(value).is_absolute():
        raise ValueError("Expected repository-relative public source")
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT) or ".." in Path(value).parts:
        raise ValueError("Source escaped public repository")
    return path

def validate_design(design):
    frames, keys = design["frames"], design["keyframes"]
    if not 1 <= len(frames) <= 255 or design["frame_count"] != len(frames) or not 1 <= len(keys) <= 255:
        raise ValueError("Invalid top/key frame count")
    speed = design["speed_ms"]
    if type(speed) is not int or not 10 <= speed <= 32767 or speed % 10:
        raise ValueError("Exact GIF timing requires a positive multiple of 10 ms")
    for stream, length in ((frames, 200), (keys, 90)):
        for frame in stream:
            if len(frame) != length:
                raise ValueError("Expected 200 top LEDs and 90 key entries")
            for value in frame:
                rgb(value)
    if any(rgb(frame[index]) != OFF for frame in keys for index in RESERVED):
        raise ValueError("Reserved key entries must remain black")

def validate_render_manifest(manifest, directory: Path, source: Path, design, width: int):
    ticks = math.lcm(len(design["frames"]), len(design["keyframes"]))
    required = {
        "schemaVersion": 1, "kind": "photo-composite-rgb-frames",
        "source": source.relative_to(ROOT).as_posix(), "sourceSha256": sha256(source.read_bytes()),
        "designId": design["id"], "width": width, "frameCount": ticks, "loopTicks": ticks,
        "sourceFrameCount": len(design["frames"]), "keyFrameCount": len(design["keyframes"]),
        "speedMs": design["speed_ms"], "totalDurationMs": ticks * design["speed_ms"],
        "fullLoopDurationMs": ticks * design["speed_ms"],
        "view": "front", "framing": "keyboard", "renderer": "editor", "keyMode": "json",
        "brightness": design.get("preview_brightness", 100), "keySpriteCount": 83,
    }
    if any(manifest.get(key) != value for key, value in required.items()):
        raise ValueError("Incomplete, stale or inconsistent photo-frame manifest")
    if type(manifest.get("height")) is not int or manifest["height"] <= 0:
        raise ValueError("Invalid photo height")
    for field, relative in HASH_FIELDS.items():
        if manifest.get(field) != sha256((ROOT / relative).read_bytes()):
            raise ValueError(f"Stale public rendering source: {relative}")
    photo = public_path(manifest.get("photo"))
    if not photo.is_relative_to(ROOT / "web/assets") or manifest.get("photoSha256") != sha256(photo.read_bytes()):
        raise ValueError("Stale or non-public source photo")
    records = manifest.get("frames", [])
    if len(records) != ticks:
        raise ValueError("Missing photo frames")
    for tick, record in enumerate(records):
        filename = f"frame-{tick:04d}.png"
        if (record.get("file") != filename or record.get("tick") != tick
                or record.get("topFrame") != tick % len(design["frames"])
                or record.get("keyFrame") != tick % len(design["keyframes"])
                or record.get("durationMs") != design["speed_ms"]
                or record.get("sha256") != sha256((directory / filename).read_bytes())):
            raise ValueError(f"Invalid photo PNG or source tick {tick}")
    return manifest

def photo_frames(source: Path, design, width: int, node: str, canvas_module: str | None):
    slug = source.name.removesuffix(".design.json")
    directory = ROOT / "build/preset-photo-frames" / (slug + ("" if width == 800 else f"-{width}"))
    manifest_path = directory / "manifest.json"
    try:
        manifest = validate_render_manifest(load(manifest_path), directory, source, design, width)
    except (OSError, ValueError, KeyError, TypeError):
        command = [node, str(ADAPTER), "--design", source.relative_to(ROOT).as_posix(),
                   "--out", str(directory), "--width", str(width)]
        if canvas_module:
            command += ["--canvas-module", canvas_module]
        subprocess.run(command, cwd=ROOT, check=True)
        manifest = validate_render_manifest(load(manifest_path), directory, source, design, width)
    return directory, manifest

def feature_colors(design):
    # Dark photo pixels must not crowd vivid lamp/character colors out.
    principal = [rgb(value) for value in design.get("palette", [])][:10]
    colors = [OFF, BACKGROUND]
    # The photo engine intentionally shows weaker lamps behind dark glass.
    # Reserve the same hues at several intensities, not just the bright source
    # RGB. Otherwise a tiny dim-orange lamp can be approximated by pink metal.
    colors += [tuple(round(channel * gain) for channel in color)
               for gain in (1, .5, .25) for color in principal]
    counts = Counter(rgb(value) for stream in (design["frames"], design["keyframes"])
                     for frame in stream for value in frame)
    colors += [color for color, _ in counts.most_common()
               if max(color) >= 180 and max(color) - min(color) >= 48]
    return list(dict.fromkeys(colors))[:32]

def quantize_frames(directory: Path, manifest, design):
    """One shared quantizer/cache makes equal RGBs stable over the whole loop."""
    records, width, height = manifest["frames"], manifest["width"], manifest["height"]
    if width * height * len(records) > 160_000_000:
        raise ValueError("Complete loop exceeds offline GIF memory budget; no frames were dropped")
    sample_count = min(24, len(records))
    ticks = sorted({round(i * (len(records) - 1) / max(1, sample_count - 1)) for i in range(sample_count)})
    # Quantize one mosaic, not each frame independently. Pillow's palette lookup
    # cache is then shared, avoiding different mappings for identical body RGBs.
    mosaic = Image.new("RGB", (width, height * len(records)))
    changed = Image.new("L", (width, height), 0)
    first = None
    for tick, record in enumerate(records):
        with Image.open(directory / record["file"]) as opened:
            if opened.size != (width, height):
                raise ValueError("Photo dimensions changed")
            frame = opened.convert("RGB")
        mosaic.paste(frame, (0, tick * height))
        if first is None:
            first = frame
        else:
            red, green, blue = ImageChops.difference(first, frame).split()
            changed = ImageChops.lighter(changed, ImageChops.lighter(red, ImageChops.lighter(green, blue)))
    static_mask = changed.point([255] + [0] * 255)
    mask_bytes, first_bytes = static_mask.tobytes(), first.tobytes()
    static_samples, dynamic_samples = bytearray(), bytearray()
    # Train the static photo separately, reserving half the table for its body
    # gradients rather than allowing changing dark keycaps to crowd them out.
    for index, value in enumerate(mask_bytes):
        if value:
            pixel = first_bytes[index * 3:index * 3 + 3]
            static_samples.extend(pixel)
            if max(pixel) > 40 and max(pixel) - min(pixel) > 18:
                static_samples.extend(pixel * 2)  # More precision for metal color gradients.
    for tick in ticks:
        sample = mosaic.crop((0, tick * height, width, (tick + 1) * height)).tobytes()
        for index in range(0, len(mask_bytes), 4):
            if not mask_bytes[index]:
                dynamic_samples.extend(sample[index * 3:index * 3 + 3])

    def trained_colors(samples, count):
        if not samples:
            samples = bytearray(first_bytes[:3])
        pixels = len(samples) // 3
        training_width = min(256, pixels)
        padding = (-pixels) % training_width
        samples.extend(samples[:3] * padding)
        training = Image.frombytes("RGB", (training_width, (pixels + padding) // training_width), bytes(samples))
        trained = training.quantize(colors=count, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        flat = trained.getpalette()
        flat += [0] * max(0, count * 3 - len(flat))
        return [tuple(flat[i:i + 3]) for i in range(0, count * 3, 3)]

    reserved = feature_colors(design)
    colors = trained_colors(static_samples, 128) + trained_colors(dynamic_samples, 127 - len(reserved))
    colors = list(dict.fromkeys(colors + reserved))
    colors += [colors[-1]] * (255 - len(colors))
    colors.append(OFF)  # Index 255 is reserved for unchanged GIF pixels.
    palette = bytes(channel for color in colors for channel in color)
    palette_image = Image.new("P", (1, 1)); palette_image.putpalette(palette)
    quantized = mosaic.quantize(palette=palette_image, dither=Image.Dither.NONE)
    del mosaic
    # Both black entries have the same RGB; keep 255 out of opaque frames.
    black_index = colors.index(OFF)
    quantized = quantized.point(list(range(255)) + [black_index])
    images = [quantized.crop((0, tick * height, width, (tick + 1) * height)) for tick in range(len(records))]
    # A single base is dithered once. Only pixels with identical RGB throughout
    # the ENTIRE loop use it, so the photograph gains detail without shimmer.
    base = first.quantize(palette=palette_image, dither=Image.Dither.FLOYDSTEINBERG)
    base = base.point(list(range(255)) + [black_index])
    for frame in images:
        frame.paste(base, mask=static_mask)
    static_count = static_mask.histogram()[255]
    return images, palette, reserved, {
        "static_photo_pixels": static_count,
        "dynamic_pixels": width * height - static_count,
        "static_photo_dither": "one fixed Floyd-Steinberg base; exact RGB unchanged throughout complete loop",
        "dynamic_dither": "none",
    }

def delta_frames(images):
    """Leave static photograph pixels in place using GIF disposal=1.

    The decoded result must still match every opaque quantized source tick.
    This reduces size without dropping frames, changing RGB or speeding up.
    """
    result = [images[0]]
    for previous, current in zip(images, images[1:]):
        unchanged = ImageChops.difference(previous, current).point([255] + [0] * 255, "L")
        delta = current.copy()
        delta.paste(255, mask=unchanged)
        result.append(delta)
    return result

def verify_palette(path: Path, palette: bytes):
    """Require one fixed global table, never per-frame color-table changes."""
    data = path.read_bytes()
    if data[:6] not in (b"GIF87a", b"GIF89a") or not data[10] & 128:
        raise AssertionError("Missing GIF global palette")
    size = 3 * 2 ** ((data[10] & 7) + 1)
    if size != 768 or data[13:13 + size] != palette:
        raise AssertionError("GIF global palette differs from fixed quantization palette")
    position = 13 + size
    while position < len(data):
        marker = data[position]; position += 1
        if marker == 0x3B:
            return
        if marker == 0x21:
            position += 1  # Extension label, followed by size-prefixed blocks.
        elif marker == 0x2C:
            if data[position + 8] & 128:
                raise AssertionError("Unexpected per-frame GIF palette")
            position += 10  # Image descriptor plus LZW minimum code size.
        else:
            raise AssertionError("Invalid GIF block")
        while data[position]:
            position += data[position] + 1
        position += 1
    raise AssertionError("GIF has no trailer")

def verify_gif(path: Path, images, duration: int):
    expected = [sha256(frame.convert("RGB").tobytes()) for frame in images]
    ticks, timeline = 0, []
    with Image.open(path) as image:
        if image.size != images[0].size or image.info.get("loop") != 0:
            raise AssertionError("GIF must use fixed dimensions and loop forever")
        for frame_index in range(image.n_frames):
            image.seek(frame_index)
            frame_duration = image.info.get("duration", 0)
            if not frame_duration or frame_duration % duration:
                raise AssertionError("GIF lost source frame timing")
            digest = sha256(image.convert("RGB").tobytes())
            repeats = frame_duration // duration
            if expected[ticks:ticks + repeats] != [digest] * repeats:
                raise AssertionError(f"Decoded GIF differs from quantized photo at tick {ticks}")
            timeline.append(frame_duration); ticks += repeats
    if ticks != len(images) or sum(timeline) != len(images) * duration:
        raise AssertionError("GIF omitted source ticks")
    return len(timeline), timeline

def save_gif(path: Path, images, palette: bytes, speed: int):
    encoded = delta_frames(images)
    encoded[0].save(path, save_all=True, append_images=encoded[1:], palette=palette,
                    duration=[speed] * len(images), loop=0, optimize=False, disposal=1,
                    dither=Image.Dither.NONE, transparency=255,
                    comment=b"Cyberboard Studio | App keyboard-photo composite | fixed palette; static photo dithered once, dynamic lamps no dither | full original timing | screen preview, not hardware calibration")
    verify_palette(path, palette)
    return verify_gif(path, images, speed)

def static_pixel_check(directory: Path, manifest, images):
    """Exclude genuine lighting changes; unchanged photo RGB must not flicker."""
    last = min(80, len(images) - 1)
    with Image.open(directory / manifest["frames"][0]["file"]) as opened:
        first = opened.convert("RGB")
    with Image.open(directory / manifest["frames"][last]["file"]) as opened:
        other = opened.convert("RGB")
    raw_diff = ImageChops.difference(first, other)
    encoded_diff = ImageChops.difference(images[0].convert("RGB"), images[last].convert("RGB"))
    stable = changed = 0
    raw_bytes, encoded_bytes = raw_diff.tobytes(), encoded_diff.tobytes()
    for index in range(0, len(raw_bytes), 3):
        raw, encoded = raw_bytes[index:index + 3], encoded_bytes[index:index + 3]
        if raw == b"\0\0\0":
            stable += 1; changed += encoded != b"\0\0\0"
    if not stable or changed:
        raise AssertionError(f"Unchanged photo pixels flicker: {changed}/{stable}")
    return {"ticks": [0, last], "unchanged_rgb_pixels": stable, "changed_after_quantization": changed}

def build(entry, output: Path, args):
    filename = entry["file"]
    if Path(filename).name != filename or not filename.endswith(".design.json"):
        raise ValueError("Catalog must contain simple .design.json filenames")
    source = ROOT / "data/designs" / filename
    design = load(source); validate_design(design)
    directory, rendered = photo_frames(source, design, args.width, args.node, args.canvas_module)
    images, palette, reserved, quantization = quantize_frames(directory, rendered, design)
    destination = output / (filename.removesuffix(".design.json") + ".gif")
    speed = design["speed_ms"]
    static_check = static_pixel_check(directory, rendered, images)
    if not args.check_only:
        temporary = destination.with_suffix(".tmp.gif")
        save_gif(temporary, images, palette, speed)
        temporary.replace(destination)
    verify_palette(destination, palette)
    decoded, timeline = verify_gif(destination, images, speed)
    row = {
        "id": design["id"], "name": design["name"],
        "source": source.relative_to(ROOT).as_posix(), "source_sha256": rendered["sourceSha256"],
        "gif": destination.name, "gif_sha256": sha256(destination.read_bytes()),
        "bytes": destination.stat().st_size, "dimensions": [rendered["width"], rendered["height"]],
        "source_frames": len(design["frames"]), "source_key_frames": len(design["keyframes"]),
        "loop_ticks": len(images), "decoded_frames": decoded,
        "source_frame_ms": speed, "total_duration_ms": sum(timeline), "loop": 0,
        "photo": rendered["photo"], "photo_sha256": rendered["photoSha256"],
        "view": rendered["view"], "framing": rendered["framing"], "renderer": rendered["renderer"],
        "key_mode": rendered["keyMode"], "brightness": rendered["brightness"],
        "composition": rendered["composition"], "background": rendered["background"],
        "rgb_quantization": "fixed global 256-entry palette (255 colors + transparency); photo composite RGB is quantized",
        "quantization": quantization,
        "palette_method": PALETTE_METHOD, "palette_sha256": sha256(palette),
        "reserved_feature_colors": ["#%02X%02X%02X" % color for color in reserved],
        "timing_check": "every decoded tick matches its quantized photo; identical frames may merge without lost duration",
        "static_pixel_check": static_check,
        "render_sources": {relative: rendered[field] for field, relative in HASH_FIELDS.items()},
    }
    print(f"{destination.name}: {decoded}/{len(images)} GIF/source ticks, {sum(timeline)} ms, "
          f"{row['bytes']:,} bytes; photo composite, fixed palette, static-only dither", flush=True)
    return row

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/previews")
    parser.add_argument("--only", nargs="+", help="Filename slugs from public main preset catalog")
    parser.add_argument("--check-only", action="store_true", help="Verify GIF/manifest without overwriting them")
    parser.add_argument("--node", default="node", help="Node executable for offline App-preview adapter")
    parser.add_argument("--canvas-module", help="Offline @napi-rs/canvas module; or STUDIO_CANVAS_MODULE")
    parser.add_argument("--width", type=int, default=800, help="Photo width 640–1400, default 800")
    args = parser.parse_args()
    if not 640 <= args.width <= 1400:
        parser.error("--width must be from 640 to 1400")
    catalog = load(ROOT / "data/preset-catalog.json")
    if catalog.get("schema_version") != 1:
        raise ValueError("Unsupported preset catalog schema")
    works = catalog["works"]
    if args.only:
        wanted = set(args.only)
        works = [entry for entry in works if entry["file"].removesuffix(".design.json") in wanted]
        if len(works) != len(wanted):
            raise ValueError("Every requested slug must occur exactly once in main catalog")
    if not works:
        raise ValueError("No presets selected")
    output = args.output.resolve()
    if not args.check_only:
        output.mkdir(parents=True, exist_ok=True)
    previews = [build(entry, output, args) for entry in works]
    if len({row["id"] for row in previews}) != len(previews):
        raise ValueError("Duplicate preset IDs")
    manifest = {
        "schema_version": 2, "kind": "app-keyboard-photo-composite-gifs",
        "renderer": "scripts/build-preset-gifs.py", "pillow_version": PILLOW_VERSION,
        "renderer_sources": {relative: sha256((ROOT / relative).read_bytes()) for relative in
                             ("scripts/build-preset-gifs.py", "scripts/render-preset-photo-frames.cjs")},
        "rendering": "unchanged App KeyboardPreview, public front keyboard photo, editor top LEDs, JSON key LEDs; original preview brightness and full loop timing",
        "encoding": "one fixed 256-entry palette per full GIF; full-cycle unchanged photo pixels use one deterministic dithered base, changing lamps use no dither; photo RGB is quantized, not original-RGB lossless",
        "display_limit": "Screen photo composite, not physical color or brightness calibration",
        "previews": previews,
    }
    if args.check_only:
        if load(output / "manifest.json") != manifest:
            raise AssertionError("Manifest differs from current public sources or verified GIFs")
    else:
        temporary = output / "manifest.json.tmp"
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output / "manifest.json")

if __name__ == "__main__":
    main()
