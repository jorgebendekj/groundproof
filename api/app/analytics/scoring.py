"""Plot status scoring. Deterministic; reviewer decisions always win over automation."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Score:
    status: str
    confidence: float
    notes: list[str]


def score(cutoff_status: str | None, cutoff_conf: float, alert_conf: float | None,
          alert_state: str | None) -> Score:
    notes: list[str] = []
    if alert_state == "confirmed":
        return Score("cleared_after_2020", 0.97, ["Analyst confirmed clearing after the cutoff"])
    if alert_state == "rejected":
        alert_conf = None
        notes.append("Alert rejected by analyst")
    if alert_conf is not None:
        if alert_conf >= 0.8:
            return Score("cleared_after_2020", alert_conf, notes + ["Monitoring detected clearing after 2020"])
        return Score("at_risk", alert_conf, notes + ["Possible clearing detected; analyst review needed"])
    if cutoff_status == "cleared_after_2020":
        return Score("cleared_after_2020", cutoff_conf, notes)
    if cutoff_status == "at_risk":
        # Baseline shows forest in 2020 and monitoring found no clearing since.
        return Score("at_risk", min(cutoff_conf, 0.55), notes + [
            "Forest present at cutoff; no clearing seen in monitoring so far (keep monitoring)"])
    if cutoff_status == "compliant":
        return Score("compliant", cutoff_conf, notes)
    return Score("undetermined", cutoff_conf if cutoff_status else 0.0, notes + ["Insufficient evidence"])
