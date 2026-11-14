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
| **ROMS ocean forecast** (`roms_hiig`), daily runs | [Currents forecast](https://www.pacioos.hawaii.edu/currents/model-hawaii/) | 2025-01-01 to 2026-11-12 | `roms_hiig/netcdf/`, 654 files, 1.24 TB | not built yet |
| **WRF weather model** (`wrf_hi`), daily runs | [Wind forecast](https://www.pacioos.hawaii.edu/weather/model-wind-hawaii/) | 2010-05-14 to 2026-11-11 | `wrf_hi/netcdf/`, 5,607 files, 0.94 TB | not built yet |
| **WaveWatch III waves** (`ww3_hawaii`), daily runs | [Wave forecast](https://www.pacioos.hawaii.edu/waves/model-hawaii/) | 2011-06-21 to 2026-11-11 | `ww3_hawaii/netcdf/`, 5,232 files, 0.49 TB | not built yet |

The Icechunk stores are **virtual**. Each holds only Zarr metadata and byte-range references
to the NetCDF copies beside it, so both the store and its data are served by Source
Cooperative. The forecast copies stop at 2026-11-12; a daily update is planned.

## View it in a browser

| Dataset | Viewer |
|---|---|
| ROMS reanalysis v2.0 | [Open surface temperature in the viewer](https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/viewer/index.html) |

It draws in an ordinary browser, with no extension.

## How to open it

**Icechunk stores:** each dataset's README has tested loading code. Python 3.12 or newer and
icechunk 2.3 or newer are required; no credentials are needed.

| Dataset | Code to open |
|---|---|
| ROMS reanalysis v2.0 | [Open in Python](https://source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/README.md) |

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
the files. How the reanalysis store was made, and how to rebuild it:
[`how_store_created.md`](https://github.com/ocean-icechunks/pacioos/blob/main/stores/roms_hiig_reanalysis/how_store_created.md).

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
  Meteorology. The copy published beside the data is built from a fork,
  [eeholmes/gridlook](https://github.com/eeholmes/gridlook).
