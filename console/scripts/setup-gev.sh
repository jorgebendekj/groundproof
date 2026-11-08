#!/usr/bin/env bash
# Fetch the pinned God's Eye View release into console/gev, strip non-commercial/surveillance data, apply the EO overlay.
set -euo pipefail
cd "$(dirname "$0")/.."
source GEV_PIN
if [ ! -d gev/.git ]; then git clone "$repo" gev; fi
git -C gev fetch -q origin && git -C gev checkout -q "$commit"
# --- strip (see docs/DECISIONS.md D-08): non-commercial data, CCTV and licence-plate readers ---
rm -rf gev/src/layers/submarineCables gev/src/layers/cctv gev/src/layers/alpr gev/server/providers/cctv gev/server/providers/cctv.js
find gev -ipath '*nepal*' -not -path '*/.git/*' -prune -exec rm -rf {} + 2>/dev/null || true
find gev -iname '*telegeography*' -not -path '*/.git/*' -exec rm -rf {} + 2>/dev/null || true
# --- overlay ---
cp -r overlay/server/. gev/server/ && cp -r overlay/src/. gev/src/ && mkdir -p gev/src/director/packs && cp overlay/director/*.json gev/src/director/packs/
echo "Overlay applied. Remaining manual wiring (needs the running GEV build to verify):"
echo "  1. server/providers/local.js : import { eoProxy } from './eo.js' and add eoProxy() to the plugin list"
echo "  2. src/app/constructCatalog.js: register eoPlots / eoAlerts / eoImagery (see docs/gev-integration.md)"
echo "  3. fix imports of removed layers (cctv, alpr, submarineCables) and run 'npm run check' in gev/"
