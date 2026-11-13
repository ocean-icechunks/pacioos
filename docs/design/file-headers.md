# What the copied files are, read from their headers (2026-11-13)

Read from the Source Cooperative copies, not the PacIOOS server: 8 bytes of every file
(`stores/survey_formats.py`), full headers of files sampled across the years, and the
ERDDAP "best" time axes. This supersedes the format guesses in
[`source-probe.md`](source-probe.md), which was written from THREDDS before there was a login.
The store plans built on it are issues #10–#14.

## Formats

| Product | Files | Format | Time dimension | Steps per file |
| --- | --- | --- | --- | --- |
| `roms_hiig` forecast | 654 | NetCDF-3 classic, big-endian | UNLIMITED (records interleave the 5 variables) | 57, 3-hourly, from 00Z |
| `roms_hiig_reanalysis` v2.0 | 4,380 | HDF5, little-endian, **uncompressed**, chunks `(1, 36, 195, 295)` | — | 8, 3-hourly |
| `ww3_hawaii` | 5,232 | NetCDF-3 classic, big-endian | UNLIMITED | 181 hourly (5 short runs in Aug 2013: 73, 106) |
| `wrf_hi` to 2017-08-10 | 2,569 | NetCDF-3 classic, big-endian | **fixed** (each variable one contiguous block) | 145–181 hourly, from 12Z |
| `wrf_hi` from 2017-08-16 | 3,038 | HDF5, little-endian, uncompressed, chunks `(1, 138, 213)` | — | ~136–166 hourly, from 03Z then 06Z |

Nothing is compressed, so every product admits computed references (the HYCOM trick): any
contiguous byte range of an array is a valid chunk.

## Things that look wrong and are deliberate

- **One 2-D plane per chunk everywhere.** ROMS: one depth level `(1, 1, 195, 295)`, 230 KB, cut
  from a record slab or an HDF5 chunk. WW3 and WRF: one step. Nothing larger is possible in the
  "best" series. Records interleave (ROMS, WW3), HDF5 chunks are separate allocations, and in
  WRF's fixed-dimension era a multi-step chunk would have to straddle runs of varying length on
  a regular chunk grid.
- **WRF is two groups.** Byte order is part of a Zarr array's codec chain, so big-endian
  NetCDF-3 and little-endian HDF5 bytes cannot be in one array. The first smoke run mixed them
  and read garbage in the HDF5 group. `manifest_variable` now asserts that every run feeding an
  array has one dtype and byte order.
- **Dtypes are declared native, with byte order in the `bytes` codec**, as in hycom: VirtualiZarr
  refuses later region writes against `>f4`.
- **The best rule is "newest run wins, lead 0 included", applied across all runs before
  splitting into groups.** Checked against ERDDAP at six overlap times (ROMS 2026-10-08T00Z and
  10-09T12Z, WW3 2026-11-05T12Z and 23Z, WRF 2026-11-07T06Z and 11-08T12Z). Each time ERDDAP's
  value equalled the newest covering run's value and no other run's.
- **ERDDAP's best axis leaves out times no run covers.** WW3 has 133,524 steps against 135,118
  on a regular hourly axis, and WRF 143,489 against 144,757, because some gaps are longer than a
  run (up to 32 days). ROMS (5,497) is complete. Whether to copy that is the open decision in
  #12 and #13.

## Metadata the stores must repair

- Reanalysis: **no `_FillValue`/`missing_value` at all**; land is netCDF's default fill
  `9.96921e36` (the same 1,118 cells as `mask == 0`). `temp` units are `ppt` (wrong); `salt`
  has no units.
- Forecast: land is `9.99e10`, declared only as `missing_value`; `salt` has no units.
- WW3: `_FillValue = -999`; `lon` is 0–360. WRF era 2 has no fill and no `standard_name`s.

## Smoke test (`stores/smoke_test.py`)

A few runs per product, local repos, reopened read-only with anonymous HTTPS access to the
copies. Every sampled plane was identical to netCDF-C `#mode=bytes` reads. It passed in a
clean venv built from `stores/requirements.txt` only (icechunk 2.3.1, virtualizarr 2.8.0,
zarr 3.4.2, xarray 2026.9.0, kerchunk 0.2.10) in 1.5 minutes.
