"""`make check-keys`: reports OK / MISSING / INVALID for every configurable secret. Never prints values."""
from __future__ import annotations

import json
import os
import smtplib
import sys
from pathlib import Path

import httpx

OK, MISSING, INVALID, SKIP = "OK", "MISSING", "INVALID", "NOT TESTABLE"


def env(k: str) -> str:
    return os.environ.get(k, "").strip()


def chk_jwt():
    v = env("JWT_SECRET")
    return (MISSING, "using dev default") if not v else (OK, "") if len(v) >= 32 and "change" not in v.lower() and "dev-only" not in v \
        else (INVALID, "too short or still a placeholder; generate: python -c 'import secrets;print(secrets.token_urlsafe(48))'")


def chk_admin():
    v = env("ADMIN_PASSWORD")
    return (MISSING, "using dev default") if not v else (INVALID, "still the default") if v == "change-me-admin" else (OK, "")


def chk_gee():
    v = env("GEE_SERVICE_ACCOUNT_JSON")
    if not v:
        return MISSING, "Whisp stays in mock mode"
    p = Path(v)
    if not p.is_file():
        return INVALID, "file not found"
    try:
        d = json.loads(p.read_text())
        assert d.get("type") == "service_account" and d.get("client_email") and d.get("private_key")
    except Exception:  # noqa: BLE001
        return INVALID, "not a service-account JSON key"
    try:
        import ee  # type: ignore
        ee.Initialize(ee.ServiceAccountCredentials(d["client_email"], str(p)))
        ee.Number(1).getInfo()
        return OK, "Earth Engine initialised"
    except ImportError:
        return SKIP, "key file looks valid; install 'real' extras to test live"
    except Exception as e:  # noqa: BLE001
        return INVALID, f"Earth Engine rejected the key: {type(e).__name__}"


def chk_firms():
    k = env("FIRMS_MAP_KEY")
    if not k:
        return MISSING, "fire layer disabled"
    try:
        r = httpx.get(f"https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/?MAP_KEY={k}", timeout=20)
        return (OK, "") if r.status_code == 200 and "Invalid" not in r.text else (INVALID, f"HTTP {r.status_code}")
    except httpx.HTTPError as e:
        return SKIP, f"network: {type(e).__name__}"


def chk_cdse():
    u, p = env("CDSE_USERNAME"), env("CDSE_PASSWORD")
    if not (u and p):
        return MISSING, "optional; only for Copernicus Data Space catalogue"
    try:
        r = httpx.post("https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
                       data={"client_id": "cdse-public", "grant_type": "password", "username": u, "password": p}, timeout=20)
        return (OK, "") if r.status_code == 200 else (INVALID, f"HTTP {r.status_code}")
    except httpx.HTTPError as e:
        return SKIP, f"network: {type(e).__name__}"


def chk_pc():
    k = env("PC_SUBSCRIPTION_KEY")
    return (MISSING, "optional; anonymous access has lower rate limits") if not k else (SKIP, "key presence only")


def chk_iceye():
    return (MISSING, "mock stays default") if not env("ICEYE_API_KEY") else (SKIP, "no sandbox available; test during partner onboarding")


def chk_c2pa():
    c, k = env("C2PA_CERT_PATH"), env("C2PA_KEY_PATH")
    if not (c and k):
        return MISSING, "dev self-signed key is used (not trusted)"
    return (OK, "") if Path(c).is_file() and Path(k).is_file() else (INVALID, "file(s) not found")


def chk_smtp():
    h = env("SMTP_HOST")
    if not h:
        return MISSING, "optional; notifications off"
    try:
        with smtplib.SMTP(h, int(env("SMTP_PORT") or 587), timeout=15) as s:
            s.starttls()
            if env("SMTP_USER"):
                s.login(env("SMTP_USER"), env("SMTP_PASSWORD"))
        return OK, ""
    except Exception as e:  # noqa: BLE001
        return INVALID, type(e).__name__


def chk_gev():
    keys = ("GOOGLE_MAPS_API_KEY", "CESIUM_ION_TOKEN", "OPENAI_API_KEY")
    have = [k for k in keys if env(k)]
    return (OK, "set: " + ", ".join(have)) if have else (MISSING, "optional; GEV falls back to keyless Esri imagery")


CHECKS = [("JWT_SECRET", chk_jwt, "required"), ("ADMIN_PASSWORD", chk_admin, "required"),
          ("GEE_SERVICE_ACCOUNT_JSON", chk_gee, "optional (real Whisp)"), ("FIRMS_MAP_KEY", chk_firms, "optional"),
          ("CDSE_USERNAME/PASSWORD", chk_cdse, "optional"), ("PC_SUBSCRIPTION_KEY", chk_pc, "optional"),
          ("ICEYE_API_KEY", chk_iceye, "later"), ("C2PA_CERT_PATH/KEY_PATH", chk_c2pa, "production"),
          ("SMTP_*", chk_smtp, "optional"), ("GEV basemap/3D/voice keys", chk_gev, "optional")]

if __name__ == "__main__":
    bad = 0
    print(f"{'ITEM':28} {'STATUS':14} NOTE")
    for name, fn, need in CHECKS:
        st, note = fn()
        bad += st == INVALID or (st == MISSING and need == "required")
        print(f"{name:28} {st:14} {note}  [{need}]")
    sys.exit(1 if bad else 0)
