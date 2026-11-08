from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from shapely.geometry.base import BaseGeometry


class NotConfigured(RuntimeError):
    """Raised when a real adapter is selected but credentials/dependencies are missing."""


@dataclass(frozen=True)
class TimeWindow:
    start: date
    end: date


@dataclass
class Quote:
    provider: str
    price_eur: float
    eta_days: int
    mode: str
    currency: str = "EUR"
    notes: str = ""


@dataclass
class Asset:
    item_id: str
    kind: str                       # optical | sar
    acquired: datetime
    arrays: dict[str, Any] = field(default_factory=dict)   # band name -> ndarray
    meta: dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(Protocol):
    id: str

    def search(self, aoi: BaseGeometry, start: date, end: date, **filters: Any) -> list[dict[str, Any]]: ...
    def quote(self, aoi: BaseGeometry, window: TimeWindow, mode: str) -> Quote: ...
    def task(self, aoi: BaseGeometry, window: TimeWindow, mode: str, approved_by: int) -> str: ...
    def status(self, order_id: str) -> str: ...
    def fetch(self, item: dict[str, Any], aoi: BaseGeometry) -> Asset: ...


def stac_item(item_id: str, provider: str, sensor: str, when: datetime, level: str, aoi: BaseGeometry,
              cost: float = 0.0, can_display: bool = True, can_share: bool = True,
              user_limit: str | None = None, **extra: Any) -> dict[str, Any]:
    from shapely.geometry import box, mapping
    return {
        "type": "Feature", "stac_version": "1.0.0", "id": item_id,
        "geometry": mapping(box(*aoi.bounds)), "bbox": list(aoi.bounds),
        "properties": {
            "datetime": when.isoformat(), "provider": provider, "sensor": sensor,
            "processing_level": level, "cost_eur": cost,
            "licence": {"can_display": can_display, "can_share": can_share, "user_limit": user_limit},
            **extra,
        },
        "assets": {}, "links": [],
    }
