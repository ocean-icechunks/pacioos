# WRF Regional Atmospheric Model: Main Hawaiian Islands Forecast

**[🌐 View data in browser](https://data.source.coop/ocean-icechunks/pacioos/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/wrf_hi/icechunk::varname=Tair::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0)** · **[💻 Data access (code)](#how-to-open-it)** · **[📦 PacIOOS dataset page](https://www.pacioos.hawaii.edu/metadata/wrf_hi.html)** · **[📄 How to cite](#citation-and-reuse)**

PacIOOS's Weather Research and Forecasting (WRF) model provides hourly weather forecasts
for the main Hawaiian Islands on a 138 × 213 grid at approximately 6 km resolution.
This Icechunk store covers the HDF5 era starting August 16, 2017 at 03:00 UTC.

```
https://data.source.coop/ocean-icechunks/pacioos/wrf_hi/icechunk
```

**This is the “best” time series that PacIOOS serves through THREDDS and ERDDAP.**
Forecast runs overlap. At each valid hour the store selects the newest available run
covering that hour, with ties going to the later filename. Uncovered hours are omitted.
The `forecast_reference_time` and `forecast_period` coordinates identify the run and lead.

**This store is virtual.** Icechunk holds Zarr metadata and byte-range references. Reads
retrieve the forecast values directly from unchanged [NetCDF copies on Source Cooperative](https://data.source.coop/ocean-icechunks/pacioos/wrf_hi/netcdf/).

## View it in a browser

| Field | Viewer |
|---|---|
| air temperature at 2m | [Open `Tair`](https://data.source.coop/ocean-icechunks/pacioos/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/wrf_hi/icechunk::varname=Tair::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0) |
| u-wind component at 10m | [Open `Uwind`](https://data.source.coop/ocean-icechunks/pacioos/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/wrf_hi/icechunk::varname=Uwind::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0) |
| v-wind component at 10m | [Open `Vwind`](https://data.source.coop/ocean-icechunks/pacioos/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/wrf_hi/icechunk::varname=Vwind::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0) |
| rainfall rate | [Open `rain`](https://data.source.coop/ocean-icechunks/pacioos/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/wrf_hi/icechunk::varname=rain::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0) |
| surface air relative humidity | [Open `Qair`](https://data.source.coop/ocean-icechunks/pacioos/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/wrf_hi/icechunk::varname=Qair::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0) |
| surface air pressure | [Open `Pair`](https://data.source.coop/ocean-icechunks/pacioos/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/wrf_hi/icechunk::varname=Pair::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0) |
| net longwave radiation flux | [Open `lwrad_down`](https://data.source.coop/ocean-icechunks/pacioos/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/wrf_hi/icechunk::varname=lwrad_down::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0) |
| solar shortwave radiation flux | [Open `swrad`](https://data.source.coop/ocean-icechunks/pacioos/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/wrf_hi/icechunk::varname=swrad::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0) |

These links open the WRF store in the shared [gridlook viewer](https://github.com/eeholmes/gridlook).

## What is in it

All eight forecast variables are in the root group.

| Variable | Dimensions | Units | CF standard name |
|---|---|---|---|
| `Tair` | time, lat, lon | Celsius | `air_temperature` |
| `Uwind` | time, lat, lon | meter second-1 | `eastward_wind` |
| `Vwind` | time, lat, lon | meter second-1 | `northward_wind` |
| `rain` | time, lat, lon | kilogram meter-2 second-1 | `precipitation_flux` |
| `Qair` | time, lat, lon | % | `relative_humidity` |
| `Pair` | time, lat, lon | millibar | `surface_air_pressure` |
| `lwrad_down` | time, lat, lon | Watts meter-2 | `surface_net_downward_longwave_flux` |
| `swrad` | time, lat, lon | Watts meter-2 | `surface_downwelling_shortwave_flux` |

| Coordinate | Size | Values |
|---|---|---|
| `time` | 80,087 | Covered hours from 2017-08-16 03:00 UTC through 2026-11-22 00:00 UTC |
| `forecast_reference_time` | on `time` | Start of the selected run, in UTC |
| `forecast_period` | on `time` | Hours since the selected run started |
| `lat` | 138 | 16.755° to 24.29° N |
| `lon` | 213 | 164.47° to 151.75° W |

**The store applies PacIOOS ERDDAP metadata over unchanged forecast data.** The summary,
license, attribution, units, and CF standard names come from the [ERDDAP record](https://pae-paha.pacioos.hawaii.edu/erddap/info/wrf_hi/index.html).
The store has a shorter forecast title, and its coverage describes the published HDF5-era series.
The `metadata_source` attribute identifies the saved ERDDAP record.

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

zarr.config.set({"async.concurrency": 128})

def open_forecast(branch="main", chunks=None):
    url = "https://data.source.coop/ocean-icechunks/pacioos/wrf_hi/icechunk"
    repo = icechunk.Repository.open(icechunk.http_storage(url))
    auth = {prefix: icechunk.credentials.HttpAccess
            for prefix in repo.config.virtual_chunk_containers or []}
    repo = repo.reopen(authorize_virtual_chunk_access=auth)
    session = repo.readonly_session(branch)
    return xr.open_zarr(session.store, consolidated=False, chunks=chunks)

ds = open_forecast()
air_temperature = ds.Tair.isel(time=0).load()

# A day of hourly 10 m eastward wind near south Oʻahu
wind = ds.Uwind.sel(lat=21.2, lon=-157.9, method="nearest").sel(
    time="2025-01-02"
).load()
print(wind)
```

## Reading it fast

A chunk is one hourly map for one variable, with shape `(1, 138, 213)` and 117,576 bytes
of uncompressed data. A point series still reads a full map per hour.

| Read | Chunks per variable | Forecast bytes | Time (measured) |
|---|---:|---:|---:|
| One map | 1 | 118 KB | 0.51 s |
| One point for 24 covered hours | 24 | 2.8 MB | 0.81 s |
| One point across the published snapshot | 80,087 | 9.4 GB | Not measured |

Timings are medians of three anonymous `Tair` reads from a local workstation on
2026-11-19, after opening the store, with `chunks=None` and Zarr concurrency set to 128.
Byte counts are payload estimates. Read times vary with the network and cache state.

- **Maps are cheap. Long point series are expensive.** A map reads one 118 KB chunk. A point
  series reads a whole map for every hour. The HDF5 chunks aren’t consistently adjacent, so the
  virtual store can’t combine them into larger time chunks. A full-snapshot point series reads
  about 9.4 GB per variable.
- **Use `chunks=None` or larger Dask chunks along time.** With `chunks={}`, Dask uses the native
  one-hour chunks, which can create tens of thousands of tasks for a long series. Larger Dask
  chunks reduce scheduling overhead while reading the same underlying maps.

Select the variable and time range before calling `.load()`, and keep Zarr concurrency
elevated for multi-hour reads.

## Provenance

- **Source.** 3,041 uncompressed HDF5 forecast runs named `wrf_hi_YYYYMMDD.nc`, copied
  unchanged from PacIOOS. Each copy has an MD5 sidecar.
- **Build.** The [build source bundle](https://data.source.coop/ocean-icechunks/pacioos/wrf_hi/build-source.zip) contains the builder,
  requirements, and saved ERDDAP metadata. The builder checked every source header and used its
  native chunk offsets. The two records for the duplicate hour in the April 29, 2019 file
  matched across all eight fields. The builder keeps the later record.
- **Validation.** Production snapshot `P9R11AXCREQ7KGD2NQQ0` opened anonymously and matched
  the 80,087 ERDDAP timestamps within its coverage. Four sampled temperature maps matched the
  source NetCDF files exactly, and four point values matched ERDDAP.
- **Environment.** Python 3.12, Icechunk 2.3.1, VirtualiZarr 2.8.0, Xarray 2026.9.0, and Zarr 3.4.2.
- **Project.** The build is tracked in [issue #12](https://github.com/ocean-icechunks/pacioos/issues/12).
  Routine forecast updates are tracked in [issue #4](https://github.com/ocean-icechunks/pacioos/issues/4).

## Citation and reuse

Cite PacIOOS when using the forecast data. Model runs were produced by Yi-Leng Chen at the
University of Hawaiʻi at Mānoa. The dataset's `license` attribute contains the PacIOOS data
license. [PacIOOS citation guidance](https://www.pacioos.hawaii.edu/data-services/) ·
[ERDDAP metadata and license](https://pae-paha.pacioos.hawaii.edu/erddap/info/wrf_hi/index.html)

The build code is available under Apache License 2.0 in the
[PacIOOS project repository](https://github.com/ocean-icechunks/pacioos).
