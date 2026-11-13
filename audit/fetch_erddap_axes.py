#!/usr/bin/env python
"""Fetch the time axis PacIOOS's ERDDAP serves for each product: four small requests.

ERDDAP's `roms_hiig`, `wrf_hi` and `ww3_hawaii` are THREDDS FMRC "best" series; the
reanalysis is a plain series. checks.py compares them with the time axes of the copies.
This is the only part of the audit that touches a PacIOOS server, and it asks for the time
coordinate only. Writes out/erddap_time_<id>.csv.

    python -I audit/fetch_erddap_axes.py
"""
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import OUT, PRODUCTS

ERDDAP = "https://pae-paha.pacioos.hawaii.edu/erddap/griddap/"
OUT.mkdir(exist_ok=True)
for ds in PRODUCTS:
    with urllib.request.urlopen(f"{ERDDAP}{ds}.csv?time", timeout=300) as r:
        (OUT / f"erddap_time_{ds}.csv").write_bytes(r.read())
    print(ds, "fetched")
    time.sleep(5)
