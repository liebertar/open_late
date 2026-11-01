"""Render engine: FLUX.2 klein 4B kept in memory, one GPU job at a time.

Runs natively on the Mac (MLX/Metal); Docker cannot reach the GPU. The console in Docker
calls it at http://host.docker.internal:8091.

    GET  /health        model loaded? queue length, average seconds per kind
    POST /jobs          {kind, prompt, refs, out, seed?, width?, height?, steps?,
                         console_job?, step?, total?}   step/total: one console job tracks a batch
    GET  /jobs/{id}     queued | running | done | failed, seconds, position
    POST /normalize     {path, height_cm} re-stage an existing image at true scale (backfill)
    POST /jobs {kind: "head", out, prompt, seed, keep?}  re-draw face and hair of an existing portrait

Image models draw every person filling the frame, so a 155 cm and a 182 cm person come out the same size.
When a job carries meta.height_cm, the person is cut out and re-staged on a shared canvas where 1 cm is the
same number of pixels for everyone, feet on one floor line (<out>.scaled.png). The cut-out also gives
silhouette widths relative to height, used to catch bodies that came out wrong for their size.

All paths are relative to DATA_DIR (open_late/data). A finished render writes
<out> and <out>.json (seconds, seed, prompt, kind) so the console can index renders from files.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path

import httpx
from fastapi import Body, FastAPI, HTTPException

DATA = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
CONSOLE = os.environ.get("CONSOLE_URL", "http://127.0.0.1:7100")
QUANTIZE = int(os.environ.get("QUANTIZE", "4"))  # FLUX.2 klein (try-on edits)
# Portraits: Z-Image-Turbo won the bake-off (data/fitting/bakeoff/run1): matte skin, full body, model look.
PORTRAIT_KIND = "zimage" if os.environ.get("PORTRAIT_MODEL", "zimage") == "zimage" else "t2i"
MODEL_NAME = {"edit": "FLUX.2 klein 4B", "t2i": "FLUX.2 klein 4B", "zimage": "Z-Image-Turbo 6B"}
STEPS = {"edit": 4, "t2i": 4, "zimage": 9}
HEAD_KEEP = 0.3  # head pass: mflux image_strength is the share of the original kept; 0.3 restyles hair, keeps the pose
CURRENT = {"portrait": MODEL_NAME[PORTRAIT_KIND], "tryon": MODEL_NAME["edit"]}  # what averages describe
TIMINGS = DATA / "fitting" / "timings.jsonl"
CANVAS = (768, 1024)          # same size as the renders
FLOOR_Y, TOP_Y = 980, 24      # feet line and the top of a 200 cm person
PX_PER_CM = (FLOOR_Y - TOP_Y) / 200
BACKDROP = (239, 239, 239)    # #EFEFEF, the catalog backdrop

app = FastAPI(title="OPEN LATE render engine")
_q: queue.Queue[str] = queue.Queue()
_jobs: dict[str, dict] = {}
_order: list[str] = []
_models: dict[str, object] = {}  # "edit", "t2i" (klein without references), "zimage"; loaded on first use
_lock = threading.Lock()


def _console(path: str, body: dict) -> None:
    """Progress for the console's job panel. Rendering never depends on the console being up."""
    try:
        httpx.post(f"{CONSOLE}{path}", json=body, timeout=3)
    except httpx.HTTPError:
        pass


def _load(kind: str = "edit"):
    """edit: klein with reference images (try-on). t2i: klein text-only. zimage: Z-Image-Turbo (portraits)."""
    if kind not in _models:
        from mflux.models.common.config.model_config import ModelConfig
        if kind == "zimage":
            from mflux.models.z_image import ZImage
            _models[kind] = ZImage(model_config=ModelConfig.z_image_turbo(), quantize=8)  # q8 = bf16 speed, half memory
        else:
            from mflux.models.flux2.variants import Flux2Klein, Flux2KleinEdit
            cls = Flux2KleinEdit if kind == "edit" else Flux2Klein
            _models[kind] = cls(quantize=QUANTIZE, model_config=ModelConfig.flux2_klein_4b())
    return _models[kind]


MATTE = os.environ.get("MATTE_MODEL", "birefnet-portrait")  # MIT; u2net_human_seg left a grey rim on light canvases
_mattes: dict[str, object] = {}


def _cutout(img):
    """Person RGBA: BiRefNet matte (~5 s on CPU), edge colours cleaned of the backdrop, interior fully opaque.

    The renders sit on a mid-grey backdrop and the staging canvas is light, so semi-transparent edge pixels still carry the
    old grey and draw a dark outline. F = (C - (1 - a) * B) / a removes it, with B the backdrop blurred in from outside."""
    import cv2
    import numpy as np
    from PIL import Image
    from rembg import new_session, remove
    if MATTE not in _mattes:
        _mattes[MATTE] = new_session(MATTE)
    rgb = img.convert("RGB")
    a = np.asarray(remove(rgb, session=_mattes[MATTE]))[:, :, 3].astype(np.float32) / 255
    C = np.asarray(rgb, dtype=np.float32)
    outside = (a < 0.02).astype(np.float32)
    B = cv2.GaussianBlur(C * outside[..., None], (0, 0), 12) / (cv2.GaussianBlur(outside, (0, 0), 12)[..., None] + 1e-4)
    a3 = a[..., None]
    F = np.clip((C - (1 - a3) * B) / np.maximum(a3, 0.05), 0, 255)
    rgb_clean = np.where((a3 > 0.02) & (a3 < 0.98), F, C).astype(np.uint8)
    alpha = (np.clip((a - 0.08) / 0.84, 0, 1) * 255).astype(np.uint8)  # opaque inside, slightly tighter fringe
    return Image.fromarray(np.dstack([rgb_clean, alpha]), "RGBA")


def normalize(src: Path, height_cm: float) -> dict:
    """Re-stage the person at true scale and measure the silhouette. Returns sidecar fields."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    cut = _cutout(Image.open(src))
    alpha = np.asarray(cut)[:, :, 3] > 128
    ys, xs = np.where(alpha)
    if len(ys) == 0:
        return {"scale_error": "no person found"}
    box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    person, mask = cut.crop(box), alpha[box[1]:box[3], box[0]:box[2]]
    h_px = round(height_cm * PX_PER_CM)
    w_px = max(1, round(person.width * h_px / person.height))
    person = person.resize((w_px, h_px), Image.LANCZOS)
    canvas = Image.new("RGB", CANVAS, BACKDROP)
    shadow = Image.new("L", CANVAS, 0)
    ImageDraw.Draw(shadow).ellipse((CANVAS[0] // 2 - w_px * 0.32, FLOOR_Y - 7, CANVAS[0] // 2 + w_px * 0.32, FLOOR_Y + 7), fill=70)
    canvas.paste((205, 205, 205), mask=shadow.filter(ImageFilter.GaussianBlur(6)))
    at = (CANVAS[0] // 2 - w_px // 2, FLOOR_Y - h_px)
    canvas.paste(person, at, person)
    out = src.with_name(src.stem + ".scaled.png")
    canvas.save(out)
    # the same staging on a transparent canvas: line-ups overlap neighbours without one backdrop hiding another
    clear = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    clear.paste(Image.new("RGBA", CANVAS, (0, 0, 0, 40)), mask=shadow.filter(ImageFilter.GaussianBlur(6)))
    clear.alpha_composite(person, at)
    cut = src.with_name(src.stem + ".cut.png")
    clear.save(cut)
    rows = mask.shape[0]
    width_at = lambda f: round(float(mask[int(rows * f)].sum()) / rows, 3)  # silhouette width / height
    cropped = bool(box[1] <= 2 or box[3] >= alpha.shape[0] - 2)  # head or feet cut off by the frame
    return {"scaled": str(out.relative_to(DATA)), "cutout": str(cut.relative_to(DATA)), "height_cm": height_cm,
            "silhouette": {"fill": round(rows / Image.open(src).height, 3),  # how much of the frame the model used
                           "w_shoulder": width_at(0.20), "w_chest": width_at(0.30), "w_hip": width_at(0.52),
                           "cropped": cropped}}


def _averages() -> dict:
    if not TIMINGS.exists():
        return {}
    acc: dict[str, list[float]] = {}
    for line in TIMINGS.read_text().splitlines()[-400:]:
        t = json.loads(line)
        if t["kind"] in CURRENT and t.get("model", "FLUX.2 klein 4B") != CURRENT[t["kind"]]:
            continue  # timings of a model no longer in use (lines without a model predate the switch)
        acc.setdefault(t["kind"], []).append(t["seconds"])
    return {k: {"avg": round(sum(v) / len(v), 1), "n": len(v)} for k, v in acc.items()}


def _head_box(img) -> tuple[int, int, int, int]:
    """Square around head and hair from a coarse person mask (these bodies are about 7.5 heads tall)."""
    import numpy as np
    from rembg import new_session, remove
    if "u2net_human_seg" not in _mattes:
        _mattes["u2net_human_seg"] = new_session("u2net_human_seg")
    a = np.asarray(remove(img, session=_mattes["u2net_human_seg"]))[:, :, 3] > 128
    ys, _ = np.where(a)
    top, bottom = int(ys.min()), int(ys.max())
    h = 0.13 * (bottom - top)
    cols = np.where(a[top:int(top + h)].any(axis=0))[0]
    cx, cy, side = (cols.min() + cols.max()) / 2, top + 0.55 * h, int(2.4 * h)
    x0, y0 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
    return x0, y0, min(img.width, x0 + side), min(img.height, y0 + side)


def _head_pass(job: dict) -> float:
    """Re-draw face and hair on a 1024 px crop of the head and paste it back. The body, and with it the size QA, stays.

    A full-body 768x1024 render gives the face ~70 px, so faces and hair come out generic. The pass always starts from
    <name>.base.png (the body render before any head pass), so repeated passes never stack."""
    from PIL import Image, ImageDraw, ImageFilter
    path = DATA / job["out"]
    base = path.with_name(path.stem + ".base.png")
    if not base.exists():
        shutil.copyfile(path, base)
    src = Image.open(base).convert("RGB")
    box = _head_box(src)
    crop = src.crop(box)
    crop_in = path.with_name(path.stem + ".head-in.png")
    crop.resize((1024, 1024), Image.LANCZOS).save(crop_in)
    t0 = time.time()
    res = _load("zimage").generate_image(seed=job["seed"], prompt=job["prompt"], num_inference_steps=job["steps"] or STEPS["zimage"],
                                         width=1024, height=1024, image_path=str(crop_in), image_strength=job.get("keep") or HEAD_KEEP)
    seconds = round(time.time() - t0, 1)
    crop_in.unlink(missing_ok=True)
    w, h = crop.size
    mask = Image.new("L", crop.size, 0)
    ImageDraw.Draw(mask).ellipse((w * 0.16, 0, w * 0.84, h * 0.74), fill=255)  # head and hair, not straps or shoulders
    out = src.copy()
    out.paste(res.image.convert("RGB").resize(crop.size, Image.LANCZOS), box[:2], mask.filter(ImageFilter.GaussianBlur(w * 0.06)))
    out.save(path)
    return seconds


def _render(job: dict) -> tuple[str, float]:
    """One generation job: text-to-image portrait or a reference edit (try-on). Writes the image and its sidecar."""
    kind = "edit" if job["refs"] else PORTRAIT_KIND if job["kind"] == "portrait" else "t2i"
    model = _load(kind)
    params = dict(seed=job["seed"], prompt=job["prompt"], num_inference_steps=job["steps"] or STEPS[kind],
                  width=job["width"], height=job["height"])
    if kind != "zimage":  # Z-Image-Turbo is guidance-distilled
        params["guidance"] = 1.0
    if kind == "edit":
        params["image_paths"] = [DATA / r for r in job["refs"]]
    t0 = time.time()
    image = model.generate_image(**params)
    seconds = round(time.time() - t0, 1)
    out = DATA / job["out"]
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(path=str(out), overwrite=True)  # mflux otherwise writes name_1.png and keeps the old file
    if job["kind"] == "portrait":
        out.with_name(out.stem + ".base.png").unlink(missing_ok=True)  # a new body: the old head-pass base is stale
    sidecar = {"kind": job["kind"], "model": MODEL_NAME[kind], "seconds": seconds, "seed": job["seed"],
               "prompt": job["prompt"], "refs": job["refs"], "meta": job.get("meta", {}),
               "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    if job.get("meta", {}).get("height_cm"):
        sidecar |= normalize(out, float(job["meta"]["height_cm"]))
    out.with_suffix(out.suffix + ".json").write_text(json.dumps(sidecar, ensure_ascii=False, indent=2))
    return kind, seconds


def _head(job: dict) -> tuple[str, float]:
    """Head pass on an existing portrait; merges into its sidecar and re-stages it."""
    out = DATA / job["out"]
    seconds = _head_pass(job)
    side_path = out.with_suffix(out.suffix + ".json")
    sidecar = json.loads(side_path.read_text()) if side_path.exists() else {}
    sidecar["head"] = {**job.get("meta", {}), "seconds": seconds, "seed": job["seed"], "keep": job.get("keep") or HEAD_KEEP,
                       "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    height = (sidecar.get("meta") or {}).get("height_cm")
    if height:
        sidecar |= normalize(out, float(height))
    side_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2))
    return "zimage", seconds


def _worker():
    # MLX streams are per thread: load models on the thread that renders with them, never on another one
    if os.environ.get("PRELOAD", "1") == "1":
        _load("edit")
    while True:
        jid = _q.get()
        job = _jobs[jid]
        if job["status"] == "cancelled":
            _q.task_done()
            continue
        job.update(status="running", started=time.time())
        cj, step, total = job.get("console_job"), job.get("step"), job.get("total")
        last = step is None or step >= total
        if cj:
            _console(f"/api/jobs/{cj}", {"message": f"Rendering {step}/{total}" if step else "Rendering"})
        try:
            kind, seconds = (_head if job["kind"] == "head" else _render)(job)
            with _lock, open(TIMINGS, "a") as f:
                f.write(json.dumps({"kind": job["kind"], "model": MODEL_NAME[kind], "seconds": seconds,
                                    "ts": time.time()}) + "\n")
            job.update(status="done", seconds=seconds)
            if cj:
                _console(f"/api/jobs/{cj}", {"done": step or 1, "message": f"{seconds} s",
                                             "status": "done" if last else None, "link": job.get("link")})
        except Exception as e:  # report and keep the worker alive
            job.update(status="failed", error=str(e)[:300])
            if cj:
                _console(f"/api/jobs/{cj}", {"message": str(e)[:200], "status": "failed" if last else None})
        finally:
            _q.task_done()


@app.on_event("startup")
def _start():
    TIMINGS.parent.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_worker, daemon=True).start()


@app.get("/health")
def health():
    return {"loaded": sorted(_models), "queue": _q.qsize(),
            "busy": any(j["status"] == "running" for j in _jobs.values()), "averages": _averages(),
            "model": f"{CURRENT['portrait']} · {CURRENT['tryon']}", "models": CURRENT}


@app.post("/jobs")
def submit(body: dict = Body(...)):
    for key in ("kind", "prompt", "out"):
        if not body.get(key):
            raise HTTPException(400, f"{key} is required")
    out = (DATA / body["out"]).resolve()
    if DATA.resolve() not in out.parents:
        raise HTTPException(400, "out must stay inside DATA_DIR")
    jid = uuid.uuid4().hex[:10]
    _jobs[jid] = {"id": jid, "status": "queued", "kind": body["kind"], "prompt": body["prompt"],
                  "refs": body.get("refs", []), "out": body["out"], "seed": int(body.get("seed", 7)),
                  "width": int(body.get("width", 768)), "height": int(body.get("height", 1024)),
                  "steps": int(body.get("steps") or 0), "console_job": body.get("console_job"),
                  "step": body.get("step"), "total": body.get("total"),
                  "link": body.get("link"), "meta": body.get("meta", {}), "keep": body.get("keep"), "queued": time.time()}
    _order.append(jid)
    _q.put(jid)
    return {"id": jid, "position": _q.qsize()}


@app.post("/jobs/{jid}/cancel")
def cancel(jid: str):
    """Drop a queued job. A running one cannot stop mid-step, so it finishes and its result stays usable."""
    job = _jobs.get(jid)
    if not job:
        raise HTTPException(404, "unknown job")
    if job["status"] == "queued":
        job["status"] = "cancelled"
        if job.get("console_job"):
            _console(f"/api/jobs/{job['console_job']}", {"message": "Cancelled", "status": "failed"})
    return {"status": job["status"]}


@app.post("/normalize")
def normalize_existing(body: dict = Body(...)):
    src = (DATA / body.get("path", "")).resolve()
    if DATA.resolve() not in src.parents or not src.exists():
        raise HTTPException(400, "path must be an existing file inside DATA_DIR")
    side = src.with_suffix(src.suffix + ".json")
    meta = json.loads(side.read_text()) if side.exists() else {}
    meta |= normalize(src, float(body["height_cm"]))
    side.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return {k: meta[k] for k in ("scaled", "silhouette") if k in meta}


@app.get("/jobs/{jid}")
def status(jid: str):
    job = _jobs.get(jid)
    if not job:
        raise HTTPException(404, "unknown job")
    waiting = [j for j in _order if _jobs[j]["status"] == "queued"]
    return {k: job.get(k) for k in ("id", "status", "kind", "out", "seconds", "error")} | {
        "position": waiting.index(jid) + 1 if jid in waiting else 0,
        "elapsed": round(time.time() - job["started"], 1) if job.get("started") and job["status"] == "running" else None}
