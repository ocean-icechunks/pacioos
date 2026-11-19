# stores/

Code for the virtual Icechunk stores over the NetCDF copies on Source Cooperative.
For persistent server installation and scheduled uploads/updates, see
[`ops/README.md`](../ops/README.md). Its runner checks a recent window on normal runs and
provides a separate historical verification command; the standalone scripts below retain
their existing behavior. Bootstrap and cron activation are manual.

`smoke_test.py` is the smoke test behind issues #10–#14. The **reanalysis store (#11) is
published**, at `ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk` (tag `v2.0`), built by
`roms_hiig_reanalysis/build_store.py`. The **ROMS forecast best-series store (#10) is published**, at
`ocean-icechunks/pacioos/roms_hiig/icechunk`, built by `roms_hiig/build_store.py`. The **WW3
best-series store (#13) is published**, at `ocean-icechunks/pacioos/ww3_hawaii/icechunk`, built by
`ww3_hawaii/build_store.py`. The PacIOOS team published the WRF HDF5-era store at
`ocean-icechunks/pacioos/wrf_hi/icechunk`; its build source and README remain team-managed,
outside Icechunker's store/README automation and the bundle publisher.

| File | What |
| --- | --- |
| `pacioos_virtual.py` | Computed references: header scans (NetCDF-3 via kerchunk, HDF5 via h5py), the THREDDS "best" rule, `ManifestArray`s with one 2-D plane per chunk, repository config |
| `smoke_test.py` | Builds a few runs of each product into local repos, reopens them read-only, and compares sampled planes with netCDF-C reads |
| `survey_formats.py` | Reads 8 bytes of every copied file: NetCDF-3 or HDF5, and the NetCDF-3 record count |
| `requirements.txt` | What the scripts need, checked in a clean venv |
| `icechunk_utils.py` | Source Cooperative credentials and repositories (copied from ocean-icechunks/icechunks) |
| `publish_viewer.py` | Builds the gridlook browser viewer and uploads it: one viewer for the product at `pacioos/viewer/`, listing every store (adapted from ocean-icechunks/icechunks) |
| `publish_bundle.py` | Publishes committed build files beside the stores, including the API-key helper; excludes tests and WRF, refuses managed READMEs and protects other README uploads with ETag conditions |
| `roms_hiig_reanalysis/` | Reanalysis v2.0 store (#11). Start with its [`how_store_created.md`](roms_hiig_reanalysis/how_store_created.md) |
| `roms_hiig/` | ROMS forecast store, best time series (#10). Start with its [`how_store_created.md`](roms_hiig/how_store_created.md) |
| `ww3_hawaii/` | WaveWatch III store, best time series, with cold-start flags and ERDDAP metadata (#13). Start with its [`how_store_created.md`](ww3_hawaii/how_store_created.md) |

```bash
/srv/conda/bin/python3.12 -m venv ~/venvs/pacioos
~/venvs/pacioos/bin/pip install --no-cache-dir -r stores/requirements.txt
~/venvs/pacioos/bin/python -I stores/smoke_test.py /tmp/pacioos-smoke   # about 1.5 minutes
```

The smoke test reads only the public copies at `https://data.source.coop/ocean-icechunks/pacioos/`,
anonymously. What the file headers showed, and why the code does what it does, is in
[`docs/design/file-headers.md`](../docs/design/file-headers.md).

Preview the build bundle with `python stores/publish_bundle.py --dry-run`; a preview may
include uncommitted changes and makes no network requests. Actual publication requires clean
committed source files. The bundle adds `upload/source_coop_credentials.py` at the product
root beside `icechunk_utils.py`; that module supports both this downloaded layout and the
repository/Icechunker runtime layout. Shared requirements include `boto3` for authentication.
Before publishing, diff live READMEs against git. Icechunker-managed READMEs stop the whole
publication before any uploads; updating their prose needs a separate reviewed edit that
preserves the generated section. No WRF files are published by this command.
