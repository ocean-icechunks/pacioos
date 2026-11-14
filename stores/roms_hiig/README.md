# PacIOOS ROMS Hawaiʻi forecast: Icechunk store, best time series

**[🌐 View data in browser](https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/viewer/index.html)** · **[💻 Data access (code)](#how-to-open-it)** · **[📦 PacIOOS dataset page](https://www.pacioos.hawaii.edu/metadata/roms_hiig.html)** · **[📄 How to cite](#citation-and-reuse)**

An [Icechunk](https://icechunk.io) store of the **PacIOOS Regional Ocean Modeling System (ROMS)
7-day forecast for the main Hawaiian Islands**. It is 3-hourly from 2025-01-01, at about 4 km
resolution, on 36 depth levels from 0.25 m to 5,500 m. A new run starts every day at 00Z, after
data assimilation (satellite SST and sea-surface height, HF-radar currents, Argo and glider
profiles). Its boundaries come from global HYCOM and its atmospheric forcing from the PacIOOS
WRF model.

```
https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/icechunk
```

**It is the "best" time series, as PacIOOS's THREDDS and ERDDAP serve it.** The daily runs
overlap: each covers 7 days. The store has one time axis, and at each time it takes the newest
run that has it. So the past is a chain of each run's first day, and the last 7 days are the
newest run's forecast. Two coordinates on `time` say where each value came from:
`forecast_reference_time` (the run) and `forecast_period` (hours into it).

**This store is virtual.** It holds Zarr metadata and byte-range references, and no array data.
Every data read goes to the daily NetCDF files, copied unchanged from PacIOOS to Source
Cooperative at `https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/netcdf/`.

What it adds over the files: **one dataset** instead of hundreds of overlapping 1.9 GB files,
the best-series rule already applied, corrected metadata, and chunks of **one depth level**
(230 KB), not the files' 36-level blocks (8.3 MB).

## View it in a browser

| Field | Viewer |
|---|---|
| Potential temperature | [Open `temp`](https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/icechunk::varname=temp::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0::dimIndices_depth=0) |
| Salinity | [Open `salt`](https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/icechunk::varname=salt::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0::dimIndices_depth=0) |
| Eastward current | [Open `u`](https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/icechunk::varname=u::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0::dimIndices_depth=0) |
| Northward current | [Open `v`](https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/icechunk::varname=v::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0::dimIndices_depth=0) |
| Sea-surface height | [Open `zeta`](https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/icechunk::varname=zeta::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0) |

The viewer is [gridlook](https://github.com/eeholmes/gridlook), published beside the store.
Both the store and the NetCDF copies are on `data.source.coop`, which sends the CORS headers a
browser needs.

## What is in it

One group (the root):

| Variable | Dimensions | Units | Standard name |
|---|---|---|---|
| `temp` | time, depth, lat, lon | Celsius | sea_water_potential_temperature |
| `salt` | time, depth, lat, lon | 1e-3 | sea_water_salinity |
| `u` | time, depth, lat, lon | meter second-1 | eastward_sea_water_velocity |
| `v` | time, depth, lat, lon | meter second-1 | northward_sea_water_velocity |
| `zeta` | time, lat, lon | meter | sea_surface_height |
| `mask` | lat, lon | | land/sea mask from the files (0 land, 1 water) |

| Coordinate | Size | Values |
|---|---|---|
| `time` | 5,497 (2026-11-14) | 2025-01-01T00Z to 7 days after the newest run, every 3 hours |
| `forecast_reference_time` | on `time` | the run each step comes from (NaT if no run covers it) |
| `forecast_period` | on `time` | hours since that run's start, 0 to 168 |
| `depth` | 36 | 0.25 to 5,500 m, positive down |
| `lat` | 195 | 17.02 to 23.98 °N |
| `lon` | 295 | −163.83 to −152.52 °E |

The time axis equals the one PacIOOS's ERDDAP serves for `roms_hiig` (checked 2026-11-14). It
is regular: if no run ever covered a time, that step would read as `NaN` with
`forecast_reference_time` NaT. None does so far. Land, and depths below the sea floor, read as
`NaN`.

**The metadata were corrected; the data were not touched.** The files give `salt` no units and
have almost no global attributes. The store takes the variable and global attributes from
PacIOOS's own ERDDAP records,
[`roms_hiig`](https://pae-paha.pacioos.hawaii.edu/erddap/info/roms_hiig/index.html) and
[`roms_hiig_ssh`](https://pae-paha.pacioos.hawaii.edu/erddap/info/roms_hiig_ssh/index.html).
Its title ends ": Forecast" instead of ERDDAP's ": 3-D Variables", because `zeta` is in the same
group here. The fill value is the files' own, `9.99e10`.

## How to open it

Needs **Python 3.12 or newer**, `icechunk >= 2.3`, `xarray` and `zarr`. No credentials and no
account.

```bash
pip install "icechunk>=2.3" xarray zarr
```

> **icechunk 1.x will not work.** Every icechunk 2.x release needs Python 3.12, so on an older
> Python `pip install icechunk` quietly installs 1.1.x, and the code below fails with
> `AttributeError: module 'icechunk' has no attribute 'http_storage'`.

```python
import icechunk
import numpy as np
import xarray as xr
import zarr

# Zarr's default of 10 concurrent reads is far too low for many small chunks.
zarr.config.set({"async.concurrency": 128})


def open_forecast(ref="main", chunks=None):
    """Open the PacIOOS ROMS Hawaii forecast, best time series. `ref` is a branch or tag."""
    url = "https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/icechunk"
    repo = icechunk.Repository.open(icechunk.http_storage(url))
    # The data stay in the NetCDF files, outside the store. Allow anonymous reads of the
    # locations the store names (they are in its saved config, so no URL is hard-coded).
    auth = {p: icechunk.credentials.HttpAccess for p in repo.config.virtual_chunk_containers or []}
    repo = repo.reopen(authorize_virtual_chunk_access=auth)
    tags = set(repo.list_tags())
    session = repo.readonly_session(tag=ref) if ref in tags else repo.readonly_session(ref)
    return xr.open_zarr(session.store, consolidated=False, chunks=chunks)


ds = open_forecast()
print(ds)

# The surface temperature forecast 3 days after the start of the newest run
newest_run = ds.forecast_reference_time.values.max()
sst = ds.temp.sel(depth=0.25, time=newest_run + np.timedelta64(3, "D"))

# A 2025 surface time series off south Oʻahu, and which run each value came from
series = ds.temp.sel(depth=0.25).sel(lat=21.2, lon=-157.9, method="nearest").sel(
    time=slice("2025-01-01", "2025-12-31")).load()
print(float(sst.mean()), float(series.mean()))
print(series.forecast_reference_time.values[:10])
```

Opening takes about a second and reads only metadata.

## Reading it fast

Each chunk is **one depth level of one variable at one time step**: `(1, 1, 195, 295)`, 230 KB.
That shape is fixed by the files. The store points inside them and cannot rechunk them.

| Read | Chunks | Data moved | Time (measured, scratch build) |
|---|---|---|---|
| One surface map | 1 | 230 KB | 0.1 s |
| One 3-D field, 36 levels | 36 | 8.3 MB | 0.7 s |
| Point series, one depth, 5,497 steps | 5,497 | 1.3 GB | 7.7 s |

Measured 2026-11-14 from a JupyterHub, with `zarr.config.set({"async.concurrency": 128})` and
`chunks=None`. Rates elsewhere will differ.

- **Maps and profiles are cheap; long point series are not.** A time series at one point reads
  a whole 230 KB plane at every step, because no chunk spans more than one time step. In the
  files, the time steps of all variables are interleaved record by record, so no reference can
  join them.
- **Use `chunks=None` (the default above), or large dask chunks, for time series.** With
  `chunks={}`, dask makes one task per 230 KB chunk, which is many times slower.

## Provenance

- **Source files:** PacIOOS's daily forecast files `hiig_forec_YYYYMMDD.nc` (NetCDF-3,
  uncompressed), copied unchanged from PacIOOS to Source Cooperative, each with an `.md5` beside
  it. 654 runs, 2025-01-01 to 2026-11-12; 27 days have no run, at most 3 in a row.
- **Built** by `build_store.py` in
  [ocean-icechunks/pacioos](https://github.com/ocean-icechunks/pacioos/tree/main/stores/roms_hiig).
  It read every file's header (the files come in four header layouts, so offsets differ between
  files) and confirmed that all share one structure.
- **Validated** from the public URL, anonymously: the time axis equals the computed one and
  ERDDAP's; every step comes from the newest run that has it; sampled planes (one step per
  month, all 5 variables) are identical to netCDF-C reads of the files; point values equal
  ERDDAP's; land reads as `NaN`.
- **How it was made, and how to rebuild it:**
  [`how_store_created.md`](https://github.com/ocean-icechunks/pacioos/blob/main/stores/roms_hiig/how_store_created.md).
  The plan and decisions are in [issue #10](https://github.com/ocean-icechunks/pacioos/issues/10).

**Updates.** For now the store covers the runs copied up to 2026-11-12. A daily update (issue
#4) will add each new run. Every update is a new Icechunk snapshot, so the series as it stood on
an earlier day stays readable.

## Citation and reuse

**The data are PacIOOS's.** Any use of this store or the NetCDF copies should cite PacIOOS, as
described at <https://www.pacioos.hawaii.edu/data-services/>. The model runs are produced by
Brian Powell (University of Hawaiʻi at Mānoa).

**The code** that copied the files and built the store was written by E. E. Holmes and is
released under the Apache License 2.0 at
[ocean-icechunks/pacioos](https://github.com/ocean-icechunks/pacioos). It can be used without
attribution.
