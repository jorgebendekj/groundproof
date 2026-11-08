from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..adapters.iceye import BudgetExceeded, TaskingDisabled
from ..config import get_settings
from ..db import get_db
from ..models import Alert, Plot, TaskingOrder, User
from ..schemas import DecisionIn, QuoteIn
from ..security import audit, current_user, require
from ..services import approve_order, decide_alert, month_spend, poll_order, request_quote
from .common import STAFF, alert_out, get_alert_or_404, get_plot_or_404, plot_out, visible_plot_query

router = APIRouter()
DB = Annotated[Session, Depends(get_db)]


@router.get("/alerts")
def list_alerts(db: DB, user: Annotated[User, Depends(current_user)], state: str | None = None,
                type: str | None = None, since: date | None = None, bbox: str | None = None):
    ids = [p.id for p in db.scalars(visible_plot_query(user)).all()]
    q = select(Alert).where(Alert.plot_id.in_(ids))
    if state:
        q = q.where(Alert.state == state)
    if type:
        q = q.where(Alert.type == type)
    out = [a for a in db.scalars(q.order_by(Alert.confidence.desc())).all()
           if not since or a.first_seen.date() >= since]
    if bbox:
        from shapely.geometry import box, shape
        b = box(*[float(x) for x in bbox.split(",")])
        out = [a for a in out if shape(a.geometry).intersects(b)]
    return [alert_out(a) for a in out]


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: int, db: DB, user: Annotated[User, Depends(current_user)]):
    a = get_alert_or_404(db, user, alert_id)
    audit(db, user, "alert_view", "alert", a.id)
    db.commit()
    return alert_out(a)


@router.get("/alerts/{alert_id}/preview/{which}")
def preview(alert_id: int, which: str, db: DB, user: Annotated[User, Depends(current_user)]):
    a = get_alert_or_404(db, user, alert_id)
    rel = (a.details.get("previews") or {}).get(which)
    if which not in ("before", "after") or not rel:
        raise HTTPException(404, "No preview")
    return Response(storage.get(rel), media_type="image/png")


@router.post("/alerts/{alert_id}/decision")
def decision(alert_id: int, body: DecisionIn, db: DB, user: Annotated[User, Depends(require(*STAFF))]):
    a = get_alert_or_404(db, user, alert_id)
    try:
        decide_alert(db, a, body.decision, user)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return alert_out(a)


@router.get("/review/queue")
def queue(db: DB, user: Annotated[User, Depends(require(*STAFF))]):
    alerts = db.scalars(select(Alert).where(Alert.state.in_(["new", "needs_field_check"]))
                        .order_by(Alert.confidence.desc())).all()
    und = [plot_out(db, p) for p in db.scalars(select(Plot)).all()]
    return {"alerts": [alert_out(a) for a in alerts],
            "undetermined_plots": [p for p in und if p["status"] == "undetermined"]}


def order_out(o: TaskingOrder) -> dict:
    return {"id": o.id, "provider": o.provider, "plot_id": o.plot_id, "status": o.status, "mode": o.mode,
            "quote": o.quote, "provider_order_id": o.provider_order_id, "approved_by": o.approved_by_id,
            "requested_by": o.requested_by_id, "window": [o.window_start.date().isoformat(),
                                                           o.window_end.date().isoformat()]}


@router.post("/tasking/quote")
def quote(body: QuoteIn, db: DB, user: Annotated[User, Depends(require(*STAFF))]):
    p = get_plot_or_404(db, user, body.plot_id)
    return order_out(request_quote(db, p, user, body.start, body.end, body.mode))


@router.post("/tasking/{order_id}/approve")
def approve(order_id: int, db: DB, user: Annotated[User, Depends(require("admin"))]):
    o = db.get(TaskingOrder, order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    if o.requested_by_id == user.id and get_settings().tasking_four_eyes:
        raise HTTPException(403, "Four-eyes rule: the requester cannot approve their own order")
    try:
        return order_out(approve_order(db, o, user))
    except (TaskingDisabled, BudgetExceeded) as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/tasking/{order_id}/poll")
def poll(order_id: int, db: DB, user: Annotated[User, Depends(require(*STAFF))]):
    o = db.get(TaskingOrder, order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    try:
        return order_out(poll_order(db, o, user))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/tasking")
def list_orders(db: DB, user: Annotated[User, Depends(require(*STAFF))]):
    return {"orders": [order_out(o) for o in db.scalars(select(TaskingOrder).order_by(TaskingOrder.id)).all()],
            "month_spend_eur": month_spend(db), "budget_eur": get_settings().tasking_monthly_budget_eur,
            "enabled": get_settings().iceye_enabled}


@router.post("/tasking/quote-area")
def quote_area(body: dict, db: DB, user: Annotated[User, Depends(require(*STAFF))]):
    """Quote only. Never creates an order; used by MCP/agents and the console 'request scene' tool."""
    from shapely.geometry import box, shape

    from ..adapters.base import TimeWindow
    from ..adapters.iceye import ICEYEMockAdapter
    try:
        g = shape(body["area"]) if isinstance(body["area"], dict) else box(*[float(x) for x in body["area"]])
        w = TimeWindow(date.fromisoformat(body["start"]), date.fromisoformat(body["end"]))
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(422, f"Invalid area/window: {e}") from e
    q = ICEYEMockAdapter().quote(g, w, body.get("mode", "spot"))
    audit(db, user, "tasking_quote_area", "area", g.wkt[:60], None, {"price_eur": q.price_eur})
    db.commit()
    return {"provider": q.provider, "price_eur": q.price_eur, "eta_days": q.eta_days, "mode": q.mode,
            "notes": q.notes, "order_created": False,
            "next_step": "A human analyst must create and an admin approve the order in the console."}
