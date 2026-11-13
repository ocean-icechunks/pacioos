#!/usr/bin/env python
"""WRF: runs whose data repeat an earlier run, and whether the repeat keeps the right times.

From out/values.parquet: a file whose first (or last) `Tair` plane is byte-identical to the
first (or last) plane of an earlier file. For each such pair, compare the shift in the data
with the shift in the time labels:

- relabelled copy: the data are the earlier run's, unshifted, but labelled later. Every valid
  time in the later file carries data from a different time. Wrong.
- fallback tail: the later file is the earlier run from some lead on, with matching times.
  The values are right for their times; the "run" is just not a new forecast.

The first case is confirmed for three pairs by reading every step (full Tair block, ~20 MB per file).

    python -I audit/repro/01_wrf_repeated_runs.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import obstore as obs
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))
from common import OUT, store

runs = pd.read_csv(OUT / "runs.csv")
for c in ("run_start", "run_end", "name_date"):
    runs[c] = pd.to_datetime(runs[c], format="mixed")
v = pd.read_parquet(OUT / "values.parquet").set_index("path")
r = runs.set_index("path").join(v)
r = r[r["product"] == "wrf_hi"].sort_values("name_date")
r["name"] = r.index.str.rsplit("/", n=1).str[-1]

rows = []
for tag, tcol in (("first", "run_start"), ("last", "run_end")):
    for h, g in r[r[f"{tag}_hash"].duplicated(keep=False)].groupby(f"{tag}_hash"):
        g = g.sort_values("name_date")
        base = g.iloc[0]
        for _, x in g.iloc[1:].iterrows():
            rows.append(dict(file=x["name"], repeats=base["name"], plane=tag,
                             label_shift_h=(x[tcol] - base[tcol]).total_seconds() / 3600))
pairs = pd.DataFrame(rows).drop_duplicates(["file", "repeats"])
# a pair sharing a plane with a label shift is a relabelled copy; zero shift on the last plane is a fallback tail
pairs["kind"] = np.where(pairs.label_shift_h != 0, "relabelled copy (wrong times)", "fallback tail (times right)")
pairs.to_csv(OUT / "wrf_repeated_runs.csv", index=False)
print(pairs.groupby("kind").agg(files=("file", "nunique"), first=("file", "min"), last=("file", "max")).to_string())
bad = pairs[pairs.kind.str.startswith("relabelled")]
print("label shifts (h):", bad.label_shift_h.value_counts().to_dict())
print("relabelled files by year:", bad.file.str[7:11].value_counts().sort_index().to_dict())

# confirm three pairs step by step
heads = {}
want = {"wrf_hi_20110915.nc", "wrf_hi_20110916.nc", "wrf_hi_20110326.nc", "wrf_hi_20110327.nc",
        "wrf_hi_20140312.nc", "wrf_hi_20140313.nc"}
for line in (OUT / "headers.jsonl").open():
    h = json.loads(line)
    if h["path"].rsplit("/", 1)[-1] in want:
        heads[h["path"].rsplit("/", 1)[-1]] = h
st = store()


def block(name):
    h = heads[name]
    t = h["vars"]["Tair"]
    b = bytes(obs.get_range(st, h["path"], start=t["begin"], length=t["vsize"]))
    return np.frombuffer(b, ">f4")[: t["shape"][0] * 138 * 213].reshape(-1, 138, 213)


for d0, d1 in (("wrf_hi_20110915.nc", "wrf_hi_20110916.nc"), ("wrf_hi_20110326.nc", "wrf_hi_20110327.nc"),
               ("wrf_hi_20140312.nc", "wrf_hi_20140313.nc")):
    a, b = block(d0), block(d1)
    idx = {x.tobytes(): i for i, x in enumerate(a)}
    m = [idx.get(x.tobytes()) for x in b]
    shift = (runs.set_index(runs.path.str.rsplit("/", n=1).str[-1]).loc[[d0, d1], "run_start"].diff().iloc[-1])
    print(f"{d1}: {sum(i is not None for i in m)}/{len(b)} steps identical to {d0} steps {m[0]}..{m[-1]}; "
          f"labels start {shift} later -> data offset {m[0]} h vs label offset {shift.total_seconds() / 3600:.0f} h")
