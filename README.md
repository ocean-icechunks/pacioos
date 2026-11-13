# pacioos

Code for creating an Icechunk pipeline for PacIOOS model data: the Hawaiʻi regional ROMS
ocean model, WRF wind and weather, and WaveWatch III waves.

PacIOOS's public servers (THREDDS, ERDDAP) do not expose the model files themselves, so the
original NetCDF files are copied, unchanged, to the
[`ocean-icechunks/pacioos`](https://source.coop/ocean-icechunks/pacioos) product on Source
Cooperative. Virtual Icechunk stores are then built over those copies, so readers use Source
Cooperative and never load the PacIOOS server.

## What is on Source Cooperative (2026-11-13)

| Dataset (PacIOOS id) | Copies of the NetCDFs | Files | Size |
| --- | --- | --- | --- |
| ROMS forecast (`roms_hiig`) | `pacioos/roms_hiig/netcdf/` | 654 | 1.24 TB |
| WRF (`wrf_hi`) | `pacioos/wrf_hi/netcdf/` | 5,607 | 0.94 TB |
| WaveWatch III (`ww3_hawaii`) | `pacioos/ww3_hawaii/netcdf/` | 5,232 | 0.49 TB |
| ROMS reanalysis v2.0 (`roms_hiig_reanalysis`) | `pacioos/roms_hiig_reanalysis/netcdf/v2.0/` | 4,380 | 1.17 TB |

Each file has a `.md5` next to it. The ROMS hindcast (`roms_hiig_assim`, 3.37 TB) is not copied
yet ([#3](https://github.com/ocean-icechunks/pacioos/issues/3)). Each dataset's Icechunk store
will go in `pacioos/<dataset>/icechunk/`; none is built yet.

## What's here

| Path | What |
| --- | --- |
| [`upload/`](upload/) | Scripts that copy the files to Source Cooperative and check the copies; how to run them |
| [`docs/design/source-probe.md`](docs/design/source-probe.md) | What the public servers and the files showed: sizes, formats, chunking, options |
| [`docs/design/transfer-plan.md`](docs/design/transfer-plan.md) | The plain-language transfer plan shared with PacIOOS (snapshot) |
| [`docs/design/virtual-icechunk-explainer.md`](docs/design/virtual-icechunk-explainer.md) | "What a virtual Icechunk store is and how it is made" (snapshot) |

## Open work (hackweek, 2026-11-17)

- [#4](https://github.com/ocean-icechunks/pacioos/issues/4): upload new forecast, WRF and WW3
  runs automatically every day.
- [#2](https://github.com/ocean-icechunks/pacioos/issues/2): what happens when files change or
  a new version (reanalysis v3.0) arrives.
- [#3](https://github.com/ocean-icechunks/pacioos/issues/3): copy the ROMS hindcast.
- Build the virtual Icechunk stores.

The history of this work up to 2026-11-13 is in
[ocean-icechunks/icechunks](https://github.com/ocean-icechunks/icechunks) PRs #35, #39 and #42,
where it started.
