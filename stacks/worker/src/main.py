"""Worker service: SVG pattern -> DXF + automatic checks.

    GET  /health
    POST /dxf  {"svg": "<svg ...>"}  -> {"dxf": "...", "pieces": {...}, "checks": [...], "passed": bool}
"""
from fastapi import FastAPI
from pydantic import BaseModel

from checks import dxf_checks, piece_checks
from svg_to_dxf import convert_text

app = FastAPI(title="open_late worker")


class DxfRequest(BaseModel):
    svg: str


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/dxf")
def to_dxf(req: DxfRequest):
    dxf, pieces = convert_text(req.svg)
    checks = [
        {"name": n, "passed": ok, "detail": d}
        for n, ok, d in piece_checks(pieces) + dxf_checks(dxf)
    ]
    return {"dxf": dxf, "pieces": pieces, "checks": checks, "passed": all(c["passed"] for c in checks)}
