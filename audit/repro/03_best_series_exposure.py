#!/usr/bin/env python
"""How many steps of each "best" series come from a problem run.

Rebuilds the THREDDS best assignment from the run start and end of every copy (newest run
start wins; where two runs start at the same time, the later file name wins, which is what
ERDDAP serves for wrf_hi 2022-02-21/22) and counts the valid times taken from:

- WRF relabelled copies (out/wrf_repeated_runs.csv, from 01_wrf_repeated_runs.py);
- WW3 files 2020-04-27..05-04, whose labels test one day early (02_time_alignment.py);
- WW3 cold starts: runs whose first step is an all-zero wave field (lead 0 wins in best).

    python -I audit/repro/03_best_series_exposure.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))
from common import OUT, PRODUCTS

runs = pd.read_csv(OUT / "runs.csv")
for c in ("run_start", "run_end", "name_date"):
    runs[c] = pd.to_datetime(runs[c], format="mixed")
runs["name"] = runs.path.str.rsplit("/", n=1).str[-1]
vals = pd.read_parquet(OUT / "values.parquet").set_index("path")
rep = pd.read_csv(OUT / "wrf_repeated_runs.csv")
bad = {"wrf_hi": set(rep[rep.kind.str.startswith("relabelled")].file),
       "ww3_hawaii": {f"ww3hawaii_2020{d}.nc" for d in ("0427", "0428", "0429", "0430", "0501", "0502", "0503", "0504")}}
cold = set(runs.set_index("path").join(vals).query("product == 'ww3_hawaii' and first_std == 0").name)

for p in ("wrf_hi", "ww3_hawaii"):
    g = runs[runs["product"] == p].sort_values(["run_start", "name"])
    step = pd.Timedelta(minutes=PRODUCTS[p][1])
    owner = {}
    for _, r in g.iterrows():  # later rows (newer start, or same start and later name) overwrite
        for t in pd.date_range(r.run_start, r.run_end, freq=step):
            owner[t] = r["name"]
    s = pd.Series(owner).sort_index()
    from_bad = s.isin(bad[p])
    print(f"{p}: best series {len(s)} steps; {int(from_bad.sum())} steps ({from_bad.mean():.2%}) come from "
          f"{s[from_bad].nunique()} suspect runs; years {sorted(set(s[from_bad].index.year))}")
    if p == "ww3_hawaii":
        lead0 = [t for t, n in s.items() if n in cold and t == g.set_index("name").at[n, "run_start"]]
        print(f"  cold starts: {len(cold)} runs; {len(lead0)} best-series steps are an all-zero wave field (lead 0)")
