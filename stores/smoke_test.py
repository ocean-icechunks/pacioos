"""Tiny smoke test: a 'best' virtual store per product, in local repos, reopened read-only, values checked.

Builds a few runs of each product into <workdir>/<product> (local Icechunk repos; nothing is
written to Source Cooperative), reopens each in a fresh read-only session with anonymous HTTPS
access to the copies, and compares sampled planes with netCDF-C's own byte-range reads.

Run:  python -I smoke_test.py <workdir>     (about 1 minute; see stores/README.md)
      python -I smoke_test.py <workdir> --wrf-era2
"""
import argparse
import shutil, sys, time
from pathlib import Path

import icechunk
import netCDF4
import numpy as np
import pandas as pd
import xarray as xr
import zarr

sys.path.insert(0, str(Path(__file__).parent))
import pacioos_virtual as pb

zarr.config.set({"async.concurrency": 64})
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("workdir", type=Path)
parser.add_argument("--wrf-era2", action="store_true", help="Test the single-group WRF HDF5 series only")
args = parser.parse_args()
WORK = args.workdir

WRF_ERA2_RUNS = ("20170816", "20170817", "20190429", "20220221", "20220222")

PRODUCTS = {
    # name: (keys oldest->newest, step, science vars, time_chunks_per_manifest)
    "roms_hiig": ([f"roms_hiig/netcdf/2026/hiig_forec_202610{d}.nc" for d in ("06", "08", "09")],
                  "3h", ["temp", "salt", "u", "v", "zeta"], 2920),
    "roms_hiig_reanalysis": ([f"roms_hiig_reanalysis/netcdf/v2.0/2009/hiig_his_zlevel_2009010{d}.nc" for d in (1, 2)],
                             "3h", ["temp", "salt", "u", "v", "zeta"], 2920),
    "ww3_hawaii": ([f"ww3_hawaii/netcdf/2013/ww3hawaii_201308{d}.nc" for d in (14, 15, 16, 17)],
                   "1h", ["Thgt", "Tper", "Tdir", "shgt", "sper", "sdir", "whgt", "wper", "wdir"], 8760),
    "wrf_hi": ([f"wrf_hi/netcdf/{date[:4]}/wrf_hi_{date}.nc" for date in WRF_ERA2_RUNS],
               "1h", ["Tair", "Pair", "rain", "Uwind", "Vwind", "lwrad_down", "swrad", "Qair"], 8760),
}

WRF_DUPLICATE_HOUR = pd.Timestamp("2019-05-06T00:00")
WRF_TIE_HOUR = pd.Timestamp("2022-02-23T00:00")


def check_wrf_era2_assignment(scans: list[dict], best: pd.DataFrame) -> None:
    """Check source anomalies and the selected original file indices."""
    first, second = scans[-2:]
    assert first["time"][0] == second["time"][0]
    assert best.loc[WRF_TIE_HOUR, "run"] == len(scans) - 1
    repeated = np.flatnonzero(scans[2]["time"] == WRF_DUPLICATE_HOUR)
    assert len(repeated) == 2
    assert best.index.is_unique
    assert best.loc[WRF_DUPLICATE_HOUR, "run"] == 2
    assert best.loc[WRF_DUPLICATE_HOUR, "lead"] in repeated


def scan(key: str, *, strict_chunks: bool = False) -> dict:
    import fsspec
    magic = fsspec.filesystem("https").cat_file(pb.URL_PREFIX + key, start=0, end=4)
    return pb.scan_nc3(key) if magic[:3] == b"CDF" else pb.scan_h5(key, strict_chunks=strict_chunks)


def build_group(scans, best, sci, dims_of, time_units):
    s0 = scans[int(best["run"][best["run"] >= 0].iloc[0])]
    coords = {c: v for c, v in s0["coords"].items() if c != "mask"}
    data = {}
    used = sorted(set(int(r) for r in best["run"] if r >= 0))
    for name in sci:
        if not any(name in scans[r]["vars"] for r in used):
            continue
        attrs = {k: v for k, v in next(s for s in scans if name in s["vars"])["vars"][name]["attrs"].items()}
        attrs = {k: (v.item() if hasattr(v, "item") and np.ndim(v) == 0 else (v.tolist() if hasattr(v, "tolist") else v))
                 for k, v in attrs.items() if k not in ("_FillValue", "coordinates", "time")}
        fv = next(s for s in scans if name in s["vars"])["vars"][name]["attrs"].get("_FillValue")
        if fv is not None:
            attrs["missing_value"] = float(fv)
        data[name] = pb.manifest_variable(name, scans, best, dims_of(name, s0), attrs)
    ds = xr.Dataset(data, coords={**{c: (c, v) for c, v in coords.items()}, "time": ("time", best.index.values)})
    if "mask" in s0["coords"]:
        ds["mask"] = (("lat", "lon"), s0["coords"]["mask"])
    # auxiliary coordinates: which run each valid time came from, and its lead
    run_t = np.array([scans[r]["time"][0] if r >= 0 else pd.NaT for r in best["run"]], "datetime64[ns]")
    ds = ds.assign_coords(
        forecast_reference_time=("time", run_t, {"standard_name": "forecast_reference_time"}),
        forecast_period=("time", (best.index.values - run_t).astype("timedelta64[m]").astype("f8") / 60,
                         {"standard_name": "forecast_period", "units": "hours"}))
    for c in ("time", "forecast_reference_time"):
        ds[c].encoding = {"units": time_units, "dtype": "float64", "chunks": (len(best),)}
    ds["forecast_period"].encoding = {"chunks": (len(best),)}
    return ds


def dims_of(name, s):
    v = s["vars"][name]
    if s["format"] == "nc3":
        d = tuple(v["dims"])
        return ("time", "depth", "lat", "lon") if d == ("time", "depth", "lat", "lon") else ("time", "lat", "lon") if len(d) == 3 else d
    return ("time", "depth", "lat", "lon") if len(v["shape"]) == 4 else ("time", "lat", "lon")


def ww3_dims(name, s):
    return ("time", "z", "lat", "lon")


def reference(key, name, lead, k=0):
    """Independent read: netCDF-C over HTTPS byte ranges."""
    with netCDF4.Dataset(pb.URL_PREFIX + key + "#mode=bytes") as nc:
        v = nc[name]
        v.set_auto_maskandscale(False)
        return np.asarray(v[lead, k] if v.ndim == 4 else v[lead])


report = []
if args.wrf_era2:
    PRODUCTS = {"wrf_hi": PRODUCTS["wrf_hi"]}

for prod, (keys, step, sci, split) in PRODUCTS.items():
    t0 = time.time()
    scans = [scan(k, strict_chunks=prod == "wrf_hi") for k in keys]
    best = pb.best_assignment(scans, step)
    if prod == "wrf_hi":
        assert all(s["format"] == "hdf5" for s in scans)
        best = best.loc[best["run"] >= 0]
        check_wrf_era2_assignment(scans, best)
    groups = {"": best}
    units = scans[0]["vars"]["time"]["attrs"]["units"].replace(" UTC", "")
    path = WORK / ("wrf_hi_era2" if args.wrf_era2 else prod)
    shutil.rmtree(path, ignore_errors=True)
    repo = icechunk.Repository.create(icechunk.local_filesystem_storage(str(path)), config=pb.repository_config(split),
                                      authorize_virtual_chunk_access=pb.reader_authorization())
    repo.save_config()
    for g, b in groups.items():
        session = repo.writable_session("main")
        ds = build_group(scans, b, sci, ww3_dims if prod == "ww3_hawaii" else dims_of, units)
        ds.vz.to_icechunk(session.store, group=g or None)
        session.commit(f"smoke {prod} {g}")
    build_s = time.time() - t0

    # ---- reopen fresh, read-only, as a reader would
    repo2 = icechunk.Repository.open(icechunk.local_filesystem_storage(str(path)),
                                     authorize_virtual_chunk_access=pb.reader_authorization())
    ro = repo2.readonly_session("main")
    for g, b in groups.items():
        t1 = time.time()
        ds = xr.open_zarr(ro.store, group=g or None, consolidated=False, chunks={}, mask_and_scale=False, decode_times=True)
        open_s = time.time() - t1
        name = [n for n in sci if n in ds][0]
        checked, bad = 0, 0
        # pick steps: first, every run start, a gap if any, last
        picks = sorted(set([0, len(b) - 1] + [int(i) for i in np.where(b["lead"].to_numpy() == 0)[0]]
                           + [int(i) for i in np.where(b["run"].to_numpy() < 0)[0][:1]]))
        if prod == "wrf_hi":
            assert ds.indexes["time"].equals(b.index)
            assert set(ds.data_vars) == set(sci)
            assert ds[name].encoding["chunks"] == (1, 138, 213)
            picks = sorted(set(picks) | set(b.index.get_indexer([WRF_DUPLICATE_HOUR, WRF_TIE_HOUR])))
        for i in picks:
            r, l = int(b["run"].iloc[i]), int(b["lead"].iloc[i])
            k = 0
            got = ds[name].isel(time=i).values
            got = got[k] if got.ndim == 3 else got
            if r < 0:
                ok = np.isnan(got).all()
            else:
                exp = reference(scans[r]["key"], name, l, k)
                exp = exp[0] if exp.ndim == 3 else exp
                ok = np.array_equal(got, exp, equal_nan=True)
            checked += 1; bad += (not ok)
        # deeper level for 4-D vars, from a middle step
        if ds[name].ndim == 4 and ds.sizes.get("depth", 1) > 1:
            i = len(b) // 2; r, l = int(b["run"].iloc[i]), int(b["lead"].iloc[i])
            if r >= 0:
                ok = np.array_equal(ds[name].isel(time=i, depth=20).values, reference(scans[r]["key"], name, l, 20), equal_nan=True)
                checked += 1; bad += (not ok)
        n_gap = int((b["run"] < 0).sum())
        report.append(dict(product=prod, group=g or "/", nt=len(b), t0=str(b.index[0]), t1=str(b.index[-1]), gap_steps=n_gap,
                           vars=len([v for v in sci if v in ds]), checked=checked, mismatches=bad,
                           build_s=round(build_s, 1), open_s=round(open_s, 2)))
        print(report[-1], flush=True)
        if prod == "roms_hiig" and g == "":
            print(ds[["forecast_reference_time", "forecast_period"]].sel(time=["2026-10-07T21:00", "2026-10-08T00:00", "2026-10-09T12:00"]).to_dataframe())
        if prod == "wrf_hi":
            print("   ", g, "runs used:", sorted(set(pd.to_datetime(ds.forecast_reference_time.values).dropna().astype(str))))

pd.DataFrame(report).to_csv(WORK / "report.csv", index=False)
if any(row["mismatches"] for row in report):
    raise SystemExit("Smoke test found data mismatches")
