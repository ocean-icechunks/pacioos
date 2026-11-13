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
- **No Icechunk store built yet.** `pacioos/<dataset>/icechunk/` is reserved. Plans: issues
  #10 (ROMS forecast), #11 (reanalysis), #12 (WRF), #13 (WW3), #14 (all-runs view), each ending
  with decisions for Eli, with audit and chunking comments added 2026-11-13.
- **Smoke test passed (PR #15, merged):** `stores/` builds a few runs of each product into
  local repos with computed references (the HYCOM trick: one depth plane per chunk for ROMS, one
  step for WRF/WW3), reopens read-only and matches netCDF-C reads. Why it is built that way:
  `docs/design/file-headers.md`. Venv: `~/venvs/pacioos` (from `stores/requirements.txt`).
- **File audit done (PR #16, merged):** `audit/report.md`; team version is the Claude Doc
  https://claude.ai/artifact/G67caCdBJ2Z7hupYuJZHnJ (snapshot `audit/report-pacioos.md`, linked
  from the README); `audit/how_audit_created.md` is a prompt to redo it.
- **Next, by Eli (2026-11-13): build the reanalysis store, #11.** Follow the virtual-icechunk
  skill's order (plan, smoke-test notebook, production, docs); start from
  `stores/pacioos_virtual.py`.

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
  The copies stop at 2026-11-12 until it exists, and the server's forecast archive is
  trimmed over time, so a missed day can be lost. Start from the NOAA OISST pipeline
  (ocean-icechunks/noaa_oisst).
- **#3 — the hindcast** (3.37 TB). Eli decides which years after looking at the reanalysis,
  maybe comparing the two (overlap 2015–2020); it may go to a different S3 bucket.
- **#2 — versions and changed files.** Hackathon scenarios. The upload script only detects a
  size change; a same-size rewrite is not noticed.

- **Skill pointers updated (2026-11-13).** The skills moved from nmfs-opensci/agent-skills to
  ocean-icechunks/ocean-icechunks-skills (ocean-icechunks/icechunks#46); `AGENTS.md` points there.
  So does the PacIOOS team note's "Set up once" step.
- **The team note was trimmed (2026-11-13)** so it does not repeat the README, `upload/README.md`,
  `AGENTS.md` or the issues: it now leads with working with an agent, then the tasks, then a
  pointer to the upload instructions. Keep it that way: link, don't copy.

## Working notes

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
