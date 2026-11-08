
from conftest import fc, square

SOY = {"supplier_name": "Fazenda Teste", "commodity": "soy", "country": "BR"}


def upload(client, headers, data, name="t.geojson", **form):
    return client.post("/api/plots/upload", headers=headers, files={"file": (name, data)}, data={**SOY, **form})


def test_upload_report_200_plots(client, analyst, admin):
    org = client.get("/api/auth/me", headers=analyst).json()["organization_id"]
    feats = [square(-55.0 + (i % 20) * 0.03, -12.0 - (i // 20) * 0.03, 0.01, id=f"S{i}") for i in range(200)]
    r = upload(client, analyst, fc(*feats), supplier_name="Synthetic 200", organization_id=org)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["total"] == 200 and j["stored"] == 200 and len(j["report"]) == 200
    assert all(row["plot_id"] for row in j["report"])


def test_upload_rejects_bad_files(client, analyst):
    assert upload(client, analyst, b"garbage", name="x.txt").status_code == 422
    assert upload(client, analyst, b"{bad", name="x.geojson").status_code == 422


def test_cutoff_mock_and_monitoring_alert(client, analyst, admin):
    org = client.get("/api/auth/me", headers=analyst).json()["organization_id"]
    data = fc(square(-55.5, -13.0, 0.01, "stable_crop", id="crop"),
              square(-55.6, -13.0, 0.01, "cleared_post_2020", id="clr", clear_date="2022-03-10"),
              square(-55.7, -13.0, 0.01, "cloudy_unknown", id="cld"))
    rep = upload(client, analyst, data, supplier_name="Pipeline Co", organization_id=org).json()["report"]
    ids = {r["external_id"]: r["plot_id"] for r in rep}
    for pid in ids.values():
        assert client.post(f"/api/plots/{pid}/check", headers=analyst).status_code == 200
    assert client.get(f"/api/plots/{ids['crop']}", headers=analyst).json()["status"] == "compliant"
    assert client.get(f"/api/plots/{ids['cld']}", headers=analyst).json()["status"] == "undetermined"
    # baseline alone cannot see post-cutoff clearing
    assert client.get(f"/api/plots/{ids['clr']}", headers=analyst).json()["status"] == "at_risk"

    r = client.post(f"/api/plots/{ids['clr']}/monitor", headers=analyst, json={"until": "2024-06-30"})
    assert r.status_code == 200 and r.json()["alert_id"]
    a = client.get(f"/api/alerts/{r.json()['alert_id']}", headers=analyst).json()
    assert a["type"] == "clearing_optical" and a["confidence"] >= 0.85
    assert a["first_seen"].startswith("2022-03") or a["first_seen"].startswith("2022-04")
    assert a["details"]["sar_corroborates"] and a["details"]["clearing_ha"] > 50
    assert a["scene_ids"] and client.get(f"/api/alerts/{a['id']}/preview/before", headers=analyst).status_code == 200
    # stable crop must not raise a false alert (seasonality handled)
    r2 = client.post(f"/api/plots/{ids['crop']}/monitor", headers=analyst, json={"until": "2024-06-30"})
    assert r2.json()["alert_id"] is None
    assert client.get(f"/api/plots/{ids['clr']}", headers=analyst).json()["status"] == "cleared_after_2020"


def test_determinism():
    from app.adapters.cutoff import MockCutoffAdapter
    a = MockCutoffAdapter().check("k1", {}, {"scenario": "partial_clearing"})
    b = MockCutoffAdapter().check("k1", {}, {"scenario": "partial_clearing"})
    assert a == b


def test_review_and_tasking_flow_audited(client, analyst, admin):
    org = client.get("/api/auth/me", headers=analyst).json()["organization_id"]
    rep = upload(client, analyst, fc(square(-56.0, -13.0, 0.01, "partial_clearing", id="part",
                                           clear_date="2021-09-01")), supplier_name="Review Co",
                 organization_id=org).json()["report"]
    pid = rep[0]["plot_id"]
    client.post(f"/api/plots/{pid}/check", headers=analyst)
    m = client.post(f"/api/plots/{pid}/monitor", headers=analyst, json={"until": "2023-12-31"}).json()
    aid = m["alert_id"]
    assert aid
    q = client.get("/api/review/queue", headers=analyst).json()
    assert aid in [a["id"] for a in q["alerts"]]
    # quote -> approval -> mock delivery -> decision
    o = client.post("/api/tasking/quote", headers=analyst, json={"plot_id": pid, "start": "2024-01-01", "end": "2024-01-10"}).json()
    assert o["status"] == "quoted" and o["quote"]["price_eur"] > 0
    assert client.post(f"/api/tasking/{o['id']}/approve", headers=analyst).status_code == 403
    ap = client.post(f"/api/tasking/{o['id']}/approve", headers=admin)
    assert ap.status_code == 200 and ap.json()["provider_order_id"].startswith("ICEYE-MOCK")
    states = [client.post(f"/api/tasking/{o['id']}/poll", headers=analyst).json()["status"] for _ in range(3)]
    assert states[-1] == "delivered"
    d = client.post(f"/api/alerts/{aid}/decision", headers=analyst, json={"decision": "confirm"})
    assert d.status_code == 200 and d.json()["state"] == "confirmed"
    assert client.get(f"/api/plots/{pid}", headers=analyst).json()["status"] == "cleared_after_2020"
    assert client.post(f"/api/alerts/{aid}/decision", headers=analyst, json={"decision": "nope"}).status_code == 422
    actions = [a["action"] for a in client.get("/api/audit?limit=1000", headers=admin).json()]
    for needed in ("tasking_quote", "tasking_approved", "tasking_status", "tasking_delivered", "alert_confirm"):
        assert needed in actions


def test_budget_cap_and_flag(client, analyst, admin, monkeypatch):
    from app.config import get_settings
    org = client.get("/api/auth/me", headers=analyst).json()["organization_id"]
    pid = upload(client, analyst, fc(square(-57, -13, 0.01, "stable_forest", id="bud")),
                 supplier_name="Budget Co", organization_id=org).json()["report"][0]["plot_id"]
    o = client.post("/api/tasking/quote", headers=analyst, json={"plot_id": pid, "start": "2024-01-01", "end": "2024-01-10"}).json()
    s = get_settings()
    monkeypatch.setattr(s, "tasking_monthly_budget_eur", 1.0)
    assert client.post(f"/api/tasking/{o['id']}/approve", headers=admin).status_code == 409
    monkeypatch.setattr(s, "tasking_monthly_budget_eur", 1e6)
    monkeypatch.setattr(s, "iceye_enabled", False)
    assert client.post(f"/api/tasking/{o['id']}/approve", headers=admin).status_code == 409
