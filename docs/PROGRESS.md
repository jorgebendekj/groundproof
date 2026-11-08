# Progress

| Milestone | State | Notes |
|---|---|---|
| M0 repo/infra | Partial | Monorepo, Dockerfile, compose, CI, Makefile written. **`docker compose up` was never run** (no Docker daemon in the build sandbox). Health endpoint, lint, mypy, tests verified locally. GEV is a pinned reference, not vendored. |
| M1 plots + validation | Done | GeoJSON / zipped shapefile (reprojection) / CSV; repair, duplicate, overlap flags; 200-plot upload tested. |
| M2 cutoff | Done (mock) | Mock default; Whisp adapter written, untested live. |
| M3 monitoring | Done (offline) | S2 + S1 detectors on deterministic synthetic scenes; PNG before/after previews; daily worker + run-now. **Real STAC pixel reads not implemented.** Fixture geometry synthetic (D-10). |
| M4 review + tip-and-cue | Done | Quote -> admin approval (flag, budget, four-eyes) -> mock delivery -> decision; all audited. |
| M5 field evidence | Done (dev signing) | PWA + Ed25519-signed manifest + hash chain; tamper test. Real C2PA embedding untested. |
| M6 evidence packs | Done | JSON + PDF per plot/supplier, <1 s for demo supplier. |
| M7 GEV integration | Partial | Overlay (eo proxy, 3 layers, tour pack, strip script) syntax-checked only; standalone console + demo tour browser-tested. AlphaEarth not done. |
| M8 MCP + auth | Done | 4 tools tested via the REST API; roles + org scoping + audit tested. GEV tool-catalog registration not done. |

Verified here: `pytest` 20 passed, `ruff`, `mypy`, Playwright smoke (console tour + field login).
Next: run compose on a machine with Docker; wire GEV overlay; real STAC reads; replace demo polygon with a verified one.
