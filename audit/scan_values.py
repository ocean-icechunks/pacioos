#!/usr/bin/env python
"""Read two small data planes from every NetCDF: the first and last time step of one variable.

The only data the audit reads (about 4 GB in all). It catches what headers cannot: runs that
are blank, all fill, constant, stuck (last step equal to the first), implausible, or byte-for-
byte duplicates of another day's run. The plane is the top level of `temp` (ROMS), `Tair`
(WRF) or `Thgt` (WW3), located from the offsets in out/headers.jsonl.

Writes out/values.parquet.

    python -I audit/scan_values.py
"""
import asyncio
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import obstore as obs
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import OUT, PRODUCTS, store

# plausible range of the sampled variable, and the land/missing value written in the files
PLAUSIBLE = {"temp": (-2.5, 40.0), "Tair": (-40.0, 50.0), "Thgt": (0.0, 60.0)}
FILLS = (9.99e10, 9.969209968386869e36, -999.0, 99999.0)


def planes(h: dict, var: str):
    """(offset, nbytes, dtype) of the top plane of `var` at the first and last step."""
    v = h["vars"][var]
    ny, nx = v["shape"][-2:]
    dtype = v["dtype"]
    plane = ny * nx * np.dtype(dtype).itemsize
    nt = v["shape"][0]
    if h["format"].startswith("nc3"):
        if v["record"]:
            offs = [v["begin"], v["begin"] + (nt - 1) * h["recsize"]]
        else:
            per_step = plane * (v["shape"][1] if len(v["shape"]) == 4 else 1)
            offs = [v["begin"], v["begin"] + (nt - 1) * per_step]
    else:
        ci = v["chunk_index"]
        offs = [ci["first_offset"], ci["last_offset"]]
    return offs, plane, dtype, (ny, nx)


def stats(a: np.ndarray, var: str) -> dict:
    lo, hi = PLAUSIBLE[var]
    fill = np.isin(a, np.array(FILLS, a.dtype)) | ~np.isfinite(a)
    good = a[~fill]
    return {"n": int(a.size), "n_fill": int(fill.sum()), "n_zero": int((a == 0).sum()),
            "min": float(good.min()) if good.size else None, "max": float(good.max()) if good.size else None,
            "std": float(good.std()) if good.size else None,
            "n_out_of_range": int(((good < lo) | (good > hi)).sum()),
            "hash": hashlib.md5(a.tobytes()).hexdigest()[:16]}


async def main():
    st = store()
    heads = [json.loads(line) for line in (OUT / "headers.jsonl").open()]
    heads = [h for h in heads if "error" not in h]
    sem = asyncio.Semaphore(32)

    async def one(h):
        product = h["path"].split("/")[1]
        var = PRODUCTS[product][2]
        offs, n, dtype, shape = planes(h, var)
        async with sem:
            bufs = await obs.get_ranges_async(st, h["path"], starts=offs, lengths=[n, n])
        out = {"path": h["path"], "var": var}
        for tag, b in zip(("first", "last"), bufs):
            a = np.frombuffer(bytes(b), dtype).astype("float32").reshape(shape)
            out.update({f"{tag}_{k}": x for k, x in stats(a, var).items()})
        return out

    rows = await asyncio.gather(*(one(h) for h in heads))
    df = pd.DataFrame(rows).sort_values("path")
    df.to_parquet(OUT / "values.parquet", index=False)
    print(len(df), "files")


asyncio.run(main())
