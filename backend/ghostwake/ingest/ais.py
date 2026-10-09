"""Turn a raw AIS dump into one clean, sorted track per vessel.

Every row we drop is counted by reason. The counts go into the run record, so when
a number on the dashboard looks off you can see what the cleaner threw away.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import h3
import numpy as np
import pandas as pd

from ghostwake.geo import H3_RES

MMSI_RE = re.compile(r"(\d{9})")


@dataclass
class CleanReport:
    rows_in: int = 0
    bad_mmsi: int = 0
    bad_timestamp: int = 0
    bad_position: int = 0
    duplicates: int = 0
    rows_out: int = 0
    vessels: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def normalise_mmsi(value: object) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    m = MMSI_RE.search(str(value))
    return m.group(1) if m else None


def parse_timestamps(col: pd.Series) -> pd.Series:
    """Accept ISO strings with Z or +00:00, and epoch seconds. Everything ends up UTC."""
    s = col.astype(str).str.strip()
    is_epoch = s.str.fullmatch(r"\d{9,11}")
    out = pd.to_datetime(s.where(~is_epoch), utc=True, errors="coerce", format="ISO8601")
    epoch = pd.to_datetime(pd.to_numeric(s.where(is_epoch), errors="coerce"), unit="s", utc=True)
    return out.fillna(epoch)


def clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, CleanReport]:
    rep = CleanReport(rows_in=len(raw))
    df = raw.copy()

    df["mmsi"] = df["mmsi"].map(normalise_mmsi)
    bad = df["mmsi"].isna()
    rep.bad_mmsi = int(bad.sum())
    df = df[~bad]

    df["ts"] = parse_timestamps(df["timestamp"])
    bad = df["ts"].isna()
    rep.bad_timestamp = int(bad.sum())
    df = df[~bad]

    lat, lon = df["lat"].astype(float), df["lon"].astype(float)
    bad = (
        lat.isna() | lon.isna()
        | (lat.abs() > 90) | (lon.abs() > 180)
        | ((lat.abs() < 1e-6) & (lon.abs() < 1e-6))  # 0,0 is a default value, not a position
    )
    rep.bad_position = int(bad.sum())
    df = df[~bad]

    before = len(df)
    df = df.drop_duplicates(subset=["mmsi", "ts"], keep="first")
    rep.duplicates = before - len(df)

    df = df.sort_values(["mmsi", "ts"]).reset_index(drop=True)
    df["h3"] = [h3.latlng_to_cell(a, o, H3_RES) for a, o in zip(df["lat"], df["lon"])]
    df = df.drop(columns=["timestamp"])

    rep.rows_out = len(df)
    rep.vessels = int(df["mmsi"].nunique())
    return df, rep


def static_info(clean_df: pd.DataFrame) -> pd.DataFrame:
    """One row per vessel with the most common name/flag/type it reported."""
    def mode(s: pd.Series):
        m = s.dropna().mode()
        return m.iloc[0] if len(m) else None

    return (
        clean_df.groupby("mmsi")
        .agg(name=("name", mode), flag=("flag", mode), vessel_type=("vessel_type", mode),
             length_m=("length_m", "median"))
        .reset_index()
    )
