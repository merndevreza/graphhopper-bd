#!/usr/bin/env python3
"""Nearest-branch calculator for billing reports.

For every trip-end point, finds the nearest branch by actual road distance
using a locally running GraphHopper server (default http://localhost:8989).

Input CSVs:
  branches.csv: branch_id,name,lat,lon
  trips.csv:    trip_id,lat,lon

Usage:
  python3 helper/nearest_branch.py \
      --branches helper/branches.csv --trips helper/trips.csv \
      --profile car -o billing.csv

How it works:
  For each trip the K branches closest by straight line are routed against
  GraphHopper (default K=5) and the branch with the shortest ROAD distance
  wins. Pure stdlib, no pip installs. Trips that cannot be routed get the
  straight-line nearest branch and a note in the `error` column instead of
  failing the whole batch.

This is the reference implementation for the billing dashboard - the logic
is plain REST calls and ports to any language.
"""

import argparse
import csv
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

EARTH_RADIUS_M = 6371008.8


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points in meters."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


class RouteError(Exception):
    pass


def route(base_url, profile, start, end, timeout, retries=1):
    """Route start->end. Returns dict with distance_m, time_s, snap distances.

    start/end are (lat, lon) tuples. Raises RouteError on failure.
    """
    params = urllib.parse.urlencode({
        "point": [f"{start[0]},{start[1]}", f"{end[0]},{end[1]}"],
        "profile": profile,
        "points_encoded": "false",
        "instructions": "false",
        "locale": "en",
    }, doseq=True)  # doseq: 'point' is a list -> point=A&point=B
    url = f"{base_url}/route?{params}"
    last_err = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            path = data["paths"][0]
            coords = path["points"]["coordinates"]  # [[lon, lat], ...]
            # How far the raw GPS points were from the snapped road points -
            # a useful data-quality signal for trip-end locations.
            snap_start = haversine_m(start[0], start[1],
                                     coords[0][1], coords[0][0])
            snap_end = haversine_m(end[0], end[1],
                                   coords[-1][1], coords[-1][0])
            return {
                "distance_m": path["distance"],
                "time_s": path["time"] / 1000.0,
                "snap_start_m": snap_start,
                "snap_end_m": snap_end,
            }
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(0.5)
        except (KeyError, IndexError, ValueError) as e:
            raise RouteError(f"unexpected GraphHopper response: {e}") from e
    raise RouteError(str(last_err))


def get_col(row, *names):
    """Return the first matching, non-empty column value (case-insensitive)."""
    lowered = {k.strip().lower(): v for k, v in row.items() if k}
    for name in names:
        v = lowered.get(name)
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return None


def to_float(value, what):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"invalid {what}: {value!r}")


def load_csv(path, needed, what):
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except OSError as e:
        sys.exit(f"cannot read {what} file {path}: {e}")
    if not rows:
        sys.exit(f"{what} file {path} is empty")
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--branches", required=True,
                    help="CSV with columns: branch_id,name,lat,lon")
    ap.add_argument("--trips", required=True,
                    help="CSV with columns: trip_id,lat,lon")
    ap.add_argument("-o", "--output", default="billing.csv",
                    help="output CSV path (default: billing.csv)")
    ap.add_argument("--url", default="http://localhost:8989",
                    help="GraphHopper base URL (default: http://localhost:8989)")
    ap.add_argument("--profile", default="car", choices=["car", "motorcycle"],
                    help="routing profile (default: car)")
    ap.add_argument("-k", type=int, default=5,
                    help="route the K straight-line-nearest branches (default: 5)")
    ap.add_argument("--timeout", type=float, default=15,
                    help="per-request timeout in seconds (default: 15)")
    ap.add_argument("--workers", type=int, default=8,
                    help="parallel route requests (default: 8)")
    args = ap.parse_args()

    branch_rows = load_csv(args.branches, None, "branches")
    branches = []
    for i, row in enumerate(branch_rows, start=2):  # line numbers include header
        try:
            branches.append({
                "branch_id": get_col(row, "branch_id", "id") or f"row{i}",
                "name": get_col(row, "name", "branch_name") or "",
                "lat": to_float(get_col(row, "lat", "latitude"), "branch lat"),
                "lon": to_float(get_col(row, "lon", "longitude", "lng"), "branch lon"),
            })
        except ValueError as e:
            sys.exit(f"branches.csv line {i}: {e}")
    if not branches:
        sys.exit("no usable branch rows")

    trip_rows = load_csv(args.trips, None, "trips")
    trips = []
    for i, row in enumerate(trip_rows, start=2):
        try:
            trips.append({
                "line": i,
                "trip_id": get_col(row, "trip_id", "id") or f"row{i}",
                "lat": to_float(get_col(row, "lat", "latitude"), "trip lat"),
                "lon": to_float(get_col(row, "lon", "longitude", "lng"), "trip lon"),
            })
        except ValueError as e:
            print(f"WARNING: trips.csv line {i}: {e} - skipped", file=sys.stderr)
    if not trips:
        sys.exit("no usable trip rows")

    fields = ["trip_id", "trip_lat", "trip_lon",
              "branch_id", "branch_name", "branch_lat", "branch_lon",
              "route_km", "route_minutes", "straight_line_km",
              "snap_start_m", "snap_end_m", "profile", "error"]
    done = 0
    t0 = time.time()

    with open(args.output, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fields)
        writer.writeheader()

        for trip in trips:
            # 1) straight-line prefilter: K nearest branches by haversine
            ranked = sorted(
                branches,
                key=lambda b: haversine_m(trip["lat"], trip["lon"], b["lat"], b["lon"]),
            )
            candidates = ranked[: max(1, args.k)]
            straight_km = {
                b["branch_id"]: haversine_m(trip["lat"], trip["lon"],
                                            b["lat"], b["lon"]) / 1000.0
                for b in candidates
            }

            # 2) route to all candidates in parallel, keep the shortest road distance
            results = {}
            with ThreadPoolExecutor(max_workers=min(args.workers, len(candidates))) as pool:
                futures = {
                    pool.submit(route, args.url, args.profile,
                                (trip["lat"], trip["lon"]), (b["lat"], b["lon"]),
                                args.timeout): b
                    for b in candidates
                }
                for fut, b in futures.items():
                    try:
                        results[b["branch_id"]] = fut.result()
                    except RouteError as e:
                        results[b["branch_id"]] = {"error": str(e)}

            row = {
                "trip_id": trip["trip_id"],
                "trip_lat": trip["lat"],
                "trip_lon": trip["lon"],
                "profile": args.profile,
                "error": "",
            }
            ok = {bid: r for bid, r in results.items() if "error" not in r}
            if ok:
                best = min(ok.items(), key=lambda kv: kv[1]["distance_m"])
                branch = next(b for b in branches if b["branch_id"] == best[0])
                r = best[1]
                row.update({
                    "branch_id": branch["branch_id"],
                    "branch_name": branch["name"],
                    "branch_lat": branch["lat"],
                    "branch_lon": branch["lon"],
                    "route_km": round(r["distance_m"] / 1000.0, 3),
                    "route_minutes": round(r["time_s"] / 60.0, 1),
                    "straight_line_km": round(straight_km[best[0]], 3),
                    "snap_start_m": round(r["snap_start_m"], 1),
                    "snap_end_m": round(r["snap_end_m"], 1),
                })
            else:
                # nothing routable: fall back to the straight-line nearest branch
                fb = candidates[0]
                reasons = "; ".join(f"{bid}: {r['error']}"
                                    for bid, r in results.items())
                row.update({
                    "branch_id": fb["branch_id"],
                    "branch_name": fb["name"],
                    "branch_lat": fb["lat"],
                    "branch_lon": fb["lon"],
                    "straight_line_km": round(straight_km[fb["branch_id"]], 3),
                    "error": f"routing failed ({reasons})",
                })
            writer.writerow(row)

            done += 1
            if done % 100 == 0 or done == len(trips):
                rate = done / max(time.time() - t0, 0.001)
                print(f"  {done}/{len(trips)} trips ({rate:.0f} trips/s)",
                      file=sys.stderr)

    print(f">> wrote {args.output} ({len(trips)} trips, "
          f"{len(branches)} branches, profile={args.profile})")


if __name__ == "__main__":
    main()
