"""Sentinel-2 (optical) and Sentinel-1 (SAR) adapters: offline synthetic mode + STAC mode."""
from __future__ import annotations

from datetime import date
from typing import Any

import httpx
from shapely.geometry.base import BaseGeometry

from ..config import get_settings
from . import synthetic as syn
from .base import Asset, NotConfigured, Quote, TimeWindow, stac_item

S2_LICENCE: dict[str, Any] = {"can_display": True, "can_share": True, "user_limit": None}
ATTRIB = "Contains modified Copernicus Sentinel data"


class _SentinelBase:
    id = ""
    sensor = ""
    kind = ""
    collection = ""
    step = 5
    level = ""

    def __init__(self, mode: str | None = None, stac_url: str | None = None):
        s = get_settings()
        self.mode = mode or s.imagery_mode
        self.stac_url = stac_url or s.stac_url

    # --- paid-only methods are not applicable ---
    def quote(self, aoi: BaseGeometry, window: TimeWindow, mode: str) -> Quote:
        return Quote(self.id, 0.0, 0, mode, notes="Free public data")

    def task(self, *a: Any, **k: Any) -> str:
        raise NotImplementedError(f"{self.id} is a public archive and cannot be tasked")

    def status(self, order_id: str) -> str:
        return "delivered"

    def search(self, aoi: BaseGeometry, start: date, end: date, **filters: Any) -> list[dict[str, Any]]:
        if self.mode == "stac":
            return self._stac_search(aoi, start, end, **filters)
        key = filters.get("plot_key", "plot")
        sc = syn.scenario_for(key, filters.get("props"))
        items = []
        for d in syn.acquisition_dates(start, end, self.step, 3 if self.kind == "optical" else 7):
            it = stac_item(f"{self.sensor}-{key}-{d:%Y%m%d}", "copernicus", self.sensor, syn.as_dt(d),
                           self.level, aoi, **S2_LICENCE,  # type: ignore[arg-type]
                            attribution=ATTRIB)
            it["properties"]["gp:synthetic"] = {"plot_key": key, "scenario": sc["scenario"],
                                                "clear_date": sc["clear_date"].isoformat()}
            if self.kind == "optical":
                it["properties"]["eo:cloud_cover"] = round(100 * syn.cloud_fraction(key, sc, d), 1)
            items.append(it)
        return items

    def _stac_search(self, aoi: BaseGeometry, start: date, end: date, **filters: Any) -> list[dict[str, Any]]:
        body = {"collections": [self.collection], "bbox": list(aoi.bounds),
                "datetime": f"{start.isoformat()}/{end.isoformat()}", "limit": 100}
        if self.kind == "optical":
            body["query"] = {"eo:cloud_cover": {"lt": filters.get("max_cloud", 80)}}
        try:
            r = httpx.post(f"{self.stac_url.rstrip('/')}/search", json=body, timeout=30)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise NotConfigured(f"STAC search failed ({self.stac_url}): {e}") from e
        return r.json().get("features", [])

    def fetch(self, item: dict[str, Any], aoi: BaseGeometry) -> Asset:
        p = item["properties"]
        when = date.fromisoformat(p["datetime"][:10])
        syn_meta = p.get("gp:synthetic")
        if self.mode != "stac" and syn_meta:
            sc = {"scenario": syn_meta["scenario"], "clear_date": date.fromisoformat(syn_meta["clear_date"])}
            key = syn_meta["plot_key"]
            if self.kind == "optical":
                ndvi = syn.ndvi_scene(key, sc, when)
                cloudy = syn.cloud_mask(key, when, p.get("eo:cloud_cover", 0) / 100)
                return Asset(item["id"], "optical", syn.as_dt(when), {"NDVI": ndvi, "CLOUD": cloudy},
                             {"attribution": ATTRIB})
            return Asset(item["id"], "sar", syn.as_dt(when), syn.sar_scene(key, sc, when),
                         {"attribution": ATTRIB})
        raise NotConfigured(
            "Real raster reads need the 'real' extras (rasterio, odc-stac) and a signed asset URL; "
            "see docs/HANDOVER.md for switching from offline to STAC mode.")


class Sentinel2Adapter(_SentinelBase):
    id, sensor, kind, collection, step, level = "sentinel-2", "S2", "optical", "sentinel-2-l2a", 5, "L2A"


class Sentinel1Adapter(_SentinelBase):
    id, sensor, kind, collection, step, level = "sentinel-1", "S1", "sar", "sentinel-1-grd", 12, "GRD"
