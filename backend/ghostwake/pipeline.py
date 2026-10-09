"""One full pass: ingest, clean, run rules, fuse with radar, score, store.

    python -m ghostwake.pipeline              # synthetic scenario, seed 7
    python -m ghostwake.pipeline --seed 11    # a different day

Safe to run repeatedly. Alerts have stable ids, so a rerun updates scores and evidence
but never touches an analyst's decision (status and reviews stay as they are).
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import delete, select

from ghostwake import __version__, risk
from ghostwake.anomalies import rules
from ghostwake.config import get_settings
from ghostwake.db import (
    AlertRow,
    Detection,
    Event,
    Position,
    Run,
    Scene,
    Vessel,
    init_db,
    now,
    session_factory,
)
from ghostwake.fusion import match
from ghostwake.ingest import ais, synthetic

SAFETY_KINDS = {"imbl_crossing", "imbl_proximity"}


def _lineage(alert, run_id: str, rep: dict, cfg) -> dict:
    sources = []
    if alert.mmsi:
        sources.append({"type": "ais", "mmsi": alert.mmsi, "window": [alert.start.isoformat(), alert.end.isoformat()]})
    if alert.detection_id:
        sources.append({
            "type": "sar_detection",
            "detection_id": alert.detection_id,
            "scene_id": alert.evidence.get("scene_id"),
            "mission": alert.evidence.get("mission"),
        })
    ident = alert.evidence.get("possible_identity")
    if ident:
        sources.append({"type": "linked_alert", "alert_id": ident["gap_alert"], "reason": "silent-track fit"})
    return {
        "run_id": run_id,
        "pipeline_version": __version__,
        "rule": alert.kind,
        "thresholds": {
            "gap_hours": cfg.gap_hours,
            "spoof_knots": cfg.spoof_knots,
            "rendezvous_km": cfg.rendezvous_km,
            "rendezvous_hours": cfg.rendezvous_hours,
            "imbl_warn_km": cfg.imbl_warn_km,
            "match_gate_km": cfg.match_gate_km,
        },
        "sources": sources,
        "cleaning": rep,
    }


def run(seed: int = 7, db_url: str | None = None) -> dict:
    cfg = get_settings()
    init_db(db_url)
    Session = session_factory(db_url)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    started = now()

    scenario = synthetic.build(seed=seed)
    clean_df, report = ais.clean(scenario.ais_raw)
    static = ais.static_info(clean_df)

    alerts = rules.run_all(clean_df, static, cfg)
    gaps = [a for a in alerts if a.kind == "ais_gap"]
    scene_results = match.match_all(clean_df, scenario.scenes, gaps, cfg)
    alerts += [a for r in scene_results for a in r.alerts]
    risk.score(alerts, dict(zip(static.mmsi, static.flag)))
    vessel_risk = risk.vessel_risk(alerts)

    with Session.begin() as s:
        # Positions and detections are a replay of the source data, so replace them wholesale.
        s.execute(delete(Position))
        s.execute(delete(Detection))
        s.execute(delete(Scene))
        s.bulk_insert_mappings(Position, [
            {"mmsi": r.mmsi, "ts": r.ts.to_pydatetime(), "lat": r.lat, "lon": r.lon,
             "sog": r.sog, "cog": r.cog, "h3": r.h3}
            for r in clean_df.itertuples()
        ])

        last = clean_df.sort_values("ts").groupby("mmsi").tail(1).set_index("mmsi")
        for v in static.itertuples():
            lr = last.loc[v.mmsi]
            s.merge(Vessel(
                mmsi=v.mmsi, name=v.name, flag=v.flag, vessel_type=v.vessel_type,
                length_m=float(v.length_m), risk=vessel_risk.get(v.mmsi, 0.0),
                last_seen=lr.ts.to_pydatetime(), last_lat=float(lr.lat), last_lon=float(lr.lon),
            ))

        for res, sc in zip(scene_results, scenario.scenes):
            s.add(Scene(id=sc["scene_id"], ts=sc["timestamp"], mission=sc["mission"]))
            s.flush()
            for d in res.detections:
                s.add(Detection(**{k: v for k, v in d.items() if k != "truth"}))

        existing = {a.id: a for a in s.scalars(select(AlertRow))}
        created = 0
        for a in alerts:
            row = existing.get(a.id)
            fields = dict(
                kind=a.kind,
                category="safety" if a.kind in SAFETY_KINDS else "enforcement",
                severity=a.severity, mmsi=a.mmsi, detection_id=a.detection_id,
                start=a.start, end=a.end, lat=a.lat, lon=a.lon, summary=a.summary,
                score=a.score, contributions=a.contributions,
                evidence=json.loads(json.dumps(a.evidence, default=float)),
                lineage=_lineage(a, run_id, report.as_dict(), cfg), run_id=run_id, updated_at=now(),
            )
            if row is None:
                s.add(AlertRow(id=a.id, status="open", created_at=now(), **fields))
                s.add(Event(type="alert.created", payload={"id": a.id, "kind": a.kind,
                                                           "severity": a.severity, "score": a.score}))
                created += 1
            else:
                for k, val in fields.items():
                    setattr(row, k, val)

        counts = {
            "positions": len(clean_df),
            "vessels": len(static),
            "scenes": len(scenario.scenes),
            "detections": sum(len(r.detections) for r in scene_results),
            "dark_candidates": sum(len(r.alerts) for r in scene_results),
            "alerts": len(alerts),
            "alerts_created": created,
        }
        s.add(Run(id=run_id, started_at=started, finished_at=now(), source=f"synthetic:seed={seed}",
                  params={"seed": seed, "scenario_start": scenario.start.isoformat()},
                  clean_report=report.as_dict(), counts=counts))
    return {"run_id": run_id, "clean": report.as_dict(), "counts": counts}


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the GhostWake pipeline once.")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--db", default=None, help="database URL (defaults to GW_DATABASE_URL)")
    args = ap.parse_args()
    out = run(seed=args.seed, db_url=args.db)
    pd.set_option("display.width", 120)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
