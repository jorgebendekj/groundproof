from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    email: str
    password: str


class DecisionIn(BaseModel):
    decision: str


class QuoteIn(BaseModel):
    plot_id: int
    start: date
    end: date
    mode: str = "spot"


class RunIn(BaseModel):
    until: date | None = None
    adapter: str | None = None


class CaptureMeta(BaseModel):
    lat: float
    lon: float
    accuracy_m: float = Field(ge=0)
    gps_track: list[list[float]] = []
    device: dict[str, Any] = {}
    captured_at: str | None = None
