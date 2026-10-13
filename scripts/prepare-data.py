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
    views = load(inputs / "photos/photo-calibration.json")
    zones = load(inputs / "photos/key-photo-layout.json")["views"]
    for name, view in views.items():
        view.pop("source_file", None)
        view.pop("asset", None)
        original = assets / f"{name}.jpg"
        # Data URLs let WebKit sample the original pixels without local-file
        # origin errors. The committed JPGs are reused, never redrawn or edited.
        view["image"] = "data:image/jpeg;base64," + base64.b64encode(original.read_bytes()).decode("ascii")
        view["keyZones"] = zones[name]
    designs = [load(inputs / "designs" / name) for name in
               ("neon-rift.design.json", "data-storm.design.json", "redline-rush.design.json")]
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
    bundle = {"views": views, "designs": designs, "baseConfig": None,
              "snapshot": {"productId": None, "firmware": None, "connected": False}, "keyLayout": keys}
    (app / "web/data.js").write_text(
        "window.STUDIO_DATA=" + json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8")
    print("Bundled 3 creative works, unchanged photos and generic geometry. No device record or USB access.")


if __name__ == "__main__":
    main()
