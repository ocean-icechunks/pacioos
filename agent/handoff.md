# Handoff — pacioos

Rolling state for this repo. Orientation only: the open threads are a record of what is
unfinished, not a task list.

## Where things stand (2026-11-14)

Moved here from `ocean-icechunks/icechunks` on 2026-11-13 so the PacIOOS team can take it over
(history: that repo's PRs #35, #39, #42; issues transferred as #1–#4 here).

- **Copied to Source Cooperative and checked** (every file has a `.md5`; listings match the
  server; sampled downloads all matched): ROMS forecast `roms_hiig` (2025-01-01 to 2026-11-12),
  `wrf_hi`, `ww3_hawaii`, and `roms_hiig_reanalysis/netcdf/v2.0/` (4,380 files, 1,169.8 GB).
  Table in `README.md`. Copy done as #1 (closed).
- **Two stores built: the reanalysis (#11, closed) and the ROMS forecast (#10).** Not built:
  #12 (WRF), #13 (WW3), #14 (all-runs view), each ending with decisions for Eli, with audit and
  chunking comments added 2026-11-13.
- **Smoke test passed (PR #15, merged):** `stores/` builds a few runs of each product into
  local repos with computed references (the HYCOM trick: one depth plane per chunk for ROMS, one
  step for WRF/WW3), reopens read-only and matches netCDF-C reads. Why it is built that way:
  `docs/design/file-headers.md`. Venv: `~/venvs/pacioos` (from `stores/requirements.txt`).
- **File audit done (PR #16, merged):** `audit/report.md`; team version is the Claude Doc
  https://claude.ai/artifact/G67caCdBJ2Z7hupYuJZHnJ (snapshot `audit/report-pacioos.md`, linked
  from the README); `audit/how_audit_created.md` is a prompt to redo it.
- **Reanalysis store, #11: published and closed 2026-11-14 (PR #18, merged).**
  `ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk`, tag `v2.0`, all 35,040 steps
  2009-01-01..2020-12-28, validated anonymously from the public URL (120 planes = netCDF-C;
  12-year point series 49.5 s). README and viewer published beside it; Eli checked the viewer.
  Decisions (Eli): one depth plane per chunk; ERDDAP metadata saved in the repo, shorter title;
  one group. Code and the PacIOOS team guide: `stores/roms_hiig_reanalysis/`, start with
  `how_store_created.md`; build with `build_store.py` (scan, check, write, validate; resumable,
  scratch unless `--dest production`). Scratch copies deleted. Lessons filed as
  ocean-icechunks/ocean-icechunks-skills#14.
- **Product README on Source Cooperative** (`ocean-icechunks/pacioos/README.md`, 2026-11-14):
  repo copy `source-coop/README.md`; re-upload it after editing. It lists the four datasets, the
  copies and stores. Update its table as each store is built. The one-line product description
  is set by Eli in Source Cooperative's settings (a suggested text was given 2026-11-14).
- **ROMS forecast store, #10: published 2026-11-14 (branch `roms-forecast-store`).**
  `ocean-icechunks/pacioos/roms_hiig/icechunk`, best series of the 654 runs through 2026-11-12,
  5,497 steps, no tag (it will change daily). Validated anonymously: axis identical to ERDDAP
  `roms_hiig`, 125 planes = netCDF-C, 12 point values = ERDDAP. Viewer and README beside it;
  product README updated; Eli checked the scratch viewer. Decisions (Eli): as the reanalysis
  (depth-plane chunks, saved ERDDAP metadata, one group, lat/lon), title ": Forecast"; regular
  3-hourly axis, an uncovered time kept as a NaN step; **yearly manifest splits kept** for the
  same convention, after monthly/quarterly were measured (#4 comments). Code and team guide:
  `stores/roms_hiig/`, start with `how_store_created.md`. Files have four header layouts, so
  every header is scanned. Scratch copies deleted 2026-11-14 (`build_store.py --dest scratch`
  recreates the scratch build).

## Open threads

- **#10–#13 — virtual stores** serve the THREDDS "best" series (Eli, 2026-11-13: it is what
  PacIOOS serves). Facts that shape them, from the audit: WRF needs two groups (byte order changes
  2017-08-16); ties between runs go to the later file name (as THREDDS); 71 relabelled WRF runs,
  WW3 2020-04-27..05-04 probably a day early, and 81 WW3 cold starts are open decisions
  (recommended: keep and flag) and questions for PacIOOS. Only one-step (or one-depth-plane)
  chunks are possible in a best series. **#14**: the all-runs view, after the best stores.
- **No materialized rewrite.** Eli (2026-11-13): stores stay virtual. "Reprocessing" in the team
  report means rewriting the NetCDFs themselves (WRF 2010–17 first), a PacIOOS decision.
- **#9 — upload script**: a failed destination listing can overwrite finished copies.

- **#4 — daily auto-update** of forecast/WRF/WW3, the PacIOOS hackweek project (2026-11-17).
  Store side, measured 2026-11-14 (comments on #4): the best series needs an incremental update
  (resize + `set_virtual_refs` for 57 steps + rewrite the time coordinates), which matched a
  full build; `vz.to_icechunk` over an existing group raises `ContainsGroupError`. ERDDAP
  `roms_hiig` also ended at the 11-12 run on 2026-11-14, so there may be nothing new to catch up.
  **Working updater:** `stores/roms_hiig/update_store.py` (diff the store against the best series
  planned from every run, write the difference in one commit, verify; `--dry-run`), with
  `test_update_store.py`. Tested locally and end to end on a scratch copy (deleted); production
  dry run up to date. Run it after the catch-up copy. Left for the hackweek: schedule, a Source
  Cooperative role (Alex Kerney set up OISST's and can help), alerts, WRF/WW3.
  The copies stop at 2026-11-12 until it exists, and the server's forecast archive is
  trimmed over time, so a missed day can be lost. Start from the NOAA OISST pipeline
  (ocean-icechunks/noaa_oisst).
- **#3 — the hindcast** (3.37 TB). Which years to copy is the **PacIOOS team's** call (Eli,
  2026-11-14: she does not know how to pick them); maybe after comparing with the reanalysis
  (overlap 2015–2020). It may go to a different S3 bucket.
- **#2 — versions and changed files.** Hackathon scenarios. The upload script only detects a
  size change; a same-size rewrite is not noticed.

- **Skill pointers updated (2026-11-13).** The skills moved from nmfs-opensci/agent-skills to
  ocean-icechunks/ocean-icechunks-skills (ocean-icechunks/icechunks#46); `AGENTS.md` points there.
  So does the PacIOOS team note's "Set up once" step.
- **The team note was trimmed (2026-11-13)** so it does not repeat the README, `upload/README.md`,
  `AGENTS.md` or the issues: it now leads with working with an agent, then the tasks, then a
  pointer to the upload instructions. Keep it that way: link, don't copy.

## Working notes

- **Reanalysis store facts** (detail in `stores/roms_hiig_reanalysis/how_store_created.md`):
  all 20 sampled files have identical chunk offsets, so one header gives every reference, but
  production still scans all files. An append rewrites root attributes. xarray needs
  `_FillValue` base64-encoded for Zarr v3. `chunks={}` makes point series ~25x slower than
  `chunks=None`. ERDDAP restarts now and then (503, then "unknown datasetID" for a minute).
- Source Cooperative refuses S3 `DeleteObjects` (answers `NoSuchBucket`): delete one key at a
  time.
- `stores/icechunk_utils.py` and `stores/publish_viewer.py` are copies of the ones in
  ocean-icechunks/icechunks (the viewer one with PacIOOS products only), so this repo stands
  alone; a fix belongs in both. Build the viewer from a gridlook clone on `main`: Eli's
  `~/gridlook` is on a docs branch.
- The notebooks in `stores/roms_hiig_reanalysis/` are run with
  `jupyter execute --inplace` in a clean venv from that folder's `requirements.txt`, and
  committed with their outputs.

- The first copy ran from a JupyterHub over a read-only SSH login, with a single approved
  `rclone` binary in `/tmp` on the PacIOOS server and keys sent over SSH stdin each run
  (`upload/upload_over_ssh.sh`). The logs of that run name the server and stay on Eli's hub,
  outside git.
- Source Cooperative login on a JupyterHub: `source-coop login --duration 1d --port 8400`, then
  replace `http://localhost:8400` in the redirect with the hub's `/user/<name>/proxy/8400`.
- Server-side copies on Source Cooperative work (1.9 GB in 40 s, MD5 identical); the layout
  move on 2026-11-12 used them, with no re-upload.
- Four Claude Docs for the PacIOOS team, all linked from `README.md` ("Start here"). Eli edits
  them; they are the live copies. The transfer plan and the explainer have snapshots in
  `docs/design/` (checked against the live docs 2026-11-13); the 2026-11-13 team note
  (upload, tasks, working with an agent: https://claude.ai/artifact/MmW3VYYgR6enaALtqToX31)
  has no snapshot; the audit doc's snapshot is `audit/report-pacioos.md`.

## Notes

- [source-probe.md](../docs/design/source-probe.md) — public-server probe, sizes, chunking, options; corrections box at top
- [transfer-plan.md](../docs/design/transfer-plan.md) — snapshot of the transfer plan doc
- [virtual-icechunk-explainer.md](../docs/design/virtual-icechunk-explainer.md) — snapshot of the explainer doc
- [file-headers.md](../docs/design/file-headers.md) — what the copies' headers showed; why the store code is built as it is
- [audit/report.md](../audit/report.md) — full file audit (problems P1–P11, method, limitations)
