#!/usr/bin/env python3
"""Bundle checked-in creative works and geometry; no personal device baseline.

data/ contains designs, calibrated photo coordinates and generic physical key
labels. Actual device records stay in the user's CLI store at runtime.
"""
import base64
import json
from pathlib import Path


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    app = Path(__file__).resolve().parents[1]
    inputs, assets = app / "data", app / "web/assets"
    assets.mkdir(parents=True, exist_ok=True)
    # Public official defaults contain builtin pages only, never a device keymap.
    builtin_source = inputs / "builtin-default-pages.json"
    builtin = load(builtin_source)
    if builtin.get("kind") != "cyberboard-standard-builtin-pages" or [p["page_index"] for p in builtin.get("pages", [])] != list(range(5)):
        raise ValueError("Official builtin-page resource is invalid")
    (assets / "builtin-default-pages.json").write_bytes(builtin_source.read_bytes())
    views = load(inputs / "photos/photo-calibration.json")
    zones = load(inputs / "photos/key-photo-layout.json")["views"]
    for name, view in views.items():
        view.pop("source_file", None)
        asset_name = view.pop("asset", f"{name}.jpg")
        original = (assets / asset_name).resolve()
        if not original.is_relative_to(assets.resolve()):
            raise ValueError("Preview photo must be inside the public asset directory")
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(original.suffix.lower())
        if mime is None:
            raise ValueError("Unsupported preview photo format: " + original.suffix)
        # Data URLs let WebKit sample the original pixels without local-file
        # origin errors. Committed photos are reused byte-for-byte in their
        # original formats, including the official R6 PNG artwork.
        view["image"] = "data:" + mime + ";base64," + base64.b64encode(original.read_bytes()).decode("ascii")
        view["keyZones"] = zones[name]
    catalog = load(inputs / "preset-catalog.json")
    if catalog.get("schema_version") != 1 or not isinstance(catalog.get("works"), list) or not catalog["works"]:
        raise ValueError("Preset catalog is invalid")
    designs, previews, seen = [], {}, set()
    for entry in catalog["works"]:
        name = entry.get("file")
        if not isinstance(name, str) or Path(name).name != name or not name.endswith(".design.json"):
            raise ValueError("Preset catalog must name public design files without a path")
        design = load(inputs / "designs" / name)
        identity = design.get("id")
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError("Preset identities must be unique")
        seen.add(identity)
        cover = entry.get("preview_frame", 48)
        if type(cover) is not int or not 0 <= cover < len(design.get("frames", [])):
            raise ValueError("Preset preview frame is outside its top animation")
        designs.append(design)
        previews[identity] = cover
    for design in designs:
        design["description"] = design.get("description") or design.get("tagline") or {
            "data-storm": "终端点亮、数据暴雨、矩阵穿流与扭曲涡流，酸绿流星撞入电蓝栅格。",
            "redline-rush": "起跑方格压缩、纵向加速、白热漂移与红线切入，红白路肩形成连续竞速。",
        }.get(design["id"], "顶部与轴灯同步编排。")
    physical = load(inputs / "keymap-layout.json")
    fields = ("physical", "row", "col", "matrix_index", "physical_name", "span")
    keys = [{**{field: key[field] for field in fields if field in key},
             "bindings": key.get("bindings", [])[:1]} for key in physical["keys"]]
    layout = {"kind": "cyberboard-physical-layout", "keys": keys}
    (assets / "keymap-layout.json").write_text(
        json.dumps(layout, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    bundle = {"views": views, "designs": designs, "presetPreviews": previews, "baseConfig": None,
              "snapshot": {"productId": None, "firmware": None, "connected": False}, "keyLayout": keys}
    catalog_path = inputs / "photos/preview-catalog.json"
    if catalog_path.is_file():
        bundle["previewCatalog"] = load(catalog_path)
    (app / "web/data.js").write_text(
        "window.STUDIO_DATA=" + json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8")
    print(f"Bundled {len(designs)} creative works, {len(views)} unchanged photo views and generic geometry. No device record or USB access.")


if __name__ == "__main__":
    main()
