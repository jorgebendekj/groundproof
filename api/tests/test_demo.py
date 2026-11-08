def test_demo_pair_end_to_end(client, analyst):
    from app import demo
    from app.db import SessionLocal
    with SessionLocal() as db:
        assert demo.load(db) == 202
    plots = {p["external_id"]: p for p in client.get("/api/plots?limit=2000", headers=analyst).json()}
    assert plots["DEMO-COMPLIANT"]["status"] == "compliant"
    assert plots["DEMO-CLEARED"]["status"] == "cleared_after_2020"
    alerts = client.get("/api/alerts", headers=analyst).json()
    a = next(x for x in alerts if x["plot_id"] == plots["DEMO-CLEARED"]["id"])
    assert a["first_seen"].startswith("2022-08") and a["details"]["sar_corroborates"]
    fc = client.get("/api/eo/plots.geojson", headers=analyst).json()
    assert len(fc["features"]) >= 202
