"""Model bake-off for fitting-room portraits: same prompt, same seeds, one backend per process.

    .venv/bin/python bakeoff.py klein  --out ../../data/fitting/bakeoff/<run>
    .venv/bin/python bakeoff.py sheet  --out ../../data/fitting/bakeoff/<run>     # contact sheet of every backend

Prompts come from the console (/api/fitting/prompts), so the bake-off renders exactly what production would.
Each backend writes <out>/<backend>/<model-id>_s<seed>.png and timings.json (seconds per image, load excluded).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

CONSOLE = "http://127.0.0.1:7100"
SUBJECTS = ["f-XS-east_asian", "m-XS-white", "f-L-black"]
SEEDS = [7, 21]
W, H = 768, 1024


def load(backend: str, q: int | None):
    from mflux.models.common.config import ModelConfig
    if backend == "klein":
        from mflux.models.flux2.variants import Flux2Klein
        return Flux2Klein(quantize=q, model_config=ModelConfig.flux2_klein_4b()), dict(num_inference_steps=4, guidance=1.0)
    if backend == "zimage":
        from mflux.models.z_image import ZImage
        return ZImage(model_config=ModelConfig.z_image_turbo(), quantize=q), dict(num_inference_steps=9)
    if backend == "boogu":
        from mflux.models.boogu import BooguImage
        return BooguImage(model_config=ModelConfig.boogu_image_turbo(), quantize=q), dict(num_inference_steps=8)
    if backend == "krea2":
        from mflux.models.krea2 import Krea2
        return Krea2(model_config=ModelConfig.krea2(), quantize=q), dict(num_inference_steps=8, guidance=1.0)
    raise SystemExit(f"unknown backend {backend}")


def render(backend: str, out: Path, q: int | None) -> None:
    prompts = httpx.get(f"{CONSOLE}/api/fitting/prompts", timeout=30).raise_for_status().json()
    t0 = time.time()
    model, params = load(backend, q)
    timings = {"backend": backend, "quantize": q, "load_s": round(time.time() - t0, 1), "images": {}}
    (out / backend).mkdir(parents=True, exist_ok=True)
    for mid in SUBJECTS:
        for seed in SEEDS:
            t = time.time()
            image = model.generate_image(seed=seed, prompt=prompts[mid]["prompt"], width=W, height=H, **params)
            image.save(path=str(out / backend / f"{mid}_s{seed}.png"), overwrite=True)
            timings["images"][f"{mid}_s{seed}"] = round(time.time() - t, 1)
            print(backend, mid, seed, timings["images"][f"{mid}_s{seed}"], "s", flush=True)
    timings["avg_s"] = round(sum(timings["images"].values()) / len(timings["images"]), 1)
    timings["prompt"] = prompts[SUBJECTS[0]]["ref"]
    (out / backend / "timings.json").write_text(json.dumps(timings, indent=2))


def sheet(out: Path) -> None:
    """Rows = backends, columns = subject x seed, each tile labelled with backend and seconds per image."""
    from PIL import Image, ImageDraw
    rows = [d for d in sorted(out.iterdir()) if (d / "timings.json").exists()]
    tw, th, pad = 256, 341, 22
    cols = [f"{m}_s{s}" for m in SUBJECTS for s in SEEDS]
    img = Image.new("RGB", (len(cols) * tw, len(rows) * (th + pad)), "white")
    draw = ImageDraw.Draw(img)
    for r, d in enumerate(rows):
        t = json.loads((d / "timings.json").read_text())
        draw.text((6, r * (th + pad) + 5), f"{d.name}  q{t['quantize']}  {t['avg_s']}s/img", fill="black")
        for c, name in enumerate(cols):
            p = d / f"{name}.png"
            if p.exists():
                img.paste(Image.open(p).convert("RGB").resize((tw, th)), (c * tw, r * (th + pad) + pad))
    img.save(out / "sheet.jpg", quality=90)
    print(out / "sheet.jpg")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("backend")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("-q", type=int, default=8)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    sheet(a.out) if a.backend == "sheet" else render(a.backend, a.out, a.q or None)
