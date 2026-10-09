"""Explainable risk scores.

Every point of a score comes from a named reason, so the analyst sees "AIS gap +25,
inside marine park +15" and not a bare 72. The weights are hand-set for now. Once
analysts have reviewed a few hundred alerts, those decisions become labels and a
small gradient-boosted model (LightGBM + SHAP) can replace the table below while
keeping the same "reason, points" output.
"""

from __future__ import annotations

from collections import defaultdict

from ghostwake.anomalies.models import Alert

BASE = {
    "dark_vessel": 35,
    "ais_gap": 25,
    "spoofing": 30,
    "rendezvous": 25,
    "ban_period_fishing": 20,
    "protected_area_loitering": 15,
    "imbl_crossing": 30,
    "imbl_proximity": 15,
}

LABELS = {
    "dark_vessel": "Seen on radar, no AIS",
    "ais_gap": "AIS switched off",
    "spoofing": "Impossible position jump",
    "rendezvous": "Met another ship at sea",
    "ban_period_fishing": "Fishing during monsoon ban",
    "protected_area_loitering": "Slow inside marine park",
    "imbl_crossing": "Crossed the IMBL",
    "imbl_proximity": "Close to the IMBL",
}


def score(alerts: list[Alert], static_flags: dict[str, str] | None = None) -> list[Alert]:
    flags = static_flags or {}
    by_vessel: dict[str, list[Alert]] = defaultdict(list)
    for a in alerts:
        if a.mmsi:
            by_vessel[a.mmsi].append(a)
        other = a.evidence.get("other_mmsi")
        if other:
            by_vessel[other].append(a)

    for a in alerts:
        parts = [{"reason": LABELS.get(a.kind, a.kind), "points": BASE.get(a.kind, 10)}]

        if a.evidence.get("zones") or a.evidence.get("zone"):
            parts.append({"reason": "Inside a marine protected area", "points": 15})
        if a.kind == "ais_gap":
            parts.append({"reason": f"Gap length {a.evidence['gap_hours']:.0f} h",
                          "points": min(20, round(a.evidence["gap_hours"]))})
        if a.kind == "dark_vessel":
            ident = a.evidence.get("possible_identity")
            if ident:
                parts.append({"reason": f"Fits the silent track of {ident['mmsi']}", "points": 20})
            if a.evidence.get("imbl_km", 99) < 10:
                parts.append({"reason": "Within 10 km of the IMBL", "points": 10})
            if a.evidence.get("length_m", 0) >= 30:
                parts.append({"reason": "Large hull (30 m or more)", "points": 5})
        if a.mmsi and flags.get(a.mmsi) in ("--", "", None):
            parts.append({"reason": "No flag state reported", "points": 10})

        # Several independent rules firing on the same ship is the strongest signal we have.
        linked = {x.kind for x in by_vessel.get(a.mmsi or "", []) if x is not a}
        if a.kind == "dark_vessel" and a.evidence.get("possible_identity"):
            linked |= {x.kind for x in by_vessel.get(a.evidence["possible_identity"]["mmsi"], [])}
        linked.discard(a.kind)
        if linked:
            parts.append({"reason": f"Also flagged for: {', '.join(sorted(LABELS.get(k, k) for k in linked))}",
                          "points": min(20, 10 * len(linked))})

        a.contributions = parts
        a.score = float(min(100, sum(p["points"] for p in parts)))
    return alerts


def vessel_risk(alerts: list[Alert]) -> dict[str, float]:
    """Combine alert scores per vessel as independent evidence: 1 - prod(1 - s)."""
    acc: dict[str, float] = defaultdict(lambda: 1.0)
    for a in alerts:
        if a.mmsi:
            acc[a.mmsi] *= 1 - a.score / 100
    return {m: round(100 * (1 - p), 1) for m, p in acc.items()}
