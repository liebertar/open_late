"""Shared state for the console: config, node state, history, jobs. Everything is a file under DATA_DIR."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path

import yaml
from fastapi import HTTPException

DATA = Path(os.environ.get("DATA_DIR", "/data"))
NODES_FILE = Path(os.environ.get("NODES_FILE", "/pipeline/nodes.yaml"))
PROMPTS = Path(os.environ.get("PROMPTS_DIR", "/pipeline/prompts"))
DOCS = Path(os.environ.get("DOCS_DIR", "/docs"))
PATTERN_URL = os.environ.get("PATTERN_URL", "http://pattern:7110")
WORKER_URL = os.environ.get("WORKER_URL", "http://worker:7120")
ENGINE_URL = os.environ.get("ENGINE_URL", "http://host.docker.internal:8091")
ACTOR = os.environ.get("ACTOR", "owner")

for d in (DATA, DATA / "runs", DATA / "jobs", DATA / "fitting"):
    d.mkdir(parents=True, exist_ok=True)

lock = threading.Lock()


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path: Path, obj) -> None:
    """Atomic write. The temp name is unique per call: two requests writing the same file at once each replace it
    whole (last one wins) instead of one renaming the other's half-written temp file away."""
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    tmp.replace(path)


# ---------- nodes, state, history ----------

def nodes() -> list[dict]:
    return yaml.safe_load(NODES_FILE.read_text())["nodes"]


def node(nid: str) -> dict:
    for n in nodes():
        if n["id"] == nid:
            return n
    raise HTTPException(404, f"unknown node {nid}")


def load_state() -> dict:
    return read_json(DATA / "state.json", {})


def put_state(nid: str, entry: dict) -> None:
    """Replace a node's state. Callers choose which fields carry over, so stale fields never linger."""
    with lock:
        state = load_state()
        state[nid] = {**entry, "updated": now()}
        write_json(DATA / "state.json", state)


def carry(st: dict) -> dict:
    """Fields that survive approve/reject: what was reviewed."""
    return {k: st[k] for k in ("run", "link", "summary", "previews", "seconds") if k in st}


def log(entry: dict) -> None:
    with lock, open(DATA / "history.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **entry}, ensure_ascii=False) + "\n")


# ---------- prompts (pipeline/prompts/*.yaml, read on every call: edit without rebuilding) ----------

_last_good: dict[str, dict] = {}


def prompt(pid: str) -> dict:
    path = PROMPTS / f"{pid}.yaml"
    if not path.exists():
        raise HTTPException(500, f"prompt {pid} not found in {PROMPTS}")
    try:
        _last_good[pid] = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        # an editor is mid-save (we can read a half-written file) or the edit is broken: keep the last good version
        if pid not in _last_good:
            raise HTTPException(500, f"prompt {pid} does not parse: {e}")
        print(f"warning: {path.name} does not parse, serving the last good version: {e}", flush=True)
    return _last_good[pid]


def render_prompt(pid: str, **values) -> tuple[str, dict]:
    """Fill a registry template. Returns the text and a reference {id, version, hash} to store with the output."""
    p = prompt(pid)
    text = " ".join(p["template"].format(**values).split())
    return text, {"id": p["id"], "version": p["version"], "hash": hashlib.sha256(text.encode()).hexdigest()[:12]}


# ---------- jobs ----------

def job_start(name: str, node_id: str | None, total: int, kind: str = "node") -> str:
    jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    write_json(DATA / "jobs" / f"{jid}.json", {
        "id": jid, "name": name, "node": node_id, "kind": kind, "status": "running", "done": 0, "total": total,
        "message": "Queued", "started": now(), "t0": time.time(), "updated": now()})
    return jid


def job_update(jid: str, **fields) -> dict:
    path = DATA / "jobs" / f"{jid}.json"
    with lock:
        job = read_json(path, None)
        if job is None:
            raise HTTPException(404, f"unknown job {jid}")
        job.update({k: v for k, v in fields.items() if v is not None}, updated=now())
        if job.get("status") in ("done", "failed") and "seconds" not in job and job.get("t0"):
            job["seconds"] = round(time.time() - job["t0"], 1)
        write_json(path, job)
    return job


def recent_jobs(limit: int = 50) -> list[dict]:
    return [read_json(p, {}) for p in sorted((DATA / "jobs").glob("*.json"), reverse=True)[:limit]]


def node_timing(nid: str) -> dict | None:
    """Average wall time of finished jobs for a node, for the 'avg seconds' badge."""
    secs = [j["seconds"] for j in recent_jobs(200) if j.get("node") == nid and j.get("status") == "done" and j.get("seconds")]
    return {"avg": round(sum(secs) / len(secs), 1), "n": len(secs)} if secs else None
