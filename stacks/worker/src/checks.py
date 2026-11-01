"""Automatic checks for node 4 (pattern). Each check returns (name, passed, detail)."""
from __future__ import annotations

import io

import numpy as np

import ezdxf


def piece_checks(report: dict) -> list[tuple[str, bool, str]]:
    out = []
    for part, r in report.items():
        out.append((f"{part}: cut line", r["cut"] >= 1, f"{r['cut']} closed outline(s) on layer 1"))
        out.append((f"{part}: sew line", r["sew"] >= 1, f"{r['sew']} line(s) on layer 14"))
        out.append((f"{part}: grain or fold", r["grain"] + r["fold"] >= 1,
                    f"grain={r['grain']} fold={r['fold']}"))
        out.append((f"{part}: material", r["material"] is not None, str(r["material"])))
        stray = [e for e in r.get("open_cut_ends", []) if not _on_any_fold(e, r.get("fold_lines", []))]
        out.append((f"{part}: cut line closed or ends on fold", not stray,
                    "ok" if not stray else f"{len(stray)} open end(s) off the fold line"))
    return out


def _on_any_fold(pt, folds, tol=1.0) -> bool:
    """True if pt lies on the infinite line through any fold segment (mm)."""
    p = np.array(pt)
    for a, b in folds:
        a, b = np.array(a), np.array(b)
        d = b - a
        if np.linalg.norm(d) < 1e-9:
            continue
        v = p - a
        if abs(d[0] * v[1] - d[1] * v[0]) / np.linalg.norm(d) <= tol:  # 2-D cross product
            return True
    return False


def dxf_checks(dxf_text: str) -> list[tuple[str, bool, str]]:
    doc = ezdxf.read(io.StringIO(dxf_text))
    msp = doc.modelspace()
    texts = [t.dxf.text for t in msp.query("TEXT")]
    return [("units declared", "UNITS = METRIC" in texts, "AAMA-style text; R12 has no $INSUNITS")]


def size_checks(reports: dict[str, dict]) -> list[tuple[str, bool, str]]:
    """Across sizes: identical piece set (topology)."""
    sizes = sorted(reports)
    base = set(reports[sizes[0]])
    same = all(set(reports[s]) == base for s in sizes)
    return [("same pieces in every size", same, ", ".join(f"{s}:{len(reports[s])}" for s in sizes))]
