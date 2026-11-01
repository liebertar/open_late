"""Sew a pattern onto a body with a position-based cloth solver on the Mac GPU.

Panels start wrapped around the body in its arms-out dressing pose, seam constraints pull them closed, gravity settles the
cloth, and then the arms come down to the portrait pose. No hood yet: the renders keep the hood from an existing image.

    python drape.py m-M-white M panels.json
"""
import json
import sys
import time
from pathlib import Path

import mlx.core as mx
import numpy as np
from pysdf import SDF
from scipy.spatial import Delaunay, cKDTree

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/fitting/bakeoff/draped"
EDGE = 0.014        # target edge length, m
RIB_H = {"XS": 0.058, "S": 0.060, "M": 0.064, "L": 0.068, "XL": 0.0725}  # folded rib height: half the cut width
GRID = 0.01         # collision grid spacing, m
SKIN = 0.004        # gap kept between cloth and body, m
DT = 1 / 300        # short steps keep the cloth stiff: fleece barely stretches under its own weight
GRAVITY = -9.8


def resample(poly, n):
    p = np.asarray(poly, float)
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
    t = np.linspace(0, s[-1], n + 1)
    return np.c_[np.interp(t, s, p[:, 0]), np.interp(t, s, p[:, 1])]


def join(*polys):
    out = [np.asarray(polys[0], float)]
    for p in polys[1:]:
        out.append(np.asarray(p, float)[1:])
    return np.vstack(out)


def length(p):
    return float(np.linalg.norm(np.diff(np.asarray(p), axis=0), axis=1).sum())


def flip(p):
    return (np.asarray(p, float) * [-1, 1])[::-1]


def inside(poly, pts):
    x, y = pts[:, 0][:, None], pts[:, 1][:, None]
    a, b = poly, np.roll(poly, -1, axis=0)
    cross = (a[:, 1] > y) != (b[:, 1] > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        at = a[:, 0] + (y - a[:, 1]) * (b[:, 0] - a[:, 0]) / (b[:, 1] - a[:, 1])
    return ((x < at) & cross).sum(axis=1) % 2 == 1


def mesh_panel(chains):
    """Closed loop of named chains -> points, triangles, chain name -> vertex ids. Interior is a hexagonal grid."""
    names = list(chains)
    loop, ids, at = [], {}, 0
    for name in names:
        c = chains[name]
        loop.append(c[:-1])
        ids[name] = at + np.arange(len(c))
        at += len(c) - 1
    loop = np.vstack(loop)
    for name in names:
        ids[name] = ids[name] % len(loop)
    lo, hi = loop.min(axis=0), loop.max(axis=0)
    h = EDGE
    ys = np.arange(lo[1], hi[1], h * 0.866)
    grid = np.vstack([np.c_[np.arange(lo[0] + (i % 2) * h / 2, hi[0], h), np.full(len(np.arange(lo[0] + (i % 2) * h / 2, hi[0], h)), y)] for i, y in enumerate(ys)])
    grid = grid[inside(loop, grid)]
    grid = grid[cKDTree(loop).query(grid)[0] > 0.6 * h]
    pts = np.vstack([loop, grid])
    tri = Delaunay(pts).simplices
    tri = tri[inside(loop, pts[tri].mean(axis=1))]
    return pts, tri, ids


class Garment:
    """All panels in one index space, rest shape in 2D, seams as vertex pairs."""

    def __init__(self):
        self.x2, self.tri, self.seam, self.part = [], [], [], []
        self.n = 0
        self.names = []
        self.sleeve_base = {}

    def add(self, name, pts, tri):
        base = self.n
        self.x2.append(pts)
        self.tri.append(tri + base)
        self.part.append(np.full(len(pts), len(self.names)))
        self.names.append(name)
        self.n += len(pts)
        return base

    def sew(self, a, b):
        self.seam.append(np.c_[a, b])


def strip(g, name, ring, step, height, rows):
    """Rib band: an open strip one column longer than the closed ring it is sewn to, its two ends sewn together."""
    m = len(ring) + 1
    pts = np.array([[i * step, j * height / rows] for j in range(rows + 1) for i in range(m)])
    q = lambda i, j: j * m + i
    tri = np.array([[q(i, j), q(i + 1, j), q(i + 1, j + 1)] for j in range(rows) for i in range(m - 1)]
                   + [[q(i, j), q(i + 1, j + 1), q(i, j + 1)] for j in range(rows) for i in range(m - 1)])
    base = g.add(name, pts, tri)
    g.sew(ring, base + np.arange(m - 1))
    g.sew(base + m - 1 + m * np.arange(rows + 1), base + m * np.arange(rows + 1))
    return {"base": base, "m": m, "rows": rows, "ring": ring, "dz": height / rows}


def build(seg, size):
    """seg: pattern segments in metres per part. Returns the garment and each panel's chains in global ids."""
    F, B, S = seg["hugo.front"], seg["hugo.back"], seg["hugo.sleeve"]
    n = lambda *polys: max(3, round(max(length(p) for p in polys) / EDGE))
    hem_f, side_f, rag_f, neck_f = F[0], F[1], join(F[2], F[3]), F[4]
    hem_b, side_b, rag_b, neck_b = B[0], B[1], join(B[2], B[3]), B[4]
    n_hem, n_side, n_rf, n_rb, n_neck_f, n_neck_b = n(hem_f, hem_b), n(side_f, side_b), n(rag_f), n(rag_b), n(neck_f), n(neck_b)
    n_rf = n_rb = max(n_rf, n_rb)

    def torso(hem, side, rag, neck, n_neck):
        h = resample(join(flip(hem), hem), 2 * n_hem)
        return {"hem": h, "sideL": resample(side, n_side), "ragL": resample(rag, n_rf), "neck": resample(join(neck, flip(neck)), 2 * n_neck),
                "ragR": resample(flip(rag), n_rf), "sideR": resample(flip(side), n_side)}

    g = Garment()
    fp, ft, fi = mesh_panel(torso(hem_f, side_f, rag_f, neck_f, n_neck_f))
    bp, bt, bi = mesh_panel(torso(hem_b, side_b, rag_b, neck_b, n_neck_b))
    fb, bb = g.add("front", fp, ft), g.add("back", bp, bt)
    g.sew(fi["sideL"] + fb, bi["sideL"] + bb)
    g.sew(fi["sideR"] + fb, bi["sideR"] + bb)

    s_front, s_back = join(S[2], S[3]), join(S[7], S[8])
    n_ua, n_cuff = n(S[4], S[6]), n(S[5])
    n_sn = n(join(S[0], S[1]))
    sleeve = {"neck": resample(join(S[0], S[1]), n_sn), "front": resample(s_front, n_rf), "underF": resample(S[4], n_ua), "cuff": resample(S[5], n_cuff),
              "underB": resample(S[6], n_ua), "back": resample(s_back, n_rf)}
    sp, st, si = mesh_panel(sleeve)
    for side in "LR":
        b = g.add(f"sleeve{side}", sp, st)
        rag_front, rag_back = fi[f"rag{side}"] + fb, bi[f"rag{side}"] + bb
        if side == "R":
            rag_front, rag_back = rag_front[::-1], rag_back[::-1]
        g.sew(rag_front, si["front"][::-1] + b)      # underarm to neck on both
        g.sew(rag_back, si["back"] + b)
        g.sew(si["underF"] + b, si["underB"][::-1] + b)
        g.sleeve_base[side] = b
    g.chains = {"front": {k: v + fb for k, v in fi.items()}, "back": {k: v + bb for k, v in bi.items()}, "sleeve": si, "n_cuff": n_cuff}

    hem_ring = np.r_[g.chains["front"]["hem"], g.chains["back"]["hem"][::-1]]
    rib_h = RIB_H[size]
    step = np.linalg.norm(fp[fi["hem"][1]] - fp[fi["hem"][0]])
    g.strips = {"rib": strip(g, "rib", hem_ring, step * 0.93, rib_h, 5)}
    cuff_step = np.linalg.norm(sp[si["cuff"][1]] - sp[si["cuff"][0]])
    for side in "LR":
        ring = g.sleeve_base[side] + si["cuff"][:-1]
        g.strips[f"cuff{side}"] = strip(g, f"cuff{side}", ring, cuff_step * 0.95, rib_h, 4)
    return g, si, sp


def arm_line(verts, shoulder, wrist):
    """Centre line and radius of the left arm along shoulder -> wrist: the arm bends at the elbow, a straight axis leaves it."""
    arm = wrist - shoulder
    al = np.linalg.norm(arm)
    d = arm / al
    t = (verts - shoulder) @ d
    off = np.linalg.norm(verts - shoulder - np.outer(t, d), axis=1)
    keep = (verts[:, 0] > shoulder[0] - 0.02) & (t > -0.01) & (t < al + 0.02) & (off < 0.11)
    bins = np.arange(0, al + 0.03, 0.03)
    centre, radius = [], []
    for b in bins:
        m = keep & (np.abs(t - b) < 0.02)
        c = (verts[m].min(axis=0) + verts[m].max(axis=0)) / 2
        centre.append(c)
        radius.append(np.linalg.norm(verts[m] - c, axis=1).max())
    return bins, np.array(centre), np.array(radius), al, d


def wrap(g, seg, sp, verts, shoulder, wrist, torso_axes, cy, z_hps):
    """First 3D position of every vertex: torso on an ellipse, sleeves around the arm axis. Nothing is sewn yet."""
    x = np.zeros((g.n, 3))
    F = np.asarray(seg["hugo.front"][1])
    half = float(F[:, 0].max())
    a, b = torso_axes
    rm = half * 2 / np.pi
    for name, sign in (("front", -1), ("back", 1)):
        mask = g.part_id == g.names.index(name)
        p = g.points[mask]
        phi = np.clip(p[:, 0] / rm, -np.pi / 2, np.pi / 2)
        top = p[:, 1].min()
        x[mask] = np.c_[a * np.sin(phi), cy + sign * b * np.cos(phi), z_hps + 0.03 - (p[:, 1] - top)]

    neck_pt = np.array([0.07, cy, z_hps])
    bins, centre, radius, al, d = arm_line(verts, shoulder, wrist)
    e1 = np.cross(d, [0, 1, 0])
    e1 *= np.sign(e1[2]) or 1
    e2 = np.array([0, -1, 0.0])
    ys = np.linspace(sp[:, 1].min(), sp[:, 1].max(), 60)
    hw = np.array([np.abs(sp[np.abs(sp[:, 1] - y) < 0.03, 0]).max() for y in ys])
    for side, tag in (("L", 1), ("R", -1)):
        mask = g.part_id == g.names.index(f"sleeve{side}")
        p = g.points[mask]
        w = np.maximum(np.interp(p[:, 1], ys, hw), 1e-3)
        cuff_y = sp[:, 1].max()
        t = p[:, 1] * (al - 0.06) / cuff_y
        t = np.clip(t, 0, al)
        axis = np.c_[[np.interp(t, bins, centre[:, i]) for i in range(3)]].T
        up = p[:, 1] < 0
        f = (-p[up, 1] / -sp[:, 1].min())[:, None]
        axis[up] = centre[0] * (1 - f) + neck_pt * f
        psi = np.clip(p[:, 0] / w, -1, 1) * np.pi
        r = (np.maximum(w / np.pi, np.interp(t, bins, radius)) + 0.012)[:, None]
        q = axis + r * (np.cos(psi)[:, None] * e1 - np.sin(psi)[:, None] * e2)
        q[:, 0] *= tag
        x[mask] = q

    for name, st in g.strips.items():
        base, m, rows = st["base"], st["m"], st["rows"]
        ring = np.vstack([x[st["ring"]], x[st["ring"][:1]]])
        along = np.array([0, 0, -1.0]) if name == "rib" else d * [1 if name == "cuffL" else -1, 1, 1]
        for j in range(rows + 1):
            x[base + j * m: base + (j + 1) * m] = ring + along * j * st["dz"]
    return x


def neck_ring(g, si):
    """Vertices around the neck opening in order, and its length in the flat pattern."""
    f, b = g.chains["front"]["neck"], g.chains["back"]["neck"]
    left, right = g.sleeve_base["L"] + si["neck"], g.sleeve_base["R"] + si["neck"]
    chain = [f, right[::-1][1:], b[::-1][1:], left[1:-1]]
    ring = np.concatenate(chain)
    flat = sum(np.linalg.norm(np.diff(g.points[c], axis=0), axis=1).sum() for c in (f, b, left, right))
    return ring, float(flat)


def neck_tethers(g, si):
    """Stretch-only ties across the neck opening. A neck binding and the hood hold this edge on a real garment."""
    ring, flat = neck_ring(g, si)
    m = len(ring)
    pairs = np.array([[ring[i], ring[(i + m // 2) % m]] for i in range(m // 2)] + [[ring[i], ring[(i + m // 4) % m]] for i in range(m)])
    rest = np.r_[np.full(m // 2, flat / np.pi * 1.2), np.full(m, flat / np.pi * 1.2 * 0.72)]
    return pairs, rest


def constraints(g):
    tri = np.vstack(g.tri)
    a = np.sort(np.vstack([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1)
    third = np.r_[tri[:, 2], tri[:, 0], tri[:, 1]]
    key = a[:, 0] * g.n + a[:, 1]
    order = np.argsort(key)
    key, a, third = key[order], a[order], third[order]
    uniq, first = np.unique(key, return_index=True)
    edges = a[first]
    same = np.where(key[:-1] == key[1:])[0]
    bends = np.c_[third[same], third[same + 1]]
    return edges, bends


def color(pairs):
    """Greedy colouring: pairs in one colour share no vertex, so they can solve in parallel."""
    used, colors = {}, np.zeros(len(pairs), int)
    for k, (i, j) in enumerate(pairs):
        ui, uj = used.setdefault(int(i), set()), used.setdefault(int(j), set())
        c = 0
        while c in ui or c in uj:
            c += 1
        colors[k] = c
        ui.add(c)
        uj.add(c)
    return colors


def groups(pairs, rest, stretch, compress):
    out = []
    colors = color(pairs)
    for c in range(colors.max() + 1):
        s = colors == c
        out.append((mx.array(pairs[s, 0]), mx.array(pairs[s, 1]), mx.array(rest[s].astype(np.float32)), mx.array(stretch[s].astype(np.float32)), mx.array(compress[s].astype(np.float32))))
    return out


class Field:
    """Signed distance to the body on a grid, plus its gradient."""

    def __init__(self, verts, faces, lo, hi):
        self.lo = np.asarray(lo, np.float32)
        shape = np.ceil((np.asarray(hi) - lo) / GRID).astype(int) + 1
        axes = [self.lo[i] + np.arange(shape[i]) * GRID for i in range(3)]
        pts = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3).astype(np.float32)
        d = -SDF(verts, faces)(pts).reshape(shape).astype(np.float32)  # pysdf is positive inside
        grad = np.stack(np.gradient(d, GRID), -1).astype(np.float32)
        self.shape, self.d, self.g = shape, mx.array(d), mx.array(grad)
        self.hi_i = mx.array((shape - 2).astype(np.int32))
        self.lo_m = mx.array(self.lo)

    def sample(self, x):
        u = (x - self.lo_m) / GRID
        i = mx.clip(mx.floor(u).astype(mx.int32), 0, self.hi_i)
        f = mx.clip(u - i, 0, 1)
        s = self.shape
        idx = lambda a, b, c: (i[:, 0] + a) * s[1] * s[2] + (i[:, 1] + b) * s[2] + (i[:, 2] + c)
        w = lambda a, b, c: (f[:, 0] if a else 1 - f[:, 0]) * (f[:, 1] if b else 1 - f[:, 1]) * (f[:, 2] if c else 1 - f[:, 2])
        dv, gv = 0, 0
        fd, fg = self.d.reshape(-1), self.g.reshape(-1, 3)
        for a in (0, 1):
            for b in (0, 1):
                for c in (0, 1):
                    k, ww = idx(a, b, c), w(a, b, c)
                    dv = dv + fd[k] * ww
                    gv = gv + fg[k] * ww[:, None]
        return dv, gv


def solve(x, sets, field, grav, iters, seam_k=1.0, drag=0.985, prev=None, pins=None):
    v = prev if prev is not None else mx.zeros_like(x)
    p = x + DT * (v * drag + DT * mx.array([0, 0, grav], dtype=mx.float32))
    for _ in range(iters):
        for name, gs in sets:
            scale = seam_k if name == "seam" else 1.0
            for i, j, rest, stretch, compress in gs:
                d = p[j] - p[i]
                l = mx.sqrt((d * d).sum(1) + 1e-12)
                c = l - rest
                k = mx.where(c > 0, stretch, compress) * scale
                move = (0.5 * k * c / l)[:, None] * d
                p = p.at[i].add(move)
                p = p.at[j].add(-move)
        dist, grad = field.sample(p)
        hit = dist < SKIN
        norm = mx.sqrt((grad * grad).sum(1) + 1e-12)[:, None]
        n = grad / norm
        push = (SKIN - dist)[:, None] * n
        move = p - x
        tangent = move - (move * n).sum(1)[:, None] * n
        p = mx.where(hit[:, None], p + push - 0.25 * tangent, p)
        if pins is not None:
            ids, target, k = pins
            p = p.at[ids].add(k * (target - p[ids]))
    return p, (p - x) / DT


def cuff_pins(g, x, wrist_l, shrink=0.75):
    """Cuff end rings follow the wrists: rib holds a real cuff there, and the solver has no self-grip to do the same."""
    ids, targets = [], []
    for side, tag in (("L", 1), ("R", -1)):
        st = g.strips[f"cuff{side}"]
        ring = st["base"] + st["rows"] * st["m"] + np.arange(st["m"])
        here = x[ring]
        wrist = wrist_l * [tag, 1, 1]
        ids.append(ring)
        targets.append(wrist + (here - here.mean(axis=0)) * shrink)
    return mx.array(np.concatenate(ids)), mx.array(np.vstack(targets).astype(np.float32))


def main(pid, size, panels_file):
    seg = {k: [np.asarray(s) / 1000 for s in v] for k, v in json.load(open(panels_file))[size].items()}
    body = np.load(OUT / f"bodies/{pid}.npz")
    frames, faces = body["frames"].astype(np.float64), body["f"]
    H = frames[0][:, 2].max()
    t0 = time.time()
    g, si, sp = build(seg, size)
    g.points, g.part_id = np.vstack(g.x2), np.concatenate(g.part)
    v0 = frames[0]
    band = np.abs(v0[:, 2] - 0.72 * H) < 0.015
    mid = band & (np.abs(v0[:, 0]) < 0.24)
    cy, ax, by = float(v0[mid, 1].min() + v0[mid, 1].max()) / 2, float(np.ptp(v0[mid, 0])) / 2, float(np.ptp(v0[mid, 1])) / 2
    x = wrap(g, seg, sp, v0, body["shoulder"], body["wrist"], (max(ax + 0.03, 0.17), max(by + 0.03, 0.13)), cy, 0.82 * H)

    edges, bends = constraints(g)
    pts = g.points
    rest = np.linalg.norm(pts[edges[:, 0]] - pts[edges[:, 1]], axis=1)
    bend_rest = np.linalg.norm(pts[bends[:, 0]] - pts[bends[:, 1]], axis=1)
    seam = np.vstack(g.seam)
    is_rib = g.part_id[edges[:, 0]] >= g.names.index("rib")
    ones = lambda n, v: np.full(n, v)
    ties, tie_rest = neck_tethers(g, si)
    sets = [("tie", groups(ties, tie_rest, ones(len(ties), 1.0), ones(len(ties), 0.0))),
            ("edge", groups(edges, rest, np.where(is_rib, 0.5, 1.0), ones(len(edges), 0.35))),
            ("bend", groups(bends, bend_rest, ones(len(bends), 0.06), ones(len(bends), 0.06))),
            ("seam", groups(seam, np.zeros(len(seam)), ones(len(seam), 1.0), ones(len(seam), 0.0)))]
    print("mesh", g.n, "verts", len(edges), "edges", len(bends), "bends", len(seam), "seam pairs", "colours", [len(s[1]) for s in sets], f"{time.time() - t0:.1f} s", flush=True)

    lo = [frames[..., 0].min() - 0.08, frames[..., 1].min() - 0.08, 0.3 * H]
    hi = [frames[..., 0].max() + 0.08, frames[..., 1].max() + 0.08, H + 0.08]
    x = mx.array(x.astype(np.float32))
    t0 = time.time()
    field = Field(frames[0], faces, lo, hi)
    print("field", field.shape, f"{time.time() - t0:.1f} s", flush=True)
    v = None
    t0 = time.time()
    out = OUT / f"sim/{pid}__{size}"
    out.mkdir(parents=True, exist_ok=True)
    tri = np.vstack(g.tri)

    def snapshot(tag):
        np.savez(out / f"{tag}.npz", x=np.array(x), tri=tri, part=g.part_id, names=np.array(g.names), uv=g.points)

    def run(steps, grav, iters, seam_k, drag, label, pins=None):
        nonlocal x, v
        for s in range(steps):
            k = seam_k(s / steps) if callable(seam_k) else seam_k
            x, v = solve(x, sets, field, grav, iters, k, drag, v, pins)
            mx.eval(x, v)
        rb = g.strips["rib"]
        print(label, f"{time.time() - t0:.1f} s", "hem z", round(float(x[rb["base"] + rb["rows"] * rb["m"]:rb["base"] + (rb["rows"] + 1) * rb["m"], 2].mean()), 3), flush=True)
        snapshot(label)

    snapshot("start")
    wrists = body["wrists"].astype(np.float64)
    run(700, 0.0, 3, lambda f: 0.03 + 0.97 * f * f, 0.97, "sew")
    ids, target = cuff_pins(g, np.array(x), wrists[0])
    run(300, 0.0, 3, 1.0, 0.97, "cuffs", (ids, target, 0.05))
    run(500, GRAVITY, 4, 1.0, 0.975, "settle", (ids, target, 0.2))
    for i, frame in enumerate(frames[1:], 1):
        field = Field(frame, faces, lo, hi)
        ids, target = cuff_pins(g, np.array(x), wrists[i])
        run(70, GRAVITY, 4, 1.0, 0.975, f"arm{i:02d}" if i % 4 == 0 else "armx", (ids, target, 0.2))
    run(900, GRAVITY, 5, 1.0, 0.985, "final", (ids, target, 0.2))
    z = np.array(x)
    rb = g.strips["rib"]
    hem = z[rb["base"] + rb["rows"] * rb["m"]: rb["base"] + (rb["rows"] + 1) * rb["m"]]
    neck = z[g.chains["back"]["neck"]]
    print("hem z", round(float(hem[:, 2].mean()), 3), "front", round(float(np.median(hem[hem[:, 1] < cy, 2])), 3), "back", round(float(np.median(hem[hem[:, 1] > cy, 2])), 3),
          "neck top", round(float(neck[:, 2].max()), 3))
    front = hem[(hem[:, 1] < cy) & (np.abs(hem[:, 0]) < 0.05), 2]  # the middle of the front, where the photo is measured
    (out / "hem.json").write_text(json.dumps({"hem_z": float(hem[:, 2].mean()), "front": float(front.mean()), "neck_top": float(neck[:, 2].max())}))


if __name__ == "__main__":
    main(*sys.argv[1:4])
