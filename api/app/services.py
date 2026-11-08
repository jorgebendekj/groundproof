"""Orchestration: cutoff checks, monitoring runs, review decisions, tasking."""
from __future__ import annotations

from datetime import date, datetime, time

from shapely.geometry import shape
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ALGORITHM_VERSION, storage
from .adapters.base import TimeWindow
from .adapters.cutoff import get_cutoff_adapter
from .adapters.iceye import BudgetExceeded, ICEYEMockAdapter, TaskingDisabled
from .adapters.sentinel import Sentinel1Adapter, Sentinel2Adapter
from .analytics.monitoring import run_detectors
from .analytics.raster import ndvi_rgb, write_png
from .config import get_settings
from .models import Alert, CheckRun, Plot, PlotResult, Scene, TaskingOrder, User, now
from .security import audit

BASELINE_START = date(2020, 1, 1)


def latest_result(db: Session, plot_id: int) -> PlotResult | None:
    return db.scalars(select(PlotResult).where(PlotResult.plot_id == plot_id)
                      .order_by(PlotResult.id.desc())).first()


def plot_key(p: Plot) -> str:
    return p.external_id or f"plot-{p.id}"


def _latest_cutoff(db: Session, plot_id: int) -> PlotResult | None:
    """Latest *pure* cutoff-adapter result (never a recomputed/fused one)."""
    runs = db.scalars(select(CheckRun.id).where(CheckRun.plot_id == plot_id, CheckRun.type == "cutoff")).all()
    if not runs:
        return None
    rows = db.scalars(select(PlotResult).where(PlotResult.check_run_id.in_(runs))
                      .order_by(PlotResult.id.desc())).all()
    return next((r for r in rows if "whisp_columns" in (r.evidence_refs or {})), None)


def recompute_status(db: Session, plot: Plot, run: CheckRun, user: User | None = None) -> PlotResult:
    from .analytics.scoring import score
    cut = _latest_cutoff(db, plot.id)
    alerts = db.scalars(select(Alert).where(Alert.plot_id == plot.id).order_by(Alert.confidence.desc())).all()
    states = {a.state for a in alerts}
    top = next((a for a in alerts if a.state != "rejected"), None)
    state = "confirmed" if "confirmed" in states else ("rejected" if alerts and states == {"rejected"} else None)
    sc = score(cut.status if cut else None, cut.confidence if cut else 0.0,
               top.confidence if top else None, state)
    res = PlotResult(plot_id=plot.id, check_run_id=run.id, status=sc.status, confidence=round(sc.confidence, 3),
                     notes=sc.notes + (cut.notes if cut else []),
                     evidence_refs={"alert_ids": [a.id for a in alerts], "cutoff_result_id": cut.id if cut else None})
    db.add(res)
    return res


def run_cutoff(db: Session, plot: Plot, user: User | None = None, adapter_name: str | None = None) -> PlotResult:
    adapter = get_cutoff_adapter(adapter_name)
    out = adapter.check(plot_key(plot), plot.geometry, plot.properties or {})
    run = CheckRun(plot_id=plot.id, type="cutoff", adapter=adapter.id, algorithm_version=ALGORITHM_VERSION,
                   parameters={"cutoff_date": "2020-12-31"}, inputs=out.inputs, finished_at=now())
    db.add(run)
    db.flush()
    res = PlotResult(plot_id=plot.id, check_run_id=run.id, status=out.status, confidence=out.confidence,
                     notes=out.notes, evidence_refs={"whisp_columns": out.columns})
    db.add(res)
    db.flush()
    # fold in any existing monitoring alerts
    final = recompute_status(db, plot, run, user)
    audit(db, user, "cutoff_check", "plot", plot.id, None, {"status": final.status})
    db.commit()
    return final


def run_monitoring(db: Session, plot: Plot, user: User | None = None, since: date | None = None,
                   until: date | None = None) -> tuple[CheckRun, Alert | None]:
    get_settings()
    until = until or date.today()
    since = since or BASELINE_START
    aoi = shape(plot.geometry)
    key = plot_key(plot)
    s2, s1 = Sentinel2Adapter(), Sentinel1Adapter()
    f = {"plot_key": key, "props": plot.properties}
    # baseline year is always needed for the seasonal comparison
    items2 = s2.search(aoi, BASELINE_START, until, **f)
    items1 = s1.search(aoi, BASELINE_START, until, **f)
    for it in items2 + items1:
        if not db.get(Scene, it["id"]):
            p = it["properties"]
            db.add(Scene(id=it["id"], provider=p["provider"], sensor=p["sensor"],
                         acquired=datetime.fromisoformat(p["datetime"]),
                         processing_level=p["processing_level"], cost_eur=p["cost_eur"],
                         licence=p["licence"], stac=it))
    a2 = [s2.fetch(i, aoi) for i in items2]
    a1 = [s1.fetch(i, aoi) for i in items1]
    eval_since = max(since, date(2021, 1, 1))
    det = run_detectors(a2, a1, plot.geometry, eval_since)
    run = CheckRun(plot_id=plot.id, type="monitoring", adapter="sentinel-1+sentinel-2/" + s2.mode,
                   algorithm_version=ALGORITHM_VERSION, parameters=det.parameters,
                   inputs=det.scene_ids + [i for i in det.inputs if i not in det.scene_ids],
                   finished_at=now())
    db.add(run)
    db.flush()
    alert = None
    if det.alert_type and det.first_seen:
        existing = db.scalars(select(Alert).where(Alert.plot_id == plot.id, Alert.type == det.alert_type)).first()
        if existing is None:
            alert = Alert(plot_id=plot.id, type=det.alert_type, geometry=plot.geometry,
                          first_seen=datetime.combine(det.first_seen, time.min),
                          scene_ids=det.scene_ids, confidence=round(det.confidence, 3), state="new",
                          details={"clearing_ha": det.clearing_ha, "sar_drop_db": det.sar_drop_db,
                                   "sar_corroborates": det.sar_corroborates, "s2_clear_obs": det.s2_clear_obs,
                                   "notes": det.notes, "parameters": det.parameters,
                                   "algorithm_version": ALGORITHM_VERSION},
                          check_run_id=run.id)
            db.add(alert)
            db.flush()
            if det.before_ndvi is not None:
                for name, arr in (("before", det.before_ndvi), ("after", det.after_ndvi)):
                    import numpy as np
                    storage.put(f"previews/alert_{alert.id}_{name}.png",
                                write_png(ndvi_rgb(np.nan_to_num(arr, nan=0.0))))
                alert.details = {**alert.details, "previews": {
                    "before": f"previews/alert_{alert.id}_before.png",
                    "after": f"previews/alert_{alert.id}_after.png"}}
    recompute_status(db, plot, run, user)
    audit(db, user, "monitoring_run", "plot", plot.id, None,
          {"alert": alert.id if alert else None, "scenes": len(items2) + len(items1)})
    db.commit()
    return run, alert


DECISIONS = {"confirm": "confirmed", "reject": "rejected", "request_field_check": "needs_field_check"}


def decide_alert(db: Session, alert: Alert, decision: str, user: User) -> Alert:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {sorted(DECISIONS)}")
    before = {"state": alert.state}
    alert.state = DECISIONS[decision]
    plot = db.get(Plot, alert.plot_id)
    assert plot is not None
    run = CheckRun(plot_id=plot.id, type="monitoring", adapter="analyst-review",
                   algorithm_version=ALGORITHM_VERSION, parameters={"decision": decision}, finished_at=now())
    db.add(run)
    db.flush()
    res = recompute_status(db, plot, run, user)
    res.reviewer_decision, res.reviewer_id = decision, user.id
    audit(db, user, f"alert_{decision}", "alert", alert.id, before, {"state": alert.state})
    db.commit()
    return alert


def month_spend(db: Session) -> float:
    first = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = db.scalars(select(TaskingOrder).where(TaskingOrder.created_at >= first,
                                                  TaskingOrder.status.not_in(["quoted", "rejected"]))).all()
    return sum(o.quote.get("price_eur", 0.0) for o in rows)


def request_quote(db: Session, plot: Plot, user: User, start: date, end: date, mode: str = "spot") -> TaskingOrder:
    aoi = shape(plot.geometry)
    q = ICEYEMockAdapter().quote(aoi, TimeWindow(start, end), mode)
    o = TaskingOrder(provider=q.provider, plot_id=plot.id, aoi=plot.geometry,
                     window_start=datetime.combine(start, time.min),
                     window_end=datetime.combine(end, time.min), mode=mode,
                     quote={"price_eur": q.price_eur, "eta_days": q.eta_days, "notes": q.notes},
                     requested_by_id=user.id)
    db.add(o)
    db.flush()
    audit(db, user, "tasking_quote", "tasking_order", o.id, None, o.quote)
    db.commit()
    return o


def approve_order(db: Session, order: TaskingOrder, approver: User) -> TaskingOrder:
    if order.status != "quoted":
        raise ValueError(f"Order is '{order.status}', not 'quoted'")
    adapter = ICEYEMockAdapter(spent_this_month=month_spend(db))
    try:
        oid = adapter.task(shape(order.aoi), TimeWindow(order.window_start.date(), order.window_end.date()),
                           order.mode, approver.id, order.quote["price_eur"])
    except (TaskingDisabled, BudgetExceeded) as e:
        audit(db, approver, "tasking_refused", "tasking_order", order.id, {"status": order.status},
              {"reason": str(e)})
        db.commit()
        raise
    order.provider_order_id, order.approved_by_id, order.status = oid, approver.id, "queued"
    audit(db, approver, "tasking_approved", "tasking_order", order.id, {"status": "quoted"}, {"status": "queued"})
    db.commit()
    return order


def poll_order(db: Session, order: TaskingOrder, user: User) -> TaskingOrder:
    if order.status in ("quoted", "rejected"):
        raise ValueError("Order is not approved")
    adapter = ICEYEMockAdapter()
    order.polls += 1
    new = adapter.status(order.provider_order_id or "", order.polls)
    if new != order.status:
        audit(db, user, "tasking_status", "tasking_order", order.id, {"status": order.status}, {"status": new})
        order.status = new
    if new == "delivered":
        plot = db.get(Plot, order.plot_id) if order.plot_id else None
        if plot and not db.get(Scene, f"iceye-mock-{plot_key(plot)}-{order.window_end:%Y%m%d}"):
            item = adapter.make_item(shape(order.aoi), order.window_end.date(), plot_key(plot),
                                     plot.properties, order.quote["price_eur"])
            db.add(Scene(id=item["id"], provider="iceye-mock", sensor="ICEYE-SAR", acquired=order.window_end,
                         processing_level="L1-GRD", cost_eur=order.quote["price_eur"],
                         licence=item["properties"]["licence"], stac=item))
            audit(db, user, "tasking_delivered", "scene", item["id"], None, {"order": order.id})
    db.commit()
    return order
