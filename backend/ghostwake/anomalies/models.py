from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

SEVERITIES = ("info", "watch", "high", "critical")


@dataclass
class Alert:
    kind: str
    severity: str
    mmsi: str | None
    start: datetime
    end: datetime
    lat: float
    lon: float
    summary: str
    evidence: dict = field(default_factory=dict)
    detection_id: str | None = None
    score: float = 0.0
    contributions: list[dict] = field(default_factory=list)

    @property
    def id(self) -> str:
        # Stable id: running the pipeline twice on the same data gives the same alerts,
        # so reruns update rows instead of piling up duplicates.
        key = f"{self.kind}|{self.mmsi}|{self.start.isoformat()}|{self.detection_id}"
        return hashlib.sha1(key.encode()).hexdigest()[:12]
