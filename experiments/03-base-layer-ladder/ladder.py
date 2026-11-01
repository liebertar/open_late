"""Bake-off, not production: does a dressed base plus a numeric hem sentence make renders follow the pattern?

Writes only under data/fitting/bakeoff/base-layer. Existing portraits and try-ons are read, never changed.
"""
import json
import sys
import time
import urllib.request as u

CONSOLE, ENGINE = "http://127.0.0.1:7100", "http://127.0.0.1:8091"
ROOT = "fitting/bakeoff/base-layer"
PEOPLE = ["m-M-white", "f-S-east_asian"]
GARMENT = "inknavy-apricot"
HPS, CROTCH = 0.82, 0.47  # share of height: high point of the shoulder and crotch, standard body proportions


def post(url, body):
    r = u.Request(url, json.dumps(body).encode(), {"content-type": "application/json"})
    return json.load(u.urlopen(r, timeout=30))


def get(url):
    return json.load(u.urlopen(url, timeout=10))


def wait(ids):
    while True:
        st = [get(f"{ENGINE}/jobs/{i}") for i in ids]
        if all(s["status"] in ("done", "failed") for s in st):
            bad = [s for s in st if s["status"] == "failed"]
            if bad:
                print("FAILED", bad, flush=True)
            return
        time.sleep(3)


DRESS = ("The person from the image now wears a plain white crew-neck t-shirt, straight-leg mid-grey cotton trousers and "
         "plain white low sneakers. Their face, hair, skin tone, body shape, pose and the grey backdrop stay exactly as in "
         "the image. Photorealistic catalog photo.")


def hem(height_cm, garment_cm):
    d = round((HPS - CROTCH) * height_cm - garment_cm)
    where = f"{d} cm above the crotch" if d > 0 else f"{-d} cm below the crotch" if d < 0 else "level with the crotch"
    return f"The hoodie measures {round(garment_cm)} cm from shoulder to hem, so the ribbed hem ends {where} of the trousers"


cat = get(f"{CONSOLE}/api/fitting/catalog")
parts = None
sys.path.insert(0, ".")
models = {m["id"]: m for m in cat["models"]}
measures = next(g["measures"] for g in cat["garments"] if g["measures"])
phr = get(f"{CONSOLE}/api/fitting/prompts")  # sanity: console answers
del phr

t0 = time.time()
ids = []
for mid in PEOPLE:
    m = models[mid]
    ids.append(post(f"{ENGINE}/jobs", {"kind": "tryon", "seed": 42, "prompt": DRESS, "refs": [f"fitting/models/{mid}.png"],
                                       "out": f"{ROOT}/models/{mid}.png", "meta": {"height_cm": m["height_cm"]}})["id"])
print("dressing", ids, flush=True)
wait(ids)
print(f"dressed in {time.time() - t0:.0f} s", flush=True)

import yaml  # noqa: E402

phrases = yaml.safe_load(open("pipeline/prompts/fitting.tryon.yaml"))["parts"]
ids = []
for mid in PEOPLE:
    m = models[mid]
    for s in cat["sizes"]:
        f = m["fits"][s]
        sleeve = phrases["sleeve"][f["codes"]["sleeve"]].format(cm=round(f["sleeve_mm"] / 10))
        text = (f"{hem(m['height_cm'], measures[s]['length'] / 10)}. {sleeve}. The person from the first image now wears the "
                f"hoodie from the second image over their t-shirt. A {phrases['fit'][f['codes']['fit']]} fit with about "
                f"{round(f['ease_mm'] / 10)} cm of ease at the chest, the hood resting down on the back. Their face, hair, skin "
                "tone, body shape, pose, grey trousers, white sneakers and the grey backdrop stay exactly as in the first "
                "image. Photorealistic catalog photo.")
        ids.append(post(f"{ENGINE}/jobs", {"kind": "tryon", "seed": 42, "prompt": text,
                                           "refs": [f"{ROOT}/models/{mid}.png", f"fitting/garments/{GARMENT}.png"],
                                           "out": f"{ROOT}/renders/{mid}__{s}.png", "meta": {"height_cm": m["height_cm"]}})["id"])
print("try-ons", len(ids), flush=True)
wait(ids)
print(f"done in {time.time() - t0:.0f} s", flush=True)
