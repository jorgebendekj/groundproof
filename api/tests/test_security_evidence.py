from conftest import fc, square
from test_pipeline import upload


def _mk(client, analyst, name, org=None, **kw):
    org = org or client.get("/api/auth/me", headers=analyst).json()["organization_id"]
    r = upload(client, analyst, fc(square(-58.0, -14.0, 0.01, "stable_crop", id=name)), supplier_name=name,
               organization_id=org, **kw).json()["report"][0]["plot_id"]
    return r


def test_auth_required_and_roles(client, buyer, field, analyst):
    assert client.get("/api/plots").status_code == 401
    assert client.get("/api/plots", headers={"Authorization": "Bearer junk"}).status_code == 401
    assert client.post("/api/plots/1/check", headers=buyer).status_code == 403
    assert client.get("/api/audit", headers=analyst).status_code == 403
    assert client.post("/api/auth/login", json={"email": "x", "password": "y"}).status_code == 401


def test_buyer_sees_only_own_org(client, analyst, buyer):
    own = client.get("/api/auth/me", headers=buyer).json()["organization_id"]
    mine = _mk(client, analyst, "BuyerOwn", org=own)
    other = _mk(client, analyst, "NotBuyers")
    ids = {p["id"] for p in client.get("/api/plots", headers=buyer).json()}
    assert mine in ids and other not in ids
    assert client.get(f"/api/plots/{other}", headers=buyer).status_code == 404
    assert client.get(f"/api/evidence/plot/{other}", headers=buyer).status_code == 404


def test_field_capture_signature_tamper_and_chain(client, analyst, field, admin):
    import json
    pid = _mk(client, analyst, "FieldPlot")
    uid = client.get("/api/auth/me", headers=field).json()["id"]
    assert client.get(f"/api/plots/{pid}", headers=field).status_code == 404  # not assigned yet
    assert client.post(f"/api/plots/{pid}/assign/{uid}", headers=analyst).status_code == 200
    meta = json.dumps({"lat": -14.0, "lon": -58.0, "accuracy_m": 4.2, "gps_track": [[-58, -14], [-58.001, -14]],
                       "device": {"ua": "pytest"}})
    jpg = b"\xff\xd8\xff\xe0FAKEJPEG" + bytes(range(200))
    for _ in range(2):
        r = client.post(f"/api/plots/{pid}/captures", headers=field, files={"photo": ("a.jpg", jpg)}, data={"meta": meta})
        assert r.status_code == 200, r.text
    caps = client.get(f"/api/plots/{pid}/captures", headers=analyst).json()
    assert len(caps) == 2 and all(c["verification"]["valid"] and c["verification"]["chain_linked"] for c in caps)
    assert caps[1]["previous_hash"] == caps[0]["chain_hash"]
    # tamper with stored photo -> verification fails
    from app import storage
    from app.db import SessionLocal
    from app.models import FieldCapture
    with SessionLocal() as db:
        c = db.get(FieldCapture, caps[0]["id"])
        storage.put(c.file_path, jpg + b"edited")
    v = client.get(f"/api/captures/{caps[0]['id']}/verify", headers=analyst).json()
    assert v["valid"] is False and v["file_hash_matches"] is False and v["signature_valid"] is True
    pack = client.get(f"/api/evidence/plot/{pid}", headers=analyst).json()
    assert [c["signature_status"] for c in pack["field_captures"]] == ["INVALID", "valid"]


def test_evidence_pack_pdf_and_json(client, analyst, buyer, admin):
    import time
    org = client.get("/api/auth/me", headers=buyer).json()["organization_id"]
    pid = _mk(client, analyst, "PackSup", org=org)
    client.post(f"/api/plots/{pid}/check", headers=analyst)
    sid = client.get(f"/api/plots/{pid}", headers=analyst).json()["supplier_id"]
    t = time.time()
    r = client.get(f"/api/evidence/supplier/{sid}?format=pdf", headers=buyer)
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and time.time() - t < 60
    j = client.get(f"/api/evidence/supplier/{sid}", headers=buyer).json()
    assert "not a certification" in j["disclaimer"] and j["summary"]["compliant"] >= 1
    assert any("AlphaEarth" in a for a in j["attributions"])
    acts = [a["action"] for a in client.get("/api/audit?limit=1000", headers=admin).json()]
    assert "evidence_export" in acts


def test_health(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["cutoff_adapter"] == "mock"


def test_whisp_requires_credentials(client, analyst):
    pid = _mk(client, analyst, "WhispPlot")
    r = client.post(f"/api/plots/{pid}/check", headers=analyst, json={"adapter": "whisp"})
    assert r.status_code == 409 and "GEE_SERVICE_ACCOUNT_JSON" in r.text
