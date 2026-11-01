"""FreeSewing SVG (mm, 1:1) -> DXF R12 with AAMA-style layer numbers.

    python svg_to_dxf.py hugo.svg hugo.dxf

Layer mapping (Valentina's AAMA export as reference; confirm against the sample room's DXF):
    1  cut line        <- path.class == "<material> sa"
    14 sew line        <- path.class == "<material>"
       materials: fabric (shell), lining, interfacing, canvas, various (e.g. rib knit)
    4  notch           <- <use href="#notch|#bnotch">   (written as POINT; orientation TBD)
    7  grainline       <- path with marker-start grainlineFrom
    6  fold (mirror)   <- path with marker-start cutonfoldFrom
    15 annotation      <- piece name text

R12 has no $INSUNITS header, so units are declared as text ("UNITS = METRIC") like AAMA files do.
"""
from __future__ import annotations

import io
import re
import sys
import xml.etree.ElementTree as ET

import ezdxf
import numpy as np
from svgpathtools import parse_path

SVG = "{http://www.w3.org/2000/svg}"
MATERIALS = ("fabric", "lining", "interfacing", "canvas", "various")
XLINK = "{http://www.w3.org/1999/xlink}href"
STEP_MM = 1.0


def translate_of(el) -> np.ndarray:
    m = re.search(r"translate\(\s*([-\d.e]+)[ ,]+([-\d.e]+)\s*\)", el.get("transform", ""))
    return np.array([float(m.group(1)), float(m.group(2))]) if m else np.zeros(2)


def sample(d: str) -> list[np.ndarray]:
    """Path -> list of polylines (one per subpath), sampled every STEP_MM."""
    out = []
    for sub in parse_path(d).continuous_subpaths():
        pts = []
        for seg in sub:
            n = max(2, int(seg.length() / STEP_MM) + 1)
            for t in np.linspace(0, 1, n)[:-1] if pts else np.linspace(0, 1, n):
                p = seg.point(t)
                pts.append((p.real, p.imag))
        end = sub[-1].point(1)
        pts.append((end.real, end.imag))
        out.append(np.array(pts))
    return out


def convert(svg_path: str, dxf_path: str) -> dict:
    text, report = convert_text(open(svg_path).read())
    open(dxf_path, "w").write(text)
    return report


def convert_text(svg_text: str) -> tuple[str, dict]:
    root = ET.fromstring(svg_text)
    doc = ezdxf.new("R12")
    msp = doc.modelspace()
    msp.add_text("UNITS = METRIC", dxfattribs={"layer": "1", "height": 5})
    report: dict[str, dict] = {}

    def walk(el, offset, part):
        if el.tag == f"{SVG}g":
            gid = el.get("id", "")
            offset = offset + translate_of(el)
            if "-part-" in gid:
                part = gid.split("-part-")[-1]
                report.setdefault(part, {"material": None, "cut": 0, "sew": 0, "notch": 0, "grain": 0, "fold": 0,
                                        "open_cut_ends": [], "fold_lines": [], "w": 0.0, "h": 0.0, "_box": None})
                msp.add_text(part, dxfattribs={"layer": "15", "height": 8,
                                                "insert": (offset[0], -offset[1])})
        if part and el.tag == f"{SVG}path" and el.get("d"):
            cls, marker = el.get("class", ""), el.get("marker-start", "")
            words = cls.split()
            layer = key = None
            if words and words[0] in MATERIALS:
                layer, key = ("1", "cut") if "sa" in words[1:] else ("14", "sew")
                report[part]["material"] = words[0]
            if "grainlineFrom" in marker:
                layer, key = "7", "grain"
            elif "cutonfoldFrom" in marker:
                layer, key = "6", "fold"
            if layer:
                for poly in sample(el.get("d")):
                    pts = [(x + offset[0], -(y + offset[1])) for x, y in poly]  # SVG y-down -> DXF y-up
                    closed = np.allclose(poly[0], poly[-1], atol=0.05) and layer in ("1", "14")
                    msp.add_polyline2d(pts[:-1] if closed else pts, close=closed, dxfattribs={"layer": layer})
                    if layer == "1" and not closed:
                        report[part]["open_cut_ends"] += [poly[0].tolist(), poly[-1].tolist()]
                    if layer == "6":
                        report[part]["fold_lines"].append([poly[0].tolist(), poly[-1].tolist()])
                    if layer == "14":  # sew-line extents = finished size of the piece
                        lo, hi = poly.min(axis=0), poly.max(axis=0)
                        box = report[part]["_box"]
                        box = (lo, hi) if box is None else (np.minimum(box[0], lo), np.maximum(box[1], hi))
                        report[part]["_box"] = box
                        report[part]["w"], report[part]["h"] = (round(float(v), 1) for v in box[1] - box[0])
                report[part][key] += 1
        if part and el.tag == f"{SVG}use" and el.get(XLINK, "").lstrip("#") in ("notch", "bnotch"):
            x, y = float(el.get("x", 0)) + offset[0], float(el.get("y", 0)) + offset[1]
            msp.add_point((x, -y), dxfattribs={"layer": "4"})
            report[part]["notch"] += 1
        for child in el:
            walk(child, offset, part)

    walk(root, np.zeros(2), None)
    for r in report.values():
        r.pop("_box", None)
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue(), report


if __name__ == "__main__":
    rep = convert(sys.argv[1], sys.argv[2])
    for part, r in rep.items():
        print(f"{part:24} {str(r['material']):9} cut={r['cut']} sew={r['sew']} notch={r['notch']} grain={r['grain']} fold={r['fold']}")
