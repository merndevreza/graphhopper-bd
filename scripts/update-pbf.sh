#!/usr/bin/env bash
# Refreshes the OSM extract and rebuilds the routing graph.
# Run this occasionally (Geofabrik publishes an updated Bangladesh extract daily);
# road networks in Bangladesh do change (new bridges, flyovers, access rules).
set -euo pipefail
cd "$(dirname "$0")/.."

echo ">> Stopping service (if running) ..."
docker compose down || true

echo ">> Downloading fresh Bangladesh extract (~356 MB) ..."
rm -f data/bangladesh-latest.osm.pbf
curl -fL --retry 3 -o data/bangladesh-latest.osm.pbf \
  "https://download.geofabrik.de/asia/bangladesh-latest.osm.pbf"

echo ">> Removing old graph cache ..."
rm -rf graph-cache

echo ">> Restarting service — next start re-imports (10-20 min) ..."
docker compose up -d
echo ">> Follow the import with:  docker compose logs -f"
