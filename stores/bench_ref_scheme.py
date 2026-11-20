"""Read speed of the same virtual store with https:// versus s3:// chunk references (#40).

Scans the headers once, then builds two local Icechunk repos in <workdir> that differ only in
the recorded prefix and its container (pacioos_virtual.REF_SCHEME). Each workload is then timed
on both, alternating which goes first, each run on a freshly opened repo. One warm-up round is
dropped so a cache on the server side does not favour whichever goes second. Both schemes reach
the same host (data.source.coop), so the difference measured is the client path: icechunk's
HTTP store versus its S3 store with anonymous, path-style requests.

Run:  python -I bench_ref_scheme.py <workdir> [--reps 5] [--concurrency 64]
"""
import argparse
import shutil
import statistics
import sys
import time
from pathlib import Path

import icechunk
import numpy as np
import xarray as xr
import zarr

sys.path.insert(0, str(Path(__file__).parent))
import pacioos_virtual as pv

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("workdir", type=Path)
parser.add_argument("--reps", type=int, default=5)
parser.add_argument("--concurrency", type=int, default=64)
args = parser.parse_args()
zarr.config.set({"async.concurrency": args.concurrency})

def first_keys(prefix: str, n: int) -> list[str]:
    """The first n file names under prefix, from the listing (WW3 has missing days)."""
    from obstore.store import S3Store
    s3 = S3Store(pv.BUCKET, endpoint=pv.PUBLIC, region="us-east-1", skip_signature=True)
    keys = sorted(o["path"] for o in s3.list_with_delimiter(f"{pv.ROOT_PREFIX}/{prefix}")["objects"]
                  if o["path"].endswith(".nc"))
    return [k.removeprefix(pv.ROOT_PREFIX + "/") for k in keys[:n]]


PRODUCTS = {
    # name: (keys, step, variable, dims)
    "ww3_hawaii": (first_keys("ww3_hawaii/netcdf/2013/", 30), "1h", "Thgt", ("time", "z", "lat", "lon")),
    "roms_hiig_reanalysis": (first_keys("roms_hiig_reanalysis/netcdf/v2.0/2009/", 10), "3h", "temp",
                             ("time", "depth", "lat", "lon")),
}


def set_scheme(scheme: str) -> None:
    # Module globals are read at call time, so this switches builds and reader auth in-process.
    pv.REF_SCHEME = scheme
    pv.REF_PREFIX = pv.S3_PREFIX if scheme == "s3" else pv.URL_PREFIX


def build(path: Path, scans, best, var, dims, units) -> None:
    shutil.rmtree(path, ignore_errors=True)
    repo = icechunk.Repository.create(icechunk.local_filesystem_storage(str(path)),
                                      config=pv.repository_config(8760),
                                      authorize_virtual_chunk_access=pv.reader_authorization())
    repo.save_config()
    ds = xr.Dataset({var: pv.manifest_variable(var, scans, best, dims, {})},
                    coords={"time": ("time", best.index.values)})
    ds["time"].encoding = {"units": units, "dtype": "float64", "chunks": (len(best),)}
    session = repo.writable_session("main")
    ds.vz.to_icechunk(session.store)
    session.commit(f"bench {pv.REF_SCHEME}")
    locations = repo.readonly_session("main").all_virtual_chunk_locations()
    assert all(u.startswith(pv.REF_PREFIX) for u in locations)


def open_array(path: Path, var: str):
    repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(path)),
                                    authorize_virtual_chunk_access=pv.reader_authorization())
    return zarr.open_array(repo.readonly_session("main").store, path=var, mode="r")


def workloads(a):
    nt, nz, ny, nx = a.shape
    plane_mb = ny * nx * a.dtype.itemsize / 2**20
    return {
        # one chunk per step: many requests, the point-series pattern
        f"point series, {nt} steps": (lambda: a[:, 0, ny // 2, nx // 2], nt * plane_mb, nt),
        # every depth plane of one step: a map or profile
        f"one step, {nz} planes": (lambda: a[nt // 2], nz * plane_mb, nz),
        # a block of steps, all planes: bulk throughput
        f"{min(nt, 48)} steps x {nz} planes": (lambda: a[:min(nt, 48)], min(nt, 48) * nz * plane_mb,
                                                min(nt, 48) * nz),
    }


rows = []
for prod, (keys, step, var, dims) in PRODUCTS.items():
    t0 = time.time()
    scans = [pv.scan_nc3(k) if prod == "ww3_hawaii" else pv.scan_h5(k) for k in keys]
    best = pv.best_assignment(scans, step)
    units = scans[0]["vars"]["time"]["attrs"]["units"].replace(" UTC", "")
    for scheme in ("https", "s3"):
        set_scheme(scheme)
        build(args.workdir / f"{prod}-{scheme}", scans, best, var, dims, units)
    print(f"{prod}: scanned {len(keys)} files and built both repos in {time.time() - t0:.0f} s", flush=True)

    names = list(workloads(open_array(args.workdir / f"{prod}-https", var)))
    times = {(n, s): [] for n in names for s in ("https", "s3")}
    reference = {}
    for rep in range(args.reps + 1):
        order = ("https", "s3") if rep % 2 == 0 else ("s3", "https")
        for name in names:
            for scheme in order:
                set_scheme(scheme)
                a = open_array(args.workdir / f"{prod}-{scheme}", var)
                fn, mb, nreq = workloads(a)[name]
                t1 = time.perf_counter()
                got = fn()
                dt = time.perf_counter() - t1
                # Both schemes must return identical bytes, or the timing means nothing.
                if name in reference:
                    assert np.array_equal(got, reference[name], equal_nan=True), (prod, name, scheme)
                else:
                    reference[name] = got
                if rep:  # rep 0 is the warm-up
                    times[(name, scheme)].append(dt)
        print(f"  rep {rep} done", flush=True)
    for name in names:
        _, mb, nreq = workloads(open_array(args.workdir / f"{prod}-https", var))[name]
        h, s = (statistics.median(times[(name, x)]) for x in ("https", "s3"))
        rows.append(dict(product=prod, workload=name, chunks=nreq, MB=round(mb, 1),
                         https_s=round(h, 2), s3_s=round(s, 2), s3_over_https=round(s / h, 2),
                         https_MBps=round(mb / h), s3_MBps=round(mb / s),
                         https_runs=[round(x, 2) for x in times[(name, "https")]],
                         s3_runs=[round(x, 2) for x in times[(name, "s3")]]))
        print(rows[-1], flush=True)

import pandas as pd
table = pd.DataFrame(rows)
table.to_csv(args.workdir / "bench.csv", index=False)
print(table.drop(columns=["https_runs", "s3_runs"]).to_string(index=False))
