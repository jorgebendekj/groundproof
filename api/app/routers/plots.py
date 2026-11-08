from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import geo
from ..adapters.base import NotConfigured
from ..db import get_db
from ..models import Organization, Plot, Supplier, User
from ..schemas import LoginIn, RunIn
from ..security import audit, current_user, make_token, require, verify_password
from ..services import run_cutoff, run_monitoring
from .common import STAFF, get_plot_or_404, plot_out, visible_plot_query

router = APIRouter()
DB = Annotated[Session, Depends(get_db)]
MAX_UPLOAD = 25 * 1024 * 1024


@router.post("/auth/login")
def login(body: LoginIn, db: DB):
    u = db.scalars(select(User).where(User.email == body.email)).first()
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Invalid credentials")
    return {"access_token": make_token(u), "token_type": "bearer", "role": u.role,
            "organization_id": u.organization_id}


@router.get("/auth/me")
def me(user: Annotated[User, Depends(current_user)]):
    return {"id": user.id, "email": user.email, "role": user.role, "organization_id": user.organization_id}


@router.post("/plots/upload")
async def upload(db: DB, user: Annotated[User, Depends(require("admin", "analyst", "buyer"))],
                 file: Annotated[UploadFile, File()], supplier_name: Annotated[str, Form()] = "Unnamed supplier",
                 commodity: Annotated[str, Form()] = "soy", country: Annotated[str, Form()] = "BR",
                 organization_id: Annotated[int | None, Form()] = None):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File too large")
    try:
        feats = geo.parse_upload(file.filename or "", data)
    except geo.IngestError as e:
        raise HTTPException(422, str(e)) from e
    org_id = user.organization_id if user.role == "buyer" else (organization_id or user.organization_id)
    if org_id is None or not db.get(Organization, org_id):
        raise HTTPException(422, "organization_id required")
    items = geo.validate_batch(feats)
    suppliers: dict[str, Supplier] = {}
    report: list[dict[str, Any]] = []
    stored = 0
    for it in items:
        name = str(it.props.get("supplier") or supplier_name)
        row = {"external_id": it.external_id, "status": it.status, "notes": it.notes, "area_ha": it.area_ha,
               "plot_id": None}
        if it.geometry is not None:
            if name not in suppliers:
                sup = db.scalars(select(Supplier).where(Supplier.name == name,
                                                        Supplier.organization_id == org_id)).first()
                suppliers[name] = sup or Supplier(name=name, country=country, organization_id=org_id)
                db.add(suppliers[name])
                db.flush()
            p = Plot(external_id=it.external_id, supplier_id=suppliers[name].id, organization_id=org_id,
                     geometry=it.geometry, geom_type=it.geom_type,
                     commodity=str(it.props.get("commodity") or commodity),
                     country=str(it.props.get("country") or country), area_ha=it.area_ha,
                     source_file=file.filename, properties={k: v for k, v in it.props.items()
                                                            if isinstance(v, (str, int, float, bool))},
                     validation_status=it.status, validation_notes=it.notes)
            db.add(p)
            db.flush()
            row["plot_id"] = p.id
            stored += 1
        report.append(row)
    audit(db, user, "plots_upload", "plot_batch", file.filename, None, {"stored": stored, "total": len(items)})
    db.commit()
    counts: dict[str, int] = {}
    for r in report:
        k = str(r["status"])
        counts[k] = counts.get(k, 0) + 1
    return {"total": len(items), "stored": stored, "counts": counts, "report": report}


@router.get("/plots")
def list_plots(db: DB, user: Annotated[User, Depends(current_user)], status: str | None = None,
               supplier_id: int | None = None, limit: int = 500, offset: int = 0):
    q = visible_plot_query(user)
    if supplier_id:
        q = q.where(Plot.supplier_id == supplier_id)
    plots = db.scalars(q.order_by(Plot.id).limit(min(limit, 2000)).offset(offset)).all()
    out = [plot_out(db, p) for p in plots]
    return [o for o in out if not status or o["status"] == status]


@router.get("/plots/{plot_id}")
def get_plot(plot_id: int, db: DB, user: Annotated[User, Depends(current_user)]):
    p = get_plot_or_404(db, user, plot_id)
    audit(db, user, "plot_view", "plot", p.id)
    db.commit()
    return plot_out(db, p, detail=True)


@router.post("/plots/{plot_id}/check")
def check_plot(plot_id: int, db: DB, user: Annotated[User, Depends(require(*STAFF))], body: RunIn | None = None):
    p = get_plot_or_404(db, user, plot_id)
    try:
        r = run_cutoff(db, p, user, (body.adapter if body else None))
    except NotConfigured as e:
        raise HTTPException(409, str(e)) from e
    return {"status": r.status, "confidence": r.confidence, "notes": r.notes}


@router.post("/plots/check-all")
def check_all(db: DB, user: Annotated[User, Depends(require(*STAFF))]):
    n = 0
    for p in db.scalars(select(Plot)).all():
        run_cutoff(db, p, user)
        n += 1
    return {"checked": n}


@router.post("/plots/{plot_id}/monitor")
def monitor_plot(plot_id: int, db: DB, user: Annotated[User, Depends(require(*STAFF))],
                 body: RunIn | None = None):
    p = get_plot_or_404(db, user, plot_id)
    try:
        run, alert = run_monitoring(db, p, user, until=body.until if body else None)
    except NotConfigured as e:
        raise HTTPException(409, str(e)) from e
    return {"check_run_id": run.id, "alert_id": alert.id if alert else None, "inputs": run.inputs}


@router.post("/monitoring/run-now")
def monitor_all(db: DB, user: Annotated[User, Depends(require(*STAFF))], body: RunIn | None = None):
    created = []
    for p in db.scalars(select(Plot)).all():
        _, a = run_monitoring(db, p, user, until=body.until if body else None)
        if a:
            created.append(a.id)
    return {"alerts_created": created}
