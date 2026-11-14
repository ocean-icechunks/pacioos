# PacIOOS Hawaiʻi model files on Source Cooperative: audit and chunking options

Prepared 2026-11-13 for the PacIOOS team. The live, editable copy is a Claude Doc:
<https://claude.ai/artifact/G67caCdBJ2Z7hupYuJZHnJ>; this file is its snapshot. It summarizes the file audit of the copies on
Source Cooperative (full technical report: `audit/report.md` in
[ocean-icechunks/pacioos](https://github.com/ocean-icechunks/pacioos)). It also sets out the
chunking choices for the virtual Icechunk stores, and what a different file layout would
make possible.

**What was audited.** Every file copied so far: 15,873 NetCDFs (3.83 TB) in four datasets. The
ROMS forecast (`roms_hiig`), the ROMS reanalysis v2.0 (`roms_hiig_reanalysis`), WRF
(`wrf_hi`) and WaveWatch III (`ww3_hawaii`). Every file's header was read, two data planes per
file, and the time axis your ERDDAP serves for each dataset. Nothing was read from your
servers apart from four ERDDAP time-axis requests and five single values. The ROMS hindcast is
not copied yet, so it is not covered.

## In short

- **The copies are complete and match what PacIOOS serves.** Every file has a checksum, and
  none is truncated. Rebuilding THREDDS's "best" time series from the copies gives exactly
  the time axis ERDDAP serves, for all four datasets.
- **A few forecast runs contain problems** that are in THREDDS and ERDDAP today too (see
  [What we found](#what-we-found)). The biggest:
  - 71 WRF runs from 2010–2013 are copies of an earlier day's run with new dates;
  - 8 WW3 files from 2020 look one day early;
  - 81 WW3 runs start from a flat sea.

  We would like to check these with you ([Questions for PacIOOS](#questions-for-pacioos)).
- **The stores can be built from the files as they are.** Nothing is compressed, so the stores
  can point at exactly the piece of a file a reader needs. That makes **maps fast**.
- **Time series at a point will be slow whatever we choose**, because of how time is laid out
  in the files. The only fix is to rewrite the NetCDFs in a different layout. The
  [last section](#would-rewriting-the-netcdfs-be-worth-it) discusses whether that is worth doing, and
  what a better file layout would look like for future files.

## What we found

| Dataset | What is fine | What needs attention |
|---|---|---|
| ROMS forecast | All 654 runs: NetCDF-3, 57 three-hourly steps from 00Z, the same grid. Land cells match `mask` in every file. | `salt` has no units. Land is marked only by `missing_value = 9.99e10`. `mask` is `short` in some files and `float` in others (same values). |
| ROMS reanalysis v2.0 | All 4,380 days, back to back (35,040 steps), identical grid to the forecast. | **No fill value is declared**: land holds netCDF's default `9.96921e36`. **`temp` units are `ppt`** (should be °C); `salt` has no units. No version number in the files. |
| WRF | Grid unchanged throughout. | **Two formats**: NetCDF-3 with 9 variables (including `sst`) to 2017-08-10, NetCDF-4 with 8 after. **71 runs (2010–2013) are an earlier run with the dates moved on by 1–6 days**, so 1.2% of the "best" series has values at the wrong time. Four pairs of runs start at the same time; two pairs are identical files. One file repeats its last time step. |
| WW3 | All NetCDF-3, the same grid throughout. | **8 files (2020-04-27 to 05-04) look one day early**, the same problem you corrected in 20 files in March 2024. **81 runs start from an all-zero wave field** (cold starts), which appears in the best series as one step of zero wave height. The land area changes once (2015-12-30). |

Details, file lists and the scripts that reproduce each finding are in `audit/report.md`.

## Chunking: what the stores can do

### What a chunk is, and why it matters here

A virtual store does not copy the data. It records, for each **chunk**, which file it is in
and which bytes. A reader fetches whole chunks. So the chunk shape decides what each kind of
question costs:

- **a map** (one time, one depth, every point): the cost is the bytes in the chunk;
- **a profile** (one time, one point, every depth): the number of chunks it touches;
- **a time series** (one point, one depth, every time): one chunk per time step, so the number
  of chunks, which is the number of requests, is what matters.

Your files are uncompressed, so a chunk can be **any contiguous range of bytes** in a file. We
compute it from the file's header, as we did for HYCOM. That lets us cut large blocks into
smaller pieces, for example one depth level instead of all 36. It cannot join pieces that are
not next to each other in the file. In particular:

- In the ROMS forecast and WW3 files, `time` is the record (UNLIMITED) dimension. Each time
  step stores every variable one after another, so one variable's consecutive time steps are
  never next to each other.
- A chunk can never span two files, and each forecast run is its own file.
- A chunk cannot be a lat/lon tile, because part of a map row is not contiguous with the next
  row's part.

### Every possible chunk, and what it costs

Costs are for one 3-D variable over the full "best" series as copied: ROMS forecast 5,497
steps, reanalysis 35,040, WW3 133,500, WRF 143,489.

| Dataset | Chunk (time, depth, lat, lon) | Size | One map | Full-depth profile | Time series at one depth | Possible? |
|---|---|---:|---|---|---|---|
| ROMS forecast | **(1, 1, 195, 295): one depth level** | **230 KB** | **230 KB, 1 request** | 8.3 MB, 36 requests | 1.3 GB, 5,497 requests | **yes: recommended** |
| | (1, 6, 195, 295): 6 levels | 1.4 MB | 1.4 MB | 8.3 MB, 6 requests | 7.6 GB, 5,497 requests | yes |
| | (1, 12, 195, 295): 12 levels | 2.8 MB | 2.8 MB | 8.3 MB, 3 requests | 15 GB, 5,497 requests | yes |
| | (1, 36, 195, 295): all depths | 8.3 MB | 8.3 MB | 8.3 MB, 1 request | 46 GB, 5,497 requests | yes (the file's own layout) |
| | several time steps | | | | | **no**: steps interleave with other variables |
| ROMS reanalysis | **(1, 1, 195, 295): one depth level** | **230 KB** | **230 KB, 1 request** | 8.3 MB, 36 requests | 8.1 GB, 35,040 requests | **yes: recommended** |
| | (1, 6 or 12, 195, 295) | 1.4 / 2.8 MB | 1.4 / 2.8 MB | 6 / 3 requests | 48 / 97 GB, 35,040 requests | yes |
| | (1, 36, 195, 295): all depths | 8.3 MB | 8.3 MB | 1 request | 290 GB, 35,040 requests | yes (the file's own chunk) |
| | (8, 36, 195, 295): a whole day, all depths | 66 MB | 66 MB | 66 MB, 1 request | 290 GB, 4,380 requests | **only for `temp`, `salt`, `zeta`**: `u` and `v` chunks alternate in the file |
| | several steps at one depth | | | | | **no**: not contiguous |
| WW3 | **(1, 1, 101, 141): one step** | **57 KB** | **57 KB** | (one level) | 7.6 GB, 133,500 requests | **the only option** |
| WRF to 2017 | **(1, 138, 213): one step** | **118 KB** | **118 KB** | (surface) | 7.5 GB, 63,498 requests | **the only option** in a best series |
| | several steps | | | | | contiguous within a run, but best runs change at irregular hours: even 2-step chunks would straddle two runs 4% of the time |
| WRF from 2017 | **(1, 138, 213): one step** | **118 KB** | **118 KB** | (surface) | 9.4 GB, 79,991 requests | **the only option**: the netCDF-4 library put index blocks between chunks |

Number of chunks to record: about 0.8 M (forecast), 5.1 M (reanalysis), 1.2 M (WW3) and
1.2 M (WRF). All are manageable. The index is split by year so a reader only loads what it
needs.

### Recommended, and why

- **ROMS forecast and reanalysis: one depth level per chunk.** Most use of these data is maps,
  usually of the surface: in the PacIOOS viewers, in gridlook, and in a typical notebook.
  One level reads 230 KB instead of 8.3 MB, 36× less. A full-depth profile then takes 36
  small requests made in parallel, which is fast. Larger depth groups (6 or 12 levels) would
  only help profiles, which are rare, and make every map and time series 6–12× more
  expensive.
- **WW3 and WRF: one time step**, because nothing else is possible.
- **Time series will be slow in every case:** one request per time step, 5,497 for a forecast
  point series, 35,040 for the reanalysis, 130–145 K for WRF and WW3. Readers can raise their
  request concurrency, which helps, but the count is fixed by the file layout. This is the
  main argument for the next section.

## Would rewriting the NetCDFs be worth it?

**For WRF, yes:** rewriting its 2010–2017 files is the one change that gives a single, simple
store. For the reanalysis it is the only way to make time series fast. For the forecasts,
writing future runs well matters more than rewriting the archive.

Rewritten files would be a new version beside the originals, and the virtual stores would
point at them instead. They can be made from the copies on Source Cooperative without touching
PacIOOS servers. They should be published only with PacIOOS's approval, as PacIOOS data.

| Dataset | What a rewrite would fix | Rewritten layout | Size | Worth it? |
|---|---|---|---|---|
| **WRF to 2017** | Two formats become one: one array per variable and one store group, instead of two groups readers must join. The 71 relabelled runs and the duplicate files can be dropped or marked in the new version. | **Minimal:** the 2017-onward layout exactly (NetCDF-4, little-endian, uncompressed, one step per chunk, the same attributes). `sst` stays as an extra variable that is empty after 2017. **Better:** the whole WRF archive in the time-chunked layout below. | 2,569 files, 0.47 TB (whole archive 0.94 TB) | **Yes**: the largest gain for the least data |
| **ROMS reanalysis** | Time series: one chunk per day or more instead of per step. A declared fill value, `temp` and `salt` units, a version number. | Compressed NetCDF-4, chunks of (8 steps = 1 day, 1 depth, a quarter of the grid). A point series drops from 35,040 requests to 4,380, and a map takes 4 requests. With fixed 30-day files, (240, 1, quarter grid) gives 146 requests. | 4,380 files, 1.17 TB, about half that compressed | **Yes, if time series matter**: it is static, so this is done once |
| **ROMS forecast** | Time series in the best series: one chunk per run-day. | Compressed NetCDF-4, chunks of (8, 1, quarter grid) aligned to the run start. A point series drops from 5,497 requests to 688. | 654 files, 1.24 TB | **Mainly for future runs**: the archive covers under 2 years |
| **WW3** | Time series. The 2020 times can be corrected and the cold starts marked in the new version. | Compressed NetCDF-4, chunks of (24 steps, 1, 101, 141) aligned to the run start. A point series drops from 133,500 requests to about 5,600. | 5,232 files, 0.49 TB | **Only if wave time series are a common need** |

Three constraints apply to any rewrite:

- **A store joins files along time, so every file must hold a whole number of time chunks.**
  A 1-day chunk fits any daily file; a 30-day chunk does not fit calendar months. The CEFI
  daily files broke on exactly this.
- **Compression ends the byte-range cutting described above**, so the chunks must be right
  when the files are written.
- **The originals stay unchanged** on Source Cooperative, and THREDDS keeps serving them. The
  rewritten files hold the same values (except where a fix is made) in a different layout,
  under a new version folder.

### A better way to structure the NetCDF files

For files that will be read from the cloud, and especially through a virtual store:

- **NetCDF-4 (HDF5), chunked and compressed.** zlib level 1–4 or zstd, with the shuffle filter.
  The probe measured about 1.9× smaller for `temp`. Compression rules out the byte-range tricks
  above, so choose chunks that are good on their own.
- **Chunk along time within each file**, with the time chunk matched to how the files join
  up:
  - **Forecast runs:** make one chunk hold **exactly one day** of the run, aligned to the
    run's start (8 steps for ROMS, 24 for WRF and WW3), and start every run at the same hour.
    Then the "best" series, which takes each run's first day, is made of whole chunks. A point
    time series reads one chunk per day, 8–24× fewer requests, and the all-runs view works too.
  - **Reanalysis:** daily files with 1-day chunks, or files of a fixed length (for example
    30 days) holding a whole number of longer chunks. Calendar months and years do not divide
    evenly.
- **One depth level per chunk**, and **lat/lon tiles** (for example the grid in halves or
  quarters). A point time series then reads only the tile it needs, and a map reads 2–4 tiles.
- **The same chunk shape in every file of a dataset, forever.** A store can only join files
  whose chunks agree. A change (like WRF's in 2017) splits the dataset in two.
- **A fixed time dimension, or NetCDF-4.** In NetCDF-3, an UNLIMITED `time` interleaves every
  variable step by step, which is what prevents time chunks today.
- **Metadata:**
  - a declared `_FillValue` on every variable;
  - CF `units` and `standard_name` (fix `temp` in the reanalysis, add `salt` units);
  - the same dtype for `mask` in every file;
  - a `product_version` and `date_created` in the global attributes;
  - the run's start time as `forecast_reference_time`.
- **Never rewrite a published file in place.** Corrections, like the March 2024 WW3 time fix,
  are better published as a new version, so anyone holding the old file, or a store pointing
  into it, can tell.
- **One file per run, named by its true start time.** Never reuse another day's run as a new
  file: if a run fails, leave the day out. The "best" series then falls back to the previous
  run's later hours, with the right times.

## Questions for PacIOOS

1. **WRF 2010–2013:** were runs sometimes repeated from an earlier day when the model failed,
   with the dates moved on? The 71 files are listed in `audit/out/wrf_repeated_runs.csv`.
2. **WW3 2020-04-27 to 05-04:** are these eight files' times one day early, like the files you
   corrected in March 2024?
3. **WW3 cold starts:** a cold-started run begins with an all-zero wave field, and its spin-up
   lasts 11 hours to more than a day (sampled 2026-11-14), so it spoils most of the day it
   supplies to the best series. ERDDAP serves these steps as they are, and the store will too,
   marking them with a flag. Is there a better choice, for example leaving out the
   cold-started run's first day where an earlier run covers it?
4. **WW3 cold starts in 2026:** there have been seven this year, four between 10-18 and 10-27
   (every second run). Is the restart file from the previous run not being carried over?
5. **The reanalysis:** is `temp` in °C (the files say `ppt`), and what are `salt`'s units?
6. **Duplicate runs:** for days with two files that start at the same time (for example WRF
   2022-02-21 and 2022-02-22), which is the right one? THREDDS uses the later file name.
7. **Rewriting the NetCDFs:** would PacIOOS want rewritten, time-chunked NetCDFs, starting
   with WRF 2010–2017 and the reanalysis, and could future runs be written in the layout above?
