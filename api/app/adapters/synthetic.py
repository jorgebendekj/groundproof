"""Deterministic synthetic Earth for offline mode, tests and demos.

Every plot has a *scenario* (from its properties or a stable hash of its id) which fully determines
the NDVI / SAR time series. Same inputs -> same outputs; no network, no keys.
"""
from __future__ import annotations

import hashlib
import math
from datetime import date, datetime
from typing import Any

import numpy as np

GRID = 32
SCENARIOS = ("stable_crop", "stable_forest", "cleared_post_2020", "partial_clearing", "cloudy_unknown",
             "cleared_pre_2020")


def _h(*parts: object) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def scenario_for(external_id: str, props: dict[str, Any] | None) -> dict[str, Any]:
    props = props or {}
    if props.get("scenario") in SCENARIOS:
        sc = props["scenario"]
    else:
        b = _h("scenario", external_id) % 100
        sc = ("stable_crop" if b < 62 else "stable_forest" if b < 80 else "cleared_post_2020" if b < 88
              else "partial_clearing" if b < 93 else "cleared_pre_2020" if b < 96 else "cloudy_unknown")
    clear_date = props.get("clear_date")
    if not clear_date:
        month = 1 + _h("m", external_id) % 12
        year = 2021 + _h("y", external_id) % 3
        clear_date = f"{year}-{month:02d}-15"
    return {"scenario": sc, "clear_date": date.fromisoformat(str(clear_date)[:10])}


def _blob_mask(seed: int, frac: float) -> np.ndarray:
    """Deterministic compact blob covering roughly `frac` of the grid."""
    rng = np.random.default_rng(seed)
    cy, cx = rng.integers(8, GRID - 8, 2)
    yy, xx = np.mgrid[0:GRID, 0:GRID]
    r = math.sqrt(frac * GRID * GRID / math.pi)
    return ((yy - cy) ** 2 + (xx - cx) ** 2) <= r * r


def cleared_mask(ext_id: str, sc: dict[str, Any], on: date) -> np.ndarray:
    kind = sc["scenario"]
    if kind == "cleared_post_2020":
        return np.ones((GRID, GRID), bool) if on >= sc["clear_date"] else np.zeros((GRID, GRID), bool)
    if kind == "partial_clearing":
        m = _blob_mask(_h("blob", ext_id), 0.18)
        return m if on >= sc["clear_date"] else np.zeros((GRID, GRID), bool)
    return np.zeros((GRID, GRID), bool)


def ndvi_scene(ext_id: str, sc: dict[str, Any], on: date) -> np.ndarray:
    kind = sc["scenario"]
    rng = np.random.default_rng(_h("ndvi", ext_id, on.isoformat()))
    noise = rng.normal(0, 0.02, (GRID, GRID))
    doy = on.timetuple().tm_yday
    if kind in ("stable_forest", "partial_clearing", "cloudy_unknown") or (
            kind == "cleared_post_2020"):
        base = np.full((GRID, GRID), 0.86)
        base -= 0.03 * (1 + math.cos(2 * math.pi * (doy - 30) / 365)) / 2  # mild dry-season dip
    elif kind == "cleared_pre_2020":
        base = np.full((GRID, GRID), 0.35 + 0.35 * (1 + math.sin(2 * math.pi * (doy - 300) / 365)) / 2)
    else:  # stable_crop: strong seasonality (planting / harvest)
        base = np.full((GRID, GRID), 0.30 + 0.45 * (1 + math.sin(2 * math.pi * (doy - 20) / 365)) / 2)
    cm = cleared_mask(ext_id, sc, on)
    base = np.where(cm, 0.18 + 0.05 * rng.random((GRID, GRID)), base)
    return np.clip(base + noise, -0.1, 0.95)


def cloud_fraction(ext_id: str, sc: dict[str, Any], on: date) -> float:
    """Fraction of the plot obscured by cloud in this S2 scene."""
    r = (_h("cloud", ext_id, on.isoformat()) % 1000) / 1000
    wet = 0.5 + 0.5 * math.sin(2 * math.pi * (on.timetuple().tm_yday - 330) / 365)  # wet season Nov-Mar
    if sc["scenario"] == "cloudy_unknown":
        return 0.9 if r < 0.97 else 0.1
    return min(1.0, max(0.0, r * 0.6 + wet * 0.45 - 0.2)) if r > 0.15 else 0.0


def cloud_mask(ext_id: str, on: date, frac: float) -> np.ndarray:
    rng = np.random.default_rng(_h("cmask", ext_id, on.isoformat()))
    noise = rng.random((GRID, GRID))
    return noise < frac  # True = cloudy (SCL classes 8/9/10 equivalent)


def sar_scene(ext_id: str, sc: dict[str, Any], on: date) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(_h("sar", ext_id, on.isoformat()))
    kind = sc["scenario"]
    if kind == "cleared_pre_2020":
        vv, vh = -9.0, -15.5
    elif kind == "stable_crop":
        s = math.sin(2 * math.pi * (on.timetuple().tm_yday - 20) / 365)
        vv, vh = -10.0 + 2 * s, -16.0 + 2.5 * s
    else:
        vv, vh = -7.0, -12.5
    vv_a = np.full((GRID, GRID), vv) + rng.normal(0, 0.5, (GRID, GRID))
    vh_a = np.full((GRID, GRID), vh) + rng.normal(0, 0.6, (GRID, GRID))
    cm = cleared_mask(ext_id, sc, on)
    return {"VV": np.where(cm, vv_a - 3.6, vv_a), "VH": np.where(cm, vh_a - 4.2, vh_a)}


def acquisition_dates(start: date, end: date, step: int, offset: int) -> list[date]:
    out, d = [], date.fromordinal(start.toordinal() + ((offset - start.toordinal()) % step))
    while d <= end:
        out.append(d)
        d = date.fromordinal(d.toordinal() + step)
    return out


def as_dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 13, 30)
