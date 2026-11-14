# How the ROMS forecast Icechunk store is made

For the PacIOOS team: what builds the virtual Icechunk store over the ROMS Hawaiʻi forecast
copies, how to run it yourselves, and a prompt to give a coding agent to redo or continue it. The
plan and the decisions are in
[issue #10](https://github.com/ocean-icechunks/pacioos/issues/10).

The work so far was done by a coding agent (Claude Code) with Eli Holmes, 2026-11-14, following
the `virtual-icechunk` skill in
[ocean-icechunks/ocean-icechunks-skills](https://github.com/ocean-icechunks/ocean-icechunks-skills),
and reusing the reanalysis store's code and decisions
([`../roms_hiig_reanalysis/how_store_created.md`](../roms_hiig_reanalysis/how_store_created.md)).
The order is the skill's: **plan → local smoke test → scratch store → production build →
documentation**. Each step has to pass before the next one starts.

## Where it stands (2026-11-14)

| Step | Status | What |
|---|---|---|
| 1. Plan | done | issue #10; decisions below |
| 2. Local smoke test | done | `forecast-smoke-test-local.ipynb` |
| 3. Scratch store on Source Cooperative | done | `build_store.py --dest scratch`; scratch viewer checked by Eli Holmes |
| 4. Production build | **done, 2026-11-14** | `build_store.py --dest production`; the store and its viewer |
| 5. Store README and loading example | **done, 2026-11-14** | `README.md`, also published beside the store; product README updated |

**The store** (public, anonymous, not tagged: it will change daily once #4 exists):

- store: `https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/icechunk`, snapshot
  `W6C8C8NEFTSGB8DYXN30`
- viewer: <https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/viewer/index.html>
- README: <https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/README.md> (the copy of
  `README.md` in this folder; upload it again after editing it)

The production build, 2026-11-14, as `build_store.py` printed it: the same 654 runs and checks as
the scratch build below; written in 6 s; validated anonymously from the public URL with the same
results (axis identical to ERDDAP's, 125 planes = netCDF-C, 12 point values = ERDDAP, land NaN),
opened in 1.0 s; a surface map 0.2 s, a 36-level field 0.8 s, the 23-month point series 8.5 s.
The README's loading code was run as written against it, in a clean venv holding only icechunk,
xarray and zarr.

**The scratch build** (2026-11-14; deleted the same day after production was checked, and `build_store.py --dest scratch` recreates it):

What `build_store.py` printed for it:

- the scan read the headers of all 654 runs (2025-01-01 to 2026-11-12) in 2 min 49 s (6
  processes, 3.9 files/s), with no errors;
- the check found every file with the same structure, coordinates and mask values, 57 steps from
  00Z of its day and `missing_value` 9.99e10, in four header layouts (193, 171, 168 and 122
  files);
- the write took 5 s: one commit, 5,497 steps, 797,065 references, 28 objects, 11.0 MB;
- validation, anonymously from the public URL, passed. The store opened in 0.8 s. Its time
  axis has 5,497 steps, 2025-01-01T00Z to 2026-11-19T00Z, **identical to ERDDAP `roms_hiig`'s**,
  with every step from the newest run that has it and no uncovered steps. 125 planes (25 steps ×
  5 variables) are identical to netCDF-C, and 12 point values (temp, salt, zeta at 4 times) equal
  ERDDAP's. Land reads as NaN. Timings, with Zarr `async.concurrency` = 128 on one JupyterHub:
  a surface map 0.1 s, a 36-level field 0.7 s, a 23-month surface point series 7.7 s (5,497
  reads, 1.3 GB).

## The decisions (Eli Holmes, 2026-11-14)

- **The same as the reanalysis store**: one depth level per chunk, `(1, 1, 195, 295)`, 230 KB;
  metadata from PacIOOS's ERDDAP (`roms_hiig` and `roms_hiig_ssh`), saved in
  `erddap_metadata.json`; one group with `temp`, `salt`, `u`, `v`, `zeta`; native `lat`/`lon`.
  The title ends ": Forecast" instead of ERDDAP's ": 3-D Variables".
- **The THREDDS "best" time series**, which is what PacIOOS serves: for each valid time, the
  most recent run that has it, including its own first step. `forecast_reference_time` and
  `forecast_period` on `time` say which run and lead each step came from. The all-runs view
  `(run, step)` is a separate store, #14.
- **A regular 3-hourly axis.** A time that no run covers stays on the axis, with no reference:
  its data read as NaN and its `forecast_reference_time` as NaT. None exist yet (the longest run
  of missing days is 3, and each run covers 7). THREDDS would instead leave such a time out.
- **Stays virtual.** No data are copied into the store. Every read goes to the NetCDF copies
  under `pacioos/roms_hiig/netcdf/`.
- **No tag.** The store will change every day once the daily update (#4) exists, and each daily
  commit is a snapshot.
- **One manifest per year of steps (2,920)**, the reanalysis store's convention. Monthly and
  quarterly splits were measured, and reads were the same. Yearly splits make each daily commit
  add up to about 3 MB of history, against 0.3–0.6 MB, which is small next to the NetCDF.
  Measurements: [#4](https://github.com/ocean-icechunks/pacioos/issues/4#issuecomment-6871030769).

## The files

All in `stores/roms_hiig/` unless noted.

| File | What it does |
|---|---|
| `forecast_store.py` | Everything the notebook and the build share: file names, the run listing, the ERDDAP metadata, building the best-series dataset, the repository config, opening the store as a reader |
| `erddap_metadata.json` | The ERDDAP attributes of `roms_hiig` and `roms_hiig_ssh`, saved 2026-11-14 (without the coverage attributes, which change daily) |
| `forecast-smoke-test-local.ipynb` | Step 2. Small stores in a temporary local folder, checked against netCDF-C, including a made-up gap. No credentials. Its last run is saved in it. |
| `make_smoke_notebook.py` | The notebook's source, as plain Python; it writes the notebook |
| `build_store.py` | Steps 3 and 4: scan every header, check them, write, validate from the public URL. Writes to scratch unless given `--dest production` |
| `README.md` | The store's README, to publish beside it |
| `requirements.txt` | What these need (it includes `../requirements.txt`) |
| `../pacioos_virtual.py` | The reference code shared by all PacIOOS products: header scans, the best rule, depth-plane references |
| `../icechunk_utils.py` | Source Cooperative credentials (through the `source-coop` CLI) and opening a repository there |
| `../publish_viewer.py` | Builds the gridlook browser viewer and uploads it beside a store (`roms_hiig`, `roms_hiig-scratch`) |

## Running it yourself

Set up as for the reanalysis (its `how_store_created.md`, "Set up once"), with this folder's
`requirements.txt`. Writing needs `source-coop login --duration 1d --port 8400`.

```bash
cd stores/roms_hiig
jupyter execute --inplace forecast-smoke-test-local.ipynb   # step 2, about 2.5 minutes
python build_store.py scan            # headers of every run -> out/scan.jsonl (read-only, ~3 min)
python build_store.py check           # stops if any file's structure differs from the first
python build_store.py write --dest scratch
python build_store.py validate --dest scratch    # ~2.5 min; asks ERDDAP if it answers
# then the same write and validate with --dest production
cd .. && python publish_viewer.py --product roms_hiig-scratch --build <gridlook clone on main>
```

The scan lists the runs on Source Cooperative and skips files already in `out/scan.jsonl`
(gitignored). The write puts the whole series in one commit. Rerun on a store that already
holds the same series, it does nothing. On a store holding a different series it stops, because
updating is the daily update's job (#4).

To refresh the ERDDAP metadata, run
`python -c "import forecast_store as fs; fs.save_erddap_metadata()"` and review
`git diff erddap_metadata.json` before committing.

## Things that look wrong and are deliberate

- **Byte offsets differ between files, so every file is scanned.** The files come in four
  header layouts. The header is 4 bytes longer in some (a longer `history` string), and the
  `mask` is `int16` in some and `float32` in others, which shifts every later offset. Each run's
  references come from its own header. The check compares everything else.
- **`_FillValue` is 9.99e10, not NaN as ERDDAP shows.** Land in the files holds `9.99e10`,
  declared as `missing_value`, and a virtual store serves the files' bytes; ERDDAP converts
  them. Readers that decode (xarray by default) see NaN. In the store's attributes it is a
  base64 string, which is how xarray keeps `_FillValue` for Zarr v3.
- **`missing_value` is float32 in some files and float64 in others.** Both are the same
  float32 number; the check compares them as float32.
- **`mask` is `int16`** in the store, whatever the file it came from, as in the reanalysis store.
  Its values are the same in every file.
- **The last 7 days of the series are a forecast.** The series ends where the newest run ends,
  7 days after its start, as ERDDAP's does.
- **ERDDAP point values are compared at the store's own grid point.** ERDDAP answers with the
  grid point it used, and the validation checks that it is the store's.
- **fsspec cannot fetch ERDDAP griddap queries:** it treats the `[ ]` in the URL as a glob.
  `build_store.py` uses urllib for them.

## Open: the daily update (#4)

Each new run takes over the last 7 days of the best series and adds 8 new steps. A daily update
appends 8 steps along `time` and re-points the references of the 49 steps before them, with the
two time-length coordinates, in one commit. This script does not do that: it writes the series
whole, and stops on a store that holds a different series. The options, the manifest-split size
to settle before the daily job starts (yearly splits, copied from the reanalysis, make each daily
commit rewrite the whole current year's manifests), and the checks to keep are in
[the #4 comment of 2026-11-14](https://github.com/ocean-icechunks/pacioos/issues/4#issuecomment-6870854483).

## Prompt for a coding agent

```text
Build (or rebuild) the virtual Icechunk store for the PacIOOS ROMS Hawaii forecast, best time
series, issue #10, using the virtual-icechunk skill from
https://github.com/ocean-icechunks/ocean-icechunks-skills. Read AGENTS.md, agent/handoff.md,
issue #10 and stores/roms_hiig/how_store_created.md first.

Source and destination
- Files: https://data.source.coop/ocean-icechunks/pacioos/roms_hiig/netcdf/<year>/
  hiig_forec_<YYYYMMDD>.nc, one 7-day run per day from 2025-01-01, NetCDF-3, read anonymously.
  They are write-once: never write, move or delete anything under netcdf/.
- Store: ocean-icechunks/pacioos/roms_hiig/icechunk. Test first in
  ocean-icechunks/test-repo/pacioos/roms_hiig/icechunk-build; never point a test at production.
- Credentials: the source-coop CLI (stores/icechunk_utils.py). Never print or commit keys.

Decisions already made (do not reopen them unless asked)
- One depth plane per chunk; metadata from stores/roms_hiig/erddap_metadata.json, title ending
  ": Forecast"; one group; lat/lon. The THREDDS best rule. A regular 3-hourly axis, an uncovered
  time kept as a NaN step. Stays virtual. No tag.

How
- Reuse stores/roms_hiig/forecast_store.py, build_store.py and stores/pacioos_virtual.py.
- Scan every header (offsets differ between files), stop if any file's structure differs.
- Validate from the public URL: the axis equals the computed one and ERDDAP's, every step from
  the newest run, sampled planes equal netCDF-C, point values equal ERDDAP, land is NaN.
- Publish the viewer with stores/publish_viewer.py and ask a person to open it.
- Verify by running, in a clean Python 3.12 venv built only from requirements.txt. Report what
  the runs printed. Retry a network failure once before calling it a bug.
- Keep this file current.
```
