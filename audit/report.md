# PacIOOS Hawaiʻi model copies: source-file audit

Audit run 2026-11-13 against the copies on Source Cooperative,
`s3://ocean-icechunks/pacioos/` (endpoint `https://data.source.coop`, anonymous).

**Scope.** Every file copied so far: the four products in the README table, 15,873 NetCDFs
(3.83 TB) and their 15,873 `.md5` sidecars. Every header was read. Data were read only
for two planes per file and for the cases named below.

Out of scope, because it is not copied: the ROMS hindcast (`roms_hiig_assim`, 3.37 TB), its
"replacement files", and the other regions on the PacIOOS server (#3, #2). Nothing in this
audit read from the PacIOOS server. ERDDAP was asked for four time axes and five single-point
values.

**Goal it serves.** One virtual Icechunk store per product, each serving the THREDDS "best"
series as PacIOOS does (#10–#13), and later an all-runs view (#14). For each problem the
question is the same as in the CEFI audit (noaa-nwfsc/cefi-icechunks#5): does it stop files
from sharing one array, or one time axis? And, because these are forecasts: **does it put
wrong data at a valid time in the best series?**

## Summary

- **The copies are complete and intact.**
  - Every file has a well-formed `.md5`.
  - For the 11,491 files uploaded in one part, the `.md5` equals Source Cooperative's ETag,
    which confirms the stored bytes without downloading them.
  - No file is truncated: every NetCDF-3 file is exactly the size its header implies, and
    every HDF5 chunk is allocated and inside the file.
  - Rebuilding the "best" time axis from the copies gives **exactly ERDDAP's axis for all four
    products**. ROMS forecast: 5,497 steps. Reanalysis: 35,040. WRF: 143,489. WW3: 133,500;
    ERDDAP has 24 more, from a newer run not yet copied. So no run that PacIOOS serves is
    missing from the copies.
- **Nothing is compressed, so every product can use computed references.** Chunking is not
  the problem here (unlike CEFI).
- **One thing blocks a single array: WRF changes format on 2017-08-16** (P1). Before that
  date it is NetCDF-3 big-endian with 9 variables; from then on, HDF5 little-endian with 8.
  The two eras need separate groups.
- **The real problems are in the forecasts' contents, and THREDDS serves them today:**
  - **WRF has 71 relabelled runs (2010–2013)** (P2). They are byte-for-byte copies of an
    earlier run with the dates moved on by 1 to 6 days, so their values sit at the wrong valid
    times. That is 1,717 steps (1.2%) of the best series. 115 other repeats are harmless
    fallbacks with the right times.
  - **WRF and WW3 have runs filed under the wrong date, or two runs with the same start**
    (P3). THREDDS breaks the tie by taking the later file name, and a build must do the same.
  - **The time labels of 8 WW3 files (2020-04-27 to 05-04) look one day early** (P4). This is
    the same error PacIOOS fixed by hand in 20 other files in March 2024. It affects 216 best
    steps.
  - **81 WW3 runs are cold starts** (P5). Their first step is an all-zero wave field, and
    because the best rule takes lead 0, 81 best steps show `Thgt = 0` everywhere. Checked on
    ERDDAP: it shows 0.0.
- **The metadata needs repairs in the stores, not in the files** (P7): the reanalysis has no
  fill attribute and `temp` units of `ppt`, `salt` has no units, and the ROMS forecast `mask`
  changes dtype between files.

## Status of each product

"Best = ERDDAP" means the best time axis rebuilt from the copies equals ERDDAP's over the
period copied.

| Product | Files | Size | Dates (file names) | Formats | Best = ERDDAP | Problems |
|---|---:|---:|---|---|---|---|
| `roms_hiig` forecast | 654 | 1.24 TB | 2025-01-01 … 2026-11-12 | NetCDF-3, big-endian, UNLIMITED time | yes (5,497) | P7 |
| `roms_hiig_reanalysis` v2.0 | 4,380 | 1.17 TB | 2009-01-01 … 2020-12-28 | HDF5, little-endian, uncompressed, chunks `(1, 36, 195, 295)` | yes (35,040) | P7, P8 (sidecars) |
| `wrf_hi` | 5,607 | 0.94 TB | 2010-05-14 … 2026-11-11 | NetCDF-3 big-endian (fixed time) to 2017-08-10; HDF5 little-endian `(1, 138, 213)` after | yes (143,489) | P1, P2, P3, P6, P9, P10 |
| `ww3_hawaii` | 5,232 | 0.49 TB | 2011-06-21 … 2026-11-11 | NetCDF-3, big-endian, UNLIMITED time | yes (133,500) | P3, P4, P5, P6, P9, P11 |

## Problems

Each problem says where it is, the evidence, why it matters for the store, and the script that
shows it. Every finding is also a row in `audit/out/findings.csv`.

### P1. WRF: two formats, two byte orders, two variable sets

- **Evidence:**
  - 2,569 files from 2010-05-14 to 2017-08-10: NetCDF-3 classic, big-endian `float32`,
    `time` a fixed dimension (each variable one contiguous block), 9 variables including
    `sst`, `_FillValue = 99999`, time units `hours since 2000-01-01 00:00:00 UTC`.
  - 3,038 files from 2017-08-16: HDF5, little-endian, uncompressed, chunks `(1, 138, 213)`,
    8 variables (no `sst`), no fill attribute, no `UTC` in the time units, different
    `long_name`s and unit spellings (`%` against `percentage`).
  - Run start hours: 12Z in era 1; 03Z (2017–18), then 06Z in era 2.
- **Why it matters:** byte order is part of a Zarr array's codec chain, so the two eras cannot
  share an array. Two groups (#12). Grids are identical across the change.
- **Repro:** `checks.py` (`schema` and `store` rows); the smoke test in `stores/` (an
  attempt to mix them read garbage).

### P2. WRF: 71 runs are relabelled copies of an earlier run

- **Evidence:** 186 WRF files share a byte-identical first or last `Tair` plane with an
  earlier file. Comparing the shift in the data with the shift in the time labels splits them
  in two:

  | Kind | Files | Years | What it is |
  |---|---:|---|---|
  | **relabelled copy** | **71** | 2010–2013 | The earlier run's data, from lead 0, with the dates moved on by 24 h (49 runs), 48 h (8), 72 h (3), 96 h (2), 120 h (2) or 144 h (7). Every value is at the wrong time. |
  | fallback tail | 115 | 2012–2022 | The earlier run from lead 24 on, with matching times. The values are right for their times; the file is just not a new forecast. |

  Confirmed step by step for three pairs. `wrf_hi_20110916.nc` holds all 169 steps of
  `wrf_hi_20110915.nc` (data offset 0 h), labelled 24 h later. `wrf_hi_20140313.nc` is
  `wrf_hi_20140312.nc` steps 24–180, labelled 24 h later: consistent, so a fallback.
- **Why it matters:** in the best series these runs win their first day (or more), so **1,717
  of 143,489 WRF best steps (1.2%) carry data from another time**. PacIOOS's THREDDS and
  ERDDAP serve the same values. A virtual store cannot fix a value, but it can leave those
  steps out or flag them. That is for PacIOOS and Eli to decide.
- **Limits:** only byte-identical planes were detected. A copy that was regridded or rewritten
  in between would not show up. The full list is `audit/out/wrf_repeated_runs.csv`.
- **Repro:** `repro/01_wrf_repeated_runs.py`; exposure in `repro/03_best_series_exposure.py`.

### P3. Runs filed under the wrong date, and two runs with the same start

- **Evidence:**

  | Files | First step | What |
  |---|---|---|
  | `wrf_hi_20160104.nc` = `wrf_hi_20160105.nc` | 2016-01-04 12Z both | byte-identical (same MD5) |
  | `wrf_hi_20191013.nc` = `wrf_hi_20191014.nc` | 2019-10-13 06Z both | byte-identical |
  | `wrf_hi_20220601.nc`, `wrf_hi_20220602.nc` | 2022-06-01 06Z both | same data, different bytes |
  | `wrf_hi_20220221.nc`, `wrf_hi_20220222.nc` | 2022-02-22 06Z both | **two different runs** of 02-22; both labels test right (`repro/02`) |
  | `ww3hawaii_20200426.nc`, `ww3hawaii_20200427.nc` | 2020-04-26 21Z both | different data; see P4 |

  Seven WRF files and eight WW3 files have a first step that is not on the date in their name
  (`checks.py`, "first time step is not on the date in the file name").
- **Why it matters:** "newest run wins" is ambiguous when two runs start at the same time.
  **THREDDS takes the file with the later name.** ERDDAP served `wrf_hi_20220222.nc` at
  2022-02-23T00Z (24.9866 against 24.8806 from 0221), and `ww3hawaii_20200427.nc` at
  2020-04-27T06Z (1.62 against 1.72 from 0426). A build must order ties by file name to match.
- **Repro:** `checks.py` (`time` rows), `repro/02_time_alignment.py`.

### P4. WW3 2020-04-27 … 05-04: time labels probably one day early

- **Evidence:** these 8 files start at 21Z on the day *before* the date in their name. All
  other WW3 runs of that era start on their name date. A time-alignment test compares each
  file with its neighbours at matched valid times, after skipping spin-up. Two forecasts of the
  same time differ least when the labels are right. Against `ww3hawaii_20200505.nc`, all six
  files that overlap it fit best shifted **24 h later**. Against 0426 the result is mixed,
  because 0426 itself overlaps the suspect files.
- **Context:** PacIOOS fixed the same error in 20 files (2024-03-01 … 03-20). Their `history`
  reads `ncap2 -s time[time]=time+1440` (22 March 2024), and those files now test right.
- **Why it matters:** if confirmed, 216 WW3 best steps (2020-04-27 … 05-05) are a day off, in
  the copies and on ERDDAP. **Suspected, not proven:** ask PacIOOS. The copies must not be
  edited (write-once); a corrected file would be a new version (#2).
- **Repro:** `repro/02_time_alignment.py`.

### P5. WW3 cold starts: 81 runs begin with an all-zero wave field

- **Evidence:** in 81 runs (2011–2026, most in 2011–13), the first step of `Thgt` is exactly 0
  over the whole sea, the signature of a model restarted from rest. ERDDAP serves `Thgt = 0.0`
  at 2026-10-27T06Z, the first step of the cold start `ww3hawaii_20261027.nc`.
- **Why it matters:** the best rule takes lead 0, so each cold start puts one all-zero step
  (and some hours of spin-up) into the best series: 81 steps. Following THREDDS exactly keeps
  them. A store could also mark or skip lead 0 of a cold start. That is a decision for #13.
- **Repro:** `checks.py` (`values`, "first step is constant").

### P6. Gaps longer than a run: the best series has holes

- **Evidence:** WRF has 16 stretches that no run covers, from 6 h to 16 days (the longest
  2024-01-22 … 02-07). WW3 has 11, up to 24 days (2015-12-06 … 12-30, and 2025-10-24 …
  11-16). ERDDAP leaves the same times out.
- **Why it matters:** the time-axis decision in #12 and #13. Matching THREDDS means an
  irregular axis.
- **Repro:** `checks.py` (`coverage` rows).

### P7. Metadata the stores must repair

- **Reanalysis:** no `_FillValue` or `missing_value` on any science variable. Land holds
  netCDF's default fill `9.96921e36`, and the HDF5 dataset fill value is the same. `temp` has
  `units = "ppt"` (it is °C); `salt` has no units. All 4,380 files were written 2023-02-16 …
  02-21 (from `history`; `source-probe.md` said March, from the server's file times).
- **ROMS forecast:** land is `9.99e10`, declared only as `missing_value`; `salt` has no units.
  `mask` is `int16` in 364 files and `float32` in 290, interleaved through 2025-10 … 2026-08.
  The values are identical (0/1, 1,118 land cells), and it is the only difference between
  files.
- **ROMS forecast and reanalysis** have identical `lat`, `lon`, `depth` and `mask` values.
- **Repro:** `checks.py` (`grid`, `metadata`), `docs/design/file-headers.md`.

### P8. Sidecars that cannot be checked without downloading

- All 4,380 reanalysis files and two ROMS forecast files (2026-11-11, -12) were uploaded in
  parts, so their ETag is not an MD5. Their bytes were checked by sampled downloads during the
  copy (`upload/README.md`), not by this audit.
- **Repro:** `scan_md5.py`.

### P9. Files edited after they were written

- WW3: the 20 files of P4's context (2024-03-01 … 03-20, time shifted +1,440 min on
  2024-03-22).
- WRF era 2: every file passed through `ncap2 -s time=floor(time)`. `wrf_hi_20170816.nc` was
  written 2017-08-28.
- **Why it matters:** PacIOOS edits files in place. The copies are snapshots, and an edit made
  on the server after a file was copied is not seen (#2; the upload script only notices a size
  change).

### Smaller inconsistencies (do not block a build)

- **P10. WRF `wrf_hi_20190429.nc` repeats its last time step:** 2019-05-06T00Z appears twice
  (166 steps, one zero interval). A build must drop one.
- **P11. WW3's land mask changes on 2015-12-30,** after the 32-day outage: 1,051 land cells
  before, 1,062 after; `lat`/`lon` are unchanged. WW3 has no `mask` variable, so this shows
  only in where the fill sits.
- **WRF era-1 fill frame:** `Tair` has 1,777 fill cells around the edges of the grid until
  2014-01-31, 340 from 2014-02-01 (180 on 2014-02-07), and none in era 2. The covered area
  changes twice.
- **Two WW3 files in the wrong year folder:** `ww3hawaii_20201230.nc` and
  `ww3hawaii_20201231.nc` are under `netcdf/2021/`. Moving them would be a delete on a
  write-once prefix, so leave them and let the build list files rather than build paths.
- **Short runs:** 84 WRF runs (1 to 123 steps) and 5 WW3 runs (73 and 106 steps) are much
  shorter than usual. The best rule handles them.

## Checked and found consistent

- **Files:** every path follows `pacioos/<product>/netcdf/[v2.0/]<year>/<name>` (apart from the
  two WW3 files above), every name matches its product pattern, no name repeats, and there is
  no stray object.
- **Integrity:** all 15,873 headers parse. NetCDF-3 sizes equal what the headers imply. HDF5
  files have every chunk allocated, no filters and no subgroups.
- **Time:** units are constant within each product apart from P1. Steps are regular (3-hourly
  ROMS, hourly WRF and WW3) apart from P10. The reanalysis files join end to end (35,040 steps,
  no gap). ROMS forecast runs all have 57 steps from 00Z.
- **Grids:** `lat`, `lon` and `depth` are identical across each product's files, and across
  WRF's two eras.
- **Values:** in 31,746 sampled planes, none is all fill, none is out of range, and none is
  constant except the WW3 cold starts. ROMS fill cells equal the land mask in every file.

## Method

Everything reads the copies on Source Cooperative anonymously. It reads metadata only, plus
two small planes per file (`scan_values.py`, 4 GB in all) and the files named in the repro
scripts.

| Step | Script | Output (in `audit/out/`) |
|---|---|---|
| List every object, parse path and name | `inventory.py` | `inventory.parquet` (not committed) |
| Read every header (NetCDF-3 with its own parser, HDF5 via h5py `chunk_iter`) and small coordinates | `scan_headers.py` | `headers.jsonl` (86 MB, not committed) |
| Read every `.md5`, compare with name and ETag | `scan_md5.py` | `md5.parquet` (not committed) |
| Read the first and last top plane of one variable per file | `scan_values.py` | `values.parquet` (not committed) |
| Fetch ERDDAP's time axes (4 requests) | `fetch_erddap_axes.py` | `erddap_time_*.csv` (not committed) |
| Run all checks | `checks.py` | `findings.csv`, `products.csv`, `runs.csv` |
| WRF repeated runs | `repro/01_wrf_repeated_runs.py` | `wrf_repeated_runs.csv` |
| Time-alignment test of suspect files | `repro/02_time_alignment.py` | – |
| Best-series steps taken from problem runs | `repro/03_best_series_exposure.py` | – |

The five single-point ERDDAP comparisons in P3 and P5 were made by hand; their values are
quoted above.

To rerun, from the repo root:

```bash
/srv/conda/bin/python3.12 -m venv audit/.venv
audit/.venv/bin/pip install --no-cache-dir -r audit/requirements.txt
audit/.venv/bin/python -I audit/inventory.py
audit/.venv/bin/python -I audit/scan_headers.py --procs 6
audit/.venv/bin/python -I audit/scan_md5.py
audit/.venv/bin/python -I audit/scan_values.py
audit/.venv/bin/python -I audit/fetch_erddap_axes.py
audit/.venv/bin/python -I audit/checks.py
audit/.venv/bin/python -I audit/repro/01_wrf_repeated_runs.py   # then 02, 03
```

Ran with numpy 2.5.4, pandas 3.1.1, pyarrow 26.0.1, obstore 0.12.1, h5py 3.16.0 and fsspec
2026.9.0 on Python 3.12.12.

On a 4-CPU hub with a 7.8 GB memory cap, the NetCDF-3 headers take about 6 minutes (32
threads) and the HDF5 headers about 30 (6 processes). The value scan takes 1.5 minutes.
**16 HDF5 processes set off the OOM killer** (61 kills on a shared hub); keep to 6. The scan
is resumable: rerun to pick up where it stopped.

## Limitations

- **Only two planes per file were read**, of one variable, at the top level. A bad stretch in
  the middle of a run, or in another variable, would not be seen. The repeated-run and
  cold-start findings rest on those planes.
- **Repeated runs were found only when byte-identical** (P2). The time-alignment test (P4) is
  statistical and was run only on suspect files, not on every run.
- **Time values of NetCDF-3 record files** were read in full for 1 file in 25 and for every
  file with an unusual length. For the rest, the first, second and last values were read, and
  regular spacing was checked from those.
- **The MD5s of 4,382 multipart uploads** were not checked here (P8).
- **Nothing on the PacIOOS server** (hindcast, replacement files, other regions) was audited.

## Appendix: files affected

| Problem | Files |
|---|---|
| P2 relabelled WRF runs (71) | `audit/out/wrf_repeated_runs.csv`, `kind = relabelled copy` |
| P3 duplicate or misdated runs | the table in P3; `findings.csv` rows `time` / "two files start at the same time" |
| P4 WW3, labels probably a day early | `ww3hawaii_20200427.nc` … `ww3hawaii_20200504.nc` (8) |
| P5 WW3 cold starts (81) | `findings.csv`, `values` / "first step is constant" |
| P10 repeated time step | `wrf_hi_20190429.nc` |
| Wrong year folder | `ww3_hawaii/netcdf/2021/ww3hawaii_20201230.nc`, `…_20201231.nc` |
