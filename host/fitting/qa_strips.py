"""Inputs for the visual QA of the fitting-room cast: true-scale lineup strips + one JSON file for the inspectors.

    .venv/bin/python qa_strips.py            # writes data/fitting/qa/{lineup_*,tryon_*}.jpg and args.json

Adjacent sizes that came out the same only show up side by side at true scale, so every gender x ethnicity group gets
one strip (XS..XL cut-outs, labelled with height, chest and hips). Lineups that have try-on renders get a second strip.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

CONSOLE = "http://127.0.0.1:7100"
DATA = Path(__file__).resolve().parents[2] / "data"
QA = DATA / "fitting" / "qa"
GARMENT = "inknavy-apricot"
W = 440  # each true-scale canvas is cropped to its central W px


def strip(paths: list[Path], labels: list[str], out: Path) -> None:
    img = Image.new("RGB", (W * len(paths), 1024 + 30), (236, 236, 236))
    draw = ImageDraw.Draw(img)
    for i, (p, label) in enumerate(zip(paths, labels)):
        cut = Image.open(p).convert("RGBA").crop((384 - W // 2, 0, 384 + W // 2, 1024))
        img.paste(cut, (i * W, 30), cut)
        draw.text((i * W + 10, 8), label, fill="black")
    img.save(out, quality=90)


def main() -> None:
    QA.mkdir(parents=True, exist_ok=True)
    cat = httpx.get(f"{CONSOLE}/api/fitting/catalog", timeout=30).json()
    prompts = httpx.get(f"{CONSOLE}/api/fitting/prompts", timeout=30).json()
    sizes, groups, tryon = cat["sizes"], [], []
    for g in ("female", "male"):
        for e in ("east_asian", "white", "black", "arab"):
            row = sorted((m for m in cat["models"] if m["gender"] == g and m["ethnicity"] == e),
                         key=lambda m: sizes.index(m["size"]))
            lineup = QA / f"lineup_{g[0]}_{e}.jpg"
            strip([DATA / "fitting/models" / f"{m['id']}.cut.png" for m in row],
                  [f"{m['size']} {m['height_cm']}cm chest{m['body']['chest'] // 10} hips{m['body']['hips'] // 10}" for m in row],
                  lineup)
            groups.append({"key": f"{g[0]}-{e}", "gender": g, "ethnicity": e, "lineup": str(lineup), "portraits": [
                {"id": m["id"], "size": m["size"], "height_cm": m["height_cm"], "chest_cm": m["body"]["chest"] / 10,
                 "hips_cm": m["body"]["hips"] / 10, "waist_cm": m["body"]["waist"] / 10, "silhouette": m["silhouette"],
                 "path": str(DATA / "fitting/models" / f"{m['id']}.png"), "prompt": prompts[m["id"]]["prompt"]}
                for m in row]})
            keys = [f"{g[0]}-{s}-{e}__{GARMENT}__{s}" for s in sizes]
            if all((DATA / "fitting/renders" / f"{k}.cut.png").exists() for k in keys):
                lineup = QA / f"tryon_{g[0]}_{e}.jpg"
                strip([DATA / "fitting/renders" / f"{k}.cut.png" for k in keys], [f"{s} wears {s}" for s in sizes], lineup)
                renders = []
                for k in keys:
                    side = json.loads((DATA / "fitting/renders" / f"{k}.png.json").read_text())
                    meta = side.get("meta", {})
                    renders.append({"key": k, "path": str(DATA / "fitting/renders" / f"{k}.png"),
                                    "portrait": str(DATA / "fitting/models" / f"{k.split('__')[0]}.png"),
                                    "fit": {x: meta.get(x) for x in ("fit", "ease_mm", "length", "length_mm", "sleeve", "sleeve_mm")},
                                    "prompt": side["prompt"]})
                tryon.append({"key": f"{g[0]}-{e}", "lineup": str(lineup),
                              "garment_photo": str(DATA / "fitting/garments" / f"{GARMENT}.png"), "renders": renders})
    (QA / "args.json").write_text(json.dumps({"groups": groups, "tryon": tryon}, ensure_ascii=False, indent=1))
    print(f"{len(groups)} groups, {sum(len(g['portraits']) for g in groups)} portraits, {len(tryon)} try-on lineups -> {QA}")


if __name__ == "__main__":
    main()
