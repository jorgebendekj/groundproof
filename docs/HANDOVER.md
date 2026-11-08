# Handover

## Launch checklist: what makes it live and real (priority order)
1. **Decide hosting + domain + EU region**, then deploy with HTTPS (not done; a reverse proxy such as Caddy is needed). Provide: cloud account/server, domain.
2. **Strong secrets**: `JWT_SECRET`, `ADMIN_PASSWORD`, set `DEMO_SEED=false`.
3. **Earth Engine service account** (paid licence for commercial use) -> real Whisp baseline. Needs a live test with your credentials.
4. **Real imagery**: a machine with internet access so the Sentinel pixel-reading code can be written and tested (not possible in the build sandbox). Optional keys: Copernicus Data Space, Planetary Computer.
5. **A real validated cleared-plot polygon** (MapBiomas Alerta) and a few known-good plots, so detector accuracy can be measured before any client relies on it.
6. **C2PA certificate** for trusted field-evidence signing.
7. **ICEYE partner agreement** when you want real tasking.
8. **Client onboarding**: user/organization management screens and password reset are NOT built yet (users are created by seed only). Needs a decision on how clients sign up.
9. Optional: SMTP (notifications are not built), NASA FIRMS key, God's Eye View keys (globe needs wiring on a machine with its build).

## What I need from you
| Item | Why it's needed | Where to create it | Variable in `.env` | How to test | Required or optional |
|---|---|---|---|---|---|
| JWT secret | Signs login tokens | generate locally: `python -c "import secrets;print(secrets.token_urlsafe(48))"` | `JWT_SECRET` | `make check-keys` | Required (app refuses to start without it when `DEMO_SEED=false`) |
| Admin password | Admin account | choose a strong one (password manager) | `ADMIN_PASSWORD` | `make check-keys` | Required |
| Google Earth Engine service account + key | Real Whisp baseline (commercial use needs a paid EE licence) | https://earthengine.google.com/ ; https://console.cloud.google.com/iam-admin/serviceaccounts | `GEE_SERVICE_ACCOUNT_JSON` (path), `CUTOFF_ADAPTER=whisp` | `make check-keys` (live `ee.Initialize` if extras installed) | Optional for demo; required for real checks |
| Copernicus Data Space account | Alternative STAC catalogue / downloads | https://dataspace.copernicus.eu | `CDSE_USERNAME`, `CDSE_PASSWORD`, `STAC_URL` | `make check-keys` | Optional |
| Planetary Computer key | Higher rate limits (anonymous works) | https://planetarycomputer.microsoft.com/account/request | `PC_SUBSCRIPTION_KEY` | `make check-keys` (presence only) | Optional |
| NASA FIRMS map key | Active-fire layer | https://firms.modaps.eosdis.nasa.gov/api/map_key/ | `FIRMS_MAP_KEY` | `make check-keys` | Optional (not yet consumed by the API; GEV reads it) |
| God's Eye View keys | Photorealistic 3D tiles, Cesium ion, voice | see `console/gev/.env.example` after `make gev` | `GOOGLE_MAPS_API_KEY`, `CESIUM_ION_TOKEN`, `OPENAI_API_KEY` | `make check-keys` (presence) | Optional (keyless Esri fallback) |
| ICEYE API credentials | Real tasking | ICEYE partner agreement | `ICEYE_API_KEY`, `ICEYE_ENABLED` | cannot test; real adapter not written | Later |
| C2PA signing certificate | Trusted content credentials | a C2PA-conformant CA | `C2PA_CERT_PATH`, `C2PA_KEY_PATH` | `make check-keys` | Production |
| SMTP credentials | Notifications | your mail provider | `SMTP_HOST/PORT/USER/PASSWORD` | `make check-keys` | Optional (not used by MVP yet) |
| Hosting, domain, EU region | Deployment | e.g. an EU cloud region | n/a | n/a | When deploying |
| Verified demo polygon | Replace synthetic DEMO-CLEARED with a real post-2020 clearing (MapBiomas Alerta) | https://alerta.mapbiomas.org | edit `demo/fixtures` | `make demo` | Recommended before investor demos |

Also review the basemap/data terms of anything GEV loads before commercial demos.

## Where to store secrets
Password manager or cloud secret manager; never email, chat or git. Copy into `.env` only on the machine that runs the app. Rotate any key that was ever exposed.

## Switching mock -> real
- **Whisp:** `pip install -e "api[real]"`; set `GEE_SERVICE_ACCOUNT_JSON`, `CUTOFF_ADAPTER=whisp`; `make check-keys` should say OK; `POST /api/plots/{id}/check` returns Whisp columns in `provenance.whisp_columns`. Without credentials it returns 409.
- **Imagery:** set `IMAGERY_MODE=stac` + `STAC_URL`. *Today search works but pixel reads raise `NotConfigured`* (D-04); someone must implement COG reads with rasterio/odc-stac.
- **ICEYE:** `ICEYE_ENABLED=true` only enables the mock workflow. A real adapter does not exist.
- **C2PA:** set cert/key paths; `embed_c2pa` is written but unverified.

## Still mocked or simplified
Synthetic imagery and cutoff data by default; detector accuracy on real imagery is unknown (docs/methods.md); dev signing key; scheduler instead of Prefect; no email, no AlphaEarth, no FIRMS use in the API; GEV overlay not wired/verified; `docker compose` unverified; Redis not used; MinIO container present but storage is local disk (S3 backend not implemented).

## Run the demo
See README "5-minute demo script".
