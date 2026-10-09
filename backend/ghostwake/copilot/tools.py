"""The only things the copilot can do. All read-only.

The copilot never gets SQL, never writes, and never sees more than these functions
return. Escalating or dismissing an alert is a human action in the UI, on purpose.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ghostwake.db import AlertRow, Review, Vessel, utc
from ghostwake.zones import BAN_WINDOWS, IMBL, ZONES


def _alert_brief(a: AlertRow) -> dict:
    return {
        "id": a.id, "kind": a.kind, "severity": a.severity, "status": a.status,
        "score": a.score, "mmsi": a.mmsi, "summary": a.summary,
        "start": utc(a.start).isoformat(), "lat": round(a.lat, 4), "lon": round(a.lon, 4),
    }


def list_alerts(s: Session, kind: str | None = None, min_score: float = 0,
                status: str | None = None, limit: int = 10) -> list[dict]:
    q = select(AlertRow).where(AlertRow.score >= min_score)
    if kind:
        q = q.where(AlertRow.kind == kind)
    if status:
        q = q.where(AlertRow.status == status)
    q = q.order_by(AlertRow.score.desc()).limit(max(1, min(limit, 25)))
    return [_alert_brief(a) for a in s.scalars(q)]


def get_alert(s: Session, alert_id: str) -> dict | None:
    a = s.get(AlertRow, alert_id)
    if a is None:
        return None
    out = _alert_brief(a)
    out["end"] = utc(a.end).isoformat()
    out["evidence"] = a.evidence
    out["contributions"] = a.contributions
    out["reviews"] = [
        {"action": r.action, "analyst": r.analyst, "note": r.note, "ts": utc(r.ts).isoformat()}
        for r in s.scalars(select(Review).where(Review.alert_id == alert_id).order_by(Review.id))
    ]
    if a.mmsi:
        out["vessel"] = vessel_profile(s, a.mmsi, with_alerts=False)
    return out


def vessel_profile(s: Session, mmsi: str, with_alerts: bool = True) -> dict | None:
    v = s.get(Vessel, mmsi)
    if v is None:
        return None
    out = {
        "mmsi": v.mmsi, "name": v.name, "flag": v.flag, "type": v.vessel_type,
        "length_m": v.length_m, "risk": v.risk,
        "last_seen": utc(v.last_seen).isoformat() if v.last_seen else None,
    }
    if with_alerts:
        out["alerts"] = [_alert_brief(a) for a in s.scalars(
            select(AlertRow).where(AlertRow.mmsi == mmsi).order_by(AlertRow.score.desc()))]
    return out


def area_rules() -> dict:
    return {
        "imbl": "Approximate India / Sri Lanka boundary, demo geometry only",
        "imbl_points": len(IMBL),
        "protected_areas": [z.name for z in ZONES],
        "monsoon_ban": {k: f"{a[1]:02d}/{a[0]:02d} to {b[1]:02d}/{b[0]:02d}" for k, (a, b) in BAN_WINDOWS.items()},
    }


# OpenAI-style function schemas, used when a real LLM is configured.
SCHEMAS = [
    {"type": "function", "function": {
        "name": "list_alerts",
        "description": "List alerts, highest score first.",
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": [
                "dark_vessel", "ais_gap", "spoofing", "rendezvous", "ban_period_fishing",
                "protected_area_loitering", "imbl_crossing", "imbl_proximity"]},
            "min_score": {"type": "number"},
            "status": {"type": "string", "enum": ["open", "escalated", "dismissed"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 25},
        }},
    }},
    {"type": "function", "function": {
        "name": "get_alert",
        "description": "Full evidence, score breakdown and review history for one alert.",
        "parameters": {"type": "object", "properties": {"alert_id": {"type": "string"}},
                       "required": ["alert_id"]},
    }},
    {"type": "function", "function": {
        "name": "vessel_profile",
        "description": "Static details, risk and alerts for one vessel by MMSI.",
        "parameters": {"type": "object", "properties": {"mmsi": {"type": "string"}},
                       "required": ["mmsi"]},
    }},
    {"type": "function", "function": {
        "name": "area_rules",
        "description": "Boundaries, protected areas and fishing-ban dates in the demo area.",
        "parameters": {"type": "object", "properties": {}},
    }},
]


def call(s: Session, name: str, args: dict) -> object:
    if name == "list_alerts":
        return list_alerts(s, **{k: v for k, v in args.items() if k in {"kind", "min_score", "status", "limit"}})
    if name == "get_alert":
        return get_alert(s, str(args.get("alert_id", "")))
    if name == "vessel_profile":
        return vessel_profile(s, str(args.get("mmsi", "")))
    if name == "area_rules":
        return area_rules()
    return {"error": f"unknown tool {name}"}
