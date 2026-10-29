#!/usr/bin/env bash
# Downloads the pinned GraphHopper release JAR and the latest Bangladesh OSM extract.
# Idempotent: skips files that are already present.
set -euo pipefail
cd "$(dirname "$0")/.."

GH_VERSION="${GH_VERSION:-11.1}"
JAR="graphhopper-web-${GH_VERSION}.jar"
JAR_URL="https://github.com/graphhopper/graphhopper/releases/download/${GH_VERSION}/${JAR}"
PBF_URL="https://download.geofabrik.de/asia/bangladesh-latest.osm.pbf"

mkdir -p data

if [ ! -f "$JAR" ]; then
  echo ">> Downloading ${JAR} (~45 MB) ..."
  curl -fL --retry 3 -o "$JAR" "$JAR_URL"
else
  echo ">> ${JAR} already present, skipping."
fi

if [ ! -f data/bangladesh-latest.osm.pbf ]; then
  echo ">> Downloading Bangladesh OSM extract (~356 MB) ..."
  # fast path: 16 parallel range-request segments (Geofabrik throttles
  # single connections hard); falls back to plain curl
  python3 scripts/fast_download.py || curl -fL --retry 3 -o data/bangladesh-latest.osm.pbf "$PBF_URL"
else
  echo ">> data/bangladesh-latest.osm.pbf already present, skipping."
fi

echo ">> Done."
ls -lh "$JAR" data/bangladesh-latest.osm.pbf
