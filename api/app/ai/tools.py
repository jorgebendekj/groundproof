"""AI toolbox: read-only access to platform data, bound to the *calling user* (roles + org scoping apply).

The AI can read, explain and quote. It can NOT change statuses, record decisions, approve or place orders.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from shapely.geometry import box, shape
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Alert, Plot, Supplier, User
from ..routers.common import alert_out, plot_out, visible_plot_query
from ..security import audit

TOOL_SPECS: list[dict[str, Any]] = [
    {"name": "plot_status", "description": "Status, confidence and reasons for ONE plot by numeric id or external id.",
     "input_schema": {"type": "object", "properties": {"plot": {"type": "string"}}, "required": ["plot"]}},
    {"name": "supplier_overview", "description": "Status counts and the non-compliant plots (with reasons and alerts) for a supplier, matched by name.",
     "input_schema": {"type": "object", "properties": {"supplier": {"type": "string"}}, "required": ["supplier"]}},
    {"name": "alerts_in_area", "description": "Clearing alerts intersecting a bbox 'minx,miny,maxx,maxy' (WGS84), optional type and ISO 'since' date.",
     "input_schema": {"type": "object", "properties": {"area": {"type": "string"}, "type": {"type": "string"}, "since": {"type": "string"}}, "required": ["area"]}},
    {"name": "list_suppliers", "description": "Suppliers visible to the user.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "quote_scene", "description": "QUOTE ONLY for a commercial satellite scene over a bbox. Never orders; a human must create and an admin approve an order.",
     "input_schema": {"type": "object", "properties": {"area": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}}, "required": ["area", "start", "end"]}},
]


def clip(v: Any, n: int = 80) -> str:
    """Untrusted text (supplier-provided ids/names) is length-limited and stripped of control characters."""
    return "".join(ch for ch in str(v) if ch.isprintable())[:n]


class Toolbox:
    def __init__(self, db: Session, user: User):
        self.db, self.user = db, user
        self.calls: list[str] = []

    def run(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        fn = getattr(self, f"t_{name}", None)
        if fn is None or name not in {t["name"] for t in TOOL_SPECS}:
            return {"error": f"unknown tool {name}"}
        self.calls.append(name)
        try:
            return fn(**args)
        except (TypeError, ValueError, KeyError) as e:
            return {"error": f"bad arguments: {e}"}

    def _plot_row(self, p: Plot, detail: bool = False) -> dict[str, Any]:
        o = plot_out(self.db, p, detail=detail)
        row = {"id": o["id"], "external_id": clip(o["external_id"]), "supplier": clip(o["supplier"]), "status": o["status"],
               "confidence": o["confidence"], "area_ha": o["area_ha"], "commodity": clip(o["commodity"], 20)}
        if detail:
            row["why"] = [clip(n, 200) for n in o.get("notes", [])]
            row["reviewer_decision"] = o.get("reviewer_decision")
        return row

    def _alerts(self, plot_ids: list[int]) -> list[Alert]:
        if not plot_ids:
            return []
        return list(self.db.scalars(select(Alert).where(Alert.plot_id.in_(plot_ids)).order_by(Alert.confidence.desc())))

    @staticmethod
    def _alert_row(a: Alert) -> dict[str, Any]:
        o = alert_out(a)
        return {"id": o["id"], "plot_id": o["plot_id"], "type": o["type"], "state": o["state"], "confidence": o["confidence"],
                "first_seen": o["first_seen"][:10], "clearing_ha": o["details"].get("clearing_ha"),
                "radar_corroborates": o["details"].get("sar_corroborates"), "scene_ids": o["scene_ids"][:5]}

    def t_plot_status(self, plot: str) -> dict[str, Any]:
        q = visible_plot_query(self.user)
        p = (self.db.scalars(q.where(Plot.id == int(plot))).first() if str(plot).isdigit() else None) \
            or self.db.scalars(q.where(Plot.external_id == str(plot))).first()
        if not p:
            return {"error": "plot not found or not visible to this user"}
        audit(self.db, self.user, "ai_tool_plot_status", "plot", p.id)
        return {"plot": self._plot_row(p, True), "alerts": [self._alert_row(a) for a in self._alerts([p.id])]}

    def t_list_suppliers(self) -> dict[str, Any]:
        q = select(Supplier)
        if self.user.role == "buyer":
            q = q.where(Supplier.organization_id == self.user.organization_id)
        return {"suppliers": [{"id": s.id, "name": clip(s.name), "country": s.country} for s in self.db.scalars(q)]}

    def t_supplier_overview(self, supplier: str) -> dict[str, Any]:
        sups = [s for s in self.t_list_suppliers()["suppliers"] if supplier.lower() in s["name"].lower()]
        if not sups:
            return {"error": f"no supplier matching '{clip(supplier)}'"}
        sid = sups[0]["id"]
        plots = list(self.db.scalars(visible_plot_query(self.user).where(Plot.supplier_id == sid)))
        rows = [self._plot_row(p) for p in plots]
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        flagged_ids = {r["id"] for r in rows if r["status"] != "compliant"}
        detail = [self._plot_row(p, True) for p in plots if p.id in flagged_ids][:15]
        alerts = [self._alert_row(a) for a in self._alerts(list(flagged_ids))][:15]
        audit(self.db, self.user, "ai_tool_supplier_overview", "supplier", sid)
        return {"supplier": sups[0]["name"], "total_plots": len(rows), "counts": counts, "flagged_plots_shown": detail,
                "alerts": alerts, "truncated": len(flagged_ids) > 15}

    def t_alerts_in_area(self, area: str, type: str | None = None, since: str | None = None) -> dict[str, Any]:
        b = box(*[float(x) for x in area.split(",")])
        ids = [p.id for p in self.db.scalars(visible_plot_query(self.user))]
        out = []
        for a in self._alerts(ids):
            if type and a.type != type:
                continue
            if since and a.first_seen.date() < date.fromisoformat(since):
                continue
            if shape(a.geometry).intersects(b):
                out.append(self._alert_row(a))
        return {"alerts": out[:25], "total": len(out)}

    def t_quote_scene(self, area: str, start: str, end: str) -> dict[str, Any]:
        from ..adapters.base import TimeWindow
        from ..adapters.iceye import ICEYEMockAdapter
        if self.user.role not in ("admin", "analyst"):
            return {"error": "quotes are available to analysts and admins only"}
        q = ICEYEMockAdapter().quote(box(*[float(x) for x in area.split(",")]),
                                     TimeWindow(date.fromisoformat(start), date.fromisoformat(end)), "spot")
        audit(self.db, self.user, "ai_tool_quote", "area", area[:60], None, {"price_eur": q.price_eur})
        return {"price_eur": q.price_eur, "eta_days": q.eta_days, "notes": q.notes, "order_created": False}
