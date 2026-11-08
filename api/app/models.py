from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


ROLES = ("admin", "analyst", "buyer", "field_partner")
PLOT_STATUSES = ("compliant", "at_risk", "cleared_after_2020", "undetermined")
ALERT_STATES = ("new", "confirmed", "rejected", "needs_field_check")


class Organization(Base):
    __tablename__ = "organization"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organization.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Supplier(Base):
    __tablename__ = "supplier"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str | None] = mapped_column(String(2))
    organization_id: Mapped[int] = mapped_column(ForeignKey("organization.id"))
    plots: Mapped[list[Plot]] = relationship(back_populates="supplier")


class Plot(Base):
    __tablename__ = "plot"
    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(100))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("supplier.id"))
    organization_id: Mapped[int] = mapped_column(ForeignKey("organization.id"))
    geometry: Mapped[dict[str, Any]] = mapped_column(JSON)  # GeoJSON, EPSG:4326
    geom_type: Mapped[str] = mapped_column(String(10))
    commodity: Mapped[str | None] = mapped_column(String(30))
    country: Mapped[str | None] = mapped_column(String(2))
    area_ha: Mapped[float | None] = mapped_column(Float)
    source_file: Mapped[str | None] = mapped_column(String(300))
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_status: Mapped[str] = mapped_column(String(20), default="valid")  # valid|fixed|flagged|invalid
    validation_notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    supplier: Mapped[Supplier] = relationship(back_populates="plots")


class CheckRun(Base):
    __tablename__ = "check_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    plot_id: Mapped[int] = mapped_column(ForeignKey("plot.id"), index=True)
    type: Mapped[str] = mapped_column(String(20))  # cutoff | monitoring
    adapter: Mapped[str] = mapped_column(String(50))
    algorithm_version: Mapped[str] = mapped_column(String(30))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    inputs: Mapped[list[str]] = mapped_column(JSON, default=list)  # STAC item ids
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class PlotResult(Base):
    __tablename__ = "plot_result"
    id: Mapped[int] = mapped_column(primary_key=True)
    plot_id: Mapped[int] = mapped_column(ForeignKey("plot.id"), index=True)
    check_run_id: Mapped[int] = mapped_column(ForeignKey("check_run.id"))
    status: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[float] = mapped_column(Float)
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_refs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reviewer_decision: Mapped[str | None] = mapped_column(String(30))
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Alert(Base):
    __tablename__ = "alert"
    id: Mapped[int] = mapped_column(primary_key=True)
    plot_id: Mapped[int] = mapped_column(ForeignKey("plot.id"), index=True)
    type: Mapped[str] = mapped_column(String(30))
    geometry: Mapped[dict[str, Any]] = mapped_column(JSON)
    first_seen: Mapped[datetime] = mapped_column(DateTime)
    scene_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float)
    state: Mapped[str] = mapped_column(String(20), default="new")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # method, params, previews
    check_run_id: Mapped[int | None] = mapped_column(ForeignKey("check_run.id"))


class FieldCapture(Base):
    __tablename__ = "field_capture"
    id: Mapped[int] = mapped_column(primary_key=True)
    plot_id: Mapped[int] = mapped_column(ForeignKey("plot.id"), index=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    file_path: Mapped[str | None] = mapped_column(String(400))
    gps_track: Mapped[list[Any]] = mapped_column(JSON, default=list)
    accuracy_m: Mapped[float | None] = mapped_column(Float)
    device_info: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # C2PA-style manifest
    signature: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64))
    previous_hash: Mapped[str] = mapped_column(String(64))
    chain_hash: Mapped[str] = mapped_column(String(64))
    signing_mode: Mapped[str] = mapped_column(String(30), default="dev-ed25519")


class TaskingOrder(Base):
    __tablename__ = "tasking_order"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(30))
    plot_id: Mapped[int | None] = mapped_column(ForeignKey("plot.id"))
    aoi: Mapped[dict[str, Any]] = mapped_column(JSON)
    window_start: Mapped[datetime] = mapped_column(DateTime)
    window_end: Mapped[datetime] = mapped_column(DateTime)
    mode: Mapped[str] = mapped_column(String(30), default="spot")
    quote: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="quoted")
    provider_order_id: Mapped[str | None] = mapped_column(String(100))
    requested_by_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    polls: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(60))
    object_type: Mapped[str] = mapped_column(String(40))
    object_id: Mapped[str] = mapped_column(String(60))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Scene(Base):
    """Locally registered STAC-like record with licence + cost metadata."""
    __tablename__ = "scene"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    provider: Mapped[str] = mapped_column(String(30))
    sensor: Mapped[str] = mapped_column(String(30))
    acquired: Mapped[datetime] = mapped_column(DateTime)
    processing_level: Mapped[str] = mapped_column(String(20))
    cost_eur: Mapped[float] = mapped_column(Float, default=0.0)
    licence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stac: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


__all__ = [n for n in dir() if n[0].isupper() or n == "now"] + ["Boolean"]
