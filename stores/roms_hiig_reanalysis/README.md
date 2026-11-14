# PacIOOS ROMS Hawaiʻi reanalysis v2.0: Icechunk store

**[🌐 View data in browser](https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/viewer/index.html)** · **[💻 Data access (code)](#how-to-open-it)** · **[📦 PacIOOS dataset page](https://www.pacioos.hawaii.edu/metadata/roms_hiig_reanalysis.html)** · **[📄 How to cite](#citation-and-reuse)**

An [Icechunk](https://icechunk.io) store of the **PacIOOS Regional Ocean Modeling System (ROMS)
reanalysis for the main Hawaiian Islands, version 2.0**. It is 3-hourly, from 2009-01-01 to
2020-12-28, at about 4 km resolution, on 36 depth levels from 0.25 m to 5,500 m. The model is
data-assimilating: it uses satellite SST and sea-surface height, HF-radar currents, and Argo and
glider profiles. Its boundaries come from global HYCOM and its atmospheric forcing from the PacIOOS WRF model.

```
https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk
```

**This store is virtual.** It holds Zarr metadata and byte-range references, and no array data.
The store is 68.8 MB, and it points at 1.17 TB of NetCDF: the 4,380 daily files of the reanalysis,
copied unchanged from PacIOOS to Source Cooperative at
`https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/netcdf/v2.0/`. Every data
read goes to those files, so the store and its data are both served by Source Cooperative.

What it adds over the files: **one dataset** with one time axis of 35,040 steps instead of 4,380
files, corrected metadata, and chunks of **one depth level** (230 KB), not the files' 36-level
blocks (8.3 MB). A surface map reads 36 times less data than it would from the files.

## View it in a browser

| Field | Viewer |
|---|---|
| Potential temperature | [Open `temp`](https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk::varname=temp::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0::dimIndices_depth=0) |
| Salinity | [Open `salt`](https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk::varname=salt::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0::dimIndices_depth=0) |
| Eastward current | [Open `u`](https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk::varname=u::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0::dimIndices_depth=0) |
| Northward current | [Open `v`](https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk::varname=v::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0::dimIndices_depth=0) |
| Sea-surface height | [Open `zeta`](https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk::varname=zeta::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0) |

The time and depth sliders move through the 35,040 steps and the 36 levels. The viewer is
[gridlook](https://github.com/eeholmes/gridlook), published beside the store. It draws in an
ordinary browser, with no extension: both the store and the NetCDF copies are on
`data.source.coop`, which sends the CORS headers a browser needs (checked in a browser,
2026-11-14).

## What is in it

One group (the root), tag **`v2.0`**:

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
| `time` | 35,040 | 2009-01-01T00Z to 2020-12-28T21Z, every 3 hours, no gaps |
| `depth` | 36 | 0.25 to 5,500 m, positive down |
| `lat` | 195 | 17.02 to 23.98 °N |
| `lon` | 295 | −163.83 to −152.52 °E |

The time axis equals the one PacIOOS's ERDDAP serves for `roms_hiig_reanalysis`. Land, and
depths below the sea floor, read as `NaN`.

**The metadata were corrected; the data were not touched.** The files have no fill value
declared (land holds netCDF's default `9.96921e36`), give `temp` the units `ppt`, and give `salt`
no units. The store takes the variable and global attributes from PacIOOS's own ERDDAP records,
[`roms_hiig_reanalysis`](https://pae-paha.pacioos.hawaii.edu/erddap/info/roms_hiig_reanalysis/index.html)
and [`roms_hiig_reanalysis_ssh`](https://pae-paha.pacioos.hawaii.edu/erddap/info/roms_hiig_reanalysis_ssh/index.html).
Its title omits ERDDAP's ": 3-D Variables", because `zeta` is in the same group here.
`product_version` is `2.0`.

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
import xarray as xr
import zarr

# Zarr's default of 10 concurrent reads is far too low for many small chunks.
zarr.config.set({"async.concurrency": 128})


def open_reanalysis(ref="v2.0", chunks=None):
    """Open the PacIOOS ROMS Hawaii reanalysis. `ref` is a tag or a branch."""
    url = "https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk"
    repo = icechunk.Repository.open(icechunk.http_storage(url))
    # The data stay in the NetCDF files, outside the store. Allow anonymous reads of the
    # locations the store names (they are in its saved config, so no URL is hard-coded).
    auth = {p: icechunk.credentials.HttpAccess for p in repo.config.virtual_chunk_containers or []}
    repo = repo.reopen(authorize_virtual_chunk_access=auth)
    tags = set(repo.list_tags())
    session = repo.readonly_session(tag=ref) if ref in tags else repo.readonly_session(ref)
    return xr.open_zarr(session.store, consolidated=False, chunks=chunks)


ds = open_reanalysis()
print(ds)

# A surface temperature map
sst = ds.temp.sel(time="2015-08-01T00:00", depth=0.25)

# A one-year surface time series off south Oʻahu
series = ds.temp.sel(depth=0.25).sel(lat=21.2, lon=-157.9, method="nearest").sel(
    time=slice("2015-01-01", "2015-12-31")).load()
print(float(sst.mean()), float(series.mean()))
```

Opening takes about a second and reads only metadata.

## Reading it fast

Each chunk is **one depth level of one variable at one time step**: `(1, 1, 195, 295)`, 230 KB.
That shape is fixed by the files. The store points inside them and cannot rechunk them.

| Read | Chunks | Data moved | Time (measured) |
|---|---|---|---|
| One surface map | 1 | 230 KB | 0.4 s |
| One 3-D field, 36 levels | 36 | 8.3 MB | 0.8 s |
| Point series, one depth, 12 years | 35,040 | 8.1 GB | 49.5 s |

Measured 2026-11-14 from a JupyterHub, with `zarr.config.set({"async.concurrency": 128})` and
`chunks=None`. Rates elsewhere will differ.

- **Maps and profiles are cheap; long point series are not.** A time series at one point reads
  a whole 230 KB plane at every step, because no chunk spans more than one time step. That is
  a property of the files, where each time step's variables are separate HDF5 chunks. Only a
  rewritten (rechunked) copy of the data could change it.
- **Use `chunks=None` (the default above), or large dask chunks, for time series.** With
  `chunks={}`, dask makes one task per 230 KB chunk, and a one-year series took 120 s instead of
  about 5 s. For dask, use something like `open_reanalysis(chunks={"time": 2920})`.
- **Raise Zarr's concurrency** as shown. The timings above used 128; Zarr's default is 10.

## Provenance

- **Source files:** the 4,380 PacIOOS v2.0 files `hiig_his_zlevel_YYYYMMDD.nc` (uncompressed
  HDF5), copied unchanged from PacIOOS to Source Cooperative, each with an `.md5` beside it.
- **Built** 2026-11-14 by `build_store.py` in
  [ocean-icechunks/pacioos](https://github.com/ocean-icechunks/pacioos/tree/main/stores/roms_hiig_reanalysis).
  It read every file's header and confirmed that all 4,380 share one layout, then wrote one
  commit per year. Tag `v2.0` is snapshot `YJNS41AQBRXSMREPVAZ0`.
- **Validated** from this public URL, anonymously:
  - the time axis equals the 35,040 expected steps;
  - 120 planes (2 time steps per year × 5 variables) are identical to netCDF-C reads of the
    files;
  - land reads as `NaN`.
- **Tested with** icechunk 2.3.1, virtualizarr 2.8.0, xarray 2026.9.0, zarr 3.4.2, Python 3.12.
  The loading code above was run as written, in a clean environment holding only the three
  packages it names.
- **How it was made, and how to rebuild it:**
  [`how_store_created.md`](https://github.com/ocean-icechunks/pacioos/blob/main/stores/roms_hiig_reanalysis/how_store_created.md).
  The plan and decisions are in [issue #11](https://github.com/ocean-icechunks/pacioos/issues/11).

**Versions.** v2.0 is the reanalysis PacIOOS published in 2023. If PacIOOS releases a new
version, its files go in a new folder (`netcdf/v3.0/`) and the store gains a new tag. The `v2.0`
references are never rewritten.

**Not verified:** read speeds from places other than the one JupyterHub where they were
measured.

## Citation and reuse

**The data are PacIOOS's.** Any use of this store or the NetCDF copies should cite PacIOOS, as
described at <https://www.pacioos.hawaii.edu/data-services/>. The model runs were produced by
Brian Powell (University of Hawaiʻi at Mānoa). The model is described in
<https://doi.org/10.5194/gmd-2018-98>.

**The code** that copied the files and built the store was written by E. E. Holmes and is
released under the Apache License 2.0 at
[ocean-icechunks/pacioos](https://github.com/ocean-icechunks/pacioos). It can be used without
attribution.
