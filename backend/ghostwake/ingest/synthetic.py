"""A 36-hour synthetic scenario around the southern tip of India.

Real AIS for Indian waters is not freely available, so the demo runs on a simulated
day and a half that is messy on purpose: duplicate rows, broken coordinates, mixed
timestamp formats and MMSIs typed three different ways. Inside it we plant the
behaviours GhostWake should catch, and we keep a ground-truth record of every one
so the tests can check recall instead of eyeballing the map.

Same seed, same scenario. Change the seed to get a different but equivalent day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from ghostwake.geo import bearing, destination, haversine_km

KM_PER_NM = 1.852
DEFAULT_START = datetime(2026, 5, 20, tzinfo=UTC)  # inside the east-coast ban window
DURATION_H = 36.0
# Approximate Sentinel-1 overpass times over the area (UTC), as hours from start.
SCENE_HOURS = (0.87, 12.97, 24.87)


class Path:
    """Keyframes of (hours, lat, lon). Positions in between are linear."""

    def __init__(self, lat: float, lon: float, t: float = 0.0):
        self.keys: list[tuple[float, float, float]] = [(t, lat, lon)]

    @property
    def end(self) -> tuple[float, float, float]:
        return self.keys[-1]

    def go(self, lat: float, lon: float, kn: float) -> Path:
        t, lat0, lon0 = self.end
        hours = haversine_km(lat0, lon0, lat, lon) / KM_PER_NM / kn
        self.keys.append((t + hours, lat, lon))
        return self

    def hold(self, hours: float) -> Path:
        t, lat, lon = self.end
        self.keys.append((t + hours, lat, lon))
        return self

    def zigzag(self, heading: float, legs: int, leg_km: float, kn: float, turn: float = 65) -> Path:
        # Trawlers work a patch of sea in short alternating legs. This is what
        # separates "fishing" from "passing through" in the track shape.
        for i in range(legs):
            _, lat, lon = self.end
            h = heading + (turn if i % 2 == 0 else -turn)
            nlat, nlon = destination(lat, lon, h, leg_km)
            self.go(nlat, nlon, kn)
        return self

    def at(self, t: float) -> tuple[float, float, float, float]:
        """(lat, lon, sog_knots, cog_deg) at hour t."""
        keys = self.keys
        if t <= keys[0][0]:
            return keys[0][1], keys[0][2], 0.0, 0.0
        for (t0, a0, o0), (t1, a1, o1) in zip(keys, keys[1:]):
            if t0 <= t <= t1:
                f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                dist = haversine_km(a0, o0, a1, o1)
                sog = 0.0 if t1 == t0 else dist / KM_PER_NM / (t1 - t0)
                cog = bearing(a0, o0, a1, o1) if dist > 0 else 0.0
                return a0 + f * (a1 - a0), o0 + f * (o1 - o0), sog, cog
        return keys[-1][1], keys[-1][2], 0.0, 0.0


@dataclass
class Vessel:
    mmsi: str | None  # None = never transmits AIS
    name: str
    flag: str
    vtype: str
    length_m: float
    path: Path
    cadence_min: float = 6.0
    ais_off: list[tuple[float, float]] = field(default_factory=list)
    spoof: list[tuple[float, float, float, float]] = field(default_factory=list)  # (t0, t1, dlat, dlon)

    def transmitting(self, t: float) -> bool:
        return self.mmsi is not None and not any(a <= t < b for a, b in self.ais_off)

    def reported(self, t: float) -> tuple[float, float]:
        lat, lon, _, _ = self.path.at(t)
        for t0, t1, dlat, dlon in self.spoof:
            if t0 <= t < t1:
                return lat + dlat, lon + dlon
        return lat, lon


@dataclass
class Scenario:
    start: datetime
    ais_raw: pd.DataFrame
    scenes: list[dict]
    truth: dict
    vessels: list[Vessel]


def _fleet() -> tuple[list[Vessel], dict]:
    v: list[Vessel] = []

    # Merchant traffic on the shipping lanes south of the tip.
    v.append(Vessel("563104920", "MSC AURORA", "SG", "cargo", 294,
                    Path(7.35, 76.10).go(7.05, 80.50, 14), cadence_min=3))
    v.append(Vessel("477552310", "EVER JADE", "HK", "cargo", 240,
                    Path(7.55, 80.45, t=4).go(7.70, 76.05, 12), cadence_min=3))
    v.append(Vessel("419000231", "DESH VIRAT", "IN", "tanker", 183,
                    Path(7.85, 76.30, t=10).go(7.25, 80.45, 11), cadence_min=3))

    # West coast: ban not in force yet, so normal fishing.
    v.append(Vessel("419112045", "ST ANTONY", "IN", "fishing", 18,
                    Path(8.36, 76.97).go(8.25, 76.70, 7).zigzag(270, 14, 3.0, 3.2)
                    .go(8.36, 76.97, 7).hold(8), cadence_min=10))
    v.append(Vessel("419112311", "MARIYA", "IN", "fishing", 21,
                    Path(8.86, 76.55).go(8.78, 76.25, 7).zigzag(250, 16, 2.6, 3.0)
                    .go(8.86, 76.55, 7).hold(6), cadence_min=10))

    # East coast during the ban: most boats sit in harbour.
    v.append(Vessel("419220017", "SAGAR LAKSHMI", "IN", "fishing", 19,
                    Path(8.755, 78.195).hold(DURATION_H), cadence_min=10))
    v.append(Vessel("419220188", "KADAL RANI", "IN", "fishing", 17,
                    Path(9.278, 79.318).hold(DURATION_H), cadence_min=10))

    # Planted behaviour 1: fishing on the east coast during the ban.
    ban = Vessel("419220402", "ARUL JOTHI", "IN", "fishing", 22,
                 Path(8.752, 78.20, t=2).go(8.58, 78.62, 7).zigzag(120, 18, 2.4, 3.0)
                 .go(8.752, 78.20, 7).hold(10), cadence_min=10)
    v.append(ban)

    # Planted behaviour 2: an Indian boat working right up to the IMBL and over it.
    imbl = Vessel("419220977", "MURUGAN", "IN", "fishing", 14,
                  Path(9.24, 79.36, t=5).go(9.30, 79.505, 5).go(9.315, 79.565, 2.5)
                  .hold(1.5).go(9.24, 79.36, 5).hold(12), cadence_min=10)
    v.append(imbl)

    # Planted behaviour 3: transponder off for ~11 h while working inside the marine park.
    gap = Vessel("412339871", "SEA FALCON", "--", "fishing", 32,
                 Path(7.70, 78.85).go(8.98, 78.62, 9).zigzag(300, 20, 2.0, 2.2)
                 .go(7.60, 78.95, 9), cadence_min=6, ais_off=[(8.0, 19.0)])
    v.append(gap)

    # Planted behaviour 4: reported position jumps ~100 km inland and back.
    spoof = Vessel("636018442", "PACIFIC STAR", "LR", "reefer", 120,
                   Path(7.60, 76.40).go(7.90, 78.30, 10).go(7.75, 79.60, 10),
                   cadence_min=4, spoof=[(14.0, 16.0, 0.9, 0.0)])
    v.append(spoof)

    # Planted behaviour 5: a reefer and a trawler sit together mid-sea (possible transshipment).
    reefer = Vessel("357221090", "ORIENT REEFER", "PA", "reefer", 110,
                    Path(7.20, 80.30, t=12).go(7.752, 79.102, 11).hold(3.5).go(7.10, 80.40, 11),
                    cadence_min=4)
    trawler = Vessel("412700315", "HAI LONG 7", "--", "fishing", 45,
                     Path(8.30, 79.35, t=14).go(7.754, 79.104, 8).hold(3.5).go(8.40, 79.40, 8),
                     cadence_min=6)
    v += [reefer, trawler]

    # Ships that never transmit. Only radar will ever see them.
    v.append(Vessel(None, "dark-1", "", "unknown", 28,
                    Path(9.08, 78.88).zigzag(200, 30, 1.8, 2.0)))
    v.append(Vessel(None, "dark-2", "", "unknown", 24,
                    Path(8.92, 79.22).zigzag(30, 30, 1.5, 1.8)))
    v.append(Vessel(None, "dark-3", "", "unknown", 46,
                    Path(7.96, 78.94).go(7.80, 79.05, 2).hold(30)))

    truth = {
        "ban": [ban.mmsi],
        "imbl": [imbl.mmsi],
        "gap": [gap.mmsi],
        "spoof": [spoof.mmsi],
        "rendezvous": [sorted([reefer.mmsi, trawler.mmsi])],
    }
    return v, truth


def _messy_timestamp(ts: datetime, rng: np.random.Generator) -> str:
    r = rng.random()
    if r < 0.6:
        return ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    if r < 0.9:
        return ts.strftime("%Y-%m-%d %H:%M:%S+00:00")
    return str(int(ts.timestamp()))  # some feeds send epoch seconds


def _messy_mmsi(mmsi: str, rng: np.random.Generator) -> str:
    r = rng.random()
    if r < 0.85:
        return mmsi
    if r < 0.95:
        return f" {mmsi} "
    return f"MMSI:{mmsi}"


def build(seed: int = 7, start: datetime = DEFAULT_START) -> Scenario:
    rng = np.random.default_rng(seed)
    vessels, truth = _fleet()

    rows = []
    for vs in vessels:
        if vs.mmsi is None:
            continue
        t = rng.uniform(0, vs.cadence_min / 60)
        while t < DURATION_H:
            # Ordinary reception loss: about 3% of messages never arrive.
            if vs.transmitting(t) and rng.random() > 0.03:
                lat, lon = vs.reported(t)
                _, _, sog, cog = vs.path.at(t)
                ts = start + timedelta(hours=t)
                rows.append({
                    "mmsi": _messy_mmsi(vs.mmsi, rng),
                    "timestamp": _messy_timestamp(ts, rng),
                    "lat": round(lat + rng.normal(0, 0.0002), 6),
                    "lon": round(lon + rng.normal(0, 0.0002), 6),
                    "sog": round(max(0.0, sog + rng.normal(0, 0.2)), 1),
                    "cog": round((cog + rng.normal(0, 3)) % 360, 1),
                    "name": vs.name,
                    "flag": vs.flag,
                    "vessel_type": vs.vtype,
                    "length_m": vs.length_m,
                })
            t += vs.cadence_min / 60 * rng.uniform(0.8, 1.2)

    df = pd.DataFrame(rows)

    # Garbage that real feeds are full of.
    dupes = df.sample(frac=0.02, random_state=seed)
    broken = df.sample(n=12, random_state=seed + 1).copy()
    broken.loc[broken.index[:6], "lat"] = 91.0
    broken.loc[broken.index[6:], ["lat", "lon"]] = 0.0  # "null island"
    df = pd.concat([df, dupes, broken], ignore_index=True)
    df = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)  # feeds arrive out of order

    scenes = []
    for h in SCENE_HOURS:
        when = start + timedelta(hours=h)
        dets = []
        for vs in vessels:
            lat, lon, _, _ = vs.path.at(h)
            if vs.length_m < 12:
                continue
            p_detect = 0.95 if vs.length_m >= 20 else 0.7
            if rng.random() > p_detect:
                continue
            # Radar position error of ~150 m, length error of ~15%.
            nlat, nlon = destination(lat, lon, rng.uniform(0, 360), abs(rng.normal(0, 0.15)))
            dets.append({
                "lat": round(nlat, 6),
                "lon": round(nlon, 6),
                "length_m": round(max(8.0, vs.length_m * rng.normal(1, 0.15)), 1),
                "confidence": round(float(min(0.99, 0.6 + vs.length_m / 300 + rng.normal(0, 0.05))), 2),
                "truth": "dark" if not vs.transmitting(h) else "ais",
                "truth_mmsi": vs.mmsi,
            })
        # Sea clutter and small returns that are not ships.
        for _ in range(2):
            dets.append({
                "lat": round(rng.uniform(7.3, 8.6), 6),
                "lon": round(rng.uniform(78.4, 80.0), 6),
                "length_m": round(rng.uniform(7, 11), 1),
                "confidence": round(rng.uniform(0.35, 0.55), 2),
                "truth": "clutter",
                "truth_mmsi": None,
            })
        scenes.append({
            "scene_id": f"S1-{when:%Y%m%dT%H%M}",
            "timestamp": when,
            "mission": "Sentinel-1 (synthetic)",
            "detections": dets,
        })

    truth["dark_mmsi_in_scenes"] = [
        d["truth_mmsi"] for s in scenes for d in s["detections"]
        if d["truth"] == "dark" and d["truth_mmsi"]
    ]
    return Scenario(start=start, ais_raw=df, scenes=scenes, truth=truth, vessels=vessels)


if __name__ == "__main__":  # quick look: python -m ghostwake.ingest.synthetic
    sc = build()
    print(sc.ais_raw.head(10).to_string())
    print(len(sc.ais_raw), "AIS rows;", sum(len(s["detections"]) for s in sc.scenes), "SAR detections")
    print(sc.truth)
