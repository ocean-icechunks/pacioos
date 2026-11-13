# Handoff — pacioos

Rolling state for this repo. Orientation only: the open threads are a record of what is
unfinished, not a task list.

## Where things stand (2026-11-13)

Moved here from `ocean-icechunks/icechunks` on 2026-11-13 so the PacIOOS team can take it over
(history: that repo's PRs #35, #39, #42; issues transferred as #1–#4 here).

- **Copied to Source Cooperative and checked** (every file has a `.md5`; listings match the
  server; sampled downloads all matched): ROMS forecast `roms_hiig` (2026 to 2026-11-12),
  `wrf_hi`, `ww3_hawaii`, and `roms_hiig_reanalysis/netcdf/v2.0/` (4,380 files, 1,169.8 GB).
  Table in `README.md`. Copy done as #1 (closed).
- **No Icechunk store built yet.** `pacioos/<dataset>/icechunk/` is reserved.
- **No sample copy has been opened with xarray** from Source Cooperative yet; bytes are
  verified by MD5 only. The first store build will do that.

## Open threads

- **#4 — daily auto-update** of forecast/WRF/WW3, the PacIOOS hackweek project (2026-11-17).
  The copies stop at 2026-11-12 until it exists, and the server's forecast archive is
  trimmed over time, so a missed day can be lost. Start from the NOAA OISST pipeline
  (ocean-icechunks/noaa_oisst).
- **#3 — the hindcast** (3.37 TB). Eli decides which years after looking at the reanalysis,
  maybe comparing the two (overlap 2015–2020); it may go to a different S3 bucket.
- **#2 — versions and changed files.** Hackathon scenarios. The upload script only detects a
  size change; a same-size rewrite is not noticed.
- **Recheck `docs/design/source-probe.md`** against real file headers before designing the
  stores; its correction box lists what the public servers got wrong.

## Working notes

- The first copy ran from a JupyterHub over a read-only SSH login, with a single approved
  `rclone` binary in `/tmp` on the PacIOOS server and keys sent over SSH stdin each run
  (`upload/upload_over_ssh.sh`). The logs of that run name the server and stay on Eli's hub,
  outside git.
- Source Cooperative login on a JupyterHub: `source-coop login --duration 1d --port 8400`, then
  replace `http://localhost:8400` in the redirect with the hub's `/user/<name>/proxy/8400`.
- Server-side copies on Source Cooperative work (1.9 GB in 40 s, MD5 identical); the layout
  move on 2026-11-12 used them, with no re-upload.
- The live Claude Docs (transfer plan, explainer) that Eli edits are linked in the snapshot
  headers in `docs/design/`; the docs are the live copies.

## Notes

- [source-probe.md](../docs/design/source-probe.md) — public-server probe, sizes, chunking, options; corrections box at top
- [transfer-plan.md](../docs/design/transfer-plan.md) — snapshot of the transfer plan doc
- [virtual-icechunk-explainer.md](../docs/design/virtual-icechunk-explainer.md) — snapshot of the explainer doc
