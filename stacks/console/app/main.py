"""OPEN LATE console: pipeline dashboard, approval gates, jobs, append-only history, fitting room.

API (pipeline)
    GET  /api/state                      nodes + current state + average timing per node
    GET  /api/jobs                       recent jobs, running first
    GET  /api/history?node=n04&limit=20  history entries, newest first
    GET  /api/runs/{run}                 files of one run
    POST /api/nodes/{id}/run             {"design": "hugo"} -> starts a job
    POST /api/nodes/{id}/approve         only after automatic checks passed
    POST /api/nodes/{id}/reject          {"code": "color", "reason": "optional note"}
    POST /api/nodes/{id}/report          host scripts report a finished run
    POST /api/jobs                       {"name", "node", "total"} -> {"id"}
    POST /api/jobs/{id}                  {"done", "message", "status", "link"}
Fitting room API lives in fitting.py. The try-on page is /fitting; grading review and model upkeep are on /fitting/qa.

A job is one execution (done = it ran to the end). Whether the result passed is node state.
"""
from __future__ import annotations

import hashlib
import html
import json
import threading
import time
from pathlib import Path

import httpx
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import fitting
from core import (ACTOR, DATA, DOCS, PATTERN_URL, WORKER_URL, carry, job_start, job_update, load_state, lock, log,
                  node, node_timing, nodes, put_state, read_json, recent_jobs, write_json)

HERE = Path(__file__).parent

app = FastAPI(title="OPEN LATE console")
app.include_router(fitting.router)


@app.middleware("http")
async def revalidate(request, call_next):
    """Pages and scripts change often while the tool is being built: browsers must revalidate (cheap 304 via ETag)
    instead of running a cached shell.js against a new page."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or not path.startswith(("/api/", "/files/")):
        response.headers["Cache-Control"] = "no-cache"
    return response
app.mount("/files", StaticFiles(directory=DATA), name="files")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
for route, sub in (("/review", "review-site"), ("/colorways", "colorway-board")):
    if (DOCS / sub).is_dir():
        app.mount(route, StaticFiles(directory=DOCS / sub, html=True), name=sub)

PREVIEW_CSS = (".fabric,.various,.lining,.interfacing{fill:none;stroke:#e6e8ec;stroke-width:2}"
               ".sa{stroke-dasharray:6 4;opacity:.75}.note{fill:none;stroke:#f0a07c;stroke-width:1.5}"
               ".mark{fill:none;stroke:#f0a07c}text{fill:#9aa3ad;font-size:14px;font-family:sans-serif}"
               "tspan{fill:#9aa3ad}")


def preview_svg(svg: str) -> str:
    """Inject stroke styles so a FreeSewing SVG renders as a light outline; pages show previews on a dark mat."""
    return svg.replace("<![CDATA[", "<![CDATA[ " + PREVIEW_CSS, 1)


def garment_measures(pieces: dict) -> dict:
    """Finished garment measurements (mm) from sew-line piece extents. Front/back are drafted on the fold."""
    by = {name.split(".")[-1]: p for name, p in pieces.items()}
    try:
        return {"chest": round(2 * (by["front"]["w"] + by["back"]["w"])),
                "length": round(by["back"]["h"] + by["waistband"]["w"] / 2),
                "sleeve": round(by["sleeve"]["h"] + by["cuff"]["h"] / 2)}
    except KeyError:
        return {}


# ---------- node 4: pattern -> DXF -> checks (runs in a thread) ----------

def run_pattern(jid: str, design: str) -> None:
    run_id = time.strftime("%Y%m%d-%H%M%S") + f"-n04-{design}"
    out = DATA / "runs" / run_id
    out.mkdir(parents=True)
    checks, pieces, hashes, measures = [], {}, {}, {}
    try:
        with httpx.Client(timeout=120) as c:
            sizes = list(c.get(f"{PATTERN_URL}/designs").raise_for_status().json()["sizes"]["sizes"])
            job_update(jid, total=len(sizes) * 2)
            for i, s in enumerate(sizes):
                job_update(jid, done=i * 2, message=f"{s} drafting pattern")
                d = c.post(f"{PATTERN_URL}/draft", json={"design": design, "size": s}).raise_for_status().json()
                hashes[s] = hashlib.sha256(json.dumps(d["measurements"], sort_keys=True).encode()).hexdigest()[:12]
                (out / f"pattern_{s}.svg").write_text(d["svg"])
                (out / f"preview_{s}.svg").write_text(preview_svg(d["svg"]))
                job_update(jid, done=i * 2 + 1, message=f"{s} converting to DXF and checking")
                r = c.post(f"{WORKER_URL}/dxf", json={"svg": d["svg"]}).raise_for_status().json()
                (out / f"pattern_{s}.dxf").write_text(r["dxf"])
                pieces[s] = sorted(r["pieces"])
                measures[s] = garment_measures(r["pieces"])
                checks += [{**ck, "size": s} for ck in r["checks"]]
    except Exception as e:  # a service is down or answered badly: record it, never fail silently
        msg = str(e)[:200]
        put_state("n04", {"status": "failed", "run": run_id, "summary": "Run failed", "fails": [msg]})
        log({"node": "n04", "action": "run", "actor": "pipeline", "outputs": f"runs/{run_id}", "error": msg})
        job_update(jid, status="failed", message=msg, link=f"/runs/{run_id}")
        return

    same = all(pieces[s] == pieces[sizes[0]] for s in sizes)
    checks.append({"name": "same pieces in every size", "passed": same, "size": "all",
                   "detail": ", ".join(f"{s}:{len(pieces[s])}" for s in sizes)})
    write_json(out / "checks.json", checks)
    write_json(out / "measures.json", {"design": design, "sizes": sizes, "measures": measures})
    fails = [c for c in checks if not c["passed"]]
    input_hash = hashlib.sha256(json.dumps({"design": design, "m": hashes}, sort_keys=True).encode()).hexdigest()[:16]
    put_state("n04", {"status": "failed" if fails else "passed", "run": run_id, "design": design,
                      "summary": f"{len(checks) - len(fails)}/{len(checks)} checks passed",
                      "previews": [f"/files/runs/{run_id}/preview_{s}.svg" for s in sizes],
                      "measures": measures, "fails": [f"{c['size']} · {c['name']} · {c['detail']}" for c in fails]})
    log({"node": "n04", "action": "run", "actor": "pipeline", "model": node("n04")["model"],
         "input_hash": input_hash, "outputs": f"runs/{run_id}", "passed": not fails})
    job_update(jid, done=len(sizes) * 2, status="done", outcome="failed" if fails else "passed",
               message=f"{len(fails)} checks failed" if fails else "Checks passed", link=f"/runs/{run_id}")


@app.post("/api/nodes/{nid}/run")
def run(nid: str, body: dict = Body(default={})):
    if not node(nid).get("runnable"):
        raise HTTPException(400, f"{nid} has no runner yet")
    design = body.get("design", "hugo")
    jid = job_start(f"{nid} pattern · {design}", nid, total=10)
    threading.Thread(target=run_pattern, args=(jid, design), daemon=True).start()
    return {"job": jid}


@app.post("/api/nodes/{nid}/report")
def report(nid: str, body: dict = Body(...)):
    """Host-native scripts (models run outside Docker) report a finished run here."""
    node(nid)
    status = body.get("status", "needs_review")
    if status not in ("passed", "failed", "needs_review"):
        raise HTTPException(400, "status must be passed, failed or needs_review")
    put_state(nid, {"status": status, "summary": body.get("summary", ""), "link": body.get("link"),
                    "fails": body.get("fails", []), "previews": body.get("previews", [])[:12],
                    "timing": body.get("timing", [])})
    log({"node": nid, "action": "report", "actor": body.get("actor", "host"), "model": body.get("model"),
         "outputs": body.get("link"), "status": status})
    return {"ok": True}


@app.post("/api/nodes/{nid}/approve")
def approve(nid: str):
    n, st = node(nid), load_state().get(nid, {})
    if n["gate"] != "approve" or st.get("status") not in ("passed", "needs_review"):
        raise HTTPException(409, "Automatic checks must pass before approval")
    put_state(nid, carry(st) | {"status": "approved"})
    log({"node": nid, "action": "approve", "actor": ACTOR, "outputs": st.get("run") or st.get("link")})
    return {"ok": True}


REJECT_CODES = {"size": "Measurements", "fit": "Fit", "color": "Colour", "detail": "Detail", "quality": "Quality", "other": "Other"}


@app.post("/api/nodes/{nid}/reject")
def reject(nid: str, body: dict = Body(...)):
    """Rejections carry a reason code (countable, usable by code) plus an optional note (for prompts)."""
    node(nid)
    code, note = body.get("code"), (body.get("reason") or "").strip()
    if code not in REJECT_CODES:
        raise HTTPException(400, f"Choose a rejection reason: {', '.join(REJECT_CODES.values())}")
    label = REJECT_CODES[code] + (f" · {note}" if note else "")
    put_state(nid, carry(load_state().get(nid, {})) | {"status": "rejected", "reason": label, "reason_code": code})
    log({"node": nid, "action": "reject", "actor": ACTOR, "code": code, "reason": note})
    with lock, open(DATA / "rules.md", "a") as f:
        f.write(f"- [{nid}][{code}] {time.strftime('%Y-%m-%d')} {note or REJECT_CODES[code]}\n")
    return {"ok": True}


@app.get("/api/reject-codes")
def reject_codes():
    return REJECT_CODES


@app.post("/api/jobs")
def create_job(body: dict = Body(...)):
    return {"id": job_start(body.get("name", "Job"), body.get("node"), int(body.get("total", 0)),
                            body.get("kind", "node"))}


@app.post("/api/jobs/{jid}")
def update_job(jid: str, body: dict = Body(...)):
    status = body.get("status")
    if status not in (None, "running", "done", "failed"):
        raise HTTPException(400, "status must be running, done or failed")
    return job_update(jid, done=body.get("done"), message=body.get("message"), status=status,
                      link=body.get("link"), outcome=body.get("outcome"))


@app.get("/api/jobs")
def jobs(limit: int = 12):
    recent = recent_jobs()
    running = [j for j in recent if j.get("status") == "running"]
    return {"jobs": (running + [j for j in recent if j.get("status") != "running"])[:limit]}


@app.get("/api/history")
def history(node: str | None = None, limit: int = 20):
    path = DATA / "history.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    if node:
        rows = [r for r in rows if r.get("node") == node]
    return {"history": rows[::-1][:limit]}


@app.get("/api/state")
def api_state():
    ns = nodes()
    return {"nodes": ns, "state": load_state(), "timing": {n["id"]: node_timing(n["id"]) for n in ns}}


def _run_dir(run_id: str) -> Path:
    d = (DATA / "runs" / run_id).resolve()
    if d.parent != (DATA / "runs").resolve() or not d.is_dir():
        raise HTTPException(404, f"run {run_id} not found")
    return d


@app.get("/api/runs/{run_id}")
def api_run(run_id: str):
    d = _run_dir(run_id)
    return {"run": run_id, "files": [{"name": f.name, "kb": f.stat().st_size // 1024, "url": f"/files/runs/{run_id}/{f.name}"}
                                     for f in sorted(d.iterdir()) if f.is_file()]}


# ---------- pages ----------

@app.get("/")
def dashboard():
    return FileResponse(HERE / "static" / "pipeline.html")


@app.get("/fitting")
def fitting_page():
    return FileResponse(HERE / "static" / "fitting.html")


@app.get("/fitting/qa")
def fit_qa_page():
    return FileResponse(HERE / "static" / "fit-qa.html")


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_files(run_id: str):
    """List a run's artifacts (StaticFiles does not list directories)."""
    d = _run_dir(run_id)
    e = html.escape
    rows = "".join(
        f'<li><a href="/files/runs/{e(run_id)}/{e(f.name)}">{e(f.name)}</a> <span>{f.stat().st_size // 1024} KB</span></li>'
        for f in sorted(d.iterdir()) if f.is_file())
    page = (HERE / "static" / "runs.html").read_text()
    return page.replace("{{TITLE}}", e(run_id)).replace("{{ROWS}}", rows)
