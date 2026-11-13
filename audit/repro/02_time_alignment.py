#!/usr/bin/env python
"""Are a file's time labels right? Compare it with its neighbours at matched valid times.

Two forecasts of the same valid time are close; the same forecast compared with a neighbour
shifted by a day is much less close. So for a suspect file E and a neighbouring run D, the RMS
difference of the surface field at matched valid times should be smallest at a shift of 0 h.
If it is smallest at -24 h or +24 h, E's labels are off by that much.

Suspects (from checks.py): WW3 files whose first step is a day before their name date
(2020-04-27 .. 2020-05-04), the WW3 pair that starts at the same time (2020-04-26/27), the
WW3 files PacIOOS shifted by +1440 min in 2024 (history: `ncap2 -s time[time]=time+1440`),
and the WRF pair 2022-02-21/22 that starts at the same time with different data.

    python -I audit/repro/02_time_alignment.py
"""
import json
import sys
from pathlib import Path

import fsspec
import h5py
import numpy as np
import obstore as obs
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))
from common import OUT, URL, store

st = store()
heads = {}
for line in (OUT / "headers.jsonl").open():
    h = json.loads(line)
    heads[h["path"].rsplit("/", 1)[-1]] = h


def series(name, var):
    """(valid times, stack of planes) for one file."""
    h = heads[name]
    unit, since = h["time_units"].split(" since ")
    if h["format"] == "hdf5":
        with fsspec.filesystem("https").open(URL + h["path"], "rb", block_size=2**22, cache_type="blockcache") as f, h5py.File(f) as hf:
            t = hf["time"][:]
            data = hf[var][:].reshape(len(t), -1)
    else:
        v = h["vars"][var]
        n = v["shape"][0]
        plane = int(np.prod(v["shape"][1:])) * 4
        if v["record"]:
            starts = [v["begin"] + i * h["recsize"] for i in range(n)]
            data = np.stack([np.frombuffer(bytes(b), ">f4") for b in obs.get_ranges(st, h["path"], starts=starts, lengths=[plane] * n)])
            tv = h["vars"]["time"]
            raw = obs.get_ranges(st, h["path"], starts=[tv["begin"] + i * h["recsize"] for i in range(n)], lengths=[4] * n)
            t = np.array([np.frombuffer(bytes(b), tv["dtype"])[0] for b in raw])
        else:
            data = np.frombuffer(bytes(obs.get_range(st, h["path"], start=v["begin"], length=v["vsize"])), ">f4")[: n * plane // 4]
            t = np.array(h["time"]["values"])
        data = data.reshape(n, -1)
    tt = pd.Timestamp(since.replace(" UTC", "")) + pd.to_timedelta(np.asarray(t, "f8"), unit={"hours": "h", "minutes": "min"}[unit])
    data = np.where((data < -900) | (data > 1e4), np.nan, data.reshape(len(tt), -1))
    return pd.DatetimeIndex(tt), data


def rms_by_shift(e, d, var, shifts=(-48, -24, 0, 24, 48)):
    te, xe = series(e, var)
    td, xd = series(d, var)
    out = {}
    for s in shifts:
        t = te + pd.Timedelta(hours=s)
        common, ie, id_ = np.intersect1d(t.values, td.values, return_indices=True)
        # skip each run's first 12 h (spin-up) so a cold start does not dominate
        keep = [k for k in range(len(common)) if ie[k] >= 12 and id_[k] >= 12]
        if len(keep) < 12:
            out[s] = None
            continue
        diff = xe[ie[keep]] - xd[id_[keep]]
        out[s] = round(float(np.sqrt(np.nanmean(diff ** 2))), 4)
    ok = [k for k in out if out[k] is not None]
    return out, (min(ok, key=lambda k: out[k]) if ok else None)


# each suspect against a neighbour whose labels test right, on both sides where possible
cases = [("ww3hawaii_20200426.nc", "ww3hawaii_20200425.nc", "Thgt")]
cases += [(f"ww3hawaii_202004{d}.nc", "ww3hawaii_20200426.nc", "Thgt") for d in ("27", "28", "29", "30")]
cases += [(f"ww3hawaii_202005{d}.nc", "ww3hawaii_20200426.nc", "Thgt") for d in ("01", "02", "03", "04")]
cases += [(f"ww3hawaii_202004{d}.nc", "ww3hawaii_20200505.nc", "Thgt") for d in ("29", "30")]
cases += [(f"ww3hawaii_202005{d}.nc", "ww3hawaii_20200505.nc", "Thgt") for d in ("01", "02", "03", "04")]
cases += [("ww3hawaii_20240301.nc", "ww3hawaii_20240229.nc", "Thgt"), ("ww3hawaii_20240318.nc", "ww3hawaii_20240319.nc", "Thgt"),
          ("ww3hawaii_20240319.nc", "ww3hawaii_20240318.nc", "Thgt")]
cases += [("wrf_hi_20220221.nc", "wrf_hi_20220219.nc", "Tair"), ("wrf_hi_20220222.nc", "wrf_hi_20220219.nc", "Tair"),
          ("wrf_hi_20220221.nc", "wrf_hi_20220223.nc", "Tair"), ("wrf_hi_20220222.nc", "wrf_hi_20220223.nc", "Tair")]
for e, d, var in cases:
    if e not in heads or d not in heads:
        print(e, d, "missing"); continue
    out, best = rms_by_shift(e, d, var)
    verdict = "no overlap" if best is None else "labels right" if best == 0 else f"labels {-best:+d} h from the data"
    print(f"{e} vs {d} ({var}) RMS by shift {out} -> {verdict}")
