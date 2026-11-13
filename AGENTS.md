# AGENTS.md

Instructions for coding agents working in this repository. `CLAUDE.md` contains only
`@AGENTS.md`, so Claude Code reads this file too; edit `AGENTS.md`, not `CLAUDE.md`.

Read `agent/handoff.md` first: where the work stands and what is open. Design notes, with the
evidence behind decisions, are in `docs/design/`.

## What this repo is

Code to copy PacIOOS's Hawaiʻi model NetCDFs (ROMS, WRF, WW3) unchanged to Source Cooperative
(`ocean-icechunks/pacioos`) and build virtual Icechunk stores over the copies. See `README.md`.

## Skills

Use the shared skills in <https://github.com/ocean-icechunks/ocean-icechunks-skills> rather than re-deriving practice here, and feed new
general lessons back there. Its README says how to install them and how to report a lesson:

- `virtual-icechunk` — building, validating and documenting virtual Icechunk stores.
- `archive-to-cloud` (proposed, ocean-icechunks/ocean-icechunks-skills#4) — auditing a source archive,
  copying it unchanged to object storage, and verifying the copies.

Keep only PacIOOS-specific facts in this repo.

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
- **Source Cooperative keys are short-lived** (about 12 hours from `source-coop creds`). Long
  uploads must stop starting new files before the keys expire, then resume; the scripts do.
