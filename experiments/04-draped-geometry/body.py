"""Fit the open body model to one row of the size chart and pose it like the portraits.

Writes <id>.npz (metres, Z up, feet on 0, front toward -Y) and an overlay on the staged portrait to judge the match. Uses the
default topology only: its assets are CC0, while the optional SMPL-X topology is non-commercial.

    python body.py f-S-east_asian m-M-white
"""
import json
import sys
import warnings
from pathlib import Path

import anny
import numpy as np
import torch
import trimesh
from PIL import Image, ImageDraw
from scipy.optimize import minimize
from scipy.spatial import ConvexHull

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT = DATA / "fitting/bakeoff/draped/bodies"
PORTRAIT = DATA / "fitting/bakeoff/base-layer/models"
FLOOR_Y, PX_PER_CM, MID_X = 980, (980 - 24) / 200, 384
AGE = 0.72            # adult anchor of the model
ARM_DEG = -36.0       # rotation of the upper arm from the model's rest pose to the portrait pose
FRAMES = 12           # arm positions between the dressing pose and the portrait pose
LEG_DEG = 7.0         # the rest pose stands wide; the portraits stand with the feet under the hips


def rot(axis, deg):
    a = np.deg2rad(deg)
    i, j = {"x": (1, 2), "y": (2, 0), "z": (0, 1)}[axis]
    m = np.eye(4)
    m[i, i], m[i, j], m[j, i], m[j, j] = np.cos(a), -np.sin(a), np.sin(a), np.cos(a)
    return torch.tensor(m, dtype=torch.float32)[None]


def girth(mesh, z):
    """Tape around the torso at height z: convex hull of the slice loop that holds the body axis, arms left out."""
    section = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if section is None:
        return 0.0
    loops = [np.asarray(d)[:, :2] for d in section.discrete]
    mid = np.median(mesh.vertices[:, :2], axis=0)
    loop = min(loops, key=lambda l: np.linalg.norm(l.mean(axis=0) - mid) - 0.5 * np.ptp(l[:, 0]))
    hull = loop[ConvexHull(loop).vertices]
    return float(np.linalg.norm(hull - np.roll(hull, 1, axis=0), axis=1).sum())


def measure(mesh):
    z0, z1 = mesh.bounds[:, 2]
    h = z1 - z0
    at = lambda lo, hi, n=6: [girth(mesh, z0 + h * f) for f in np.linspace(lo, hi, n)]
    return {"height": h, "chest": max(at(0.70, 0.75)), "waist": min(at(0.58, 0.65)), "seat": max(at(0.46, 0.54))}


def fit(model, gender, want):
    keys = ["height", "weight", "muscle", "proportions"]

    def build(x):
        p = {"gender": gender, "age": AGE} | {k: float(np.clip(v, 0, 1)) for k, v in zip(keys, x)}
        return p, model(phenotype_kwargs={k: torch.tensor([v]) for k, v in p.items()})

    def loss(x):
        _, o = build(x)
        got = measure(trimesh.Trimesh(o["rest_vertices"][0].numpy(), faces, process=False))
        return sum((30 if k == "height" else 1) * ((got[k] - want[k]) / want[k]) ** 2 for k in want) + 0.001 * sum(np.clip(np.abs(v - 0.5) - 0.5, 0, None) ** 2 for v in x)

    faces = model.faces.numpy()
    x0 = np.array([0.5 + (want["height"] - 1.767) / 1.09, 0.5, 0.5, 0.5])  # height moves 1.09 m across its range
    simplex = np.vstack([x0, x0 + np.diag([0.04, 0.2, 0.2, 0.2])])
    res = minimize(loss, x0, method="Nelder-Mead", options={"initial_simplex": simplex, "maxfev": 320, "xatol": 0.002, "fatol": 1e-6})
    return build(res.x)


def main():
    bodies = json.load(open(DATA / "fitting/bodies.json"))["bodies"]
    model = anny.create_fullbody_model(triangulate_faces=True)
    faces = model.faces.numpy()
    OUT.mkdir(parents=True, exist_ok=True)
    for pid in sys.argv[1:]:
        sex, size, _ = pid.split("-", 2)
        row = bodies["male" if sex == "m" else "female"][size]
        want = {"height": row["height"] / 1000, "chest": row["chest"] / 1000, "waist": row["waist"] / 1000, "seat": row["seat"] / 1000}
        pheno, o = fit(model, 0.0 if sex == "m" else 1.0, want)  # the model's gender axis: 0 male, 1 female
        rest = trimesh.Trimesh(o["rest_vertices"][0].numpy(), faces, process=False)
        got = measure(rest)
        frames, wrists, joints = [], [], None
        for t in np.linspace(0, 1, FRAMES):  # arms come down from the dressing pose to the portrait pose
            pose = {"upperarm01.L": rot("z", t * ARM_DEG), "upperarm01.R": rot("z", -t * ARM_DEG),
                    "upperleg01.L": rot("z", LEG_DEG), "upperleg01.R": rot("z", -LEG_DEG)}
            o2 = model(phenotype_kwargs={k: torch.tensor([v]) for k, v in pheno.items()}, pose_parameters=pose)
            v = o2["vertices"][0].numpy().astype(np.float64)
            shift = np.array([v[:, 0].mean(), 0, v[:, 2].min()])
            frames.append(v - shift)
            bones = o2["bone_poses"][0, :, :3, 3].numpy() - shift
            wrists.append(bones[model.bone_labels.index("wrist.L")])
            if joints is None:
                joints = {b: bones[model.bone_labels.index(b)] for b in ("upperarm01.L", "wrist.L")}
        v = frames[-1]
        np.savez(OUT / f"{pid}.npz", frames=np.array(frames, dtype=np.float32), f=faces, shoulder=joints["upperarm01.L"],
                 wrist=joints["wrist.L"], wrists=np.array(wrists), pheno=json.dumps(pheno), got=json.dumps(got))
        print(pid, {k: round(want[k] * 1000) for k in want}, {k: round(got[k] * 1000) for k in got}, {k: round(x, 3) for k, x in pheno.items()}, flush=True)

        img = Image.open(PORTRAIT / f"{pid}.scaled.png").convert("RGB")
        mask = Image.new("L", img.size, 0)
        draw = ImageDraw.Draw(mask)
        px = np.c_[MID_X + v[:, 0] * 100 * PX_PER_CM, FLOOR_Y - v[:, 2] * 100 * PX_PER_CM]
        for tri in faces:
            draw.polygon([tuple(px[i]) for i in tri], fill=255)
        img.paste((220, 40, 40), mask=mask.point(lambda a: a // 2))
        img.save(OUT / f"{pid}.overlay.png")


if __name__ == "__main__":
    main()
