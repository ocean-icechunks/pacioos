#!/usr/bin/env python
"""Read the header of every NetCDF in the inventory: metadata and small coordinates, no data.

Writes one JSON line per file to out/headers.jsonl. Re-running skips files already recorded,
so a dropped connection costs one file, not the run.

Per file: format (magic number), size the header implies, global attributes, and per variable
dims, shape, dtype (with byte order), attributes and storage. NetCDF-3: `begin`, `vsize`,
record or fixed. HDF5: chunks, filters, fill value, and a summary of the chunk index
(allocated count, distinct sizes, whether offsets are evenly spaced, first and last offset).

Time: every value for HDF5 files and fixed-dimension NetCDF-3 files. For record (UNLIMITED)
NetCDF-3 files, whose time values are scattered one per record, the first, second and last
value, and every value for one file in FULL_TIME_EVERY plus any file with an unusual record count.

Coordinates: lat/lon/depth/z values, and a hash and land count of `mask`.

    python -I audit/scan_headers.py [--threads 32] [--procs 6] [--limit N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import OUT, URL, nc3_expected_size, parse_nc3, store

HEADERS = OUT / "headers.jsonl"
FULL_TIME_EVERY = 25
USUAL_NUMRECS = {57, 181}
COORDS = ("lat", "lon", "depth", "z")


def _js(x):
    if isinstance(x, bytes):
        return x.decode("utf-8", "replace")
    if isinstance(x, np.ndarray):
        return x.tolist() if x.size <= 64 else f"<array {x.shape} {x.dtype}>"
    if isinstance(x, np.generic):
        x = x.item()
    if isinstance(x, float) and not np.isfinite(x):
        return str(x)
    if isinstance(x, (list, tuple)):
        return [_js(v) for v in x]
    return x


def _hash(a: np.ndarray) -> str:
    return hashlib.md5(np.ascontiguousarray(a).tobytes()).hexdigest()[:12]


# ------------------------------------------------------------------ NetCDF-3

def scan_nc3(st, key: str, i: int, size: int) -> dict:
    import obstore as obs

    n = 65536
    while True:
        buf = bytes(obs.get_range(st, key, start=0, length=min(n, size)))
        try:
            h = parse_nc3(buf)
            break
        except EOFError:
            if n >= size:
                raise
            n *= 4
    v = h["variables"]
    rec = {"format": f"nc3-cdf{h['version']}", "numrecs": h["numrecs"], "recsize": h["recsize"],
           "header_len": h["header_len"], "expected_size": nc3_expected_size(h),
           "dims": h["dims"], "attrs": {k: _js(a) for k, a in h["attrs"].items()},
           "vars": {k: {kk: (_js(vv) if kk != "attrs" else {a: _js(b) for a, b in vv.items()})
                        for kk, vv in x.items()} for k, x in v.items()}}
    # time values
    t = v["time"]
    itemsize = np.dtype(t["dtype"]).itemsize
    if t["record"]:
        nrec = h["numrecs"]
        full = (i % FULL_TIME_EVERY == 0) or nrec not in USUAL_NUMRECS
        idx = list(range(nrec)) if full else sorted({0, min(1, nrec - 1), nrec - 1})
        starts = [t["begin"] + r * h["recsize"] for r in idx]
        raw = obs.get_ranges(st, key, starts=starts, lengths=[itemsize] * len(starts))
        vals = [np.frombuffer(bytes(b), t["dtype"])[0].item() for b in raw]
        rec["time"] = {"index": idx, "values": vals, "full": full}
    else:
        raw = bytes(obs.get_range(st, key, start=t["begin"], length=t["vsize"]))
        vals = np.frombuffer(raw[: t["shape"][0] * itemsize], t["dtype"]).tolist()
        rec["time"] = {"index": list(range(len(vals))), "values": vals, "full": True}
    rec["time_units"] = t["attrs"].get("units")
    # coordinates
    rec["coords"] = {}
    for c in COORDS + ("mask",):
        if c in v and not v[c]["record"]:
            cv = v[c]
            nbytes = int(np.prod(cv["shape"])) * np.dtype(cv["dtype"]).itemsize
            a = np.frombuffer(bytes(obs.get_range(st, key, start=cv["begin"], length=nbytes)), cv["dtype"])
            rec["coords"][c] = ({"hash": _hash(a.astype(a.dtype.newbyteorder("="))), "n_zero": int((a == 0).sum()), "n": int(a.size)}
                                if c == "mask" else {"hash": _hash(a.astype(a.dtype.newbyteorder("="))), "first": a[0].item(),
                                                     "last": a[-1].item(), "n": int(a.size)})
    return rec


# ------------------------------------------------------------------ HDF5

def _h5_chunks(d) -> dict:
    """Summary of a chunked dataset's chunk index, using h5py's fast chunk_iter."""
    infos = []
    d.id.chunk_iter(lambda c: infos.append((c.chunk_offset, c.byte_offset, c.size)))
    infos.sort()
    expected = int(np.prod([-(-s // c) for s, c in zip(d.shape, d.chunks)]))
    offs = np.array([x[1] for x in infos], "int64")
    sizes = sorted({x[2] for x in infos})
    stride = sorted({int(s) for s in np.diff(offs)}) if len(offs) > 1 else []
    return {"n_chunks": len(infos), "expected_chunks": expected, "chunk_sizes": sizes[:5],
            "stride": stride[:5], "first_offset": int(offs[0]) if len(offs) else None,
            "last_offset": int(offs[-1]) if len(offs) else None,
            "max_end": int(max(x[1] + x[2] for x in infos)) if infos else None}


def scan_h5(key: str) -> dict:
    import fsspec
    import h5py

    fs = fsspec.filesystem("https")
    rec = {"format": "hdf5", "vars": {}, "coords": {}}
    with fs.open(URL + key, "rb", block_size=2**20, cache_type="blockcache") as f, h5py.File(f, "r") as h:
        rec["superblock"] = h.id.get_create_plist().get_version()[0] if hasattr(h.id.get_create_plist(), "get_version") else None
        rec["attrs"] = {k: _js(a) for k, a in h.attrs.items()}
        rec["groups"] = [k for k, o in h.items() if isinstance(o, h5py.Group)]
        max_end = 0
        for name, d in h.items():
            if not isinstance(d, h5py.Dataset):
                continue
            dcpl = d.id.get_create_plist()
            info = {"shape": list(d.shape), "dtype": d.dtype.str, "chunks": list(d.chunks) if d.chunks else None,
                    "layout": {0: "compact", 1: "contiguous", 2: "chunked"}.get(dcpl.get_layout(), str(dcpl.get_layout())),
                    "filters": [dcpl.get_filter(j)[0] for j in range(dcpl.get_nfilters())],
                    "fillvalue": _js(d.fillvalue),
                    "dims": [(dim[0].name.lstrip("/") if len(dim) else None) for dim in d.dims] if d.ndim else [],
                    "attrs": {k: _js(a) for k, a in d.attrs.items()
                              if k not in ("DIMENSION_LIST", "REFERENCE_LIST", "_Netcdf4Dimid", "_Netcdf4Coordinates", "CLASS", "NAME")}}
            if d.chunks is not None and d.ndim >= 2:
                info["chunk_index"] = _h5_chunks(d)
                max_end = max(max_end, info["chunk_index"]["max_end"] or 0)
            elif d.chunks is None and d.id.get_offset() is not None:
                info["offset"] = int(d.id.get_offset())
                max_end = max(max_end, int(d.id.get_offset()) + d.id.get_storage_size())
            rec["vars"][name] = info
        t = h["time"]
        rec["time"] = {"index": list(range(t.shape[0])), "values": t[:].tolist(), "full": True}
        rec["time_units"] = _js(t.attrs.get("units"))
        for c in COORDS + ("mask",):
            if c in h:
                a = h[c][:]
                rec["coords"][c] = ({"hash": _hash(a), "n_zero": int((a == 0).sum()), "n": int(a.size)} if c == "mask"
                                    else {"hash": _hash(a), "first": a[0].item(), "last": a[-1].item(), "n": int(a.size)})
        rec["max_data_end"] = max_end
    return rec


# ------------------------------------------------------------------ driver

def one(args) -> dict:
    key, i, size = args
    out = {"path": key, "size": size}
    t0 = time.time()
    for attempt in range(4):
        try:
            import obstore as obs
            st = store()
            magic = bytes(obs.get_range(st, key, start=0, length=8))
            out["magic"] = magic[:4].hex()
            if magic[:3] == b"CDF":
                out.update(scan_nc3(st, key, i, size))
            elif magic[:4] == b"\x89HDF":
                out.update(scan_h5(key))
            else:
                out["format"] = "unknown"
            out.pop("error", None)
            break
        except Exception as e:  # recorded; a file that will not parse is a finding
            out["error"] = f"{type(e).__name__}: {e}"[:500]
            out["traceback"] = traceback.format_exc()[-1500:]
            time.sleep(2 * (attempt + 1))
    out["seconds"] = round(time.time() - t0, 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, default=32, help="for NetCDF-3 files (pure byte-range reads)")
    ap.add_argument("--procs", type=int, default=6, help="for HDF5 files (h5py holds a global lock); more than ~6 hit the OOM killer on a 7.8 GB hub")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    inv = pd.read_parquet(OUT / "inventory.parquet")
    inv = inv[inv.kind == "nc"].sort_values("path").reset_index(drop=True)
    done = set()
    if HEADERS.exists():
        for line in HEADERS.open():
            r = json.loads(line)
            if "error" not in r:
                done.add(r["path"])
    todo = [(p, i, int(s)) for i, (p, s) in enumerate(zip(inv.path, inv["size"])) if p not in done]
    if a.limit:
        todo = todo[: a.limit]
    # magic first, cheaply, to split the work
    import obstore as obs
    st = store()
    with ThreadPoolExecutor(64) as ex:
        magic = dict(zip([t[0] for t in todo], ex.map(lambda t: bytes(obs.get_range(st, t[0], start=0, length=4)), todo)))
    nc3 = [t for t in todo if magic[t[0]][:3] == b"CDF"]
    other = [t for t in todo if magic[t[0]][:3] != b"CDF"]
    print(f"{len(done)} done, {len(nc3)} NetCDF-3 and {len(other)} other to scan", flush=True)
    t0, n = time.time(), 0
    with HEADERS.open("a") as fh:
        with ThreadPoolExecutor(a.threads) as ex:
            for fut in as_completed([ex.submit(one, t) for t in nc3]):
                fh.write(json.dumps(fut.result()) + "\n"); n += 1
                if n % 500 == 0:
                    fh.flush(); print(f"  {n} files, {time.time() - t0:.0f} s", flush=True)
        with mp.get_context("spawn").Pool(a.procs, maxtasksperchild=20) as pool:
            for r in pool.imap_unordered(one, other, chunksize=4):
                fh.write(json.dumps(r) + "\n"); n += 1
                if n % 500 == 0:
                    fh.flush(); print(f"  {n} files, {time.time() - t0:.0f} s", flush=True)
    print(f"scanned {n} files in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
