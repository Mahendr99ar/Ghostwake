"""HTTP API for the ops console.

Reads are open. Writes (reviewing an alert) need the analyst token. The copilot and
review endpoints are rate limited per client so a free-tier deployment can't be run
into the ground by one tab left open.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from html import escape
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ghostwake import __version__
from ghostwake.config import get_settings
from ghostwake.copilot import agent
from ghostwake.db import (
    AlertRow,
    Detection,
    Event,
    Position,
    Review,
    Run,
    Scene,
    Vessel,
    init_db,
    now,
    session_factory,
    utc,
)
from ghostwake.detect.sar import chip
from ghostwake.zones import AOI, zones_geojson

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="GhostWake API", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Analyst"],
)


def db():
    s = session_factory()()
    try:
        yield s
    finally:
        s.close()


# --------------------------------------------------------------------------- helpers

_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(request: Request, per_minute: int = 20) -> None:
    key = f"{request.client.host if request.client else 'anon'}:{request.url.path.split('/')[2]}"
    q, t = _hits[key], time.monotonic()
    while q and t - q[0] > 60:
        q.popleft()
    if len(q) >= per_minute:
        raise HTTPException(429, "Too many requests. Try again in a minute.")
    q.append(t)


def require_analyst(authorization: str = Header(default="")) -> None:
    token = authorization.removeprefix("Bearer ").strip()
    if not token or not secrets.compare_digest(token, settings.analyst_token):
        raise HTTPException(401, "Analyst token required for this action.")


def iso(dt) -> str | None:
    return utc(dt).isoformat().replace("+00:00", "Z") if dt else None


def alert_json(a: AlertRow, full: bool = False) -> dict:
    out = {
        "id": a.id, "kind": a.kind, "category": a.category, "severity": a.severity,
        "status": a.status, "mmsi": a.mmsi, "detection_id": a.detection_id,
        "start": iso(a.start), "end": iso(a.end), "lat": a.lat, "lon": a.lon,
        "summary": a.summary, "score": a.score,
    }
    if full:
        out |= {"contributions": a.contributions, "evidence": a.evidence, "lineage": a.lineage,
                "created_at": iso(a.created_at), "updated_at": iso(a.updated_at)}
    return out


# --------------------------------------------------------------------------- reads

@app.get("/api/health")
def health(s: Session = Depends(db)):
    last = s.scalars(select(Run).order_by(Run.started_at.desc()).limit(1)).first()
    open_alerts = s.scalar(select(func.count()).select_from(AlertRow).where(AlertRow.status == "open"))
    newest = s.scalar(select(func.max(Position.ts)))
    return {
        "ok": True,
        "version": __version__,
        "copilot": "llm" if settings.llm_base_url and settings.llm_model else "offline",
        "open_alerts": open_alerts or 0,
        "last_run": None if last is None else {
            "id": last.id, "finished_at": iso(last.finished_at), "source": last.source,
            "counts": last.counts, "cleaning": last.clean_report, "params": last.params,
        },
        "data_through": iso(newest),
    }


@app.get("/api/meta")
def meta():
    return {"aoi": AOI, "zones": zones_geojson()}


@app.get("/api/alerts")
def list_alerts(
    s: Session = Depends(db),
    status: str | None = None,
    kind: str | None = None,
    category: str | None = None,
    min_score: float = 0,
    limit: int = Query(200, le=500),
):
    q = select(AlertRow).where(AlertRow.score >= min_score)
    if status:
        q = q.where(AlertRow.status == status)
    if kind:
        q = q.where(AlertRow.kind == kind)
    if category:
        q = q.where(AlertRow.category == category)
    q = q.order_by(AlertRow.score.desc(), AlertRow.start).limit(limit)
    return [alert_json(a) for a in s.scalars(q)]


@app.get("/api/alerts/{alert_id}")
def get_alert(alert_id: str, s: Session = Depends(db)):
    a = s.get(AlertRow, alert_id)
    if a is None:
        raise HTTPException(404, "No such alert.")
    out = alert_json(a, full=True)
    out["reviews"] = [
        {"action": r.action, "analyst": r.analyst, "note": r.note, "ts": iso(r.ts)}
        for r in s.scalars(select(Review).where(Review.alert_id == a.id).order_by(Review.id))
    ]
    if a.mmsi:
        v = s.get(Vessel, a.mmsi)
        out["vessel"] = v and {"mmsi": v.mmsi, "name": v.name, "flag": v.flag, "type": v.vessel_type,
                               "length_m": v.length_m, "risk": v.risk}
    if a.detection_id:
        d = s.get(Detection, a.detection_id)
        out["detection"] = d and {"id": d.id, "scene_id": d.scene_id, "ts": iso(d.ts), "lat": d.lat,
                                  "lon": d.lon, "length_m": d.length_m, "confidence": d.confidence,
                                  "model_version": d.model_version}
    return out


@app.get("/api/vessels")
def vessels(s: Session = Depends(db)):
    return [
        {"mmsi": v.mmsi, "name": v.name, "flag": v.flag, "type": v.vessel_type, "length_m": v.length_m,
         "risk": v.risk, "last_seen": iso(v.last_seen), "lat": v.last_lat, "lon": v.last_lon}
        for v in s.scalars(select(Vessel).order_by(Vessel.risk.desc()))
    ]


@app.get("/api/tracks")
def tracks(s: Session = Depends(db), mmsi: str | None = None):
    """Every track as compact arrays: [lon, lat] path plus seconds since the scenario start."""
    q = select(Position.mmsi, Position.ts, Position.lon, Position.lat).order_by(Position.mmsi, Position.ts)
    if mmsi:
        q = q.where(Position.mmsi == mmsi)
    rows = s.execute(q).all()
    if not rows:
        return {"t0": None, "tracks": []}
    t0 = min(utc(r.ts) for r in rows)
    by: dict[str, dict] = {}
    for m, ts, lon, lat in rows:
        tr = by.setdefault(m, {"mmsi": m, "path": [], "t": []})
        tr["path"].append([round(lon, 5), round(lat, 5)])
        tr["t"].append(int((utc(ts) - t0).total_seconds()))
    return {"t0": iso(t0), "tracks": list(by.values())}


@app.get("/api/detections")
def detections(s: Session = Depends(db)):
    scenes = {sc.id: iso(sc.ts) for sc in s.scalars(select(Scene))}
    return [
        {"id": d.id, "scene_id": d.scene_id, "ts": scenes.get(d.scene_id), "lat": d.lat, "lon": d.lon,
         "length_m": d.length_m, "confidence": d.confidence, "matched_mmsi": d.matched_mmsi}
        for d in s.scalars(select(Detection))
    ]


@app.get("/api/detections/{det_id}/chip")
def detection_chip(det_id: str, s: Session = Depends(db)):
    d = s.get(Detection, det_id)
    if d is None:
        raise HTTPException(404, "No such detection.")
    return {"id": d.id, "size": 64, "pixel_m": 5, "pixels": chip(d.id, d.length_m), "synthetic": True}


# --------------------------------------------------------------------------- writes

class ReviewIn(BaseModel):
    action: Literal["escalate", "dismiss", "reopen"]
    note: str = Field(default="", max_length=1000)


@app.post("/api/alerts/{alert_id}/review", dependencies=[Depends(require_analyst)])
def review(alert_id: str, body: ReviewIn, request: Request, s: Session = Depends(db),
           x_analyst: str = Header(default="analyst")):
    rate_limit(request, per_minute=settings.review_per_minute)
    a = s.get(AlertRow, alert_id)
    if a is None:
        raise HTTPException(404, "No such alert.")
    if body.action == "dismiss" and not body.note.strip():
        raise HTTPException(422, "Say why you are dismissing it. The note is the audit trail.")
    a.status = {"escalate": "escalated", "dismiss": "dismissed", "reopen": "open"}[body.action]
    a.updated_at = now()
    s.add(Review(alert_id=a.id, action=body.action, analyst=x_analyst[:64], note=body.note.strip()))
    s.add(Event(type="alert.reviewed", payload={"id": a.id, "status": a.status}))
    s.commit()
    return alert_json(a)


# --------------------------------------------------------------------------- copilot

class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    alert_id: str | None = None


@app.post("/api/copilot")
def copilot(body: AskIn, request: Request, s: Session = Depends(db)):
    rate_limit(request, per_minute=settings.copilot_per_minute)
    return agent.answer(s, body.question, body.alert_id)


# --------------------------------------------------------------------------- live stream

@app.get("/api/stream")
async def stream(after: int = 0):
    """Server-sent events. One line per new alert or review; a comment every 15 s keeps proxies awake."""
    Session_ = session_factory()

    async def gen():
        cursor, last_beat = after, time.monotonic()
        if cursor == 0:
            with Session_() as s:
                cursor = s.scalar(select(func.max(Event.id))) or 0
        yield f"event: hello\ndata: {json.dumps({'cursor': cursor})}\n\n"
        while True:
            with Session_() as s:
                rows = s.scalars(select(Event).where(Event.id > cursor).order_by(Event.id).limit(50)).all()
            for e in rows:
                cursor = e.id
                yield f"id: {e.id}\nevent: {e.type}\ndata: {json.dumps(e.payload)}\n\n"
            if time.monotonic() - last_beat > 15:
                last_beat = time.monotonic()
                yield ": keep-alive\n\n"
            await asyncio.sleep(3)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- case file

@app.get("/api/alerts/{alert_id}/report", response_class=HTMLResponse)
def report(alert_id: str, s: Session = Depends(db)):
    """A printable case file. Open it in a browser and print to PDF."""
    a = get_alert(alert_id, s)
    e = escape
    rows = "".join(f"<tr><td>{e(c['reason'])}</td><td class=n>+{c['points']}</td></tr>"
                   for c in a["contributions"])
    ev = "".join(f"<tr><th>{e(str(k))}</th><td>{e(json.dumps(v, default=str))}</td></tr>"
                 for k, v in a["evidence"].items())
    src = "".join(f"<li>{e(json.dumps(x))}</li>" for x in a["lineage"].get("sources", []))
    revs = "".join(f"<li>{e(r['ts'][:16])}: {e(r['action'])} by {e(r['analyst'])}. {e(r['note'])}</li>"
                   for r in a["reviews"]) or "<li>Not reviewed yet.</li>"
    vessel = a.get("vessel") or {}
    title = f"{vessel.get('name') or 'Unidentified vessel'} / {a['kind'].replace('_', ' ')}"
    generated = now().strftime("%d %b %Y %H:%M UTC")
    return f"""<!doctype html><html><head><meta charset=utf-8><title>Case {e(a['id'])}</title>
<style>
body{{font:14px/1.5 Georgia,serif;max-width:760px;margin:40px auto;color:#111;padding:0 20px}}
h1{{font:600 22px/1.2 system-ui,sans-serif;margin:0 0 4px}} .meta{{color:#555;font:12px system-ui}}
h2{{font:600 13px system-ui;text-transform:uppercase;letter-spacing:.08em;margin:28px 0 8px;border-bottom:1px solid #ccc}}
table{{border-collapse:collapse;width:100%}} td,th{{text-align:left;padding:4px 6px;border-bottom:1px solid #eee;vertical-align:top}}
th{{width:30%;color:#444;font-weight:500}} .n{{text-align:right;font-family:ui-monospace,monospace}}
code,li{{font-size:12px}} .score{{font:600 40px system-ui;float:right}}
</style></head><body>
<div class=score>{a['score']:.0f}</div>
<h1>{e(title)}</h1>
<div class=meta>Case {e(a['id'])}, {e(a['severity'])} severity, status {e(a['status'])}. Generated {generated}.</div>
<p>{e(a['summary'])}. Window {e(a['start'][:16])} to {e(a['end'][:16])} UTC at {a['lat']:.4f}, {a['lon']:.4f}.</p>
<h2>Why it scored {a['score']:.0f}</h2><table>{rows}</table>
<h2>Evidence</h2><table>{ev}</table>
<h2>Where it came from</h2><ul>{src}</ul>
<p class=meta>Pipeline {e(a['lineage'].get('pipeline_version', ''))}, run {e(a['lineage'].get('run_id', ''))}, rule {e(a['lineage'].get('rule', ''))}.</p>
<h2>Decisions</h2><ul>{revs}</ul>
<p class=meta>Demo data. Boundaries are approximate and not for navigation.</p>
</body></html>"""
