"""MCP server (stdio) exposing GroundProof to AI agents. Calls the REST API so roles + audit apply.

Run:  GP_API_URL=http://localhost:8000 GP_API_EMAIL=analyst@example.com GP_API_PASSWORD=... python -m app.mcp_server
Tool set is read-only except `request_tasking`, which only ever returns a quote.
"""
from __future__ import annotations

import os
from typing import Any

import httpx


class GroundProofTools:
    def __init__(self, http: Any):
        self.http = http

    def _get(self, path: str, **params: Any) -> Any:
        r = self.http.get(path, params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()

    def plot_status(self, plot_or_supplier: str) -> dict[str, Any]:
        """Status of one plot (numeric id) or of all plots of a supplier (name), with reasons."""
        key = str(plot_or_supplier).strip()
        if key.isdigit():
            p = self._get(f"/api/plots/{key}")
            return {"plot": self._plot(p)}
        sups = [s for s in self._get("/api/suppliers") if key.lower() in s["name"].lower()]
        if not sups:
            return {"error": f"No supplier matching '{key}'"}
        sup = sups[0]
        plots = self._get("/api/plots", supplier_id=sup["id"], limit=2000)
        alerts = {a["plot_id"]: a for a in self._get("/api/alerts")}
        out = []
        for p in plots:
            row = self._plot(self._get(f"/api/plots/{p['id']}")) if p["status"] in ("at_risk", "cleared_after_2020", "undetermined") else {
                "id": p["id"], "external_id": p["external_id"], "status": p["status"]}
            if p["id"] in alerts:
                a = alerts[p["id"]]
                row["alert"] = {"id": a["id"], "type": a["type"], "state": a["state"], "confidence": a["confidence"],
                                "first_seen": a["first_seen"][:10], "clearing_ha": a["details"].get("clearing_ha"),
                                "radar_corroborates": a["details"].get("sar_corroborates"), "scenes": a["scene_ids"]}
            out.append(row)
        counts: dict[str, int] = {}
        for r in out:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return {"supplier": sup["name"], "counts": counts, "plots": [r for r in out if r["status"] != "compliant"],
                "note": "Evidence to support due diligence, not a certification."}

    @staticmethod
    def _plot(p: dict[str, Any]) -> dict[str, Any]:
        return {"id": p["id"], "external_id": p["external_id"], "status": p["status"], "confidence": p["confidence"],
                "why": p.get("notes", []), "reviewer_decision": p.get("reviewer_decision"), "area_ha": p["area_ha"]}

    def eo_alerts_in_area(self, area: str, type: str | None = None, since: str | None = None) -> list[dict[str, Any]]:
        """Alerts intersecting a bbox 'minx,miny,maxx,maxy' (WGS84), optionally by type and first-seen date."""
        alerts = self._get("/api/alerts", bbox=area, type=type, since=since)
        return [{k: a[k] for k in ("id", "plot_id", "type", "state", "confidence", "first_seen", "scene_ids")}
                | {"clearing_ha": a["details"].get("clearing_ha")} for a in alerts]

    def evidence_pack(self, supplier: str) -> dict[str, Any]:
        sups = [s for s in self._get("/api/suppliers") if supplier.lower() in s["name"].lower()]
        if not sups:
            return {"error": f"No supplier matching '{supplier}'"}
        pack = self._get(f"/api/evidence/supplier/{sups[0]['id']}")
        return {"supplier": pack["supplier"], "summary": pack["summary"], "generated_at": pack["generated_at"],
                "pdf_url": f"/api/evidence/supplier/{sups[0]['id']}?format=pdf", "disclaimer": pack["disclaimer"]}

    def request_tasking(self, area: str, start: str, end: str) -> dict[str, Any]:
        """QUOTE ONLY. Never places an order; ordering needs a human analyst + admin approval."""
        r = self.http.post("/api/tasking/quote-area", json={"area": [float(x) for x in area.split(",")],
                                                             "start": start, "end": end})
        r.raise_for_status()
        return r.json()


def build_server():  # pragma: no cover - thin wiring
    try:  # mcp>=2 renamed FastMCP -> MCPServer
        from mcp.server.mcpserver import MCPServer as FastMCP  # type: ignore[import-not-found]
    except ImportError:
        from mcp.server.fastmcp import FastMCP  # type: ignore[attr-defined,no-redef]
    base = os.environ.get("GP_API_URL", "http://localhost:8000")
    http = httpx.Client(base_url=base, timeout=60)
    tok = http.post("/api/auth/login", json={"email": os.environ["GP_API_EMAIL"],
                                              "password": os.environ["GP_API_PASSWORD"]}).json()["access_token"]
    http.headers["Authorization"] = f"Bearer {tok}"
    t = GroundProofTools(http)
    mcp = FastMCP("groundproof")
    for fn in (t.plot_status, t.eo_alerts_in_area, t.evidence_pack, t.request_tasking):
        mcp.tool()(fn)
    return mcp


if __name__ == "__main__":  # pragma: no cover
    build_server().run()
