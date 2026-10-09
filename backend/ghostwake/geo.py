"""Small spherical-earth helpers. Good to a few metres at the scales we care about."""

import math

import h3

EARTH_KM = 6371.0088
KM_PER_NM = 1.852
H3_RES = 7  # ~5 km2 cells, fine enough for heatmaps and pattern-of-life


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def destination(lat: float, lon: float, bearing_deg: float, dist_km: float) -> tuple[float, float]:
    d = dist_km / EARTH_KM
    b = math.radians(bearing_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def knots(dist_km: float, hours: float) -> float:
    if hours <= 0:
        return math.inf
    return dist_km / KM_PER_NM / hours


def _to_local_xy(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    # Equirectangular projection around (lat0, lon0). Over tens of km the error is negligible.
    x = math.radians(lon - lon0) * math.cos(math.radians(lat0)) * EARTH_KM
    y = math.radians(lat - lat0) * EARTH_KM
    return x, y


def distance_to_polyline_km(lat: float, lon: float, line: list[tuple[float, float]]) -> float:
    """Shortest distance from a point to a polyline given as (lat, lon) pairs."""
    best = math.inf
    for (a_lat, a_lon), (b_lat, b_lon) in zip(line, line[1:]):
        ax, ay = _to_local_xy(a_lat, a_lon, lat, lon)
        bx, by = _to_local_xy(b_lat, b_lon, lat, lon)
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2))
        px, py = ax + t * dx, ay + t * dy
        best = min(best, math.hypot(px, py))
    return best


def side_of_polyline(lat: float, lon: float, line: list[tuple[float, float]]) -> int:
    """+1 or -1 depending on which side of the nearest segment the point sits.

    Used to tell whether a boat has crossed a boundary between two fixes.
    """
    best, sign = math.inf, 1
    for (a_lat, a_lon), (b_lat, b_lon) in zip(line, line[1:]):
        ax, ay = _to_local_xy(a_lat, a_lon, lat, lon)
        bx, by = _to_local_xy(b_lat, b_lon, lat, lon)
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2))
        d = math.hypot(ax + t * dx, ay + t * dy)
        if d < best:
            best = d
            cross = dx * (0 - ay) - dy * (0 - ax)
            sign = 1 if cross >= 0 else -1
    return sign


def point_in_polygon(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        yi, xi = ring[i]
        yj, xj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def cell(lat: float, lon: float, res: int = H3_RES) -> str:
    return h3.latlng_to_cell(lat, lon, res)
