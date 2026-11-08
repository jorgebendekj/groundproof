"""Baseline EUDR cutoff check adapters (31 Dec 2020)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..config import get_settings
from . import synthetic as syn
from .base import NotConfigured

CUTOFF = "2020-12-31"


@dataclass
class CutoffResult:
    status: str            # compliant | at_risk | cleared_after_2020 | undetermined
    confidence: float
    columns: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    adapter: str = ""
    inputs: list[str] = field(default_factory=list)


class CutoffAdapter(Protocol):
    id: str

    def check(self, plot_key: str, geometry: dict[str, Any], props: dict[str, Any]) -> CutoffResult: ...


class MockCutoffAdapter:
    """Deterministic fake. Emulates the *shape* of Whisp output; values are synthetic."""
    id = "mock-cutoff"

    def check(self, plot_key: str, geometry: dict[str, Any], props: dict[str, Any]) -> CutoffResult:
        sc = syn.scenario_for(plot_key, props)
        k = sc["scenario"]
        cleared = k == "cleared_post_2020"
        tcl = {"cleared_post_2020": 0.0, "partial_clearing": 55.0}.get(k, 0.0)
        cols = {
            "GFC_TC_2020": 87 if k in ("stable_forest", "cleared_post_2020", "partial_clearing") else 12,
            "JRC_GFC_2020": int(k in ("stable_forest", "cleared_post_2020", "partial_clearing")),
            "ESA_TC_2020": int(k != "stable_crop" and k != "cleared_pre_2020"),
            "GFC_loss_year_post2020": (sc["clear_date"].year if cleared else 0),
            "treecover_pct_loss": tcl,
            "data_source": "MOCK (synthetic, not Whisp output)",
        }
        notes = ["Mock adapter: synthetic values for demo/testing, not evidence."]
        if k == "cleared_post_2020":
            # A real tree-cover-loss product often lags; baseline sees forest in 2020 only.
            return CutoffResult("at_risk", 0.55, cols, notes + [
                "Forest cover in 2020 baseline; later change must come from monitoring."], self.id)
        if k == "partial_clearing":
            return CutoffResult("at_risk", 0.5, cols, notes + ["Forest in 2020 baseline"], self.id)
        if k == "cloudy_unknown":
            return CutoffResult("undetermined", 0.3, cols, notes + ["Conflicting/insufficient datasets"], self.id)
        if k == "cleared_pre_2020":
            return CutoffResult("compliant", 0.85, cols, notes + ["Non-forest already in 2020 baseline"], self.id)
        return CutoffResult("compliant", 0.9 if k == "stable_crop" else 0.8, cols, notes, self.id)


class WhispAdapter:
    """Real adapter. Requires `openforis-whisp` and Google Earth Engine credentials."""
    id = "whisp"

    def __init__(self) -> None:
        s = get_settings()
        if not s.gee_service_account_json:
            raise NotConfigured("GEE_SERVICE_ACCOUNT_JSON is not set; Whisp needs Earth Engine credentials")
        try:
            import openforis_whisp  # noqa: F401
        except ImportError as e:
            raise NotConfigured("Install the 'real' extras: pip install openforis-whisp") from e

    def check(self, plot_key: str, geometry: dict[str, Any], props: dict[str, Any]) -> CutoffResult:
        import ee  # type: ignore
        import openforis_whisp as whisp  # type: ignore
        s = get_settings()
        ee.Initialize(ee.ServiceAccountCredentials(None, s.gee_service_account_json))
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"plotId": plot_key}, "geometry": geometry}]}
        df = whisp.whisp_formatted_stats_geojson_to_df(fc)  # one row per plot, risk columns included
        row = df.iloc[0].to_dict()
        risk = str(row.get("risk_pcrop") or row.get("risk_timber") or "").lower()
        status = {"low": "compliant", "more_info_needed": "undetermined", "high": "at_risk"}.get(risk, "undetermined")
        conf = {"compliant": 0.8, "undetermined": 0.3, "at_risk": 0.6}[status]
        return CutoffResult(status, conf, {k: _py(v) for k, v in row.items()},
                            [f"Whisp risk flag: {risk or 'n/a'}"], self.id)


def _py(v: Any) -> Any:
    try:
        return v.item()
    except AttributeError:
        return v


def get_cutoff_adapter(name: str | None = None) -> CutoffAdapter:
    name = name or get_settings().cutoff_adapter
    if name == "whisp":
        return WhispAdapter()
    return MockCutoffAdapter()
