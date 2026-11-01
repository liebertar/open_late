"""Quick look at a drape: flat-shaded front and side views of the cloth over the body, at the staging scale."""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/fitting/bakeoff/draped"
FLOOR_Y, PX_PER_CM, MID_X = 980, (980 - 24) / 200, 384
LIGHT = np.array([-0.25, -0.75, 0.6]) / np.linalg.norm([-0.25, -0.75, 0.6])


def raster(verts, tris, colors, axis=(0, 2), near=1, size=(768, 1024), sign=-1):
    """Z-buffered triangles: pixels of verts[:, axis], depth along verts[:, near] (sign -1: smaller is closer)."""
    w, h = size
    px = np.c_[MID_X + verts[:, axis[0]] * 100 * PX_PER_CM, FLOOR_Y - verts[:, axis[1]] * 100 * PX_PER_CM]
    depth = verts[:, near] * sign * -1
    img, zb = np.zeros((h, w, 3), np.float32), np.full((h, w), np.inf, np.float32)
    idx = np.zeros((h, w), np.int32) - 1
    n = np.cross(verts[tris[:, 1]] - verts[tris[:, 0]], verts[tris[:, 2]] - verts[tris[:, 0]])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    shade = 0.45 + 0.55 * np.abs(n @ LIGHT)
    for k, t in enumerate(tris):
        a, b, c = px[t]
        x0, x1 = int(max(min(a[0], b[0], c[0]), 0)), int(min(max(a[0], b[0], c[0]) + 1, w - 1))
        y0, y1 = int(max(min(a[1], b[1], c[1]), 0)), int(min(max(a[1], b[1], c[1]) + 1, h - 1))
        if x1 < x0 or y1 < y0:
            continue
        ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-9:
            continue
        l0 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / d
        l1 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / d
        l2 = 1 - l0 - l1
        ok = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if not ok.any():
            continue
        z = l0 * depth[t[0]] + l1 * depth[t[1]] + l2 * depth[t[2]]
        yy, xx, zz = ys[ok], xs[ok], z[ok]
        near_px = zz < zb[yy, xx]
        yy, xx, zz = yy[near_px], xx[near_px], zz[near_px]
        zb[yy, xx] = zz
        img[yy, xx] = colors[k] * shade[k]
        idx[yy, xx] = k
    return img, zb, idx


def view(pid, size, tag="final"):
    sim = np.load(OUT / f"sim/{pid}__{size}/{tag}.npz")
    body = np.load(OUT / f"bodies/{pid}.npz")
    frame = -1 if tag == "final" else int(tag[3:]) if tag.startswith("arm") else 0
    bv, bf = body["frames"][frame].astype(np.float64), body["f"]
    x, tri, part = sim["x"].astype(np.float64), sim["tri"], sim["part"]
    pal = np.array([[.2, .3, .6], [.3, .5, .3], [.7, .4, .2], [.7, .4, .2], [.6, .2, .4], [.6, .2, .4], [.6, .2, .4]], np.float32)
    v = np.vstack([bv, x])
    t = np.vstack([bf, tri + len(bv)])
    c = np.vstack([np.full((len(bf), 3), .8, np.float32), pal[part[tri[:, 0]]]])
    front, _, _ = raster(v, t, c)
    cy = (bv[:, 1].min() + bv[:, 1].max()) / 2
    side = v.copy()
    side[:, 0] = v[:, 1] - cy
    side[:, 1] = -v[:, 0]
    right, _, _ = raster(side, t, c)
    a = Image.fromarray((front.clip(0, 1) * 255).astype(np.uint8)).crop((134, 60, 634, 1000))
    b = Image.fromarray((right.clip(0, 1) * 255).astype(np.uint8)).crop((134, 60, 634, 1000))
    canvas = Image.new("RGB", (1000, 940), "white")
    canvas.paste(a, (0, 0))
    canvas.paste(b, (500, 0))
    return canvas


if __name__ == "__main__":
    pid, size = sys.argv[1:3]
    tags = sys.argv[4:] or ["final"]
    for tag in tags:
        view(pid, size, tag).save(f"{sys.argv[3]}_{tag}.png")
