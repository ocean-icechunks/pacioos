# PacIOOS Hawaiʻi ocean, wave and weather models

**[🌐 View data in browser](#view-it-in-a-browser)** · **[💻 Data access (code)](#how-to-open-it)** · **[📦 Data access (PacIOOS)](https://www.pacioos.hawaii.edu/data-services/)**

Model output from the [Pacific Islands Ocean Observing System (PacIOOS)](https://www.pacioos.hawaii.edu)
for the main Hawaiian Islands. The ocean, wave and weather models are run at the University of
Hawaiʻi at Mānoa. The original NetCDF files are copied here **unchanged**, and
[Icechunk](https://icechunk.io) stores are built over them, so that a whole archive opens in
about a second as one lazy `xarray` dataset.

| Dataset (PacIOOS id) | About | Dates | NetCDF copies | Icechunk store |
|---|---|---|---|---|
| **ROMS ocean reanalysis v2.0** (`roms_hiig_reanalysis`), 3-hourly, ~4 km, 36 depths | [PacIOOS](https://www.pacioos.hawaii.edu/metadata/roms_hiig_reanalysis.html) | 2009-01-01 to 2020-12-28 | `roms_hiig_reanalysis/netcdf/v2.0/`, 4,380 files, 1.17 TB | **`https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk`** ([README](https://source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/README.md)) |
| **ROMS ocean forecast** (`roms_hiig`), daily runs | [Currents forecast](https://www.pacioos.hawaii.edu/currents/model-hawaii/) | 2025-01-01 to 2026-11-17 | `roms_hiig/netcdf/`, 657 files, 1.25 TB | **`https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/icechunk`**, best time series ([README](https://source.coop/ocean-icechunks/pacioos/roms_hiig/README.md)) |
| **WRF weather model** (`wrf_hi`), daily runs | [Wind forecast](https://www.pacioos.hawaii.edu/weather/model-wind-hawaii/) | 2017-08-16 to 2026-11-22 | `wrf_hi/netcdf/`, 3,041 files, 0.46 TB | **`https://data.source.coop/ocean-icechunks/pacioos/wrf_hi/icechunk`**, hourly best time series ([README](https://source.coop/ocean-icechunks/pacioos/wrf_hi/README.md)) |
| **WaveWatch III waves** (`ww3_hawaii`), daily runs | [Wave forecast](https://www.pacioos.hawaii.edu/waves/model-hawaii/) | 2011-06-21 to 2026-11-16 | `ww3_hawaii/netcdf/`, 5,237 files, 0.49 TB | **`https://data.source.coop/ocean-icechunks/pacioos/ww3_hawaii/icechunk`**, best time series, hourly, with flags on cold starts ([README](https://source.coop/ocean-icechunks/pacioos/ww3_hawaii/README.md)) |

The Icechunk stores are **virtual**. Each holds only Zarr metadata and byte-range references
to the NetCDF copies beside it, so both the store and its data are served by Source
Cooperative. As of 2026-11-18, NetCDF copies extend to the 2026-11-17 ROMS run and 2026-11-16
WW3 run. The ROMS forecast and WW3 stores include those runs, with forecast coverage
through 2026-11-24T00Z and 2026-11-23T18Z, respectively. The latest copied WRF run is dated
2026-11-15 and the WRF Icechunk forecast extends through 2026-11-22T00Z.
A daily update is planned. Where the files lack
metadata (WW3 above all), the stores take PacIOOS's ERDDAP attributes, and each store's
`metadata_source` attribute says so.

Each Icechunker-managed dataset's README gains a **Global metadata attributes** section when
Icechunker next processes a completed transfer. It distinguishes attributes of the published
Icechunk snapshot from those of the latest copied NetCDF file and identifies both sources.
Later syncs refresh changed content while preserving the rest of the README. Static ROMS
reanalysis documents its existing `v2.0` store tag. The PacIOOS team's WRF store and README
are excluded from this automation. Existing archives are not scanned just to initialize
these listings.

## View it in a browser

One viewer, [`pacioos/viewer/`](https://data.source.coop/ocean-icechunks/pacioos/viewer/index.html),
offers ROMS forecast, reanalysis and WW3. The team-managed WRF store is not yet in this
catalog. The links below open each store directly.

| Dataset | Viewer |
|---|---|
| ROMS reanalysis v2.0 | [Open surface temperature in the viewer](https://data.source.coop/ocean-icechunks/pacioos/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk::varname=temp::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0::dimIndices_depth=0) |
| ROMS forecast, best time series | [Open surface temperature in the viewer](https://data.source.coop/ocean-icechunks/pacioos/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/icechunk::varname=temp::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0::dimIndices_depth=0) |
| WRF forecast, best time series | [Open air temperature in the viewer](https://data.source.coop/ocean-icechunks/pacioos/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/wrf_hi/icechunk::varname=Tair::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0) |
| WaveWatch III, best time series | [Open significant wave height in the viewer](https://data.source.coop/ocean-icechunks/pacioos/viewer/index.html#icechunk+https://data.source.coop/ocean-icechunks/pacioos/ww3_hawaii/icechunk::varname=Thgt::px=0::py=0::alt=4000000::lat=20.5::lon=-158.2::dimIndices_time=0) |

It draws in an ordinary browser, with no extension.

## How to open it

**Icechunk stores:** each dataset's README has tested loading code. Python 3.12 or newer and
icechunk 2.3 or newer are required; no credentials are needed.

| Dataset | Code to open |
|---|---|
| ROMS reanalysis v2.0 | [Open in Python](https://source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/README.md) |
| ROMS forecast, best time series | [Open in Python](https://source.coop/ocean-icechunks/pacioos/roms_hiig/README.md) |
| WRF forecast, best time series | [Open in Python](https://source.coop/ocean-icechunks/pacioos/wrf_hi/README.md) |
| WaveWatch III, best time series | [Open in Python](https://source.coop/ocean-icechunks/pacioos/ww3_hawaii/README.md) |

**NetCDF copies:** anonymous HTTPS (with byte ranges) or S3 (endpoint
`https://data.source.coop`, bucket `ocean-icechunks`), at

```
https://data.source.coop/ocean-icechunks/pacioos/<dataset>/netcdf/[<version>/]<year>/<file>.nc
```

Each file has an `.md5` beside it. The copies are **write-once**: a new version of a dataset
goes in a new folder (for example `netcdf/v3.0/`), and existing files are never changed.

**Known problems in the files** (relabelled WRF runs in 2010–13, WW3 cold starts, and others)
are listed in the
[file audit](https://github.com/ocean-icechunks/pacioos/blob/main/audit/report-pacioos.md).

## How this was built

The code, notes and audit are in
[ocean-icechunks/pacioos](https://github.com/ocean-icechunks/pacioos). The files were copied
from the PacIOOS server with `rclone` and checked against MD5 sums. Each store is built in the
same order: a written plan, a local smoke test, a scratch store with a viewer, then the
published store, which is validated anonymously from its public URL against netCDF-C reads of
the files.

The build files are published here too, beside the stores, as they are in the repository's
`stores/` folder: in each dataset folder (`roms_hiig/`, `roms_hiig_reanalysis/`, `ww3_hawaii/`)
the store's `requirements.txt`, smoke-test notebook(s), `build_store.py` and the modules it
uses, the saved ERDDAP metadata, and `how_store_created.md` (how it was made and how to rebuild
it); at this root, the shared modules and scripts (`pacioos_virtual.py`, `icechunk_utils.py`,
`best_series_update.py`, `publish_viewer.py`, ...) and the shared `requirements.txt`. The builds
are Python scripts rather than one production notebook; `build_store.py` is that step. The WRF
store's build files are in [`wrf_hi/build-source.zip`](https://data.source.coop/ocean-icechunks/pacioos/wrf_hi/build-source.zip).

Bundle publication leaves WRF untouched and stops before any upload if a destination README
contains Icechunker's generated metadata markers. Updates to those READMEs must preserve the
generated section through a separate reviewed prose update. Unmanaged README uploads are
conditional on the remote ETag, protecting edits made during publication.

## Citation and reuse

**The data are PacIOOS's.** Any use of the NetCDF copies or the Icechunk stores should cite
PacIOOS, as described at <https://www.pacioos.hawaii.edu/data-services/>.

**The code** that copied the files and built the stores was written by E. E. Holmes and is
released under the Apache License 2.0. It can be used without attribution.

## Credits

- **Data:** PacIOOS, University of Hawaiʻi at Mānoa. ROMS ocean model: Brian S. Powell. WRF
  weather model: Yi-Leng Chen. WaveWatch III wave model: Kwok Fai Cheung.
- **Icechunk packaging:** built with [Icechunk](https://icechunk.io),
  [VirtualiZarr](https://virtualizarr.readthedocs.io) and [Xarray](https://xarray.dev), hosted
  on [Source Cooperative](https://source.coop/ocean-icechunks/pacioos).
- **Viewer:** [gridlook](https://github.com/d70-t/gridlook), developed by Andrej Fast, Tobi
  Kölling, Fabian Wachsmann and contributors at DKRZ and the Max Planck Institute for
  Meteorology. The copy published at `pacioos/viewer/` is built from a fork,
  [eeholmes/gridlook](https://github.com/eeholmes/gridlook).
