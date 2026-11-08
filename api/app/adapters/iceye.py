"""ICEYE mock adapter: quote -> approved task -> status progression -> fetch sample SAR."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from shapely.geometry.base import BaseGeometry

from ..config import get_settings
from . import synthetic as syn
from .base import Asset, NotConfigured, Quote, TimeWindow, stac_item
from .synthetic import _h

PRICE_PER_KM2 = {"spot": 14.0, "strip": 6.0}
STATES = ("queued", "scheduled", "acquired", "delivered")


class TaskingDisabled(PermissionError):
    pass


class BudgetExceeded(PermissionError):
    pass


class ICEYEMockAdapter:
    id = "iceye-mock"

    def __init__(self, spent_this_month: float = 0.0):
        self.spent = spent_this_month

    def search(self, aoi: BaseGeometry, start: date, end: date, **filters: Any) -> list[dict[str, Any]]:
        return []  # archive search not offered by the mock

    def quote(self, aoi: BaseGeometry, window: TimeWindow, mode: str = "spot") -> Quote:
        minx, miny, maxx, maxy = aoi.bounds
        km2 = max(25.0, abs(maxx - minx) * 111 * abs(maxy - miny) * 111)  # 5x5 km minimum
        price = round(km2 * PRICE_PER_KM2.get(mode, 14.0), 2)
        return Quote(self.id, price, 3 + _h(aoi.wkt) % 4, mode, notes="MOCK quote, not a real offer")

    def task(self, aoi: BaseGeometry, window: TimeWindow, mode: str, approved_by: int | None,
             quote_price: float | None = None) -> str:
        s = get_settings()
        if not s.iceye_enabled:
            raise TaskingDisabled("Commercial tasking is disabled (ICEYE_ENABLED=false)")
        if not approved_by:
            raise PermissionError("Tasking requires a named human approver")
        price = quote_price if quote_price is not None else self.quote(aoi, window, mode).price_eur
        if self.spent + price > s.tasking_monthly_budget_eur:
            raise BudgetExceeded(
                f"Order of EUR {price:.0f} would exceed monthly budget EUR {s.tasking_monthly_budget_eur:.0f}")
        return f"ICEYE-MOCK-{_h(aoi.wkt, window.start, approved_by) % 10**8:08d}"

    def status(self, order_id: str, polls: int = 0) -> str:
        return STATES[min(polls, len(STATES) - 1)]

    def fetch(self, item: dict[str, Any], aoi: BaseGeometry) -> Asset:
        key = item.get("properties", {}).get("gp:synthetic", {}).get("plot_key", item["id"])
        sc = {"scenario": item.get("properties", {}).get("gp:synthetic", {}).get("scenario", "stable_forest"),
              "clear_date": date(2021, 6, 15)}
        when = datetime.fromisoformat(item["properties"]["datetime"]).date()
        return Asset(item["id"], "sar", datetime.combine(when, datetime.min.time()),
                     syn.sar_scene(key, sc, when), {"attribution": "ICEYE MOCK sample, not real imagery"})

    def make_item(self, aoi: BaseGeometry, when: date, plot_key: str, props: dict[str, Any] | None,
                  price: float) -> dict[str, Any]:
        sc = syn.scenario_for(plot_key, props)
        it = stac_item(f"iceye-mock-{plot_key}-{when:%Y%m%d}", "iceye-mock", "ICEYE-SAR",
                       syn.as_dt(when), "L1-GRD", aoi, cost=price, can_display=True, can_share=False,
                       user_limit="single-organisation")
        it["properties"]["gp:synthetic"] = {"plot_key": plot_key, "scenario": sc["scenario"],
                                            "clear_date": sc["clear_date"].isoformat()}
        return it


def get_provider(name: str):
    from .sentinel import Sentinel1Adapter, Sentinel2Adapter
    if name == "iceye-mock":
        return ICEYEMockAdapter()
    if name == "iceye":
        raise NotConfigured("Real ICEYE API needs a partner agreement; the mock is the default")
    return {"sentinel-1": Sentinel1Adapter, "sentinel-2": Sentinel2Adapter}[name]()
