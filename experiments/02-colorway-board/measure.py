"""Rendered vs intended outer colour: median of a torso patch -> CIEDE2000 against the target hex.
Only the outer body colour is measured; the patch is a fixed central crop, so it is a rough check."""
import json, sys
from pathlib import Path
import numpy as np, colour
from PIL import Image

E = Path(sys.argv[1]); cfg = json.load(open(E / "colorways.json"))["colorways"]

def lab_of_rgb(rgb):  # rgb 0..1 sRGB
    return colour.XYZ_to_Lab(colour.sRGB_to_XYZ(rgb))

def hex_rgb(h): return np.array([int(h[i:i+2], 16) for i in (1, 3, 5)]) / 255

out = {}
for c in cfg:
    p = E / "out" / f"{c['id']}_product.png"
    if not p.exists(): continue
    im = np.asarray(Image.open(p).convert("RGB")) / 255.0
    h, w, _ = im.shape
    patch = im[int(h*.50):int(h*.62), int(w*.40):int(w*.60)].reshape(-1, 3)
    med = np.median(patch, axis=0)
    de = float(colour.delta_E(lab_of_rgb(hex_rgb(c["outer_hex"])), lab_of_rgb(med), method="CIE 2000"))
    out[c["id"]] = {"rendered_hex": "#%02X%02X%02X" % tuple((med*255).round().astype(int)), "delta_e00": round(de, 1)}
    print(f"{c['id']:16} target {c['outer_hex']}  rendered {out[c['id']]['rendered_hex']}  ΔE00 {de:5.1f}")
json.dump(out, open(E / "out" / "measure.json", "w"), indent=2)
