from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Alert, Plot, User
from ..services import latest_result

STAFF = ("admin", "analyst")


def visible_plot_query(user: User):
    q = select(Plot)
    if user.role == "buyer":
        q = q.where(Plot.organization_id == user.organization_id)
    elif user.role == "field_partner":
        q = q.where(Plot.assigned_to_id == user.id)
    return q


def get_plot_or_404(db: Session, user: User, plot_id: int) -> Plot:
    p = db.scalars(visible_plot_query(user).where(Plot.id == plot_id)).first()
    if not p:
        raise HTTPException(404, "Plot not found")
    return p


def get_alert_or_404(db: Session, user: User, alert_id: int) -> Alert:
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found")
    get_plot_or_404(db, user, a.plot_id)
    return a


def plot_out(db: Session, p: Plot, detail: bool = False) -> dict[str, Any]:
    r = latest_result(db, p.id)
    out: dict[str, Any] = {"id": p.id, "external_id": p.external_id, "supplier_id": p.supplier_id,
           "supplier": p.supplier.name, "commodity": p.commodity, "country": p.country, "area_ha": p.area_ha,
           "geom_type": p.geom_type, "validation_status": p.validation_status,
           "validation_notes": p.validation_notes,
           "status": r.status if r else "unchecked", "confidence": r.confidence if r else None}
    if detail:
        out["geometry"] = p.geometry
        out["notes"] = r.notes if r else []
        out["reviewer_decision"] = r.reviewer_decision if r else None
        out["provenance"] = r.evidence_refs if r else {}
    return out


def alert_out(a: Alert) -> dict[str, Any]:
    return {"id": a.id, "plot_id": a.plot_id, "type": a.type, "state": a.state, "confidence": a.confidence,
            "first_seen": a.first_seen.isoformat(), "scene_ids": a.scene_ids, "geometry": a.geometry,
            "details": a.details}
