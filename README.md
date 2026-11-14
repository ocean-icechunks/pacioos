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
goes in `pacioos/<dataset>/icechunk/`. The reanalysis store is built (tag `v2.0`, 2026-11-14):
`https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk`, with a
[viewer](https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/viewer/index.html)
(see [its README](stores/roms_hiig_reanalysis/README.md), and
[`how_store_created.md`](stores/roms_hiig_reanalysis/how_store_created.md) for how it was made).
The others are not built yet.

## Start here: notes for the PacIOOS team

Four short documents, written for PacIOOS (the live versions; the repo keeps snapshots of the
first two in `docs/design/`):

- [**PacIOOS models on Source Cooperative: how to upload, what's next, and working with an agent**](https://claude.ai/artifact/MmW3VYYgR6enaALtqToX31)
  (2026-11-13): running the upload yourselves, the open tasks, and using a coding agent to
  learn this repo and build the stores.
- [**Getting the PacIOOS model files onto Source Cooperative**](https://claude.ai/artifact/4Nqhx91MozRLbfjYXmfpP7)
  (2026-11-10): the transfer plan, the routes for copying, and the questions for PacIOOS.
- [**PacIOOS model files on Source Cooperative: audit and chunking options**](https://claude.ai/artifact/G67caCdBJ2Z7hupYuJZHnJ)
  (2026-11-13): what the file audit found, every chunking option for the stores, and whether
  reprocessing would be better (snapshot: [`audit/report-pacioos.md`](audit/report-pacioos.md)).
- [**How a virtual Icechunk store gets made**](https://claude.ai/artifact/BTCTko294KTQebZW6Y2K4o)
  (2026-11-10): what a virtual store is, why the files go to the cloud first, and where
  missing metadata goes.

## What's here

| Path | What |
| --- | --- |
| [`upload/`](upload/) | Scripts that copy the files to Source Cooperative and check the copies; how to run them |
| [`audit/`](audit/) | File audit of the copies (2026-11-13): [`report.md`](audit/report.md) (technical), [`report-pacioos.md`](audit/report-pacioos.md) (for the PacIOOS team), [`how_audit_created.md`](audit/how_audit_created.md) (a prompt to redo it) |
| [`stores/`](stores/) | Virtual Icechunk store code: the smoke test behind issues #10–#14, and the reanalysis build (#11) |
| [`docs/design/file-headers.md`](docs/design/file-headers.md) | What the copied files are, read from their headers; the reasons behind the store design |
| [`docs/design/source-probe.md`](docs/design/source-probe.md) | What the public servers and the files showed: sizes, formats, chunking, options |
| [`docs/design/transfer-plan.md`](docs/design/transfer-plan.md) | The plain-language transfer plan shared with PacIOOS (snapshot) |
| [`docs/design/virtual-icechunk-explainer.md`](docs/design/virtual-icechunk-explainer.md) | "What a virtual Icechunk store is and how it is made" (snapshot) |

## Open work (hackweek, 2026-11-17)

- [#4](https://github.com/ocean-icechunks/pacioos/issues/4): upload new forecast, WRF and WW3
  runs automatically every day.
- [#2](https://github.com/ocean-icechunks/pacioos/issues/2): what happens when files change or
  a new version (reanalysis v3.0) arrives.
- [#3](https://github.com/ocean-icechunks/pacioos/issues/3): copy the ROMS hindcast.
- Build the virtual Icechunk stores: #10 (ROMS forecast), #11 (reanalysis), #12 (WRF), #13 (WW3),
  #14 (all-runs view for forecast skill).

The history of this work up to 2026-11-13 is in
[ocean-icechunks/icechunks](https://github.com/ocean-icechunks/icechunks) PRs #35, #39 and #42,
where it started.

## Reuse and citation

**The code** in this repository, which copies the PacIOOS files and builds the Icechunk stores,
was written by E. E. Holmes and is released under the [Apache License 2.0](LICENSE). You are free
to use, copy, modify and redistribute it, including commercially. Attribution is appreciated but
not required: you do not need to cite it or ask permission.

**The data** are PacIOOS's. The NetCDF copies and the Icechunk stores on Source Cooperative hold
PacIOOS model output unchanged, so any use of them should cite PacIOOS, as described at
<https://www.pacioos.hawaii.edu/data-services/>.
