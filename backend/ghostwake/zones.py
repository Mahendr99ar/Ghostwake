"""Reference geography for the demo area: southern tip of India, Gulf of Mannar and Palk Bay.

IMPORTANT: these shapes are hand-drawn approximations for a portfolio demo.
They are NOT legal boundaries and must never be used for navigation.
Swap them for official shapefiles (Marine Regions EEZ, WDPA protected areas,
and the 1974/1976 India-Sri Lanka boundary points) before any real use.
"""

from dataclasses import dataclass
from datetime import date, datetime

from ghostwake.geo import point_in_polygon

# Map window the UI opens on.
AOI = {"min_lat": 7.0, "max_lat": 10.6, "min_lon": 76.0, "max_lon": 80.6}

# Approximate India-Sri Lanka IMBL, north (Palk Bay) to south (Gulf of Mannar). (lat, lon)
IMBL: list[tuple[float, float]] = [
    (10.20, 80.05),
    (9.95, 79.90),
    (9.55, 79.55),
    (9.10, 79.52),
    (8.70, 79.10),
    (8.20, 78.60),
    (7.60, 78.10),
]


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    kind: str  # "protected" | "coast"
    ring: list[tuple[float, float]]

    def contains(self, lat: float, lon: float) -> bool:
        return point_in_polygon(lat, lon, self.ring)


GULF_OF_MANNAR_MPA = Zone(
    id="gom-mnp",
    name="Gulf of Mannar Marine National Park (approx.)",
    kind="protected",
    ring=[
        (9.30, 79.25),
        (9.25, 78.95),
        (9.05, 78.55),
        (8.80, 78.15),
        (8.68, 78.25),
        (8.92, 78.66),
        (9.12, 79.05),
        (9.18, 79.30),
    ],
)

ZONES = [GULF_OF_MANNAR_MPA]

# Harbours. Boats sitting together in a harbour are not a rendezvous.
PORTS = {
    "Thoothukudi": (8.755, 78.195),
    "Pamban / Rameswaram": (9.278, 79.318),
    "Vizhinjam": (8.37, 76.98),
    "Kollam": (8.87, 76.56),
    "Colombo": (6.95, 79.84),
}
PORT_RADIUS_KM = 3.0

# Any point we know is on the Indian side of the IMBL. Used to orient "crossing".
INDIAN_SIDE_REF = (9.28, 79.31)

# Annual monsoon fishing ban for mechanised boats. Dates follow the commonly cited
# central notification (east coast 15 Apr to 14 Jun, west coast 1 Jun to 31 Jul).
# States sometimes shift these, so check the current notification before relying on them.
BAN_WINDOWS = {
    "east": ((4, 15), (6, 14)),
    "west": ((6, 1), (7, 31)),
}

KANYAKUMARI_LON = 77.55  # rough split between west and east coast waters at the tip


def coast_of(lat: float, lon: float) -> str:
    return "west" if lon < KANYAKUMARI_LON else "east"


def in_ban_window(coast: str, when: datetime | date) -> bool:
    (m1, d1), (m2, d2) = BAN_WINDOWS[coast]
    md = (when.month, when.day)
    return (m1, d1) <= md <= (m2, d2)


def zones_geojson() -> dict:
    features = [
        {
            "type": "Feature",
            "properties": {"id": z.id, "name": z.name, "kind": z.kind},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[lon, lat] for lat, lon in z.ring + [z.ring[0]]]],
            },
        }
        for z in ZONES
    ]
    features.append(
        {
            "type": "Feature",
            "properties": {"id": "imbl", "name": "IMBL India / Sri Lanka (approx.)", "kind": "boundary"},
            "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in IMBL]},
        }
    )
    return {"type": "FeatureCollection", "features": features}
