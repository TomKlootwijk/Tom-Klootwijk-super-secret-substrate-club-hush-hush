#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 2 ]]; then echo "usage: $0 NL.zip flevoland-latest.osm.pbf" >&2; exit 2; fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
GEONAMES="$1"; OSM="$2"
mkdir -p data/real
python -m ugts_spatial ingest-geonames "$GEONAMES" data/real/flevoland_geonames.ugkg \
  --bbox 52.20 5.10 52.90 6.00 --country-code NL --limit 15000 \
  --observations examples/observations_variable.csv --teacher-dimensions 64
python -m ugts_spatial ingest-osm "$OSM" data/real/flevoland_osm.ugkg \
  --limit 100000 --spatial-resolution 14 --neighbors 4
python -m ugts_spatial inspect-graph data/real/flevoland_geonames.ugkg > data/real/flevoland_geonames.summary.json
python -m ugts_spatial inspect-graph data/real/flevoland_osm.ugkg > data/real/flevoland_osm.summary.json
