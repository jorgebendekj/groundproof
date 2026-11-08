# GroundProof: EUDR supply-chain verification MVP

Evidence to support due diligence (not certification) that supplier plots were not deforested after 31 Dec 2020.

## Setup
```bash
python3 -m venv .venv && . .venv/bin/activate
make install
cp .env.example .env     # optional; runs with no keys
make demo                # seeds 202 demo plots, serves http://localhost:8000
```
Console: http://localhost:8000/console/ · Field app: http://localhost:8000/field/ · API docs: /docs
Logins: `analyst@example.com / demo-analyst`, `admin@example.com / change-me-admin`, `buyer@example.com / demo-buyer`, `field@example.com / demo-field`.

## 5-minute demo script
1. `make demo`, open `/console/`, sign in as analyst. The legend shows plots by status (200 synthetic soy plots + 2).
2. Click **Demo tour**: a compliant plot, then its neighbour cleared Aug 2022: Sentinel-2 NDVI before/after, radar corroboration, scene IDs.
3. In the review queue open an alert, press **Confirm**; status flips to `cleared_after_2020`. Press **Request scene (quote)** to see the mock ICEYE quote.
4. As admin (`/docs` -> Authorize): `POST /api/tasking/{id}/approve` (needs `ICEYE_ENABLED=true`), then `POST /api/tasking/{id}/poll` three times to "deliver".
5. Assign a plot to the field user (`POST /api/plots/{id}/assign/{uid}`), open `/field/` on a phone, capture a photo; `GET /api/plots/{id}/captures` shows a verified signature + hash chain.
6. Download the pack: `GET /api/evidence/supplier/{id}?format=pdf`.
7. MCP: `GP_API_EMAIL=analyst@example.com GP_API_PASSWORD=demo-analyst python -m app.mcp_server` (from `api/`) and ask "which plots of supplier Fazenda Demo are at risk and why?".

Full God's Eye View globe: `make gev` (see docs/DECISIONS.md D-08 and docs/HANDOVER.md).
