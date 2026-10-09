"""Behaviour rules over clean AIS tracks.

Each rule is a plain function that takes tracks and returns Alerts. No rule knows about
the others; scoring and linking happen later in risk.py. That keeps every rule small
enough to test on its own with a planted event.
"""

from __future__ import annotations

from collections.abc import Iterable
from itertools import combinations

import numpy as np
import pandas as pd

from ghostwake.anomalies.models import Alert
from ghostwake.config import Settings, get_settings
from ghostwake.geo import distance_to_polyline_km, haversine_km, knots, side_of_polyline
from ghostwake.zones import (
    IMBL,
    INDIAN_SIDE_REF,
    PORT_RADIUS_KM,
    PORTS,
    ZONES,
    coast_of,
    in_ban_window,
)


def _tracks(df: pd.DataFrame) -> Iterable[tuple[str, pd.DataFrame]]:
    for mmsi, g in df.groupby("mmsi", sort=False):
        yield str(mmsi), g.sort_values("ts").reset_index(drop=True)


def near_port(lat: float, lon: float) -> str | None:
    for name, (plat, plon) in PORTS.items():
        if haversine_km(lat, lon, plat, plon) <= PORT_RADIUS_KM:
            return name
    return None


def ais_gaps(df: pd.DataFrame, cfg: Settings | None = None) -> list[Alert]:
    cfg = cfg or get_settings()
    out = []
    for mmsi, g in _tracks(df):
        dt_h = g["ts"].diff().dt.total_seconds() / 3600
        for i in np.flatnonzero(dt_h.to_numpy() >= cfg.gap_hours):
            a, b = g.iloc[i - 1], g.iloc[i]
            # A boat tied up in harbour that stops transmitting is normal, not a story.
            if near_port(a.lat, a.lon) and near_port(b.lat, b.lon):
                continue
            dist = haversine_km(a.lat, a.lon, b.lat, b.lon)
            hours = float(dt_h.iloc[i])
            inside = [z.id for z in ZONES if z.contains(a.lat, a.lon) or z.contains(b.lat, b.lon)]
            out.append(Alert(
                kind="ais_gap",
                severity="high" if inside or hours >= 2 * cfg.gap_hours else "watch",
                mmsi=mmsi,
                start=a.ts.to_pydatetime(),
                end=b.ts.to_pydatetime(),
                lat=float(a.lat),
                lon=float(a.lon),
                summary=f"AIS silent for {hours:.1f} h",
                evidence={
                    "gap_hours": round(hours, 2),
                    "last_fix": {"lat": a.lat, "lon": a.lon, "ts": a.ts.isoformat()},
                    "next_fix": {"lat": b.lat, "lon": b.lon, "ts": b.ts.isoformat()},
                    "distance_km": round(dist, 2),
                    "implied_knots": round(knots(dist, hours), 1),
                    "zones": inside,
                },
            ))
    return out


def spoofing(df: pd.DataFrame, cfg: Settings | None = None) -> list[Alert]:
    """Consecutive fixes that would need an impossible speed. One alert per vessel."""
    cfg = cfg or get_settings()
    out = []
    for mmsi, g in _tracks(df):
        lat, lon = g["lat"].to_numpy(), g["lon"].to_numpy()
        hours = g["ts"].diff().dt.total_seconds().to_numpy()[1:] / 3600
        jumps = []
        for i in range(1, len(g)):
            d = haversine_km(lat[i - 1], lon[i - 1], lat[i], lon[i])
            if d > 5 and knots(d, max(hours[i - 1], 1 / 3600)) > cfg.spoof_knots:
                jumps.append((i, d))
        if not jumps:
            continue
        first, last = jumps[0][0], jumps[-1][0]
        worst = max(jumps, key=lambda j: j[1])
        out.append(Alert(
            kind="spoofing",
            severity="high",
            mmsi=mmsi,
            start=g.ts.iloc[first - 1].to_pydatetime(),
            end=g.ts.iloc[last].to_pydatetime(),
            lat=float(lat[first - 1]),
            lon=float(lon[first - 1]),
            summary=f"Position jumped {worst[1]:.0f} km between two fixes",
            evidence={"jumps": len(jumps), "largest_jump_km": round(worst[1], 1)},
        ))
    return out


def loitering_in_protected(df: pd.DataFrame, min_hours: float = 1.0) -> list[Alert]:
    out = []
    for mmsi, g in _tracks(df):
        for z in ZONES:
            inside = np.array([
                z.contains(a, o) and near_port(a, o) is None for a, o in zip(g.lat, g.lon)
            ])
            slow = g["sog"].to_numpy() < 4.5
            mask = inside & slow
            if mask.sum() < 2:
                continue
            ts = g["ts"].to_numpy()
            dwell = 0.0
            for i in range(1, len(g)):
                if mask[i] and mask[i - 1]:
                    dwell += (ts[i] - ts[i - 1]) / np.timedelta64(1, "h")
            if dwell < min_hours:
                continue
            idx = np.flatnonzero(mask)
            out.append(Alert(
                kind="protected_area_loitering",
                severity="watch",
                mmsi=mmsi,
                start=g.ts.iloc[idx[0]].to_pydatetime(),
                end=g.ts.iloc[idx[-1]].to_pydatetime(),
                lat=float(g.lat.iloc[idx[0]]),
                lon=float(g.lon.iloc[idx[0]]),
                summary=f"{dwell:.1f} h slow or stopped inside {z.name}",
                evidence={"zone": z.id, "dwell_hours": round(dwell, 2)},
            ))
    return out


def _resample(g: pd.DataFrame, freq: str = "10min", max_gap: str = "30min") -> pd.DataFrame:
    """Put a track on a regular clock so two tracks can be compared minute by minute."""
    g = g.set_index("ts")[["lat", "lon", "sog"]]
    grid = pd.date_range(g.index.min().ceil(freq), g.index.max().floor(freq), freq=freq)
    if len(grid) == 0:
        return pd.DataFrame(columns=["lat", "lon", "sog"])
    both = g.reindex(g.index.union(grid)).interpolate(method="time", limit_area="inside")
    r = both.loc[grid]
    # Don't invent positions across real gaps.
    gap = pd.Series(g.index, index=g.index).diff().reindex(both.index).bfill()
    r = r[gap.loc[grid] <= pd.Timedelta(max_gap)]
    return r


def rendezvous(df: pd.DataFrame, cfg: Settings | None = None) -> list[Alert]:
    cfg = cfg or get_settings()
    grids = {m: _resample(g) for m, g in _tracks(df)}
    out = []
    for a, b in combinations(sorted(grids), 2):
        ga, gb = grids[a], grids[b]
        common = ga.index.intersection(gb.index)
        if len(common) < 3:
            continue
        A, B = ga.loc[common], gb.loc[common]
        d = np.array([haversine_km(*p) for p in zip(A.lat, A.lon, B.lat, B.lon)])
        close = (d <= cfg.rendezvous_km) & (A.sog.to_numpy() < 3) & (B.sog.to_numpy() < 3)
        # longest run of consecutive close samples
        best_len, best_end, run = 0, 0, 0
        for i, c in enumerate(close):
            run = run + 1 if c else 0
            if run > best_len:
                best_len, best_end = run, i
        hours = best_len * 10 / 60
        if hours < cfg.rendezvous_hours:
            continue
        i0 = best_end - best_len + 1
        mlat, mlon = float(A.lat.iloc[i0]), float(A.lon.iloc[i0])
        if near_port(mlat, mlon):
            continue
        out.append(Alert(
            kind="rendezvous",
            severity="high",
            mmsi=a,
            start=common[i0].to_pydatetime(),
            end=common[best_end].to_pydatetime(),
            lat=mlat,
            lon=mlon,
            summary=f"Stopped alongside {b} for {hours:.1f} h at sea",
            evidence={
                "other_mmsi": b,
                "hours": round(hours, 2),
                "min_distance_km": round(float(d[i0:best_end + 1].min()), 3),
            },
        ))
    return out


def imbl(df: pd.DataFrame, static: pd.DataFrame, cfg: Settings | None = None) -> list[Alert]:
    """Protective rule: warn Indian boats before they cross into Sri Lankan waters."""
    cfg = cfg or get_settings()
    indian_side = side_of_polyline(*INDIAN_SIDE_REF, IMBL)
    flags = dict(zip(static.mmsi, static.flag))
    types = dict(zip(static.mmsi, static.vessel_type))
    out = []
    for mmsi, g in _tracks(df):
        # Merchant ships cross maritime boundaries legally every day. This rule is for
        # small Indian fishing boats, who get arrested when they drift over the line.
        indian = mmsi.startswith("419") or flags.get(mmsi) == "IN"
        if not indian or types.get(mmsi) != "fishing":
            continue
        dist = np.array([distance_to_polyline_km(a, o, IMBL) for a, o in zip(g.lat, g.lon)])
        if dist.min() > cfg.imbl_warn_km:
            continue
        sides = np.array([side_of_polyline(a, o, IMBL) for a, o in zip(g.lat, g.lon)])
        crossed = np.flatnonzero(sides != indian_side)
        i = int(crossed[0]) if len(crossed) else int(dist.argmin())
        row = g.iloc[i]
        first_warn = int(np.flatnonzero(dist <= cfg.imbl_warn_km)[0])
        lead_min = (row.ts - g.ts.iloc[first_warn]).total_seconds() / 60
        out.append(Alert(
            kind="imbl_crossing" if len(crossed) else "imbl_proximity",
            severity="critical" if len(crossed) else "watch",
            mmsi=mmsi,
            start=g.ts.iloc[first_warn].to_pydatetime(),
            end=row.ts.to_pydatetime(),
            lat=float(row.lat),
            lon=float(row.lon),
            summary=(
                f"Crossed the IMBL; first came within {cfg.imbl_warn_km:.0f} km {lead_min:.0f} min earlier"
                if len(crossed) else f"Came within {dist.min():.1f} km of the IMBL"
            ),
            evidence={
                "min_distance_km": round(float(dist.min()), 2),
                "fixes_over_line": int(len(crossed)),
                "warning_lead_minutes": round(lead_min),
            },
        ))
    return out


def ban_period_fishing(df: pd.DataFrame, static: pd.DataFrame, min_hours: float = 2.0) -> list[Alert]:
    """Fishing-speed activity away from harbour while the monsoon ban is in force."""
    types = dict(zip(static.mmsi, static.vessel_type))
    out = []
    for mmsi, g in _tracks(df):
        if types.get(mmsi) != "fishing":
            continue
        sog = g["sog"].to_numpy()
        fishing = (sog >= 0.8) & (sog <= 4.5)
        fishing &= np.array([near_port(a, o) is None for a, o in zip(g.lat, g.lon)])
        fishing &= np.array([in_ban_window(coast_of(a, o), t) for a, o, t in zip(g.lat, g.lon, g.ts)])
        ts = g["ts"].to_numpy()
        best, cur, best_rng, start = 0.0, 0.0, (0, 0), 0
        for i in range(1, len(g)):
            if fishing[i] and fishing[i - 1]:
                if cur == 0:
                    start = i - 1
                cur += (ts[i] - ts[i - 1]) / np.timedelta64(1, "h")
                if cur > best:
                    best, best_rng = cur, (start, i)
            else:
                cur = 0.0
        if best < min_hours:
            continue
        i0, i1 = best_rng
        coast = coast_of(g.lat.iloc[i0], g.lon.iloc[i0])
        out.append(Alert(
            kind="ban_period_fishing",
            severity="high",
            mmsi=mmsi,
            start=g.ts.iloc[i0].to_pydatetime(),
            end=g.ts.iloc[i1].to_pydatetime(),
            lat=float(g.lat.iloc[i0]),
            lon=float(g.lon.iloc[i0]),
            summary=f"{best:.1f} h at fishing speed during the {coast}-coast ban",
            evidence={"coast": coast, "fishing_hours": round(best, 2)},
        ))
    return out


def run_all(df: pd.DataFrame, static: pd.DataFrame, cfg: Settings | None = None) -> list[Alert]:
    cfg = cfg or get_settings()
    return (
        ais_gaps(df, cfg)
        + spoofing(df, cfg)
        + loitering_in_protected(df)
        + rendezvous(df, cfg)
        + imbl(df, static, cfg)
        + ban_period_fishing(df, static)
    )
