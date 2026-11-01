"""Bake-off, not production: if the geometry is already right in the input image, does klein keep the hem where it is?

Fakes the geometry a drape would give: the torso of an existing render is stretched or squeezed so the hem lands where
the pattern puts it, then the result goes through a klein edit at several image_strength values. Only writes under
data/fitting/bakeoff/draped/proxy. Run with host/fitting/.venv/bin/python, render engine stopped.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
BASE = DATA / "fitting/bakeoff/base-layer"
OUT = DATA / "fitting/bakeoff/draped/proxy"
FLOOR_Y, PX_PER_CM = 980, (980 - 24) / 200
HPS = 0.82  # share of height: high point of the shoulder, standard body proportions
LENGTH_MM = {"XS": 547, "M": 627, "XL": 706}  # node 04 pattern
PEOPLE = {"f-S-east_asian": (160, "L"), "m-M-white": (175, "L")}  # id: height, render the torso is taken from
KEEP = [0.5, 0.75]  # image_strength: share of the input kept
PROMPT = ("Photorealistic catalog photo of the same person in the same navy hoodie, grey trousers and white sneakers. "
          "The hoodie keeps exactly the length, hem position and silhouette shown in the image. Natural soft cotton folds, "
          "clean ribbed hem. Face, hair, pose, proportions and the plain light backdrop stay exactly as in the image.")


def navy(rgb):
    r, g, b = (rgb[..., i].astype(int) for i in range(3))
    return (r < 75) & (g < 75) & (b < 95)


def hem_row(rgb):
    """Lowest row where the middle of the body is navy. Whole-row counts pick up the cuffs instead of the hem."""
    rows = np.where(navy(rgb[:, 334:434]).sum(axis=1) > 60)[0]
    return int(rows.max()) if len(rows) else -1


def target_row(height_cm, length_mm):
    return round(FLOOR_Y - (HPS * height_cm - length_mm / 10) * PX_PER_CM)


def torso_columns(rgb, hem):
    """The navy run through the middle of the row just above the hem: the torso between the sleeves."""
    row = navy(rgb)[hem - 6]
    x0 = x1 = 384
    while x0 > 0 and row[x0 - 1]:
        x0 -= 1
    while x1 < len(row) and row[x1]:
        x1 += 1
    return x0, x1


def guide(person, render, target):
    """Stretch the torso rows between chest and hem so the hem lands on target; show the base layer where it retreats."""
    hem = hem_row(render)
    x0, x1 = torso_columns(render, hem)
    top = hem - 110  # the chest above this row stays put
    out = render.copy()
    rows = np.linspace(top, hem, target - top).round().astype(int)
    out[top:target, x0:x1] = render[rows][:, x0:x1]
    if target < hem:
        out[target:hem + 2, x0:x1] = person[target:hem + 2, x0:x1]
    return out, hem


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    guides = []
    for pid, (height, src) in PEOPLE.items():
        person = np.asarray(Image.open(BASE / f"models/{pid}.scaled.png").convert("RGB"))
        render = np.asarray(Image.open(BASE / f"renders/{pid}__{src}.scaled.png").convert("RGB"))
        for size, length in LENGTH_MM.items():
            want = target_row(height, length)
            img, hem = guide(person, render, want)
            path = OUT / f"guide__{pid}__{size}.png"
            Image.fromarray(img).save(path)
            guides.append((pid, size, want, path))
            print(pid, size, "source hem", hem, "target", want, "guide hem", hem_row(img), flush=True)
    if "--guides-only" in sys.argv:
        return

    from mflux.models.common.config.model_config import ModelConfig
    from mflux.models.flux2.variants import Flux2Klein  # the edit class skips steps but never starts from the image
    model = Flux2Klein(quantize=4, model_config=ModelConfig.flux2_klein_4b())
    rows = []
    for pid, size, want, path in guides:
        for keep in KEEP:
            t0 = time.time()
            image = model.generate_image(seed=42, prompt=PROMPT, num_inference_steps=4, width=768, height=1024, guidance=1.0,
                                         image_path=path, image_strength=keep)
            name = OUT / f"out__{pid}__{size}__k{int(keep * 100)}.png"
            image.save(path=str(name), overwrite=True)
            got = hem_row(np.asarray(Image.open(name).convert("RGB")))
            rows.append({"person": pid, "size": size, "keep": keep, "target_row": want, "hem_row": got,
                         "error_cm": round((got - want) / PX_PER_CM, 1), "seconds": round(time.time() - t0, 1)})
            print(rows[-1], flush=True)
    (OUT / "result.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
