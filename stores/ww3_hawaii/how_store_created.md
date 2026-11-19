# How the WW3 Hawaiʻi Icechunk store is made

For the PacIOOS team: what builds the virtual Icechunk store over the WaveWatch III Hawaiʻi
copies, where its metadata came from, how to run it yourselves, and a prompt to give a coding
agent to redo or continue it. The plan and the decisions are in
[issue #13](https://github.com/ocean-icechunks/pacioos/issues/13).

The work was done by a coding agent (Claude Code) with Eli Holmes, 2026-11-14 to 11-16,
following the `virtual-icechunk` skill in
[ocean-icechunks/ocean-icechunks-skills](https://github.com/ocean-icechunks/ocean-icechunks-skills)
and reusing the ROMS forecast store's code
([`../roms_hiig/how_store_created.md`](../roms_hiig/how_store_created.md)). The order is the
skill's: **plan → local smoke test → scratch store → production build → documentation**. Each
step has to pass before the next one starts.

## Where it stands (2026-11-16)

| Step | Status | What |
|---|---|---|
| 1. Plan | done | issue #13; decisions below |
| 2. Local smoke test | done | `ww3-smoke-test-local.ipynb` |
| 3. Scratch store on Source Cooperative | done | `build_store.py --dest scratch`; scratch viewer published for Eli Holmes |
| 4. Production build | **done, 2026-11-16** | `build_store.py --dest production`; the store and its viewer |
| 5. Store README and loading example | **done, 2026-11-16** | `README.md` and `cold_starts_2026.png`, published beside the store · build files (`requirements.txt`, notebooks, scripts, saved metadata) published beside it with `../publish_bundle.py`, 2026-11-19 |
| 6. Daily update | **updater done, 2026-11-16**; schedule open (#4) | `update_store.py`, over `../best_series_update.py`; first production update 2026-11-16 |

**The store** (public, anonymous, not tagged: it will change daily once #4 exists):

- store: `https://data.source.coop/ocean-icechunks/pacioos/ww3_hawaii/icechunk`, built as snapshot
  `ZRCNA5VTJJGRR12GECW0`; updated 2026-11-16 to `H4T38ERC0AV8DM92RAZG` (runs through 11-15)
- viewer: <https://data.source.coop/ocean-icechunks/pacioos/viewer/index.html> (one viewer for the product; pick the store in its dataset list)
- README: <https://data.source.coop/ocean-icechunks/pacioos/ww3_hawaii/README.md> (the copy of
  `README.md` in this folder; upload it again, with the figure, after editing it)

What `build_store.py` printed for the production build, 2026-11-16:

- the check: all 5,232 files have the same structure and consecutive hourly times; run lengths
  181 (5,227 runs), 73 (4) and 106 (1); first `Thgt` offsets 4,576 (5,212 files) and 4,760
  (20); 81 cold starts; 8 files whose first time is not on their name date
  (`ww3hawaii_20200427.nc` … `20200504.nc`);
- the write: 135,094 hourly steps, 2011-06-21T21Z to 2026-11-18T18Z, 1,594 of them uncovered,
  1,201,500 references, one commit in 22 s;
- validation, anonymously from the public URL, passed:
  - every step comes from the newest run that has it, ties to the later file name;
  - flags: 3,856 steps from 81 cold-start runs, 216 steps from 8 suspect files;
  - ERDDAP `ww3_hawaii` had 133,596 times, to 2026-11-22T18Z; the 133,500 inside the store's
    span are **identical** to the store's covered steps;
  - 72 planes (18 steps × 4 variables) identical to netCDF-C reads;
  - 12 point values at 20.50°N 202.50°E (Thgt, Tper, wdir at 4 times) equal ERDDAP's, 3 of them
    NaN on both sides;
  - one map 0.5 s; the point series of all 135,094 steps (7.7 GB) 164 s.

The README's loading code was run as written against it, in a clean venv holding only
icechunk 2.3.1, xarray 2026.9.0 and zarr 3.4.2 (and their dependencies). That run caught a bug:
`forecast_reference_time.values.max()` is NaT when any step is uncovered, so the README drops
NaT first.

**The scratch build** (deleted 2026-11-16 after production was checked; `--dest scratch` recreates it), 2026-11-14, gave the same counts and passed the same validation
(snapshot `WN020N5KCHE3P48WZYZ0`, written in 18 s; full point series 143 s). The header scan of
all 5,232 files took 12.5 minutes and agreed with the file audit.

## The decisions (Eli Holmes, 2026-11-14)

- **The THREDDS "best" time series**, which is what PacIOOS serves: for each valid time, the
  most recent run that has it, including its first step; ties go to the later file name (at
  2020-04-26T21Z, `ww3hawaii_20200427.nc` wins over `…0426.nc`), as on ERDDAP.
- **A regular hourly axis.** A time no run covers stays on the axis with no reference: its data
  read as NaN, its `forecast_reference_time` as NaT. There are 11 such gaps, 1,594 hours; ERDDAP
  leaves them out. The same choice as the ROMS forecast store.
- **Drop the files' `z` dimension (length 1); keep `z = 0` as a scalar coordinate.** Arrays are
  `(time, lat, lon)`, which is what readers and the viewer expect. The bytes referenced are the
  same.
- **One flag coordinate, `best_step_flag`** (CF `flag_masks`), set at build time from the data
  and the file headers: `1` `cold_start_run`, `2` `suspect_time_label`. Steps are flagged, never
  removed or shifted: the store serves what PacIOOS serves.
- **Metadata from PacIOOS's ERDDAP**, saved in the repo, and **the store says so** (below).
  The PacIOOS team had noticed that the files lack metadata.
- **Chunks of one variable at one step**, `(1, 101, 141)`, 57 KB: the files' own unit.
- **One manifest per year of steps (8,760)**, the ROMS stores' convention (#4 has the
  measurements). The time-length coordinates are each one chunk.
- **Stays virtual**, **one group**, **no tag**.

## Where the metadata came from

The files have one global attribute, a `title` padded with 148 dots: "WaveWatch-III results
from ORE level2 model.  Results provided by Ning Li, K.-F. Cheung, PI……". Their variable
attributes are reasonable (long and standard names, units, valid range, `_FillValue = -999`),
but there is no institution, license, summary, creator, keywords or coverage.

So the store takes **every global attribute and every variable and coordinate attribute from
PacIOOS's ERDDAP record
[`ww3_hawaii`](https://pae-paha.pacioos.hawaii.edu/erddap/info/ww3_hawaii/index.html)**,
fetched on 2026-11-14 and saved to `erddap_metadata.json`. The build reads that saved copy, never
ERDDAP live, so a rebuild gives the same store. Three places say so:

1. the store's global attribute `metadata_source` (the two ROMS stores carry the same
   attribute, added 2026-11-14 as attributes-only commits);
2. the store README's section "Where the metadata came from";
3. the table below.

Left out of ERDDAP's globals: `_CoordSysBuilder`, `cdm_data_type`, `defaultGraphQuery`,
`drawLandMask`, `sourceUrl`, `infoUrl`, the four `…most_…ing` edges and ERDDAP's time coverage
(the store writes its own). Left out of ERDDAP's variable attributes: the server-only ones
(`ioos_category`, `colorBar*`, `_CoordinateAxisType`, `actual_range`, `coordinates`, …) and its
`_FillValue = NaN`. The store adds the globals `source_files`, `forecast_runs`,
`metadata_source`, `time_coverage_start`/`_end`, and appends the best-series rule to `comment`.

`python -c "import ww3_store as ws; ws.compare_with_live_erddap()"` says whether ERDDAP has
changed since the saved copy.

### Attributes, file against store

Every variable and coordinate attribute where a file (`ww3hawaii_20261101.nc`; all files share
one structure) and the store differ. Attributes not listed are identical. Generated
2026-11-16 from the file and the production store.

| Variable | Attribute | File | Store (from ERDDAP) |
|---|---|---|---|
| `time` | axis | `t` | `T` |
| `time` | calendar | — | `proleptic_gregorian` |
| `time` | long_name | `time` | `Forecast time for ForecastModelRunCollection` |
| `time` | short_name | `time` | — |
| `time` | units | `minutes since 2008-01-01 00:00:00` | `minutes since 2008-01-01` (the same epoch; ERDDAP's is seconds since 1970) |
| `z` | axis | `z` | `Z` |
| `z` | long_name | `depth below mean sea level` | `Depth` |
| `z` | positive | — | `down` |
| `z` | units | `meters` | `m` |
| `lat` | axis | `y` | `Y` |
| `lat` | long_name | `latitude` | `Latitude` |
| `lon` | axis | `x` | `X` |
| `lon` | long_name | `longitude` | `Longitude` |
| `Tper` | standard_name | `sea_surface_wave_period` | `sea_surface_wave_period_at_variance_spectral_density_maximum` |
| `Tper` | units | `seconds` | `second` |
| `Tdir` | standard_name | `sea_surface_wave_from_direction` | `sea_surface_wave_from_direction_at_variance_spectral_density_maximum` |

The `Tdir` and `Tper` standard names are PacIOOS's corrections on ERDDAP (its `history`:
"2025-05-08 Modified standard_name of Tdir …"); the files were never rewritten.
`_FillValue` is the files' `-999` for the nine wave variables. Readers that decode see NaN.
The store adds `forecast_reference_time`, `forecast_period` and `best_step_flag`, which the files
do not have.

| Global | File | Store |
|---|---|---|
| `title` | `WaveWatch-III results from ORE level2 model.  Results provided by Ning Li, K.-F. Cheung, PI.` followed by 148 dots | `WaveWatch III (WW3) Hawaii Regional Wave Model` |
| 50 others (summary, license, institution, creator, keywords, `geospatial_*`, …) | — | ERDDAP's, word for word |
| `comment` | — | ERDDAP's, plus the best-series rule |
| `time_coverage_start`, `_end`, `source_files`, `forecast_runs`, `metadata_source` | — | the store's own |

## The files

All in `stores/ww3_hawaii/` unless noted.

| File | What it does |
|---|---|
| `ww3_store.py` | Everything shared: the run listing, the header scan with the cold-start and time-label checks, the ERDDAP metadata, building the best-series dataset, the repository config, opening the store |
| `erddap_metadata.json` | The ERDDAP attributes of `ww3_hawaii`, saved 2026-11-14 |
| `ww3-smoke-test-local.ipynb` | Step 2. Six cases in local temporary repos, checked against netCDF-C and ERDDAP (below). No credentials. Its last run is saved in it |
| `make_smoke_notebook.py` | The notebook's source, as plain Python; it writes the notebook |
| `build_store.py` | Steps 3 and 4: scan every header, check them, write, validate from the public URL. Writes to scratch unless given `--dest production` |
| `make_cold_start_figure.py` | Draws `cold_starts_2026.png` for the README from the published store |
| `update_store.py` | The daily update (#4): plan the best series from every run, write the difference from the store in one commit, verify. `--dry-run` to see what it would do |
| `test_update_store.py` | Tests of `update_store.py` against local repos (runs 2026-09-15 .. 11-11): catch-up and rerun, late run, late cold-start run, gap fill, refusal, dry run |
| `README.md`, `cold_starts_2026.png` | The store's README and its figure, to publish beside it |
| `requirements.txt` | What these need (it includes `../requirements.txt`) |
| `../pacioos_virtual.py` | Reference code shared by all PacIOOS products: header scans, the best rule |
| `../best_series_update.py` | The diff, one-commit update and verify shared by the forecast stores' `update_store.py` |
| `../icechunk_utils.py` | Source Cooperative credentials (through the `source-coop` CLI) |
| `../publish_viewer.py` | Builds the gridlook viewer and uploads it: `pacioos` (the product viewer at `pacioos/viewer/`, all stores) or `ww3_hawaii-scratch` |

The smoke test's cases: **A** the 2020 tie and the suspect week; **B** the 2013 short runs and a
131-step gap (covered steps equal ERDDAP's times); **C** the 24-day gap of 2015 (NaN steps) and
the land change (1,051 → 1,062 fill cells); **D** the October 2026 cold starts; **E** the two
2020 files in the `2021/` folder; **F** both header layouts. It took 1 min 49 s.

## Running it yourself

Set up as for the reanalysis (its `how_store_created.md`, "Set up once"), with this folder's
`requirements.txt`. Writing needs `source-coop login --duration 1d --port 8400`.

```bash
cd stores/ww3_hawaii
jupyter execute --inplace ww3-smoke-test-local.ipynb   # step 2, about 2 minutes
python build_store.py scan        # headers of every run -> out/scan.jsonl (read-only, ~12 min)
python build_store.py check       # stops if any file's structure differs from the first
python build_store.py write --dest scratch
python build_store.py validate --dest scratch    # ~4 min, most of it the full point series
# then the same write and validate with --dest production
cd .. && python publish_viewer.py --product ww3_hawaii-scratch --build <gridlook clone on main>
```

The scan lists the runs on Source Cooperative (not built from dates: two 2020 files are in the
2021 folder) and skips files already in `out/scan.jsonl` (gitignored). The write puts the whole
series in one commit. Rerun on a store that already holds the same series, it does nothing. On
a store holding a different series it stops, because updating is the daily update's job (#4).

## The daily update (#4): `update_store.py`

The same as the ROMS forecast's (its `how_store_created.md` explains the steps): scan any new
headers, check every file, plan the whole best series, then `../best_series_update.py` diffs the
plan against the store's `time` and `forecast_reference_time`, writes the changed references
and every coordinate on time (including `best_step_flag`) in one commit, and verifies from
storage. A daily run appends 24 steps and re-points the 157 from the new run's start to the old
end.

```bash
python update_store.py --dest production --dry-run    # what would change; writes nothing
python update_store.py --dest production
```

**Tested 2026-11-16:**

- `test_update_store.py`, local repos over the runs 2026-09-15 .. 11-11, about 20 minutes (most
  of it verify reading back over HTTPS). Six scenarios pass, each checked against a fresh build:
  three missed days (72 appended, 157 re-pointed) and a rerun that commits nothing; a late run
  (24 re-pointed); a late cold-start run (48 re-pointed and flagged, 192 → 240 flagged steps); a
  10-run hole (107 NaN steps) filled; a shorter plan refused; a dry run.
- Source Cooperative reset connections in three runs in a row (`Connection reset by peer`, a
  short body); verify and the tests now retry read errors, and the passing run needed one retry.
- **First production update, 2026-11-16**, after the catch-up copy: 96 steps appended, 157
  re-pointed, from the 11-12 .. 11-15 runs (all 181 steps, none a cold start). Committed
  `H4T38ERC0AV8DM92RAZG` in 3.6 s; verified from storage (coordinates = plan, 135,190 steps; 72
  planes = netCDF-C); then read anonymously: the 133,596 covered steps equal ERDDAP's times, to
  2026-11-22T18Z. README updated and re-uploaded.

To refresh the ERDDAP metadata, run `python -c "import ww3_store as ws; ws.save_erddap_metadata()"`
and review `git diff erddap_metadata.json` before committing.

## Things that look wrong and are deliberate

- **`lon` is 0–360** (199–206 °E), as in the files and on ERDDAP, while ERDDAP's
  `geospatial_bounds` polygon is in −180–180. A virtual store cannot rewrite the coordinate.
- **Cold starts and the 2020 suspect week are served unchanged**, as ERDDAP serves them, and
  flagged. Checked against ERDDAP at 11 cold starts: its first-day values are exactly the
  cold-start run's, starting with `Thgt = 0`. ERDDAP's axis runs evenly hourly through the
  suspect week.
- **The cold-start flag covers only the cold-start runs.** The runs after a cold start inherit
  its under-developed waves and are not flagged (the README's figure: October 2026 stays low
  until about 11-01). Flagging those would need a threshold someone chooses; it is left to
  PacIOOS.
- **Every header is scanned**, because 20 files have a 184-byte longer header (probably the 20
  files PacIOOS corrected by hand in 2024), which shifts every offset. The check compares
  structure, not offsets or run length.
- **The validation's ERDDAP point comparison is NaN-aware.** `wdir` is NaN at some sea points
  and times in both the files and ERDDAP (no wind sea), and NaN ≠ NaN.
- **ERDDAP can end days after the store**, whenever the copies are behind: at the build the copies
  stopped at the 2026-11-11 run while ERDDAP had runs to 11-15. The validation compares only the
  span the store covers. After the 2026-11-16 catch-up and update both ended at 2026-11-22T18Z.

## Questions for PacIOOS

These are also in the team's audit report (questions 3 and 4).

1. Are `ww3hawaii_20200427.nc` … `20200504.nc` a day early, like the 20 files corrected in 2024
   (`ncap2 -s time[time]=time+1440`)? If so, corrected copies would go in a new version (#2), and
   the store would be rebuilt on them.
2. Why are there so many cold starts in 2026 (7; four between 10-18 and 10-27, every second
   run)? Is the restart file from the previous run not being carried over?

## Prompt for a coding agent

```text
Build (or rebuild) the virtual Icechunk store for the PacIOOS WaveWatch III Hawaii model, best
time series, issue #13, using the virtual-icechunk skill from
https://github.com/ocean-icechunks/ocean-icechunks-skills. Read AGENTS.md, agent/handoff.md,
issue #13 and stores/ww3_hawaii/how_store_created.md first.

Source and destination
- Files: https://data.source.coop/ocean-icechunks/pacioos/ww3_hawaii/netcdf/<year>/
  ww3hawaii_<YYYYMMDD>.nc, one run a day from 2011-06-21, NetCDF-3, read anonymously. List them;
  do not build paths from dates. They are write-once: never write, move or delete anything under
  netcdf/.
- Store: ocean-icechunks/pacioos/ww3_hawaii/icechunk. Test first in
  ocean-icechunks/test-repo/pacioos/ww3_hawaii/icechunk-build; never point a test at production.
- Credentials: the source-coop CLI (stores/icechunk_utils.py). Never print or commit keys.

Decisions already made (do not reopen them unless asked)
- The THREDDS best rule, ties to the later file name. A regular hourly axis, an uncovered time
  kept as a NaN step. z dropped as a dimension, kept as a scalar. best_step_flag for cold starts
  and suspect time labels; nothing removed or shifted. Metadata from erddap_metadata.json, and
  the store says so (metadata_source). One plane per chunk, yearly manifest splits. No tag.

How
- Reuse stores/ww3_hawaii/ww3_store.py, build_store.py and stores/pacioos_virtual.py.
- Scan every header (two layouts), stop if any file's structure differs.
- Validate from the public URL: covered steps equal ERDDAP's times, every step from the newest
  run, flags as the audit (81 cold starts, 8 suspect files), sampled planes equal netCDF-C,
  point values equal ERDDAP.
- Publish the viewer with stores/publish_viewer.py and ask a person to open it.
- Verify by running, in a clean Python 3.12 venv built only from requirements.txt. Report what
  the runs printed. Retry a network failure once before calling it a bug.
- Keep this file current.
```
