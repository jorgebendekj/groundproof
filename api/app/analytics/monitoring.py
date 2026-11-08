"""Explainable clearing detectors. Method, parameters and limits are documented in docs/methods.md."""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from ..adapters.base import Asset
from ..adapters.synthetic import GRID
from ..config import get_settings
from ..geo import GEOD

BASELINE_YEAR = 2020
CUTOFF_DATE = date(2020, 12, 31)
MAX_CLOUD = 0.4          # scenes above this plot-level cloud fraction are not used
PERSISTENCE = 2          # consecutive clear observations needed to confirm a change


@dataclass
class Detection:
    clearing_ha: float = 0.0
    first_seen: date | None = None
    s2_clear_obs: int = 0
    s2_hits: int = 0
    sar_drop_db: float = 0.0
    sar_ha: float = 0.0
    sar_corroborates: bool = False
    confidence: float = 0.0
    alert_type: str | None = None        # clearing_optical | clearing_sar_only
    scene_ids: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    before_ndvi: Any = None
    after_ndvi: Any = None
    mask: Any = None
    parameters: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def pixel_area_ha(g: BaseGeometry) -> float:
    minx, miny, maxx, maxy = g.bounds
    if g.geom_type == "Point":
        minx, miny, maxx, maxy = minx - 0.0005, miny - 0.0005, maxx + 0.0005, maxy + 0.0005
    a, _ = GEOD.polygon_area_perimeter([minx, maxx, maxx, minx], [miny, miny, maxy, maxy])
    return abs(a) / 10_000 / (GRID * GRID)


def plot_pixel_mask(g: BaseGeometry) -> np.ndarray:
    """Boolean GRIDxGRID mask of pixels whose centre lies in the plot (all True for points)."""
    if g.geom_type == "Point":
        return np.ones((GRID, GRID), bool)
    from shapely import contains_xy
    minx, miny, maxx, maxy = g.bounds
    xs = minx + (np.arange(GRID) + 0.5) / GRID * (maxx - minx)
    ys = maxy - (np.arange(GRID) + 0.5) / GRID * (maxy - miny)
    X, Y = np.meshgrid(xs, ys)
    m = contains_xy(g, X, Y)
    return m if m.any() else np.ones((GRID, GRID), bool)


def _doy_close(d: date, ref: date, window: int) -> bool:
    delta = abs((d.replace(year=2001, day=min(d.day, 28)) - ref.replace(year=2001, day=min(ref.day, 28))).days)
    return min(delta, 365 - delta) <= window


def _baseline(assets: list[Asset], on: date, kind: str, window: int) -> dict[str, np.ndarray] | None:
    pool = [a for a in assets if a.acquired.year == BASELINE_YEAR and _doy_close(a.acquired.date(), on, window)]
    if not pool:
        return None
    if kind == "optical":
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return {"NDVI": np.nanmedian(np.stack([np.where(a.arrays["CLOUD"], np.nan, a.arrays["NDVI"])
                                               for a in pool]), axis=0)}
    return {k: np.median(np.stack([a.arrays[k] for a in pool]), axis=0) for k in ("VV", "VH")}


def detect_optical(assets: list[Asset], aoi: BaseGeometry, since: date, params: dict[str, Any]
                   ) -> tuple[Detection, list[tuple[date, np.ndarray, np.ndarray, Asset]]]:
    pm = plot_pixel_mask(aoi)
    pa = pixel_area_ha(aoi)
    det = Detection(parameters=params)
    hits: list[tuple[date, np.ndarray, np.ndarray, Asset]] = []
    streak: list[tuple[date, np.ndarray, np.ndarray, Asset]] = []
    for a in sorted((x for x in assets if x.acquired.date() >= since), key=lambda x: x.acquired):
        cloudy = a.arrays["CLOUD"]
        if (cloudy & pm).sum() / max(1, pm.sum()) > MAX_CLOUD:
            continue
        base = _baseline(assets, a.acquired.date(), "optical", 30)
        if base is None:
            continue
        valid = pm & ~cloudy & ~np.isnan(base["NDVI"])
        if valid.sum() < 0.3 * pm.sum():
            continue
        det.s2_clear_obs += 1
        drop = base["NDVI"] - a.arrays["NDVI"]
        m = valid & (drop > params["ndvi_drop_threshold"]) & (a.arrays["NDVI"] < 0.5)
        ha = m.sum() * pa
        if ha >= params["min_clearing_ha"] or (pm.sum() * pa < params["min_clearing_ha"] * 4 and m.mean() > 0.25):
            streak.append((a.acquired.date(), m, base["NDVI"], a))
            det.s2_hits += 1
            if len(streak) >= PERSISTENCE and not hits:
                hits = list(streak)
        else:
            streak = []
            if not hits:
                det.s2_hits = 0
    if hits:
        first = hits[0]
        last = streak[-1] if streak else hits[-1]
        det.first_seen = first[0]
        det.mask = last[1]
        det.clearing_ha = round(float(last[1].sum() * pa), 3)
        det.before_ndvi, det.after_ndvi = last[2], last[3].arrays["NDVI"]
        det.scene_ids = [h[3].item_id for h in streak[-3:]]
        det.alert_type = "clearing_optical"
    return det, hits


def detect_sar(assets: list[Asset], aoi: BaseGeometry, since: date, params: dict[str, Any], det: Detection
               ) -> None:
    pm = plot_pixel_mask(aoi)
    pa = pixel_area_ha(aoi)
    best: tuple[date, float, float, str, np.ndarray] | None = None
    consecutive = 0
    first_date: date | None = None
    for a in sorted((x for x in assets if x.acquired.date() >= since), key=lambda x: x.acquired):
        base = _baseline(assets, a.acquired.date(), "sar", 45)
        if base is None:
            continue
        drop_vh = base["VH"] - a.arrays["VH"]
        drop_vv = base["VV"] - a.arrays["VV"]
        m = pm & (drop_vh > params["sar_drop_db"]) & (drop_vv > params["sar_drop_db"] * 0.5)
        ha = m.sum() * pa
        if ha >= params["min_clearing_ha"] or (pm.sum() * pa < params["min_clearing_ha"] * 4 and m.mean() > 0.25):
            consecutive += 1
            first_date = first_date or a.acquired.date()
            if consecutive >= PERSISTENCE:
                best = (a.acquired.date(), float(drop_vh[m].mean()), float(ha), a.item_id, m)
        else:
            consecutive = 0
            if best is None:
                first_date = None
    if best:
        det.sar_drop_db = round(best[1], 2)
        det.sar_ha = round(best[2], 3)
        det.sar_first_seen = first_date  # type: ignore[attr-defined]
        det.inputs.append(best[3])
        det.sar_corroborates = True
        det._sar_mask = best[4]  # type: ignore[attr-defined]


def run_detectors(optical: list[Asset], sar: list[Asset], aoi_geojson: dict[str, Any], since: date,
                  overrides: dict[str, Any] | None = None) -> Detection:
    s = get_settings()
    params = {"min_clearing_ha": s.min_clearing_ha, "ndvi_drop_threshold": s.ndvi_drop_threshold,
              "sar_drop_db": s.sar_drop_db, "persistence": PERSISTENCE, "max_cloud": MAX_CLOUD,
              "baseline_year": BASELINE_YEAR}
    params.update(overrides or {})
    aoi = shape(aoi_geojson)
    det, _ = detect_optical(optical, aoi, since, params)
    detect_sar(sar, aoi, since, params, det)
    sar_ok = det.sar_corroborates
    if det.alert_type == "clearing_optical":
        det.confidence = min(0.95, 0.65 + (0.2 if sar_ok else 0.0) + (0.1 if det.s2_hits >= 3 else 0.0))
        if sar_ok:
            det.inputs.extend(det.scene_ids)
        else:
            det.inputs = list(det.scene_ids)
            det.notes.append("No SAR corroboration (SAR drop below threshold or no baseline).")
    elif sar_ok:
        recent_s2 = det.s2_clear_obs
        det.alert_type = "clearing_sar_only"
        det.clearing_ha = det.sar_ha
        det.first_seen = getattr(det, "sar_first_seen", None)
        det.confidence = 0.5
        det.scene_ids = list(det.inputs)
        det.notes.append(
            f"Radar backscatter dropped {det.sar_drop_db} dB; optical had {recent_s2} usable clear "
            "observations, so clearing is not optically confirmed.")
    return det
