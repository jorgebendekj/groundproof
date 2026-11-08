from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..db import get_db
from ..evidence import pack as packmod
from ..evidence import signing
from ..models import AuditLog, FieldCapture, Supplier, User, now
from ..schemas import CaptureMeta
from ..security import audit, current_user, require
from .common import STAFF, get_plot_or_404, plot_out, visible_plot_query

router = APIRouter()
DB = Annotated[Session, Depends(get_db)]
MAX_PHOTO = 15 * 1024 * 1024


@router.get("/field/plots")
def my_plots(db: DB, user: Annotated[User, Depends(require("field_partner", "admin", "analyst"))]):
    return [plot_out(db, p, detail=True) for p in db.scalars(visible_plot_query(user)).all()]


@router.post("/plots/{plot_id}/assign/{user_id}")
def assign(plot_id: int, user_id: int, db: DB, user: Annotated[User, Depends(require(*STAFF))]):
    p = get_plot_or_404(db, user, plot_id)
    partner = db.get(User, user_id)
    if not partner or partner.role != "field_partner":
        raise HTTPException(422, "Target must be a field_partner user")
    p.assigned_to_id = partner.id
    audit(db, user, "plot_assign", "plot", p.id, None, {"partner": partner.id})
    db.commit()
    return {"ok": True}


@router.post("/plots/{plot_id}/captures")
async def create_capture(plot_id: int, db: DB, user: Annotated[User, Depends(require("field_partner", "admin"))],
                         photo: Annotated[UploadFile, File()], meta: Annotated[str, Form()]):
    p = get_plot_or_404(db, user, plot_id)
    try:
        m = CaptureMeta.model_validate(json.loads(meta))
    except (ValueError, TypeError) as e:
        raise HTTPException(422, f"Invalid meta: {e}") from e
    data = await photo.read()
    if not data or len(data) > MAX_PHOTO:
        raise HTTPException(422, "Photo missing or too large")
    last = db.scalars(select(FieldCapture).where(FieldCapture.plot_id == p.id)
                      .order_by(FieldCapture.id.desc())).first()
    prev = last.chain_hash if last else signing.GENESIS
    sha = storage.sha256(data)
    when = datetime.fromisoformat(m.captured_at.rstrip("Z")) if m.captured_at else now()
    manifest = signing.build_manifest(sha, p.id, user.id, when,
                                      {"lat": m.lat, "lon": m.lon, "accuracy_m": m.accuracy_m}, m.device, prev)
    sig = signing.sign(manifest)
    cap = FieldCapture(plot_id=p.id, partner_id=user.id, gps_track=m.gps_track, accuracy_m=m.accuracy_m,
                       device_info=m.device, captured_at=when, manifest=manifest, signature=sig, sha256=sha,
                       previous_hash=prev, chain_hash=signing.chain_hash(prev, sha, manifest),
                       signing_mode=manifest["signing_mode"])
    db.add(cap)
    db.flush()
    cap.file_path = storage.put(f"captures/plot{p.id}/capture{cap.id}.jpg", data)
    audit(db, user, "field_capture", "field_capture", cap.id, None, {"plot": p.id, "sha256": sha})
    db.commit()
    return {"id": cap.id, "sha256": sha, "chain_hash": cap.chain_hash, "signature_status": "valid"}


def _verify(c: FieldCapture) -> dict:
    try:
        data = storage.get(c.file_path) if c.file_path else None
    except FileNotFoundError:
        data = None
    return signing.verify_capture(data, c.manifest, c.signature, c.sha256, c.previous_hash, c.chain_hash)


@router.get("/plots/{plot_id}/captures")
def list_captures(plot_id: int, db: DB, user: Annotated[User, Depends(current_user)]):
    p = get_plot_or_404(db, user, plot_id)
    caps = db.scalars(select(FieldCapture).where(FieldCapture.plot_id == p.id).order_by(FieldCapture.id)).all()
    out, expected_prev = [], signing.GENESIS
    for c in caps:
        v = _verify(c)
        chain_ok = c.previous_hash == expected_prev
        expected_prev = c.chain_hash
        out.append({"id": c.id, "captured_at": c.captured_at.isoformat(), "accuracy_m": c.accuracy_m,
                    "sha256": c.sha256, "previous_hash": c.previous_hash, "chain_hash": c.chain_hash,
                    "signing_mode": c.signing_mode, "verification": {**v, "chain_linked": chain_ok},
                    "gps_points": len(c.gps_track)})
    return out


@router.get("/captures/{capture_id}/photo")
def photo(capture_id: int, db: DB, user: Annotated[User, Depends(current_user)]):
    c = db.get(FieldCapture, capture_id)
    if not c or not c.file_path:
        raise HTTPException(404, "Not found")
    get_plot_or_404(db, user, c.plot_id)
    return Response(storage.get(c.file_path), media_type="image/jpeg")


@router.get("/captures/{capture_id}/verify")
def verify(capture_id: int, db: DB, user: Annotated[User, Depends(current_user)]):
    c = db.get(FieldCapture, capture_id)
    if not c:
        raise HTTPException(404, "Not found")
    get_plot_or_404(db, user, c.plot_id)
    return _verify(c)


@router.get("/signing/public-key")
def public_key():
    return {"alg": "ed25519", "public_key_b64": signing.public_key_b64(),
            "mode": "dev self-signed; replace with a trusted C2PA certificate for production"}


# ---- evidence packs ----
def _supplier_for(db: Session, user: User, supplier_id: int) -> Supplier:
    s = db.get(Supplier, supplier_id)
    if not s or (user.role == "buyer" and s.organization_id != user.organization_id) or user.role == "field_partner":
        raise HTTPException(404, "Supplier not found")
    return s


@router.get("/evidence/plot/{plot_id}")
def evidence_plot(plot_id: int, db: DB, user: Annotated[User, Depends(require("admin", "analyst", "buyer"))],
                  format: str = "json"):
    p = get_plot_or_404(db, user, plot_id)
    pack = packmod.plot_pack(db, p)
    audit(db, user, "evidence_export", "plot", p.id, None, {"format": format})
    db.commit()
    if format == "pdf":
        return Response(packmod.render_pdf(pack), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="plot-{p.id}-evidence.pdf"'})
    return pack


@router.get("/evidence/supplier/{supplier_id}")
def evidence_supplier(supplier_id: int, db: DB,
                      user: Annotated[User, Depends(require("admin", "analyst", "buyer"))], format: str = "json"):
    s = _supplier_for(db, user, supplier_id)
    pack = packmod.supplier_pack(db, s)
    audit(db, user, "evidence_export", "supplier", s.id, None, {"format": format})
    db.commit()
    if format == "pdf":
        return Response(packmod.render_pdf(pack), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="supplier-{s.id}-evidence.pdf"'})
    return pack


@router.get("/suppliers")
def suppliers(db: DB, user: Annotated[User, Depends(require("admin", "analyst", "buyer"))]):
    q = select(Supplier)
    if user.role == "buyer":
        q = q.where(Supplier.organization_id == user.organization_id)
    return [{"id": s.id, "name": s.name, "country": s.country} for s in db.scalars(q).all()]


@router.get("/audit")
def audit_log(db: DB, user: Annotated[User, Depends(require("admin"))], limit: int = 200, action: str | None = None):
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))
    if action:
        q = q.where(AuditLog.action == action)
    return [{"id": a.id, "user_id": a.user_id, "action": a.action, "object": f"{a.object_type}:{a.object_id}",
             "before": a.before, "after": a.after, "at": a.at.isoformat()} for a in db.scalars(q).all()]


# ---- console feed (GeoJSON) ----
@router.get("/eo/plots.geojson")
def plots_geojson(db: DB, user: Annotated[User, Depends(current_user)]):
    feats = []
    for p in db.scalars(visible_plot_query(user)).all():
        o = plot_out(db, p)
        feats.append({"type": "Feature", "geometry": p.geometry, "properties": {
            k: o[k] for k in ("id", "external_id", "supplier", "commodity", "status", "confidence", "area_ha")}})
    return {"type": "FeatureCollection", "features": feats}
