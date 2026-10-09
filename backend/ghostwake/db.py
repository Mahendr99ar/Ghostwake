"""Database tables. SQLite for local runs and tests, Postgres (Neon) in production.

Times are stored as UTC. SQLite drops the timezone on the way back, so read them
through `utc()` before doing arithmetic or sending them to the browser.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from ghostwake.config import get_settings


class Base(DeclarativeBase):
    pass


def now() -> datetime:
    return datetime.now(UTC)


def utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    clean_report: Mapped[dict] = mapped_column(JSON, default=dict)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)


class Vessel(Base):
    __tablename__ = "vessels"
    mmsi: Mapped[str] = mapped_column(String(9), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(64))
    flag: Mapped[str | None] = mapped_column(String(4))
    vessel_type: Mapped[str | None] = mapped_column(String(32))
    length_m: Mapped[float | None] = mapped_column(Float)
    risk: Mapped[float] = mapped_column(Float, default=0.0)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_lat: Mapped[float | None] = mapped_column(Float)
    last_lon: Mapped[float | None] = mapped_column(Float)


class Position(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mmsi: Mapped[str] = mapped_column(String(9), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    sog: Mapped[float | None] = mapped_column(Float)
    cog: Mapped[float | None] = mapped_column(Float)
    h3: Mapped[str | None] = mapped_column(String(16), index=True)
    __table_args__ = (UniqueConstraint("mmsi", "ts", name="uq_position_mmsi_ts"),)


class Scene(Base):
    __tablename__ = "scenes"
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    mission: Mapped[str | None] = mapped_column(String(64))


class Detection(Base):
    __tablename__ = "detections"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    length_m: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(48))
    matched_mmsi: Mapped[str | None] = mapped_column(String(9), index=True)
    match_km: Mapped[float | None] = mapped_column(Float)


class AlertRow(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(String(16))  # "enforcement" | "safety"
    severity: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)
    mmsi: Mapped[str | None] = mapped_column(String(9), index=True)
    detection_id: Mapped[str | None] = mapped_column(String(64))
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    summary: Mapped[str] = mapped_column(String(240))
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    contributions: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    lineage: Mapped[dict] = mapped_column(JSON, default=dict)
    run_id: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Review(Base):
    """Append-only. A dismissed alert that gets re-opened keeps both decisions on record."""

    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"), index=True)
    action: Mapped[str] = mapped_column(String(16))
    analyst: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(String(1000), default="")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Event(Base):
    """Feed for the live stream. The browser remembers the last id it saw."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


Index("ix_alert_status_score", AlertRow.status, AlertRow.score)

_engines: dict[str, object] = {}


def engine_for(url: str | None = None):
    url = url or get_settings().database_url
    if url not in _engines:
        kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
        _engines[url] = create_engine(url, **kw)
    return _engines[url]


def init_db(url: str | None = None) -> None:
    Base.metadata.create_all(engine_for(url))


def session_factory(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine_for(url), expire_on_commit=False)
