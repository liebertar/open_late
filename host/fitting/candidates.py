"""Best-of-N casting: render several candidates for a portrait, then promote the one a reviewer picks.

    .venv/bin/python candidates.py render m-M-black m-XS-black --n 3   # c1..c3 per id, same prompt, new seeds
    .venv/bin/python candidates.py strips m-M-black m-XS-black          # each candidate swapped into its size lineup
    .venv/bin/python candidates.py promote m-M-black c2                # c2 becomes the model photo

Some bodies keep coming out wrong for their size with the same prompt (the model's prior beats the words), so one
re-roll at a time is a coin flip. Candidates land in data/fitting/candidates/<id>/ with the engine's usual true-scale
cut-outs, which is what the reviewer compares against the rest of the size lineup.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import httpx

CONSOLE = "http://127.0.0.1:7100"
ENGINE = "http://127.0.0.1:8091"
DATA = Path(__file__).resolve().parents[2] / "data"


def render(ids: list[str], n: int) -> None:
    prompts = httpx.get(f"{CONSOLE}/api/fitting/prompts", timeout=30).raise_for_status().json()
    models = {m["id"]: m for m in httpx.get(f"{CONSOLE}/api/fitting/catalog", timeout=30).raise_for_status().json()["models"]}
    unknown = [i for i in ids if i not in models]
    if unknown:
        raise SystemExit(f"unknown model ids: {unknown}")
    total = len(ids) * n
    cj = httpx.post(f"{CONSOLE}/api/jobs", json={"name": f"Model candidates · {len(ids)} × {n}", "total": total, "kind": "portrait"},
                    timeout=10).raise_for_status().json()["id"]
    step = 0
    for mid in ids:
        m, p = models[mid], prompts[mid]
        for k in range(1, n + 1):
            step += 1
            attempt = m["attempt"] + k
            httpx.post(f"{ENGINE}/jobs", timeout=15, json={
                "kind": "portrait", "prompt": p["prompt"], "refs": [], "out": f"fitting/candidates/{mid}/c{k}.png",
                "seed": (p["seed"] + 7919 * attempt) % 100000, "console_job": cj, "step": step, "total": total,
                "link": "/fitting", "meta": {"prompt": f"{p['ref']['id']}@{p['ref']['version']}",
                                             "prompt_hash": p["ref"]["hash"], "height_cm": m["height_cm"], "attempt": attempt}}
                       ).raise_for_status()
    print(f"queued {total} candidates -> {DATA / 'fitting/candidates'} (console job {cj})")


def strips(ids: list[str]) -> None:
    """<id>/strip_c<k>.jpg: the group's true-scale lineup with candidate k in its size slot, for side-by-side review."""
    from qa_strips import strip
    sizes = httpx.get(f"{CONSOLE}/api/fitting/catalog", timeout=30).raise_for_status().json()["sizes"]
    for mid in ids:
        gender, size, eth = mid.split("-", 2)
        for cand in sorted((DATA / "fitting/candidates" / mid).glob("c*.cut.png")):
            k = cand.name.split(".")[0]
            paths = [cand if s == size else DATA / "fitting/models" / f"{gender}-{s}-{eth}.cut.png" for s in sizes]
            strip(paths, [f"{s} {'<- ' + k if s == size else ''}" for s in sizes], cand.parent / f"strip_{k}.jpg")
        print(mid, "strips done")


def promote(mid: str, cand: str) -> None:
    src, models = DATA / "fitting/candidates" / mid, DATA / "fitting/models"
    side = json.loads((src / f"{cand}.png.json").read_text())
    for suffix in (".png", ".scaled.png", ".cut.png"):
        shutil.copyfile(src / f"{cand}{suffix}", models / f"{mid}{suffix}")
    side |= {"scaled": f"fitting/models/{mid}.scaled.png", "cutout": f"fitting/models/{mid}.cut.png", "promoted_from": cand}
    (models / f"{mid}.png.json").write_text(json.dumps(side, ensure_ascii=False, indent=2))
    (models / f"{mid}.base.png").unlink(missing_ok=True)  # new body: the head pass must start from it
    stale = list((DATA / "fitting/renders").glob(f"{mid}__*"))
    for f in stale:  # try-ons of the replaced person
        f.unlink()
    for d in (DATA / "fitting/views").glob(f"{mid}__*"):  # and their rotation stills
        shutil.rmtree(d, ignore_errors=True)
    httpx.post(f"{CONSOLE}/api/fitting/models/head", json={"ids": [mid], "force": True}, timeout=30).raise_for_status()
    print(f"{mid} <- {cand} (attempt {side['meta'].get('attempt')}); removed {len(stale)} old try-on files; head pass queued")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("ids", nargs="+")
    r.add_argument("--n", type=int, default=3)
    st = sub.add_parser("strips")
    st.add_argument("ids", nargs="+")
    p = sub.add_parser("promote")
    p.add_argument("id")
    p.add_argument("candidate")
    a = ap.parse_args()
    if a.cmd == "render":
        render(a.ids, a.n)
    elif a.cmd == "strips":
        strips(a.ids)
    else:
        promote(a.id, a.candidate)
