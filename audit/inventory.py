#!/usr/bin/env python
"""List every object under pacioos/ on Source Cooperative and parse its path and name.

Writes out/inventory.parquet: one row per object (NetCDF, .md5 sidecar, or anything else),
with product, version, year folder, name, date parsed from the name, size, ETag and upload time.

    python -I audit/inventory.py
"""
import re
import sys
from pathlib import Path

import obstore as obs
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import OUT, PATH_RE, PRODUCTS, ROOT, store

OUT.mkdir(exist_ok=True)
rows = []
for o in obs.list(store(), ROOT).collect():
    p = o["path"]
    m = PATH_RE.match(p)
    d = m.groupdict() if m else {"product": p.split("/")[1] if p.count("/") > 1 else None,
                                 "version": None, "year": None, "name": p.rsplit("/", 1)[-1]}
    kind = "md5" if p.endswith(".nc.md5") else "nc" if p.endswith(".nc") else "other"
    nc_name = d["name"][:-4] if kind == "md5" else d["name"]
    pat = PRODUCTS.get(d["product"], (None,))[0]
    dm = re.match(pat, nc_name) if pat else None
    rows.append(dict(path=p, kind=kind, layout_ok=bool(m), name_ok=bool(dm),
                     name_date=pd.Timestamp(dm.group(1)) if dm else pd.NaT, size=o["size"],
                     etag=(o.get("e_tag") or "").strip('"'), uploaded=o["last_modified"], **d))
inv = pd.DataFrame(rows)
inv.to_parquet(OUT / "inventory.parquet", index=False)
print(inv.groupby(["product", "kind"]).agg(n=("path", "size"), bytes=("size", "sum")).to_string())
