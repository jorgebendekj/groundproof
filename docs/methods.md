# Detector methods and limits

All results record `algorithm_version` (`gp-1.0.0`), parameters and input scene IDs; same inputs give the same outputs.

## Cutoff check (baseline)
Adapter returns a status + confidence + dataset columns. `MockCutoffAdapter`: deterministic synthetic. `WhispAdapter`: runs Whisp (needs Earth Engine) and maps its risk flag (`low`->compliant, `more_info_needed`->undetermined, `high`->at_risk). *Limit:* the column mapping is a first guess, untested live; Whisp datasets lag and cannot see clearing after their last update, which is what monitoring is for.

## Sentinel-2 optical detector
1. Skip scenes with > 40% plot-level cloud (SCL-derived mask; offline mode simulates it).
2. Baseline: per-pixel median NDVI of cloud-free 2020 scenes within +-30 days of the same day-of-year (seasonal, so crop cycles do not trigger).
3. Pixel flagged when `baseline - NDVI > 0.25` and `NDVI < 0.5` (`NDVI_DROP_THRESHOLD`).
4. Change is confirmed after 2 consecutive clear observations (persistence); area = flagged pixels x pixel area, must reach `MIN_CLEARING_HA` (0.5; for tiny plots a 25% fraction rule).
*Limits:* haze/shadows, burn scars, flooding and harvest of perennial crops can mimic loss; plantations (tree crops) are not distinguished from forest; 10 m pixels miss clearings < ~0.1 ha; no minimum-canopy definition (FAO forest) is applied.

## Sentinel-1 radar detector
Baseline = median VV/VH (dB) of 2020 scenes within +-45 days of the same day-of-year. Pixel flagged when VH drops > `SAR_DROP_DB` (3 dB) and VV drops > half of that; persistence of 2 acquisitions; same area rule. *Limits:* speckle (no multi-temporal filtering yet), soil-moisture and rain effects, flooded vegetation; no terrain correction in the offline model.

## Fusion and confidence
Optical hit: 0.65, +0.20 if radar corroborates, +0.10 if >=3 hits (cap 0.95). Radar-only (optical cloudy or no hit): 0.50, alert type `clearing_sar_only`. Auto-status: confidence >= 0.8 -> `cleared_after_2020`; lower -> `at_risk`. Analyst decisions override (confirm -> `cleared_after_2020` 0.97; reject removes the alert from scoring). Weights are heuristics, not calibrated against ground truth.

## Offline synthetic world
Scenarios (stable crop, stable forest, cleared post-2020, partial clearing, cloudy/unknown, cleared pre-2020) derive from plot properties or a hash of the plot id. It validates the pipeline, **not** the accuracy of the detectors on real imagery.
