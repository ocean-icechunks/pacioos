# How the reanalysis Icechunk store is made

For the PacIOOS team: what builds the virtual Icechunk store over the ROMS Hawaiʻi reanalysis
v2.0 copies, how to run it yourselves, and a prompt to give a coding agent to redo or continue
it. The plan and the decisions are in
[issue #11](https://github.com/ocean-icechunks/pacioos/issues/11).

The work so far was done by a coding agent (Claude Code) with Eli Holmes, 2026-11-13 and 14,
following the `virtual-icechunk` skill in
[ocean-icechunks/ocean-icechunks-skills](https://github.com/ocean-icechunks/ocean-icechunks-skills).
That skill sets the order: **plan → local smoke test → scratch store → production build →
documentation**. Each step has to pass before the next one starts.

## Where it stands (2026-11-14)

| Step | Status | What |
|---|---|---|
| 1. Plan | done | issue #11; decisions below |
| 2. Local smoke test | done | `reanalysis-smoke-test-local.ipynb` |
| 3. Scratch store on Source Cooperative | done | `reanalysis-scratch-sc.ipynb`, viewer, scratch README |
| 4. Production build, all 4,380 files | **done, 2026-11-14** | `build_store.py`; the store, tagged `v2.0`, and its viewer |
| 5. Project README and loading example | not yet | |

**The store** (public, anonymous, tag `v2.0`):

- store: `https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk`
- viewer: <https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/viewer/index.html>

The production build, 2026-11-14, as `build_store.py` printed it:

- the scan read the headers of all 4,380 files in 10 minutes (6 processes, 7.5 files/s), with
  no errors;
- the check found every file with the same size, chunk offsets, coordinates and mask, and 8
  steps at 00–21Z of its own day;
- the write took 66 s: 12 yearly commits, 35,040 steps, about 5.1 million references, 171
  objects, 68.8 MB;
- validation, anonymously from the public URL, passed. The store opened in 1.2 s. Its time
  axis equals the 35,040 expected steps. 120 planes (2 steps per year × 5 variables) are
  identical to netCDF-C. Land reads as NaN. Timings, with Zarr `async.concurrency` = 128 on
  one JupyterHub: a surface map 0.4 s, a 36-level field 0.8 s, and a 12-year surface point
  series 49.5 s (35,040 reads, 8.1 GB).

The same build was run first to `test-repo/pacioos/roms_hiig_reanalysis/icechunk-build`, with
the same results.

Scratch store, viewer and README from step 3 (these may be rewritten or deleted at any time):

- store: `https://data.source.coop/ocean-icechunks/test-repo/pacioos/roms_hiig_reanalysis/icechunk`
- viewer: <https://data.source.coop/ocean-icechunks/test-repo/pacioos/roms_hiig_reanalysis/viewer/index.html>
- README: <https://data.source.coop/ocean-icechunks/test-repo/pacioos/roms_hiig_reanalysis/README.md>

The viewer draws the scratch store in an ordinary browser, with no extension (Eli Holmes,
2026-11-14). Both the store and the NetCDF copies are on `data.source.coop`, which sends the
CORS headers a browser needs.

## The decisions (Eli Holmes, 2026-11-14)

- **One depth level per chunk**, `(1, 1, 195, 295)`, 230 KB. The files are uncompressed HDF5
  with one 8.3 MB chunk per variable per time step holding all 36 depths. The store's
  references point at each depth plane inside those chunks. A surface map reads 230 KB, not
  8.3 MB. A 12-year point series at one depth reads about 8 GB, not about 290 GB.
- **Metadata from PacIOOS's ERDDAP.** The files lack a fill value, call temperature `ppt`,
  and give salinity no units. ERDDAP's record of the dataset has the corrected attributes, and
  the store uses them. The title drops ERDDAP's ": 3-D Variables", because the store also
  holds `zeta`. The attributes are saved in `erddap_metadata.json` so a build does not need
  ERDDAP to be up.
- **One group** with all five variables (`temp`, `salt`, `u`, `v`, `zeta`).
- **Stays virtual.** No data are copied into the store. Every read goes to the NetCDF copies
  under `pacioos/roms_hiig_reanalysis/netcdf/v2.0/`. The store is tagged `v2.0`.

## The files

All in `stores/roms_hiig_reanalysis/` unless noted.

| File | What it does |
|---|---|
| `reanalysis_store.py` | Everything the notebooks and the production build share: file names, the ERDDAP metadata, building the virtual dataset, the repository config, opening the store as a reader |
| `erddap_metadata.json` | The ERDDAP attributes of `roms_hiig_reanalysis` and `roms_hiig_reanalysis_ssh`, saved 2026-11-14 |
| `reanalysis-smoke-test-local.ipynb` | Step 2. Builds small stores in a temporary local folder and checks them against netCDF-C. No credentials. Its last run is saved in it. |
| `reanalysis-scratch-sc.ipynb` | Step 3. Writes the small store to the scratch prefix on Source Cooperative, reads it back anonymously, checks CORS, uploads the scratch README |
| `build_store.py` | Step 4, the production build: scan every header, check them, write year by year, validate from the public URL, tag `v2.0`. Resumable. Writes to scratch unless given `--dest production` |
| `requirements.txt` | What these need (it includes `../requirements.txt`) |
| `../pacioos_virtual.py` | The general reference code for all PacIOOS products: header scans, depth-plane references |
| `../icechunk_utils.py` | Source Cooperative credentials (through the `source-coop` CLI) and opening a repository there |
| `../publish_viewer.py` | Builds the gridlook browser viewer and uploads it beside a store |

## Running it yourself

### Set up once

```bash
# Python 3.12 or newer (icechunk 2.x needs it). On the JupyterHub: /srv/conda/bin/python3.12.
python3.12 -m venv ~/venvs/pacioos
~/venvs/pacioos/bin/pip install -r stores/roms_hiig_reanalysis/requirements.txt
```

Writing to Source Cooperative (steps 3 and 4) needs write access to the `ocean-icechunks`
account and the `source-coop` CLI:

```bash
source-coop login --duration 1d --port 8400
```

On a JupyterHub, replace `http://localhost:8400` in the redirect with the hub's
`/user/<name>/proxy/8400`. The keys last about 12 hours. The scripts refresh them through the
CLI and refuse to start a write with less than 15 minutes left.

The viewer needs Node 20 or newer and gridlook:

```bash
git clone https://github.com/eeholmes/gridlook ~/gridlook && (cd ~/gridlook && npm ci)
```

### Step 2: local smoke test (no credentials, 2 to 3 minutes)

Open `reanalysis-smoke-test-local.ipynb` in Jupyter with the venv's kernel and run all cells,
or from this folder:

```bash
~/venvs/pacioos/bin/jupyter execute --inplace reanalysis-smoke-test-local.ipynb
```

Every check is an `assert`, so a run that finishes has passed. It reads only the public copies
and writes only to a temporary folder, which it deletes.

### Step 3: scratch store, viewer and README (credentials, about 1 minute)

```bash
cd stores
~/venvs/pacioos/bin/python publish_viewer.py --product roms_hiig_reanalysis-scratch --build ~/gridlook
cd roms_hiig_reanalysis
~/venvs/pacioos/bin/jupyter execute --inplace reanalysis-scratch-sc.ipynb
```

The notebook writes only under `ocean-icechunks/test-repo/`. If the scratch store already
exists, it skips the write and checks the existing store. To start again, use the guarded
delete cell at its end. Then open the viewer link. Only a person looking at it can say whether
it draws.

### Step 4: the production build

```bash
cd stores/roms_hiig_reanalysis
python build_store.py scan            # headers of all 4,380 files -> out/scan.jsonl (read-only)
python build_store.py check           # stops if any file's layout differs from the first
python build_store.py write --dest scratch      # the full store, under test-repo/ first
python build_store.py validate --dest scratch   # from the public URL; tags v2.0 if it passes
# then the same write and validate with --dest production
```

Every phase can be rerun. The scan skips files already in `out/scan.jsonl` (gitignored).
The write skips years the store already holds, commits one year at a time, and opens fresh
keys before each year. It stops cleanly if the keys have under 20 minutes left: log in again
and rerun it.

### Refreshing the ERDDAP metadata

The notebooks compare the saved copy with ERDDAP whenever ERDDAP answers, and print any
difference. To take a change:

```bash
cd stores/roms_hiig_reanalysis
~/venvs/pacioos/bin/python -c "import reanalysis_store as rs; rs.save_erddap_metadata()"
git diff erddap_metadata.json        # review before committing
```

## Things that look wrong and are deliberate

- **`_FillValue` is a base64 string in the store's attributes.** xarray keeps it that way for
  Zarr v3 and refuses a plain number when it opens the store. It decodes to `9.96921e36`, the
  value the files hold on land.
- **An append rewrites the store's global attributes** with those of the appended data. So
  each batch carries the attributes for the whole span, or they are set once, at the end.
- **Open with `chunks=None` (or large dask chunks) for point time series.** With
  `chunks={}`, dask makes one task per 230 KB chunk, and a one-year series took 120 s instead
  of about 5 s.
- **The time axis is checked against 35,040 computed steps, not against ERDDAP.** It is the
  same count and span ERDDAP lists (checked 2026-11-13).
- **The notebooks never write under `pacioos/<dataset>/netcdf/`.** The NetCDF copies are
  write-once (see `AGENTS.md`).

## Prompt for a coding agent

Paste this into a session started in this repository, to redo the work, continue it to the
production build, or apply it to another PacIOOS product.

```text
Build (or rebuild) the virtual Icechunk store for the PacIOOS ROMS Hawaii reanalysis v2.0,
issue #11, using the virtual-icechunk skill from
https://github.com/ocean-icechunks/ocean-icechunks-skills. Read AGENTS.md, agent/handoff.md,
issue #11 and stores/roms_hiig_reanalysis/how_store_created.md first.

Source and destination
- Files: https://data.source.coop/ocean-icechunks/pacioos/roms_hiig_reanalysis/netcdf/v2.0/
  <year>/hiig_his_zlevel_<YYYYMMDD>.nc, 4,380 daily files 2009-01-01..2020-12-28, read
  anonymously. They are write-once: never write, move or delete anything under netcdf/.
- Store: ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk, tagged v2.0. Test first in
  ocean-icechunks/test-repo/pacioos/roms_hiig_reanalysis/icechunk; never point a test at the
  production prefix.
- Credentials: the source-coop CLI (stores/icechunk_utils.py). Never print or commit keys.

Decisions already made (do not reopen them unless asked)
- One depth plane per chunk (1, 1, 195, 295), cut inside the uncompressed HDF5 chunks.
- Metadata from stores/roms_hiig_reanalysis/erddap_metadata.json (PacIOOS ERDDAP), title
  without ": 3-D Variables"; the build must not depend on ERDDAP being up.
- One group with temp, salt, u, v, zeta. Stays virtual: no materialized copy.

How
- Reuse stores/roms_hiig_reanalysis/reanalysis_store.py and stores/pacioos_virtual.py; do not
  re-derive them. Follow the skill's order: local smoke test, scratch store with viewer and
  README, production build, project README.
- Production: scan the header of every file (pv.scan_h5, about 1 s each; at most ~6 processes
  on a 7.8 GB hub, resumable, one JSON line per file) and stop if any file's chunk offsets
  differ from the rest. Build year by year (one manifest per year, 2,920 steps), committing
  each year so a failure resumes. Stop starting new work when the Source Cooperative keys
  have under 15 minutes left. Set the global attributes for the whole span.
- Validate from the public URL, anonymously: the time axis equals the 35,040 computed steps,
  sampled planes in every year equal netCDF-C (#mode=bytes) reads, land reads as NaN. Time
  the open, a map and a multi-year point series with zarr async.concurrency = 128.
- Publish the viewer with stores/publish_viewer.py (add a production entry to PRODUCTS) and
  ask a person to open it.
- Verify by running, in a clean Python 3.12 venv built only from requirements.txt. Report what
  the runs printed. Retry a network failure once before calling it a bug.
- Keep this file current: what changed, and anything the next person would need.
```
