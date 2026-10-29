#!/usr/bin/env python3
"""Segmented parallel downloader for the Bangladesh OSM extract.

Geofabrik throttles single connections (~30 KB/s from some regions) but
supports HTTP range requests, so we fetch 16 segments in parallel.
Stdlib only. Verifies the final size before declaring success.
"""

import os
import sys
import threading
import time
import urllib.request

URL = "https://download.geofabrik.de/asia/bangladesh-latest.osm.pbf"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "bangladesh-latest.osm.pbf")
SEGMENTS = 16
CHUNK = 1024 * 1024  # read chunks of 1 MB per request


def head_size(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=30) as r:
        return int(r.headers["Content-Length"])


def fetch_range(url, start, end, fd, offset, progress, lock):
    """Download bytes [start, end] into fd at offset. Retries with resume."""
    pos = start
    while pos <= end:
        req = urllib.request.Request(url, headers={"Range": f"bytes={pos}-{end}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                while pos <= end:
                    data = r.read(CHUNK)
                    if not data:
                        break
                    fd.write(data, offset + (pos - start))
                    pos += len(data)
                    with lock:
                        progress[0] += len(data)
        except OSError:
            time.sleep(2)  # retry remaining range from where it stopped


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    total = head_size(URL)
    print(f"total: {total/1048576:.0f} MB, {SEGMENTS} parallel segments", flush=True)

    # preallocate the file
    with open(OUT, "wb") as f:
        f.truncate(total)

    bounds = [ (i * total) // SEGMENTS for i in range(SEGMENTS + 1) ]
    fd = os.open(OUT, os.O_WRONLY)
    fh = os.fdopen(fd, "rb+", buffering=0)
    fh.write = lambda data, off: os.pwrite(fd, data, off)

    progress = [0]
    lock = threading.Lock()
    threads = []
    for i in range(SEGMENTS):
        t = threading.Thread(
            target=fetch_range,
            args=(URL, bounds[i], bounds[i + 1] - 1, fh, bounds[i], progress, lock),
            daemon=True,
        )
        t.start()
        threads.append(t)

    t0 = time.time()
    while any(t.is_alive() for t in threads):
        time.sleep(5)
        done = progress[0]
        rate = done / max(time.time() - t0, 0.1) / 1048576
        print(f"  {done/1048576:.0f}/{total/1048576:.0f} MB  ({rate:.1f} MB/s)", flush=True)
    for t in threads:
        t.join()

    actual = os.path.getsize(OUT)
    if actual != total:
        sys.exit(f"SIZE MISMATCH: got {actual}, expected {total} - rerun this script")
    print(f"DONE: {actual} bytes in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
