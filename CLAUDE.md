# GroundProof

Platform for EU buyers to verify supplier plots (Brazil/Paraguay/Bolivia) were not deforested after 31 Dec 2020 (EUDR), monitor them with Sentinel-1/2, resolve doubt with signed field evidence, export evidence packs. Outputs are "evidence to support due diligence", not certification: keep that wording in UI/exports.

## Layout
`api/` FastAPI (app/: geo, adapters/, analytics/, evidence/, routers/, services, mcp_server) + tests; `workers/` daily scheduler; `console/standalone` demo console (served at /console), `console/overlay` + `console/scripts/setup-gev.sh` for God's Eye View; `field-app/` PWA (served at /field); `demo/`; `docs/` (DECISIONS, methods, PROGRESS, HANDOVER).

## Run / test
`make install && make test` (20 tests, ~2 min, demo test is slow) · `make lint` (ruff+mypy) · `make demo` (seed + serve :8000, console at /console/) · `make smoke` (Playwright, server must run with demo data) · `make check-keys` · `docker compose up` (not verified, see PROGRESS).
Logins (DEMO_SEED): admin@example.com/change-me-admin, analyst@example.com/demo-analyst, buyer@example.com/demo-buyer, field@example.com/demo-field.

## Conventions
Mock/offline is the default for everything needing keys; real adapters switch on only when configured and raise `NotConfigured` otherwise. Secrets only in `.env`. Every state change calls `audit()`. Roles enforced via `require()`; buyers are scoped to their organization. Results must be reproducible (store scene ids, algorithm_version, parameters). Log choices in docs/DECISIONS.md.

## Licence rules
- God's Eye View: MIT covers code only; do not ship its non-commercial data (TeleGeography cables, Nepal flood pack), CCTV/ALPR layers or third-party basemaps without checking terms.
- Whisp: MIT; Google Earth Engine needs a paid licence for commercial use; mock adapter stays default.
- AlphaEarth embeddings: CC-BY 4.0; show "The AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google DeepMind" wherever used (already in evidence packs).
- AGPL/GPL tools (OpenDroneMap, InSAR stacks): never import; separate service only, log the decision.
- Unsure licence: don't use it; list in HANDOVER.
- Supplier/plot data is buyer data: no third-party analytics, EU/local storage, log access.
