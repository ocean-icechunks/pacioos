# AGENTS.md

Instructions for coding agents working in this repository. `CLAUDE.md` contains only
`@AGENTS.md`, so Claude Code reads this file too; edit `AGENTS.md`, not `CLAUDE.md`.

Read `agent/handoff.md` first: where the work stands and what is open. Design notes, with the
evidence behind decisions, are in `docs/design/`.

**Current implementation brief:** [`docs/design/deployable-icechunker.md`](docs/design/deployable-icechunker.md)
(approved 2026-11-19). It defines the reusable packaging principles and the approved
simplification: one command with help, one active installation, no permanent
installer/release copies, and a fresh deployment instead of migration. It supersedes older
layout, migration and retention guidance in the handoff, operator guide and automation plan.

## What this repo is

Code to copy PacIOOS's Hawaiʻi model NetCDFs (ROMS, WRF, WW3) unchanged to Source Cooperative
(`ocean-icechunks/pacioos`) and build virtual Icechunk stores over the copies. See `README.md`.

## Skills

Use the shared skills in <https://github.com/ocean-icechunks/ocean-icechunks-skills> rather than re-deriving practice here, and feed new
general lessons back there. Its README says how to install them and how to report a lesson:

- `virtual-icechunk` — building, validating and documenting virtual Icechunk stores.
- `archive-to-cloud` (proposed, ocean-icechunks/ocean-icechunks-skills#4) — auditing a source archive,
  copying it unchanged to object storage, and verifying the copies.

Keep PacIOOS implementation facts in this repo. The user also explicitly requested reusable
packaging principles in `docs/design/deployable-icechunker.md`; preserve that design brief.
Feeding general lessons into shared skills is a separate follow-up, not a prerequisite for
implementing the approved simplification.

## Rules

- **The NetCDF copies on Source Cooperative are write-once.** Icechunk versions the store, not
  the files its references point at; overwriting a NetCDF silently changes or breaks every
  snapshot that uses it. Never overwrite or delete under `pacioos/<dataset>/netcdf/`. A new
  version goes in a new folder (`netcdf/v3.0/`). The upload script enforces this; keep it so.
  Versioning scenarios: issue #2.
- **Layout:** `pacioos/<dataset>/netcdf/[<version>/]<year>/<file>` for the files,
  `pacioos/<dataset>/icechunk/` for the store. Dataset names are PacIOOS's public THREDDS/ERDDAP
  ids.
- **The PacIOOS server runs the live forecast.** Keep load light (the upload script reads each
  file once at low priority). Write nothing there that PacIOOS has not approved.
- **No secrets or server details in git or in public issues:** no host names or IPs of the
  internal server, usernames, keys or credential files. Upload logs name the server; they are
  gitignored and stay that way. Folder paths of the data on the server, as in
  `upload/README.md`, are fine.
- **Source Cooperative service-account API keys may be stored on the PacIOOS server** for
  unattended jobs (approved 2026-11-18). Keep them outside git, owned by the job user, in a
  mode-700 directory with a mode-600 key file. Never include keys in logs or cron command
  lines. Exchange them for short-lived S3 credentials at runtime; refresh between bounded
  upload batches and stop starting files before temporary credentials expire.
- **Scheduled validation has two scopes** (approved 2026-11-18). Routine jobs validate a
  configurable recent window of newly transferred/pending source files (default: past three
  days plus the current forecast horizon). With no incoming transfers, do not scan source
  headers or read science data. Historical repository verification/cache initialization runs
  separately, initially planned weekly. Reuse validated header metadata; never silently
  populate an empty historical cache during normal sync. Preserve cheap
  update safety checks on every run. See `docs/design/deployable-icechunker.md` for the new
  interface and rollout; `docs/design/automation-plan.md` records the earlier design.
  The current implementation is in `ops/`; bootstrap and cron activation are
  reserved for the human operator's testing.
- **All new local provisioning belongs under one root** (2026-11-18): default
  `$HOME/icechunker`, configurable with `--root`. Scripts, downloads, Python/environments,
  config/API keys, state, caches and temporary files must stay inside it. Reject path and
  symlink escapes. Source model files are read-only inputs outside the root. The user's
  cron entries are the only local provisioning exception. Do not relocate virtual
  environments. The approved fresh-reset plan allows removing confirmed old PacIOOS tool
  deployments and their cron entries after the replacement payload is ready; protect all
  source data, unrelated jobs and published stores. Do not implement migration or compatibility
  wrappers. The human will reprovision keys/config, execute bootstrap and install new cron.
