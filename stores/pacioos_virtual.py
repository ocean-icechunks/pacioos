"""Smoke test helpers: computed virtual references for PacIOOS model files on Source Cooperative.

Smoke-test code for the ideas in issues #10-#14; not yet the production build.

Every product here is uncompressed, so any contiguous byte range of an array is a valid
chunk. References are computed from each file's own header:

- NetCDF-3 (ROMS forecast, WW3, WRF to 2017-08-10): offsets from kerchunk's header parser.
  Record (UNLIMITED) variables give one contiguous slab per (variable, record); fixed-dim
  variables one slab per variable.
- HDF5 (reanalysis, WRF from 2017-08-16): offsets of the native chunks from h5py.

Inside a slab of shape (nz, ny, nx) or (nt, ny, nx), C order means each leading index is a
contiguous (ny, nx) plane, so a slab can be cut into planes (per depth level, or per step).
"""
from __future__ import annotations

import json
import warnings

import fsspec
import h5py
import numpy as np
import pandas as pd
import xarray as xr

URL_PREFIX = "https://data.source.coop/ocean-icechunks/pacioos/"


# ------------------------------------------------------------------ headers

def _decode_time(values, units: str) -> pd.DatetimeIndex:
    unit, since = units.split(" since ")
    t0 = pd.Timestamp(since.replace(" UTC", ""))
    return t0 + pd.to_timedelta(np.asarray(values, "f8"), unit={"hours": "h", "minutes": "min"}[unit])


def scan_nc3(key: str) -> dict:
    """Header of one NetCDF-3 file: per variable, the (offset, nbytes) of each slab, plus times."""
    from kerchunk.netCDF3 import NetCDF3ToZarr

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        h = NetCDF3ToZarr(URL_PREFIX + key, inline_threshold=0, max_chunk_size=0)
        refs = h.translate()["refs"]
    out = {"key": key, "format": "nc3", "vars": {}}
    for name, v in h.variables.items():
        zarray = json.loads(refs[f"{name}/.zarray"])
        chunks = sorted((k for k in refs if k.startswith(name + "/") and not k.split("/")[1].startswith(".")),
                        key=lambda k: int(k.split("/")[1].split(".")[0]))
        out["vars"][name] = {
            "dims": v.dimensions, "shape": tuple(zarray["shape"]), "dtype": zarray["dtype"],
            "chunk": tuple(zarray["chunks"]),
            "offsets": np.array([refs[k][1] for k in chunks], "uint64"),
            "nbytes": np.array([refs[k][2] for k in chunks], "uint64"),
            "attrs": {a: (x.decode() if isinstance(x, bytes) else x) for a, x in v._attributes.items()},
        }
    # time values: read the tiny time slabs directly
    tv = out["vars"]["time"]
    fs = fsspec.filesystem("https")
    raw = b"".join(fs.cat_ranges([URL_PREFIX + key] * len(tv["offsets"]), tv["offsets"].tolist(),
                                 (tv["offsets"] + tv["nbytes"]).tolist()))
    out["time"] = _decode_time(np.frombuffer(raw, tv["dtype"]), tv["attrs"]["units"])
    for c in ("lat", "lon", "depth", "z", "mask"):
        if c in out["vars"]:
            cv = out["vars"][c]
            b = fs.cat_file(URL_PREFIX + key, start=int(cv["offsets"][0]), end=int(cv["offsets"][0] + cv["nbytes"][0]))
            out.setdefault("coords", {})[c] = np.frombuffer(b, cv["dtype"]).reshape(cv["shape"]).astype(np.dtype(cv["dtype"]).newbyteorder("="))
    return out


def scan_h5(key: str) -> dict:
    """Header of one HDF5 file: per chunked variable, the native chunk offsets in C order, plus times."""
    fs = fsspec.filesystem("https")
    out = {"key": key, "format": "hdf5", "vars": {}}
    with fs.open(URL_PREFIX + key, "rb", block_size=2**20, cache_type="blockcache") as f, h5py.File(f, "r") as h:
        for name, d in h.items():
            if not isinstance(d, h5py.Dataset):
                continue
            assert d.compression is None and not d.shuffle, (key, name)
            rec = {"dims": None, "shape": d.shape, "dtype": d.dtype.str, "chunk": d.chunks,
                   "attrs": {a: (x.decode() if isinstance(x, bytes) else x) for a, x in d.attrs.items()
                             if not a.startswith("_Netcdf4") and a not in ("CLASS", "NAME", "REFERENCE_LIST", "DIMENSION_LIST")}}
            if d.chunks is not None and d.ndim >= 3:
                n = d.id.get_num_chunks()
                infos = [d.id.get_chunk_info(i) for i in range(n)]
                order = np.argsort([i.chunk_offset for i in infos], axis=0)[:, 0]
                infos = [infos[i] for i in order]
                rec["offsets"] = np.array([i.byte_offset for i in infos], "uint64")
                rec["nbytes"] = np.array([i.size for i in infos], "uint64")
                assert len(infos) == d.shape[0] // d.chunks[0], (key, name)  # every chunk allocated
            out["vars"][name] = rec
        out["time"] = _decode_time(h["time"][:], out["vars"]["time"]["attrs"]["units"])
        for c in ("lat", "lon", "depth", "mask"):
            if c in h:
                out.setdefault("coords", {})[c] = h[c][:]
    return out


# ------------------------------------------------------------------ the "best" rule

def best_assignment(scans: list[dict], step: str) -> pd.DataFrame:
    """THREDDS FMRC 'best': for each valid time, the most recent run that has it.

    Returns one row per step of a regular axis from the first run's start to the last run's end;
    times no run covers have run = -1 (no reference, read as fill).
    """
    run_times = [s["time"] for s in scans]
    t = pd.date_range(min(r[0] for r in run_times), max(r[-1] for r in run_times), freq=step)
    run = np.full(len(t), -1)
    lead = np.full(len(t), -1)
    # runs ordered oldest -> newest; later ones overwrite, so the newest wins
    order = np.argsort([r[0] for r in run_times], kind="stable")
    for i in order:
        idx = t.get_indexer(run_times[i])
        assert (idx >= 0).all(), "run time off the regular axis"
        run[idx] = i
        lead[idx] = np.arange(len(idx))
    return pd.DataFrame({"run": run, "lead": lead}, index=t)


# ------------------------------------------------------------------ manifest arrays

def plane_refs(scan: dict, name: str, lead: int) -> tuple[np.ndarray, np.ndarray, int]:
    """Offsets of the (ny, nx) planes of variable `name` at time index `lead` of one file.

    Works for record slabs (one per step, shape nz*ny*nx), fixed contiguous arrays (one slab
    of nt*ny*nx) and HDF5 chunks of (1, nz, ny, nx) or (1, ny, nx).
    """
    v = scan["vars"][name]
    ny, nx = v["shape"][-2:]
    plane = ny * nx * np.dtype(v["dtype"]).itemsize
    nz = v["shape"][1] if len(v["shape"]) == 4 else 1
    if len(v["offsets"]) == 1 and v["shape"][0] > 1:        # one contiguous fixed-dim array
        assert v["nbytes"][0] == v["shape"][0] * nz * plane
        base = v["offsets"][0] + np.uint64(lead * nz * plane)
    else:                                                    # one slab / chunk per step
        assert v["nbytes"][lead] == nz * plane, (name, v["nbytes"][lead], nz * plane)
        base = v["offsets"][lead]
    offs = base + np.arange(nz, dtype="uint64") * np.uint64(plane)
    return offs, np.full(nz, plane, "uint64"), nz


def manifest_variable(name: str, scans: list[dict], best: pd.DataFrame, dims: tuple, attrs: dict,
                      fill_value=float("nan")) -> xr.Variable:
    from virtualizarr.manifests import ChunkManifest, ManifestArray
    from virtualizarr.manifests.utils import create_v3_array_metadata

    used = sorted(set(int(r) for r in best["run"] if r >= 0))
    v0 = next(scans[r]["vars"][name] for r in used if name in scans[r]["vars"])
    # every run feeding one array must agree on dtype (incl. byte order) and shape
    assert len({(scans[r]["vars"][name]["dtype"], scans[r]["vars"][name]["shape"][1:]) for r in used if name in scans[r]["vars"]}) == 1, name
    ny, nx = v0["shape"][-2:]
    nz = v0["shape"][1] if len(v0["shape"]) == 4 else 1
    nt = len(best)
    paths = np.full((nt, nz), "", dtype=np.dtypes.StringDType())
    offsets = np.zeros((nt, nz), "uint64")
    lengths = np.zeros((nt, nz), "uint64")
    for i, (r, l) in enumerate(zip(best["run"], best["lead"])):
        if r < 0 or name not in scans[r]["vars"]:
            continue
        o, n, _ = plane_refs(scans[r], name, l)
        paths[i] = URL_PREFIX + scans[r]["key"]
        offsets[i], lengths[i] = o, n
    endian = {">": "big", "<": "little"}[np.dtype(v0["dtype"]).str[0]]
    four_d = len(dims) == 4
    grid = (nt, nz, 1, 1) if four_d else (nt, 1, 1)
    metadata = create_v3_array_metadata(
        shape=(nt, nz, ny, nx) if four_d else (nt, ny, nx),
        chunk_shape=(1, 1, ny, nx) if four_d else (1, ny, nx),
        data_type=np.dtype(v0["dtype"]).newbyteorder("="),
        codecs=[{"name": "bytes", "configuration": {"endian": endian}}],
        fill_value=fill_value,
        dimension_names=dims,
    )
    manifest = ChunkManifest.from_arrays(paths=paths.reshape(grid), offsets=offsets.reshape(grid),
                                         lengths=lengths.reshape(grid))
    return xr.Variable(dims, ManifestArray(metadata=metadata, chunkmanifest=manifest), attrs=attrs)


# ------------------------------------------------------------------ icechunk

def repository_config(time_chunks_per_manifest: int):
    import icechunk

    config = icechunk.RepositoryConfig.default()
    config.set_virtual_chunk_container(
        icechunk.VirtualChunkContainer(url_prefix=URL_PREFIX, store=icechunk.http_store()))
    config.manifest = icechunk.ManifestConfig(
        splitting=icechunk.ManifestSplittingConfig.from_dict({
            icechunk.ManifestSplitCondition.AnyArray(): {
                icechunk.ManifestSplitDimCondition.DimensionName("time"): time_chunks_per_manifest}}))
    return config


def reader_authorization():
    import icechunk
    return {URL_PREFIX: icechunk.credentials.HttpAccess}
