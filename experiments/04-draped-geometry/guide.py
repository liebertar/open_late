"""Draped mesh -> input image for the image model, and the image model's output -> the final photo.

The mesh is rendered with its pattern coordinates, so pocket, rib and seams land where the pattern puts them. The hood is not
simulated yet and comes from an existing render. The model only repaints the garment: face, hands and legs stay the original
pixels. Run with host/fitting/.venv/bin/python, render engine stopped.

    python guide.py m-M-white L panels.json XS S M L XL
"""
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/fitting/bakeoff"
OUT = DATA / "draped"
FLOOR_Y, PX_PER_CM, MID_X = 980, (980 - 24) / 200, 384
W, H, SS = 768, 1024, 2
BACKDROP = 239 / 255
LIT_MID = 0.62        # typical lighting value on the cloth, used to match its colour to the existing render
LIGHT = np.array([-0.35, -0.8, 0.5]) / np.linalg.norm([-0.35, -0.8, 0.5])
STEPS, KEEP = 8, 0.5
PROMPT = ("Photorealistic catalog photo of a person in a heavyweight cotton fleece pullover hoodie, solid ink navy all over, no zipper, no logo, no tags, "
          "grey trousers and white sneakers. Soft natural folds, matte brushed cotton, clean navy ribbed hem and navy cuffs, a kangaroo pocket. "
          "The hoodie keeps exactly the shape, length and silhouette shown in the image. Plain light backdrop, soft studio light.")


def navy(rgb):
    r, g, b = (rgb[..., i].astype(int) for i in range(3))
    return (r < 75) & (g < 75) & (b < 95)


def hem_row(rgb):
    """Lowest row where the middle of the body is navy. Whole-row counts pick up the cuffs instead of the hem."""
    rows = np.where(navy(rgb[:, 334:434]).sum(axis=1) > 60)[0]
    return int(rows.max()) if len(rows) else -1


def to_row(z):
    return FLOOR_Y - z * 100 * PX_PER_CM


def rasterize(x, tri):
    """Front view, nearest surface wins. Returns triangle id per pixel and two barycentric coordinates."""
    w, h = W * SS, H * SS
    px = np.c_[(MID_X + x[:, 0] * 100 * PX_PER_CM) * SS, to_row(x[:, 2]) * SS]
    depth = x[:, 1]
    zb = np.full((h, w), np.inf, np.float32)
    ids = np.full((h, w), -1, np.int32)
    b0, b1 = np.zeros((h, w), np.float32), np.zeros((h, w), np.float32)
    for k, t in enumerate(tri):
        a, b, c = px[t]
        x0, x1 = int(max(min(a[0], b[0], c[0]), 0)), int(min(max(a[0], b[0], c[0]) + 1, w - 1))
        y0, y1 = int(max(min(a[1], b[1], c[1]), 0)), int(min(max(a[1], b[1], c[1]) + 1, h - 1))
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if x1 < x0 or y1 < y0 or abs(d) < 1e-9:
            continue
        ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        l0 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / d
        l1 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / d
        l2 = 1 - l0 - l1
        ok = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if not ok.any():
            continue
        z = l0 * depth[t[0]] + l1 * depth[t[1]] + l2 * depth[t[2]]
        yy, xx, zz, a0, a1 = ys[ok], xs[ok], z[ok], l0[ok], l1[ok]
        keep = zz < zb[yy, xx]
        yy, xx = yy[keep], xx[keep]
        zb[yy, xx], ids[yy, xx], b0[yy, xx], b1[yy, xx] = zz[keep], k, a0[keep], a1[keep]
    return ids, b0, b1, zb


def attr(values, tri, ids, b0, b1):
    t = tri[np.maximum(ids, 0)]
    return b0[..., None] * values[t[..., 0]] + b1[..., None] * values[t[..., 1]] + (1 - b0 - b1)[..., None] * values[t[..., 2]]


def vertex_normals(x, tri):
    n = np.cross(x[tri[:, 1]] - x[tri[:, 0]], x[tri[:, 2]] - x[tri[:, 0]])
    out = np.zeros_like(x)
    for i in range(3):
        np.add.at(out, tri[:, i], n)
    return out / (np.linalg.norm(out, axis=1, keepdims=True) + 1e-12)


def edge_distance(uv, tri, part):
    """Metres from each vertex to the edge of its panel in the flat pattern."""
    e = np.sort(np.vstack([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1)
    u, c = np.unique(e, axis=0, return_counts=True)
    edge = np.zeros(len(uv), bool)
    edge[u[c == 1].ravel()] = True
    out = np.zeros(len(uv), np.float32)
    for p in np.unique(part):
        m = part == p
        out[m] = cKDTree(uv[edge & m]).query(uv[m])[0]
    return out


def pocket_texture(seg):
    """Distance in mm inside the pocket outline, on a 1 mm grid of the front panel (mirrored on x)."""
    poly = np.vstack([np.asarray(s)[:-1] for s in seg["hugo.pocket"]])
    tex = np.zeros((800, 500), np.uint8)
    cv2.fillPoly(tex, [poly.round().astype(np.int32)], 255)
    return cv2.distanceTransform(tex, cv2.DIST_L2, 3)


def shade(pid, size, seg, fabric):
    sim = np.load(OUT / f"sim/{pid}__{size}/final.npz")
    x, tri, part, uv, names = sim["x"].astype(np.float64), sim["tri"], sim["part"], sim["uv"], list(sim["names"])
    ids, b0, b1, depth = rasterize(x, tri)
    hit = ids >= 0
    n = attr(vertex_normals(x, tri), tri, ids, b0, b1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-9
    n *= np.where(n[..., 1:2] > 0, -1, 1)
    lit = np.minimum(0.34 + 0.8 * np.clip(n @ LIGHT, 0, 1), 0.95)
    d = np.where(hit, depth, depth[hit].max()).astype(np.float32)
    ao = 1 - 0.55 * np.clip((d - cv2.GaussianBlur(d, (0, 0), 14 * SS)) / 0.03, 0, 1)
    img = fabric * (lit * ao)[..., None]

    px_part = np.where(hit, part[tri[np.maximum(ids, 0), 0]], -1)
    pu = attr(uv.astype(np.float32), tri, ids, b0, b1)
    seam = attr(edge_distance(uv, tri, part)[:, None], tri, ids, b0, b1)[..., 0]
    img *= (0.72 + 0.28 * np.clip(seam / 0.004, 0, 1))[..., None]
    rib = px_part >= names.index("rib")
    img[rib] *= (0.84 + 0.16 * np.sin(pu[..., 0] * 2 * np.pi / 0.007))[rib][..., None]
    pocket = pocket_texture(seg)
    front = px_part == names.index("front")
    pd = np.zeros(front.shape, np.float32)
    px, py = (np.abs(pu[..., 0][front]) * 1000).astype(int).clip(0, 499), (pu[..., 1][front] * 1000).astype(int).clip(0, 799)
    pd[front] = pocket[py, px]
    img[pd > 0] *= 1.1
    img *= (1 - 0.45 * ((pd > 0) & (pd < 4)))[..., None]
    img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
    alpha = cv2.resize(hit.astype(np.float32), (W, H), interpolation=cv2.INTER_AREA)
    return img, alpha, x, part, names


def compose(pid, ref_size, size, seg):
    """Input image for the model: base-layer person, shaded cloth, the hood of an existing render, hands on top."""
    base = np.asarray(Image.open(DATA / f"base-layer/models/{pid}.scaled.png").convert("RGB")).astype(np.float32) / 255
    ref = np.asarray(Image.open(DATA / f"base-layer/renders/{pid}__{ref_size}.scaled.png").convert("RGB"))
    fabric = np.median(ref[navy(ref)], axis=0).astype(np.float32) / 255 / LIT_MID
    cloth, alpha, x, part, names = shade(pid, size, seg, fabric)
    neck_y = int(to_row(json.load(open(OUT / f"sim/{pid}__{size}/hem.json"))["neck_top"]))
    alpha[:neck_y + 40, MID_X - 70:MID_X + 70] = 0  # the open neck: the hood covers it
    r, g, b = (ref[..., i].astype(int) for i in range(3))
    apricot = (r > 150) & (r - b > 60)
    hood = (navy(ref) | apricot).astype(np.uint8)
    hood[:neck_y - 22] = 0  # hair is dark too: the hood starts at the neck
    hood[neck_y + 62:] = 0
    hood[:, :MID_X - 100] = 0
    hood[:, MID_X + 100:] = 0
    hood = cv2.morphologyEx(hood, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    cords = np.zeros_like(hood, np.float32)
    cords[neck_y + 40:neck_y + 165, MID_X - 34:MID_X + 34] = 1
    keep = np.maximum(cv2.GaussianBlur(hood.astype(np.float32), (0, 0), 3), cv2.GaussianBlur(cords, (0, 0), 12))[..., None]

    wrist_y = int(to_row(np.percentile(x[part == names.index("cuffL"), 2], 10))) + 6
    br, bg, bb = base[..., 0], base[..., 1], base[..., 2]
    skin = (br > 0.42) & (br - bb > 0.1) & (br >= bg) & (br < 0.95)
    arm = skin.copy()
    arm[:neck_y + 70] = False
    arm[wrist_y - 24:] = False  # bare forearms of the base layer: sleeves cover them even where the sleeve hangs apart from the arm
    base = base.copy()
    base[cv2.dilate(arm.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0] = BACKDROP
    hem_y = int(to_row(json.load(open(OUT / f"sim/{pid}__{size}/hem.json"))["front"]))
    shirt = (base > 0.8).all(axis=-1)
    shirt[:neck_y + 70] = False
    shirt[hem_y - 2:] = False  # the t-shirt shows below the hem only, never beside the sleeves
    base[cv2.dilate(shirt.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0] = BACKDROP

    out = base * (1 - alpha[..., None]) + cloth * alpha[..., None]
    out = out * (1 - keep) + (ref.astype(np.float32) / 255) * keep

    skin[:wrist_y] = False
    skin = cv2.GaussianBlur(cv2.morphologyEx(skin.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(np.float32), (0, 0), 1)[..., None]
    out = out * (1 - skin) + base * skin
    garment = np.clip(alpha + keep[..., 0], 0, 1) * (1 - skin[..., 0])
    fade = np.clip((neck_y + 62 - np.arange(H)) / 42, 0, 1).astype(np.float32)[:, None]  # no hard line where the old hood ends
    return (out.clip(0, 1) * 255).astype(np.uint8), garment, base, ref.astype(np.float32) / 255, cv2.GaussianBlur(hood.astype(np.float32), (0, 0), 1.5) * fade


def main(pid, ref_size, panels_file, *sizes):
    seg_all = json.load(open(panels_file))
    (OUT / "guides").mkdir(parents=True, exist_ok=True)
    (OUT / "final").mkdir(parents=True, exist_ok=True)
    jobs = []
    for size in sizes:
        t0 = time.time()
        guide, garment, base, ref, hood = compose(pid, ref_size, size, seg_all[size])
        path = OUT / f"guides/{pid}__{size}.png"
        Image.fromarray(guide).save(path)
        jobs.append((size, path, garment, base, ref, hood))
        print("guide", pid, size, f"{time.time() - t0:.1f} s", "hem row", hem_row(guide), flush=True)
    if os.environ.get("GUIDES_ONLY"):
        return
    from mflux.models.common.config.model_config import ModelConfig
    from mflux.models.flux2.variants import Flux2Klein
    model = Flux2Klein(quantize=4, model_config=ModelConfig.flux2_klein_4b())
    rows = []
    for size, path, garment, base, ref, hood in jobs:
        t0 = time.time()
        image = model.generate_image(seed=42, prompt=PROMPT, num_inference_steps=STEPS, width=W, height=H, guidance=1.0, image_path=path, image_strength=KEEP)
        raw = OUT / f"final/{pid}__{size}.raw.png"
        image.save(path=str(raw), overwrite=True)
        made = np.asarray(Image.open(raw).convert("RGB")).astype(np.float32) / 255
        a = cv2.GaussianBlur(cv2.erode(garment, np.ones((3, 3), np.uint8)), (0, 0), 1.0)[..., None]  # dilating drags in the model's backdrop
        final = made * a + base * (1 - a)
        final = final * (1 - hood[..., None]) + ref * hood[..., None]  # the hood stays the photographed one, lining included
        final = (final.clip(0, 1) * 255).astype(np.uint8)
        Image.fromarray(final).save(OUT / f"final/{pid}__{size}.png")
        sim = json.load(open(OUT / f"sim/{pid}__{size}/hem.json"))
        want, got = to_row(sim["front"]), hem_row(final)
        rows.append({"person": pid, "size": size, "sim_row": round(want, 1), "photo_row": got, "error_cm": round((got - want) / PX_PER_CM, 1), "seconds": round(time.time() - t0, 1)})
        print(rows[-1], flush=True)
    (OUT / f"final/{pid}.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:])
