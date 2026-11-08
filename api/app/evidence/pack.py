"""Evidence packs (JSON + PDF). Wording: evidence to support due diligence, not certification."""
from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ALGORITHM_VERSION, storage
from ..models import Alert, CheckRun, FieldCapture, Plot, PlotResult, Supplier, TaskingOrder, now
from . import signing

DISCLAIMER = ("This document is evidence to support due diligence under Regulation (EU) 2023/1115 (EUDR). "
              "It is not a certification and does not replace the operator's own due-diligence statement.")
ATTRIBUTIONS = [
    "Contains modified Copernicus Sentinel data (Sentinel-1, Sentinel-2).",
    "Baseline cutoff datasets: Whisp / Forest Data Partnership (MIT) when the real adapter is enabled.",
    "The AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google DeepMind "
    "(included only where embeddings were used).",
]


def plot_pack(db: Session, plot: Plot) -> dict[str, Any]:
    results = db.scalars(select(PlotResult).where(PlotResult.plot_id == plot.id).order_by(PlotResult.id)).all()
    runs = db.scalars(select(CheckRun).where(CheckRun.plot_id == plot.id).order_by(CheckRun.id)).all()
    alerts = db.scalars(select(Alert).where(Alert.plot_id == plot.id)).all()
    caps = db.scalars(select(FieldCapture).where(FieldCapture.plot_id == plot.id).order_by(FieldCapture.id)).all()
    orders = db.scalars(select(TaskingOrder).where(TaskingOrder.plot_id == plot.id)).all()
    cap_rows = []
    for c in caps:
        try:
            data = storage.get(c.file_path) if c.file_path else None
        except FileNotFoundError:
            data = None
        v = signing.verify_capture(data, c.manifest, c.signature, c.sha256, c.previous_hash, c.chain_hash)
        cap_rows.append({"id": c.id, "captured_at": c.captured_at.isoformat(), "accuracy_m": c.accuracy_m,
                         "sha256": c.sha256, "signing_mode": c.signing_mode,
                         "signature_status": "valid" if v["valid"] else "INVALID", "checks": v})
    return {
        "disclaimer": DISCLAIMER, "generated_at": now().isoformat() + "Z",
        "algorithm_version": ALGORITHM_VERSION,
        "plot": {"id": plot.id, "external_id": plot.external_id, "commodity": plot.commodity,
                 "country": plot.country, "area_ha": plot.area_ha, "geometry": plot.geometry,
                 "validation_status": plot.validation_status, "validation_notes": plot.validation_notes,
                 "supplier": plot.supplier.name},
        "current_status": ({"status": results[-1].status, "confidence": results[-1].confidence,
                            "notes": results[-1].notes, "reviewer_decision": results[-1].reviewer_decision}
                           if results else None),
        "history": [{"at": r.created_at.isoformat(), "status": r.status, "confidence": r.confidence,
                     "check_run_id": r.check_run_id, "reviewer_decision": r.reviewer_decision} for r in results],
        "check_runs": [{"id": r.id, "type": r.type, "adapter": r.adapter, "algorithm_version": r.algorithm_version,
                        "parameters": r.parameters, "inputs": r.inputs,
                        "finished_at": r.finished_at.isoformat() if r.finished_at else None} for r in runs],
        "alerts": [{"id": a.id, "type": a.type, "state": a.state, "confidence": a.confidence,
                    "first_seen": a.first_seen.isoformat(), "scene_ids": a.scene_ids, "details": a.details}
                   for a in alerts],
        "field_captures": cap_rows,
        "tasking": [{"id": o.id, "provider": o.provider, "status": o.status, "quote": o.quote} for o in orders],
        "attributions": ATTRIBUTIONS,
    }


def supplier_pack(db: Session, supplier: Supplier) -> dict[str, Any]:
    plots = db.scalars(select(Plot).where(Plot.supplier_id == supplier.id)).all()
    packs = [plot_pack(db, p) for p in plots]
    summary: dict[str, int] = {}
    for p in packs:
        k = (p["current_status"] or {}).get("status", "unchecked")
        summary[k] = summary.get(k, 0) + 1
    return {"disclaimer": DISCLAIMER, "generated_at": now().isoformat() + "Z",
            "supplier": {"id": supplier.id, "name": supplier.name, "country": supplier.country},
            "summary": summary, "plots": packs, "attributions": ATTRIBUTIONS}


def _plot_story(pack: dict[str, Any], styles) -> list:
    p, st = pack["plot"], pack["current_status"] or {}
    out: list = [Paragraph(f"Plot {p['external_id'] or p['id']} ({p['supplier']})", styles["Heading2"])]
    rows = [["Status", st.get("status", "unchecked")], ["Confidence", st.get("confidence", "n/a")],
            ["Area (ha)", p["area_ha"]], ["Commodity / country", f"{p['commodity']} / {p['country']}"],
            ["Validation", f"{p['validation_status']} {'; '.join(p['validation_notes'])}"]]
    out.append(_table(rows))
    for n in st.get("notes", []):
        out.append(Paragraph(f"• {n}", styles["Normal"]))
    out.append(Spacer(1, 4 * mm))
    out.append(Paragraph("Check runs and provenance", styles["Heading3"]))
    rows = [["Run", "Type", "Adapter", "Version", "Input scenes"]] + [
        [r["id"], r["type"], r["adapter"], r["algorithm_version"], ", ".join(r["inputs"][:3]) or "-"]
        for r in pack["check_runs"]]
    out.append(_table(rows, header=True))
    for a in pack["alerts"]:
        out.append(Spacer(1, 3 * mm))
        out.append(Paragraph(f"Alert #{a['id']}: {a['type']} ({a['state']}), confidence {a['confidence']}, "
                             f"first seen {a['first_seen'][:10]}, ~{a['details'].get('clearing_ha')} ha", styles["Normal"]))
        pv = a["details"].get("previews") or {}
        imgs = []
        for label in ("before", "after"):
            if pv.get(label):
                try:
                    imgs.append(Image(io.BytesIO(storage.get(pv[label])), 45 * mm, 45 * mm))
                except FileNotFoundError:
                    pass
        if imgs:
            out.append(Table([imgs, ["Before (2020 baseline NDVI)", "After (latest clear scene)"]]))
            out.append(Paragraph("Source: Sentinel-2 L2A (modified Copernicus Sentinel data); NDVI false colour.",
                                 styles["Italic"]))
    if pack["field_captures"]:
        out.append(Paragraph("Field captures", styles["Heading3"]))
        out.append(_table([["#", "Captured", "Accuracy m", "Signature"]] + [
            [c["id"], c["captured_at"][:19], c["accuracy_m"], c["signature_status"]] for c in pack["field_captures"]],
            header=True))
    return out


def _table(rows, header: bool = False):
    t = Table([[str(c) for c in r] for r in rows], hAlign="LEFT")
    st = [("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 8)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey))
    t.setStyle(TableStyle(st))
    return t


def render_pdf(pack: dict[str, Any]) -> bytes:
    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="GroundProof evidence pack", leftMargin=15 * mm,
                            rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm)
    story: list = [Paragraph("GroundProof evidence pack", styles["Title"]),
                   Paragraph(f"Generated {pack['generated_at']}", styles["Normal"]),
                   Paragraph(f"<i>{DISCLAIMER}</i>", styles["Normal"]), Spacer(1, 5 * mm)]
    if "plots" in pack:
        story.append(Paragraph(f"Supplier: {pack['supplier']['name']}", styles["Heading1"]))
        story.append(_table([["Status", "Plots"]] + list(pack["summary"].items()), header=True))
        for p in pack["plots"]:
            story.append(Spacer(1, 6 * mm))
            story += _plot_story(p, styles)
    else:
        story += _plot_story(pack, styles)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Attributions", styles["Heading3"]))
    for a in pack["attributions"]:
        story.append(Paragraph(a, styles["Normal"]))
    doc.build(story)
    return buf.getvalue()
