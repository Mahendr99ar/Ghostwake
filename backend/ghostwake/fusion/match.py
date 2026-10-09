"""Match radar detections to AIS. Whatever radar sees and AIS doesn't explain is a dark candidate.

For each SAR scene we estimate where every AIS vessel was at the exact image time,
then solve a one-to-one assignment (Hungarian algorithm) between those positions and
the detections. Greedy nearest-neighbour matching breaks down when two ships sit close
together; the assignment does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from ghostwake.anomalies.models import Alert
from ghostwake.config import Settings, get_settings
from ghostwake.geo import KM_PER_NM, destination, distance_to_polyline_km, haversine_km
from ghostwake.zones import IMBL, ZONES

MIN_DARK_LENGTH_M = 15.0
MIN_DARK_CONFIDENCE = 0.5
UNMATCHED = 1e6


@dataclass
class Estimate:
    mmsi: str
    lat: float
    lon: float
    minutes_to_fix: float
    method: str  # "interpolated" | "dead_reckoned"


@dataclass
class SceneResult:
    scene_id: str
    timestamp: datetime
    detections: list[dict] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)


def estimate_positions(df: pd.DataFrame, when: datetime, window_min: float = 30) -> list[Estimate]:
    when_ts = pd.Timestamp(when)
    out = []
    for mmsi, g in df.groupby("mmsi"):
        before = g[g.ts <= when_ts].tail(1)
        after = g[g.ts > when_ts].head(1)
        b = before.iloc[0] if len(before) else None
        a = after.iloc[0] if len(after) else None
        db = (when_ts - b.ts).total_seconds() / 60 if b is not None else np.inf
        da = (a.ts - when_ts).total_seconds() / 60 if a is not None else np.inf
        if db <= window_min and da <= window_min:
            f = db / (db + da) if db + da > 0 else 0.0
            out.append(Estimate(str(mmsi), b.lat + f * (a.lat - b.lat), b.lon + f * (a.lon - b.lon),
                                min(db, da), "interpolated"))
        elif min(db, da) <= window_min / 2:
            ref, dt_h = (b, db / 60) if db <= da else (a, -da / 60)
            lat, lon = destination(ref.lat, ref.lon, ref.cog, ref.sog * KM_PER_NM * dt_h)
            out.append(Estimate(str(mmsi), lat, lon, min(db, da), "dead_reckoned"))
    return out


def match_scene(
    df: pd.DataFrame,
    scene: dict,
    gaps: list[Alert] | None = None,
    cfg: Settings | None = None,
    model_version: str = "synthetic-truth-v0",
) -> SceneResult:
    cfg = cfg or get_settings()
    when = scene["timestamp"]
    dets = scene["detections"]
    est = estimate_positions(df, when)
    res = SceneResult(scene_id=scene["scene_id"], timestamp=when)

    cost = np.full((len(dets), len(est)), UNMATCHED)
    gate = np.zeros(len(est))
    for j, e in enumerate(est):
        # The further we are from a real fix, the less sure we are where the ship was.
        gate[j] = min(5.0, cfg.match_gate_km + 0.1 * e.minutes_to_fix)
        for i, d in enumerate(dets):
            km = haversine_km(d["lat"], d["lon"], e.lat, e.lon)
            if km <= gate[j]:
                cost[i, j] = km

    matched: dict[int, tuple[Estimate, float]] = {}
    if len(dets) and len(est):
        rows, cols = linear_sum_assignment(cost)
        for i, j in zip(rows, cols):
            if cost[i, j] < UNMATCHED:
                matched[i] = (est[j], float(cost[i, j]))

    for i, d in enumerate(dets):
        det_id = f"{scene['scene_id']}-{i:03d}"
        rec = {
            "id": det_id,
            "scene_id": scene["scene_id"],
            "ts": when,
            "lat": d["lat"],
            "lon": d["lon"],
            "length_m": d["length_m"],
            "confidence": d["confidence"],
            "model_version": model_version,
            "matched_mmsi": None,
            "match_km": None,
            "truth": d.get("truth"),
        }
        if i in matched:
            e, km = matched[i]
            rec["matched_mmsi"], rec["match_km"] = e.mmsi, round(km, 3)
        res.detections.append(rec)

        if i in matched or d["length_m"] < MIN_DARK_LENGTH_M or d["confidence"] < MIN_DARK_CONFIDENCE:
            continue
        res.alerts.append(_dark_alert(rec, scene, gaps or []))
    return res


def _dark_alert(det: dict, scene: dict, gaps: list[Alert]) -> Alert:
    lat, lon, when = det["lat"], det["lon"], det["ts"]
    zones = [z.id for z in ZONES if z.contains(lat, lon)]
    imbl_km = distance_to_polyline_km(lat, lon, IMBL)
    evidence = {
        "scene_id": scene["scene_id"],
        "mission": scene.get("mission"),
        "length_m": det["length_m"],
        "confidence": det["confidence"],
        "zones": zones,
        "imbl_km": round(imbl_km, 1),
        "possible_identity": _guess_identity(det, gaps),
    }
    severity = "high" if zones or imbl_km < 10 or evidence["possible_identity"] else "watch"
    where = "inside a protected area" if zones else f"{imbl_km:.0f} km from the IMBL"
    return Alert(
        kind="dark_vessel",
        severity=severity,
        mmsi=None,
        start=when,
        end=when,
        lat=lat,
        lon=lon,
        summary=f"{det['length_m']:.0f} m vessel on radar with no AIS, {where}",
        evidence=evidence,
        detection_id=det["id"],
    )


def _guess_identity(det: dict, gaps: list[Alert]) -> dict | None:
    """Was a known vessel silent at this moment, and could it have been here?

    We draw the straight line between its last and next AIS fix and ask how far the
    detection sits from where that line puts the ship at image time. A proper version
    would run a Kalman filter with currents; the straight line is the honest baseline.
    """
    best = None
    when = det["ts"]
    for g in gaps:
        if not (g.start <= when <= g.end):
            continue
        a, b = g.evidence["last_fix"], g.evidence["next_fix"]
        span = (g.end - g.start).total_seconds()
        f = (when - g.start).total_seconds() / span if span else 0.0
        plat, plon = a["lat"] + f * (b["lat"] - a["lat"]), a["lon"] + f * (b["lon"] - a["lon"])
        off_km = haversine_km(det["lat"], det["lon"], plat, plon)
        if off_km > 20:
            continue
        if best is None or off_km < best["km_from_expected_path"]:
            best = {"mmsi": g.mmsi, "km_from_expected_path": round(off_km, 1), "gap_alert": g.id}
    return best


def match_all(df: pd.DataFrame, scenes: list[dict], gaps: list[Alert], cfg: Settings | None = None):
    results = [match_scene(df, s, gaps, cfg) for s in scenes]
    # One silent ship can only be one blip per image. If several blips fit its track,
    # keep the identity guess on the closest and drop it from the rest.
    for res in results:
        best: dict[str, Alert] = {}
        for a in res.alerts:
            ident = a.evidence.get("possible_identity")
            if not ident:
                continue
            cur = best.get(ident["mmsi"])
            km = ident["km_from_expected_path"]
            if cur is None or km < cur.evidence["possible_identity"]["km_from_expected_path"]:
                best[ident["mmsi"]] = a
        for a in res.alerts:
            ident = a.evidence.get("possible_identity")
            if ident and best.get(ident["mmsi"]) is not a:
                a.evidence["possible_identity"] = None
                if not a.evidence["zones"] and a.evidence["imbl_km"] >= 10:
                    a.severity = "watch"
    return results
