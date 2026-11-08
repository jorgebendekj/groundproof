from app.mcp_server import GroundProofTools
from conftest import fc, square
from test_pipeline import upload


def test_agent_can_answer_at_risk_question(client, analyst):
    org = client.get("/api/auth/me", headers=analyst).json()["organization_id"]
    rep = upload(client, analyst, fc(square(-54.0, -13.0, 0.01, "cleared_post_2020", id="m1", clear_date="2022-02-01"),
                                    square(-54.1, -13.0, 0.01, "stable_crop", id="m2")),
                 supplier_name="McpSupplier X", organization_id=org).json()["report"]
    for r in rep:
        client.post(f"/api/plots/{r['plot_id']}/check", headers=analyst)
        client.post(f"/api/plots/{r['plot_id']}/monitor", headers=analyst, json={"until": "2024-06-30"})
    client.headers.update(analyst)
    t = GroundProofTools(client)
    s = t.plot_status("mcpsupplier")
    assert s["counts"]["cleared_after_2020"] == 1 and s["counts"]["compliant"] == 1
    bad = s["plots"][0]
    assert bad["alert"]["type"] == "clearing_optical" and bad["alert"]["radar_corroborates"] and bad["why"]
    hits = t.eo_alerts_in_area("-54.5,-13.5,-53.5,-12.5", since="2021-01-01")
    assert any(h["plot_id"] == bad["id"] for h in hits)
    q = t.request_tasking("-54.05,-13.0,-54.0,-12.99", "2024-01-01", "2024-01-10")
    assert q["order_created"] is False and q["price_eur"] > 0
    pack = t.evidence_pack("McpSupplier")
    assert pack["summary"] and pack["pdf_url"].endswith("format=pdf")
    assert t.plot_status("nonexistent-supplier")["error"]
    client.headers.pop("Authorization")


def test_mcp_sdk_import_resolves():
    """Regression: mcp 2.x renamed FastMCP -> MCPServer; the server must import under either."""
    try:
        from mcp.server.mcpserver import MCPServer  # noqa: F401
    except ImportError:
        from mcp.server.fastmcp import FastMCP  # noqa: F401
