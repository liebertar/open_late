"""Fitting room: synthetic models per size, garments per colorway, try-on renders through the host engine.

Fit is computed, not guessed: each model has body measurements (FreeSewing body sets for the people
who wear that size), each garment size has finished measurements (from the latest pattern run).
The difference drives both the numbers shown in the UI and the wording of the render prompt.

Scale is measured, not prompted: image models fill the frame whatever the height, so the engine cuts
each person out and re-stages them at true scale (meta.height_cm). The cut-out's silhouette widths are
used to check that bodies get wider from XS to XL within a group.

    GET  /api/fitting/catalog            models, garments, sizes, cached renders, timings, engine status
    POST /api/fitting/models/head        {ids?, force?} re-draw face and hair of existing portraits (bodies stay)
    POST /api/fitting/views              {model, garment, size} side and back stills of a finished try-on
    POST /api/fitting/models/build       {ids?, force?, stale?, reroll?} render missing / outdated portraits;
                                         reroll re-draws with a new seed (bodies that failed the size-order check)
    POST /api/fitting/tryon              {model, garment, size} -> ready | queued
    GET  /api/fitting/tryon/{key}        ready | queued | running | failed
    DELETE /api/fitting/tryon/{key}      stop waiting for a render
    POST /api/fitting/lineup             {gender, ethnicity, garment} everyone in their own size
    GET  /api/sizechart                  finished garment measurements + who wears each size
    GET  /api/engine                     render engine status
"""
from __future__ import annotations

import hashlib
import math
import shutil

import httpx
from fastapi import APIRouter, Body, HTTPException

from core import DATA, DOCS, ENGINE_URL, PATTERN_URL, job_start, load_state, prompt, read_json, render_prompt, write_json

router = APIRouter()
FIT = DATA / "fitting"
PORTRAITS, GARMENTS, RENDERS = FIT / "models", FIT / "garments", FIT / "renders"
VIEWS = FIT / "views"  # rotation stills per try-on: views/<render key>/v045.png ...
VIEW_ANGLES = ("045", "090", "135", "180")  # the viewer mirrors 135/90/45 for 225/270/315
for d in (PORTRAITS, GARMENTS, RENDERS):
    d.mkdir(parents=True, exist_ok=True)
BOARD = DOCS / "colorway-board"

GENDERS = {"female": "Woman", "male": "Man"}
ETHNICITIES = {"east_asian": "East Asian", "white": "White", "black": "Black", "arab": "Arab"}
FIT_WORDS = {  # code -> label on screen; prompt phrases live in pipeline/prompts/fitting.tryon.yaml
    "fit": {"tight": "Tight", "fitted": "Slim", "regular": "Regular", "relaxed": "Relaxed", "oversized": "Oversized"},
    "length": {"cropped": "Above the hip", "hip": "At the hip", "below_hip": "Below the hip", "thigh": "Mid-thigh"},
    # rib cuffs grip the wrist, so extra sleeve length stacks up the forearm instead of covering the hand
    "sleeve": {"short": "Above the wrist", "wrist": "At the wrist", "bunch": "Soft folds at the wrist", "long": "Stacks on the forearm"},
}

# Chest ease (mm) each fit preference aims for: the middle of the fit bands in fit(). Provisional until wear-tested.
PREF_EASE = {"slim": 60, "regular": 125, "relaxed": 210}

_pending: dict[str, str] = {}  # render key -> engine job id (in-memory; renders on disk are the truth)


def _url(rel: str | None) -> str | None:
    return f"/files/{rel}" if rel else None


# ---------- catalog ----------

def bodies() -> dict:
    """Body sets per gender and size, from the pattern service; cached so the room works offline."""
    cache = FIT / "bodies.json"
    try:
        data = httpx.get(f"{PATTERN_URL}/bodies", timeout=5).raise_for_status().json()
        if read_json(cache, None) != data:  # every page load asks; only write when the sets changed
            write_json(cache, data)
        return data
    except httpx.HTTPError:
        if cache.exists():
            return read_json(cache, {})
        raise HTTPException(503, "pattern service is down and no cached body sets")


def model_list(b: dict) -> list[dict]:
    parts = prompt("fitting.portrait")["parts"]
    head = prompt("fitting.head")["parts"]
    out = []
    for gender, gender_label in GENDERS.items():
        for size in b["sizes"]:
            body = b["bodies"][gender][size]
            for eth, eth_label in ETHNICITIES.items():
                mid = f"{gender[0]}-{size}-{eth}"
                h = int(hashlib.sha256(mid.encode()).hexdigest(), 16)
                photo = PORTRAITS / f"{mid}.png"
                age = 24 + h % 11
                text, ref = render_prompt(
                    "fitting.portrait", age=age, ethnicity=parts["ethnicity"][eth], person=parts["person"][gender],
                    build=parts["build"][gender][size], hair=parts["hair"][gender],
                    underwear=parts["underwear"][gender].format(shade=parts["shade"][eth]))
                meta = read_json(photo.with_suffix(".png.json"), {})
                hairs = head["hair"][gender][eth]
                hair = hairs[b["sizes"].index(size) % len(hairs)]  # one hairstyle per size slot within a lineup
                head_text, head_ref = render_prompt(
                    "fitting.head", age=age, ethnicity=parts["ethnicity"][eth], person=parts["person"][gender], hair=hair,
                    face=head["face"][size])
                out.append({
                    "id": mid, "gender": gender, "gender_label": gender_label, "size": size, "ethnicity": eth,
                    "ethnicity_label": eth_label, "age": age, "seed": h % 100000,
                    "height_cm": round(body["height"] / 10), "chest_cm": round(body["chest"] / 10),
                    "body": {k: body[k] for k in ("chest", "hips", "waist", "neck", "shoulderToShoulder",
                                                    "shoulderToWrist", "hpsToWaistBack", "waistToHips", "height")},
                    "portrait": _url(f"fitting/models/{mid}.png") if photo.exists() else None,
                    "staged": _url(meta.get("scaled")) if photo.exists() else None,  # true-scale version
                    "cutout": _url(meta.get("cutout")) if photo.exists() else None,  # same, transparent background
                    "silhouette": meta.get("silhouette"),
                    "portrait_seconds": meta.get("seconds"),
                    "portrait_prompt": (meta.get("meta") or {}).get("prompt"),  # id@version it was made with
                    # outdated only when this model's own prompt text changed, not when another size's wording did
                    "stale": photo.exists() and (meta.get("meta") or {}).get("prompt_hash") != ref["hash"],
                    "attempt": (meta.get("meta") or {}).get("attempt", 0),
                    "hair": hair, "head_done": (meta.get("head") or {}).get("prompt_hash") == head_ref["hash"],
                    "_prompt": text, "_ref": ref, "_head_prompt": head_text, "_head_ref": head_ref,
                })
    return out


def check_order(models: list[dict]) -> None:
    """Flags a body to re-roll: cut off by the frame, or hips narrower than the size below (relative to height)."""
    for m in models:
        sil = m.get("silhouette") or {}
        if sil.get("cropped", sil.get("fill", 0) >= 0.99):  # older sidecars have no crop flag: full-height fill
            m["order_issue"] = "Body cut off by the frame"
    sizes = list(dict.fromkeys(m["size"] for m in models))
    for gender in GENDERS:
        for eth in ETHNICITIES:
            group = sorted((m for m in models if m["gender"] == gender and m["ethnicity"] == eth),
                           key=lambda m: sizes.index(m["size"]))
            for prev, cur in zip(group, group[1:]):
                a, b = (prev.get("silhouette") or {}).get("w_hip"), (cur.get("silhouette") or {}).get("w_hip")
                if a and b and b + 0.01 < a:
                    cur["order_issue"] = f"Came out narrower than {prev['size']}"


def garment_list() -> list[dict]:
    """Colorways from the board, measurements from the latest Hugo pattern run."""
    cw = read_json(BOARD / "colorways.json", {"colorways": []})["colorways"]
    n04 = load_state().get("n04", {})
    measures = n04.get("measures", {}) if n04.get("design", "hugo") == "hugo" else {}
    out = []
    for c in cw:
        src = BOARD / "img" / f"{c['id']}_product.png"
        dst = GARMENTS / f"{c['id']}.png"
        if src.exists() and (not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime):
            shutil.copy(src, dst)
        out.append({"id": c["id"], "name": f"{c['outer']} × {c['lining']}", "outer": c["outer"], "outer_hex": c["outer_hex"],
                    "lining_hex": c["lining_hex"], "image": _url(f"fitting/garments/{c['id']}.png") if dst.exists() else None,
                    "measures": measures})
    return out


def fit(body: dict, g: dict) -> dict:
    """Garment vs body (mm) -> numbers and fit codes. Raglan sleeve is measured from the neck point."""
    ease = g["chest"] - body["chest"]
    length = g["length"] - (body["hpsToWaistBack"] + body["waistToHips"])
    sleeve = g["sleeve"] - (body["shoulderToShoulder"] / 2 - body["neck"] / (2 * math.pi) + body["shoulderToWrist"])

    def pick(v, table):
        return next(code for limit, code in table if v < limit)

    codes = {"fit": pick(ease, [(30, "tight"), (90, "fitted"), (160, "regular"), (260, "relaxed"), (math.inf, "oversized")]),
             "length": pick(length, [(-60, "cropped"), (30, "hip"), (110, "below_hip"), (math.inf, "thigh")]),
             "sleeve": pick(sleeve, [(-40, "short"), (40, "wrist"), (110, "bunch"), (math.inf, "long")])}
    return {"ease_mm": round(ease), "length_mm": round(length), "sleeve_mm": round(sleeve),
            **{k: FIT_WORDS[k][c] for k, c in codes.items()}, "codes": codes}


def recommend(fits: dict, sizes: list[str], pref: str) -> dict:
    """Two sizes, not one: the closest to the preferred ease and the neighbour on the side the body falls toward.
    Even models trained on purchase history get about 56% of orders right on the first guess and 82% within two.
    Confidence is how far the best size lands from the target, in thirds of half a size step (about 19 mm)."""
    target = PREF_EASE[pref]
    best = min(sizes, key=lambda s: abs(fits[s]["ease_mm"] - target))
    i, gap = sizes.index(best), fits[best]["ease_mm"] - target
    alt = sizes[i + 1] if i == 0 or (gap < 0 and i + 1 < len(sizes)) else sizes[i - 1]
    miss = abs(gap)
    return {"size": best, "alt": alt, "alt_dir": "roomier" if sizes.index(alt) > i else "closer",
            "confidence": "high" if miss <= 19 else "medium" if miss <= 38 else "low"}


def render_index() -> dict:
    out = {}
    for meta_path in RENDERS.glob("*.png.json"):
        key = meta_path.name[: -len(".png.json")]
        meta = read_json(meta_path, {})
        out[key] = {"url": _url(f"fitting/renders/{key}.png"), "staged": _url(meta.get("scaled")), "cutout": _url(meta.get("cutout")),
                    "seconds": meta.get("seconds"), "ts": meta.get("ts"), "prompt": (meta.get("meta") or {}).get("prompt")}
    return out


def view_index() -> dict:
    """{render key: {"045": true-scale url, ...}} for the rotation stills that exist."""
    out: dict[str, dict] = {}
    for side in VIEWS.glob("*/v*.png.json"):
        key, angle = side.parent.name, side.name[1:4]
        out.setdefault(key, {})[angle] = _url(read_json(side, {}).get("scaled")) or _url(f"fitting/views/{key}/v{angle}.png")
    return out


def _drop_outputs(mid: str) -> None:
    """Try-ons and rotation stills show the person as they were: remove them when the photo changes."""
    for f in RENDERS.glob(f"{mid}__*"):
        f.unlink()
    for d in VIEWS.glob(f"{mid}__*"):
        shutil.rmtree(d, ignore_errors=True)


def averages() -> dict:
    def avg(folder):
        secs = [read_json(p, {}).get("seconds") for p in folder.glob("*.png.json")]
        secs = [s for s in secs if s]
        return {"avg": round(sum(secs) / len(secs), 1), "n": len(secs)} if secs else None
    return {"tryon": avg(RENDERS), "portrait": avg(PORTRAITS)}


@router.get("/api/engine")
def engine_status() -> dict:
    try:
        return {"online": True, **httpx.get(f"{ENGINE_URL}/health", timeout=1.5).json()}
    except httpx.HTTPError:
        return {"online": False}


@router.get("/api/fitting/catalog")
def catalog():
    b = bodies()
    current = prompt("fitting.portrait")
    cur_ref = f"{current['id']}@{current['version']}"
    models = [{k: v for k, v in m.items() if not k.startswith("_")} for m in model_list(b)]
    garments = garment_list()
    measures = next((g["measures"] for g in garments if g["measures"]), {})
    for m in models:
        m["fits"] = {s: fit(m["body"], measures[s]) for s in b["sizes"] if s in measures}
        if len(m["fits"]) == len(b["sizes"]):
            m["reco"] = {p: recommend(m["fits"], b["sizes"], p) for p in PREF_EASE}
    check_order(models)
    return {"sizes": b["sizes"], "models": models, "portrait_prompt": cur_ref, "garments": garments,
            "renders": render_index(), "views": view_index(), "averages": averages(), "engine": engine_status(), "pending": list(_pending)}


@router.get("/api/fitting/prompts")
def portrait_prompts():
    """Rendered portrait prompt per model, for host scripts (bake-offs, regression runs) that must match production."""
    return {m["id"]: {"prompt": m["_prompt"], "ref": m["_ref"], "seed": m["seed"]} for m in model_list(bodies())}


@router.get("/api/sizechart")
def sizechart():
    """One chart for every page: finished garment measurements and the people each size is drafted for."""
    b = bodies()
    n04 = load_state().get("n04", {})
    measures = n04.get("measures", {}) if n04.get("design", "hugo") == "hugo" else {}
    cm = lambda mm: round(mm / 10, 1)  # noqa: E731
    return {
        "design": "Hugo hoodie", "sizes": b["sizes"], "source": n04.get("run"),
        "garment": {s: {k: cm(v) for k, v in measures[s].items()} for s in b["sizes"] if s in measures},
        "wearer": {g: {s: {"height": round(b["bodies"][g][s]["height"] / 10), "chest": cm(b["bodies"][g][s]["chest"])}
                       for s in b["sizes"]} for g in GENDERS},
        "note": "Finished measurements come from the latest pattern run. Bodies are the standard FreeSewing sets for now and will be replaced with Size Korea data.",
    }


# ---------- rendering ----------

def _engine_job(body: dict) -> dict:
    try:
        # 15 s: while a render holds the GIL (matting, image I/O) the engine can answer slowly
        return httpx.post(f"{ENGINE_URL}/jobs", json=body, timeout=15).raise_for_status().json()
    except httpx.HTTPError as e:
        raise HTTPException(503, f"Cannot reach the render engine ({e.__class__.__name__}). Run host/fitting/run.sh")


@router.post("/api/fitting/models/build")
def build_models(body: dict = Body(default={})):
    ids = set(body.get("ids") or [])

    def wanted(m):
        if ids and m["id"] not in ids:
            return False
        if body.get("force") or not m["portrait"]:
            return True
        return bool(body.get("stale")) and m["stale"]
    todo = [m for m in model_list(bodies()) if wanted(m)]
    if body.get("reroll") and not ids:  # default reroll target: bodies flagged by the size-order check
        flagged = [m for m in catalog()["models"] if m.get("order_issue")]
        todo = [m for m in model_list(bodies()) if m["id"] in {f["id"] for f in flagged}]
    if not todo:
        return {"queued": 0}
    for m in todo:  # try-ons of a person whose photo is being replaced would show the old person
        _drop_outputs(m["id"])
    total = 2 * len(todo)  # body, then its head pass
    cj = job_start(f"Model photos · {len(todo)}", None, total=total, kind="portrait")
    for i, m in enumerate(todo, 1):
        attempt = m["attempt"] + 1 if body.get("reroll") else 0
        _engine_job({"kind": "portrait", "prompt": m["_prompt"], "refs": [], "out": f"fitting/models/{m['id']}.png",
                     "seed": (m["seed"] + 7919 * attempt) % 100000, "console_job": cj, "step": 2 * i - 1, "total": total,
                     "link": "/fitting", "meta": {"prompt": f"{m['_ref']['id']}@{m['_ref']['version']}",
                                                  "prompt_hash": m["_ref"]["hash"], "height_cm": m["height_cm"],
                                                  "attempt": attempt}})
        _queue_head(m, cj, 2 * i, total)
    return {"queued": len(todo), "job": cj}


def _queue_head(m: dict, cj: str | None = None, step: int | None = None, total: int | None = None) -> dict:
    ref = m["_head_ref"]
    return _engine_job({"kind": "head", "prompt": m["_head_prompt"], "refs": [], "out": f"fitting/models/{m['id']}.png",
                        "seed": m["seed"], "console_job": cj, "step": step, "total": total, "link": "/fitting",
                        "meta": {"prompt": f"{ref['id']}@{ref['version']}", "prompt_hash": ref["hash"], "hair": m["hair"]}})


@router.post("/api/fitting/models/head")
def head_pass(body: dict = Body(default={})):
    """Re-draw face and hair of existing portraits; bodies stay. Default: every portrait without a current head pass."""
    ids = set(body.get("ids") or [])
    todo = [m for m in model_list(bodies())
            if m["portrait"] and (not ids or m["id"] in ids) and (body.get("force") or not m["head_done"])]
    if not todo:
        return {"queued": 0}
    for m in todo:  # try-ons would show the old face
        _drop_outputs(m["id"])
    cj = job_start(f"Face and hair · {len(todo)}", None, total=len(todo), kind="portrait")
    for i, m in enumerate(todo, 1):
        _queue_head(m, cj, i, len(todo))
    return {"queued": len(todo), "job": cj}


def _queue_tryon(model: dict, garment: dict, size: str) -> dict:
    key = f"{model['id']}__{garment['id']}__{size}"
    f = fit(model["body"], garment["measures"][size])
    phrases = prompt("fitting.tryon")["parts"]
    text, ref = render_prompt("fitting.tryon", fit=phrases["fit"][f["codes"]["fit"]], ease=round(f["ease_mm"] / 10),
                              length=phrases["length"][f["codes"]["length"]],
                              sleeve=phrases["sleeve"][f["codes"]["sleeve"]].format(cm=round(f["sleeve_mm"] / 10)))
    done = RENDERS / f"{key}.png"
    if done.exists() and (read_json(done.with_suffix(".png.json"), {}).get("meta") or {}).get("prompt_hash") == ref["hash"]:
        return {"status": "ready", "key": key, "url": _url(f"fitting/renders/{key}.png")}
    if key in _pending:  # an outdated render stays on screen until the new one replaces it
        return tryon_status(key)
    shutil.rmtree(VIEWS / key, ignore_errors=True)  # rotation stills of the outdated render
    # the size goes first: the sidebar truncates long names and the size is what tells these jobs apart
    cj = job_start(f"{size} try-on · {garment['name']} · {model['ethnicity_label']} {model['gender_label']} ({model['size']})",
                   None, total=1, kind="tryon")
    job = _engine_job({
        "kind": "tryon", "seed": 42, "out": f"fitting/renders/{key}.png", "console_job": cj, "link": "/fitting",
        "refs": [f"fitting/models/{model['id']}.png", f"fitting/garments/{garment['id']}.png"], "prompt": text,
        "meta": {"prompt": f"{ref['id']}@{ref['version']}", "prompt_hash": ref["hash"], "height_cm": model["height_cm"],
                 **{k: v for k, v in f.items() if k != "codes"}}})
    _pending[key] = job["id"]
    return {"status": "queued", "key": key, "position": job.get("position")}


def _lookup(model_id: str | None, garment_id: str | None, size: str | None) -> tuple[dict, dict, list]:
    b = bodies()
    model = next((m for m in model_list(b) if m["id"] == model_id), None)
    garment = next((g for g in garment_list() if g["id"] == garment_id), None)
    if not model or not garment or (size is not None and size not in b["sizes"]):
        raise HTTPException(400, "Unknown model, garment, or size")
    if not garment["image"] or not garment["measures"]:
        raise HTTPException(409, "This garment has no photo or pattern measurements yet (run the pattern first)")
    return model, garment, b["sizes"]


@router.post("/api/fitting/restage")
def restage():
    """Re-run true-scale staging on every existing portrait and render (after the staging code changes)."""
    by_id = {m["id"]: m for m in model_list(bodies())}
    files = [(PORTRAITS / f"{mid}.png", m["height_cm"]) for mid, m in by_id.items() if (PORTRAITS / f"{mid}.png").exists()]
    files += [(p, by_id[p.name.split("__")[0]]["height_cm"]) for p in RENDERS.glob("*__*.png")
              if "." not in p.stem and p.name.split("__")[0] in by_id]
    done = 0
    for path, height in files:
        try:
            httpx.post(f"{ENGINE_URL}/normalize", json={"path": str(path.relative_to(DATA)), "height_cm": height},
                       timeout=60).raise_for_status()
            done += 1
        except httpx.HTTPError:
            pass
    return {"restaged": done, "of": len(files)}


@router.post("/api/fitting/tryon")
def tryon(body: dict = Body(...)):
    model, garment, _ = _lookup(body.get("model"), body.get("garment"), body.get("size"))
    if not model["portrait"]:
        raise HTTPException(409, "This model has no photo yet")
    return _queue_tryon(model, garment, body["size"])


@router.post("/api/fitting/lineup")
def lineup(body: dict = Body(...)):
    """Everyone in one gender x ethnicity wearing their own size: reviews the grading across sizes."""
    gender, eth = body.get("gender"), body.get("ethnicity")
    if gender not in GENDERS or eth not in ETHNICITIES:
        raise HTTPException(400, "Check the gender and ethnicity values")
    out = []
    for size in bodies()["sizes"]:
        model, garment, _ = _lookup(f"{gender[0]}-{size}-{eth}", body.get("garment"), size)
        if model["portrait"]:
            out.append(_queue_tryon(model, garment, size))
    return {"renders": out}


@router.post("/api/fitting/views")
def views(body: dict = Body(...)):
    """Rotation stills (45/90/135/180) of a finished try-on, re-staged at true scale like every other photo."""
    model, garment, _ = _lookup(body.get("model"), body.get("garment"), body.get("size"))
    key = f"{model['id']}__{garment['id']}__{body['size']}"
    if not (RENDERS / f"{key}.png").exists():
        raise HTTPException(409, "Make the try-on first")
    parts = prompt("fitting.view")["parts"]
    have = view_index().get(key, {})
    todo = [a for a in VIEW_ANGLES if a not in have]
    if not todo:
        return {"queued": 0, "key": key}
    cj = job_start(f"Angles · {garment['name']} · {model['ethnicity_label']} {model['gender_label']} ({body['size']})", None,
                   total=len(todo), kind="tryon")
    pos = parts["pos"][model["gender"]]
    for i, a in enumerate(todo, 1):
        text, ref = render_prompt("fitting.view", person=parts["person"][model["gender"]], pos=pos,
                                  view=parts["view"][a].format(pos=pos))
        _engine_job({"kind": "view", "seed": 42, "prompt": text, "out": f"fitting/views/{key}/v{a}.png",
                     "refs": [f"fitting/renders/{key}.png", f"fitting/garments/{garment['id']}.png"],
                     "console_job": cj, "step": i, "total": len(todo), "link": "/fitting",
                     "meta": {"prompt": f"{ref['id']}@{ref['version']}", "prompt_hash": ref["hash"],
                              "height_cm": model["height_cm"], "angle": a}})
    return {"queued": len(todo), "key": key, "job": cj}


@router.delete("/api/fitting/tryon/{key}")
def cancel_tryon(key: str):
    """Stop waiting for a render. A queued job is dropped; a running one finishes on the GPU and lands in the cache."""
    jid = _pending.pop(key, None)
    if not jid:
        return {"status": "missing", "key": key}
    try:
        return {"key": key, **httpx.post(f"{ENGINE_URL}/jobs/{jid}/cancel", timeout=2).json()}
    except httpx.HTTPError:
        return {"status": "cancelled", "key": key, "engine": "offline"}


@router.get("/api/fitting/tryon/{key}")
def tryon_status(key: str):
    if (RENDERS / f"{key}.png").exists():
        _pending.pop(key, None)
        return {"status": "ready", "key": key, "url": _url(f"fitting/renders/{key}.png")}
    jid = _pending.get(key)
    if not jid:
        return {"status": "missing", "key": key}
    try:
        st = httpx.get(f"{ENGINE_URL}/jobs/{jid}", timeout=2).json()
    except httpx.HTTPError:
        return {"status": "queued", "key": key, "engine": "offline"}
    if st.get("status") == "failed":
        _pending.pop(key, None)
    return {"key": key, **{k: st.get(k) for k in ("status", "position", "elapsed", "error")}}
