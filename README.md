# GraphHopper Bangladesh — routing service for the billing dashboard

Self-hosted routing engine (GraphHopper 11.1) with a Bangladesh-only OSM extract,
running in Docker. Provides road distances/times for **nearest-branch** and
**trip-distance** calculations used by the billing report.

Works unchanged on an Apple Silicon Mac (development) and on an x86 Linux server
(production) — Java + multi-arch base image.

## Quick start

```bash
cd graphhopper-bd
./scripts/download.sh     # GraphHopper 11.1 JAR (~45 MB) + Bangladesh PBF (~356 MB), one-time
docker compose up -d      # builds the image; FIRST start imports OSM data (10-20 min)
docker compose logs -f    # watch until you see "Server started ... started"
```

Then open **http://localhost:8989** — the built-in map UI lets you click two points
and route between them. Check `docker compose ps` for `(healthy)`.

## Files

| Path | Purpose |
|---|---|
| `config.yml` | Profiles (`car`, `motorcycle`), CH speed mode, ports |
| `Dockerfile` | temurin-21-jre + pinned `graphhopper-web-11.1.jar` |
| `docker-compose.yml` | Service, ports 8989/8990, healthcheck, memory |
| `scripts/download.sh` | One-time download of JAR + PBF (idempotent) |
| `scripts/update-pbf.sh` | Refresh OSM data + rebuild the graph (monthly is plenty) |
| `helper/nearest_branch.py` | Batch nearest-branch → billing CSV (stdlib only) |
| `helper/branches.csv` | Sample branches — replace with your real branch list |
| `helper/trips.csv` | Sample trip-end points |
| `data/` | `bangladesh-latest.osm.pbf` (git-ignored, ~356 MB) |
| `graph-cache/` | Built routing graph (git-ignored, generated at first start) |

## The billing calculation

```
trip-end (lat, lon)
   │  1. haversine prefilter → K=5 closest branches (avoids routing to all)
   ▼
GraphHopper GET /route  →  per candidate: road km + minutes + snapped endpoints
   │  2. shortest road distance wins
   ▼
billing row: branch_id, route_km, route_minutes, straight_line_km,
             snap_start_m / snap_end_m, error
```

* `snap_start_m` — distance from the raw GPS point to the road GraphHopper snapped to.
  A large value (> ~200 m) usually means a bad GPS fix — useful data-quality flag
  before billing on that trip.
* `error` column: unreachable/unroutable trips are flagged, never crash the batch.
* Why K=5: routing 5 candidates is ~5 ms with CH; correctness gap vs routing to all
  branches is negligible when branches are spread over cities.

## Batch nearest-branch (reference implementation)

```bash
python3 helper/nearest_branch.py \
    --branches helper/branches.csv \
    --trips helper/trips.csv \
    --profile car -o billing.csv
# add --profile motorcycle, -k 10, --url http://<server>:8989
```

Output columns: `trip_id, trip_lat, trip_lon, branch_id, branch_name, branch_lat,
branch_lon, route_km, route_minutes, straight_line_km, snap_start_m, snap_end_m,
profile, error`

## REST API examples

```bash
# Route, car profile
curl -s "http://localhost:8989/route?point=23.7925,90.4078&point=23.7275,90.4123&profile=car&points_encoded=false&instructions=false"

# Same, motorcycle
curl -s "http://localhost:8989/route?...&profile=motorcycle"

# Snap a raw GPS point to the nearest road (trip data-quality checks)
curl -s "http://localhost:8989/nearest?point=23.7806,90.4194"
```

Response `paths[0].distance` = meters, `paths[0].time` = ms.

## Updating the map data

Geofabrik publishes an updated Bangladesh extract daily; roads change (new
bridges/flyovers). Refresh monthly or when you notice wrong distances:

```bash
./scripts/update-pbf.sh   # stops service, re-downloads, rebuilds graph, restarts
```

## Server deployment (production)

The same folder runs identically on a Linux x86 server:

```bash
# 1. install Docker on the server (docker compose v2 plugin included)
# 2. copy the project folder WITHOUT the big generated data:
rsync -av --exclude data/ --exclude graph-cache/ \
    graphhopper-bd/ user@server:/opt/graphhopper-bd/
# 3. on the server, download JAR+PBF there and start (import runs once):
cd /opt/graphhopper-bd && ./scripts/download.sh && docker compose up -d
```

Notes:
* To skip the server-side import you can instead stop the service locally and
  `rsync` `graph-cache/` over too — the cache is portable between machines
  running the **same GraphHopper version** (copy it while the service is stopped).
* GraphHopper does not require auth — keep it on an internal network / firewall it.
* For >10k trips per billing run, nothing special needed: CH queries are ~1 ms.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Cannot connect to the Docker daemon` | Start Docker Desktop |
| First start seems stuck | Normal: import takes 10-20 min — `docker compose logs -f` shows progress |
| Container restarts / OOM | Raise Docker Desktop memory limit (Settings → Resources) and/or lower `JAVA_OPTS -Xmx` |
| Port 8989 busy | Change the **left** port in `docker-compose.yml` (`8989:8989` → e.g. `8999:8989`) |
| Wrong-looking distances after months | Run `./scripts/update-pbf.sh` |
| Helper can't reach server | Check `--url` (default `http://localhost:8989`) |
