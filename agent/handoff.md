# Handoff — pacioos

Rolling state for this repo. Orientation only: the open threads are a record of what is
unfinished, not a task list.

## Where things stand (2026-11-19)

### WRF publication and archive scope (#12)

- **WRF Era 2 store published (#12).** The single root group at
  `ocean-icechunks/pacioos/wrf_hi/icechunk` has 80,087 covered hours from 3,041 HDF5
  runs, 2017-08-16T03Z through 2026-11-22T00Z. Production snapshot
  `P9R11AXCREQ7KGD2NQQ0` opened anonymously, matched the ERDDAP time axis and four
  point values, and matched four source NetCDF planes. It uses the approved forecast
  title and saved ERDDAP metadata. The tested loading example and build source bundle
  are beside the public store. Daily updates are tracked in #4.

- **WRF Era 1 removed from public distribution.** With explicit authorization, deleted 2,569
  Era 1 NetCDF objects (471,465,439,096 bytes) after checking the published PacIOOS stores and
  WRF scratch snapshots for references. The public WRF inventory contains 3,041 Era 2 NetCDFs
  (464,032,417,051 bytes). Also deleted and verified removal of the 2,569 Era 1 checksum
  sidecars (136,157 bytes). The uploader skips WRF runs before 2017-08-16.

### Reconciliation with main prepared (2026-11-19)

Merged main's product-viewer/build-bundle and team WRF documentation into
`deployable-icechunker` without rewriting the published branch history. The two textual
conflicts (this handoff and the Source Cooperative product README) are resolved by preserving
both sets of work. Shared product viewer links and main's latest dataset READMEs are retained.
The historical deployment notes below remain dated observations, not live server checks.

Integration safeguards now disable all automated WRF README/header/store-metadata work,
including direct publication; WRF copies can still be verified/acknowledged. Its existing
team-owned store and README remain untouched, and any old pending README state is retained
for operator review. ROMS forecast/WW3 and versioned reanalysis documentation keep their
existing behavior; the 15-minute default is preserved.

The separate bundle publisher preflights all destination READMEs before any upload, rejects
Icechunker metadata markers (even incomplete ones), and conditionally completes multipart
README uploads using the preflight ETag or create-only condition. Concurrent edits fail;
manual edits made before preflight still require the operator's live-versus-git review.
Managed README prose changes need a separate reviewed edit preserving the generated block.
Bundle dry runs may preview pending working-tree changes without credentials/network;
real publication still requires clean committed inputs and sends exact file bytes.

The bundle excludes development tests and publishes `upload/source_coop_credentials.py`
beside `icechunk_utils.py` at the product root. Credential lookup supports this downloaded
layout as well as the repository/deployed layout, and shared requirements include boto3.
No WRF files, NetCDF objects, stores or viewers are included in bundle publication.

Local validation: 83 operations/deployment tests, six store-authentication tests, eight
bundle-publisher tests and six upload-authentication tests passed (103 total), plus Python
compilation and whitespace checks. The network-free bundle preview lists 38 files, including the sibling API-key helper,
with no development tests, WRF directories, NetCDF objects, stores or viewer assets.
No production reads/writes, server deployment, cron changes or push were performed. The
resolved merge is being prepared for explicit commit approval, as requested earlier.

- **One product viewer and the build files published, 2026-11-19 (PR #34,
  merged).** Viewer at `pacioos/viewer/index.html`, catalog = forecast,
  reanalysis, WW3 (`publish_viewer.py --product pacioos`). `stores/publish_bundle.py` uploads
  the committed READMEs, `requirements.txt`, notebooks, scripts and saved metadata, mirroring
  `stores/` under `pacioos/`; rerun it after editing a README (it replaces `pacioos/README.md`).
  39 files verified by MD5 and content type. **The old per-dataset viewers
  (`pacioos/<dataset>/viewer/`) are still up** until Eli checks the new one, then delete them
  (one key at a time). Why the files had been missing: ocean-icechunks/ocean-icechunks-skills#19.
- **The PacIOOS team worked on their own, 2026-11-18:** they built and published a WRF store
  (`pacioos/wrf_hi/icechunk`, HDF5 era from 2017-08-16, snapshot `P9R11AXCREQ7KGD2NQQ0`, with
  `wrf_hi/README.md` and `build-source.zip`), ran the ROMS and WW3 updaters (copies to the 11-17
  ROMS / 11-16 WW3 runs) and edited the live product and store READMEs. Their code is not in
  this repo. Their live READMEs were copied in unchanged before ours were edited; **before any
  README upload, diff the live copy against git** — they may edit them again. Leave `wrf_hi/`
  to them (`publish_bundle.py` refuses it; WRF is not in the viewer until they want it).
- **`~/venvs/pacioos` is now Python 3.13** (`/srv/conda/envs/notebook/bin/python3`): the hub
  image lost `/srv/conda/bin/python3.12`; the old venv is `~/venvs/pacioos.broken-py312`.
  The requirements files' "use /srv/conda/bin/python3.12" comment is stale. The WW3 smoke
  notebook ran clean in it (26 cells, 0 errors).

### PR commit preparation (2026-11-19)

Prepared the deployable Icechunker runtime, authentication, incremental validation, dataset
README metadata, 15-minute default and associated documentation/tests as one reviewable
change. Reconciled the root README's store coverage with the dataset/product READMEs and
corrected the historical automation plan's stale implementation status. Notebook checkpoints
are ignored. The six superseded local wrappers (`check-setup`, `cron-config`, `run-sync`,
`verify-store`, `launch.sh`, `tool.sh`) remain untracked and are excluded from the proposed
commit and runtime payload. Only the unified `icechunker` interface is supported.

The latest full local checks passed: 81 operations/deployment tests plus 10 authentication
tests, and `git diff --check`. Commit preparation makes no server changes; the remaining
15-minute-default deployment and production metadata-validation caveats below still apply.
The user requires explicit approval before the prepared commit is created.

### Minimum source-file age reduced to 15 minutes (2026-11-19)

The user requested lowering the default `minimum_age_minutes` from 120 to **15 minutes**.
Local changes cover `ops/common.py`, `ops/config.example.toml`, the standalone uploader's
`MIN_AGE_MINUTES` default/help, its test fixture and operator/upload documentation. The
deployment design records the setting, last-modification-time semantics and limitations:
the waiting period reduces the risk of copying an unfinished file but does not prove
completion. Eleven targeted config/upload tests, uploader shell syntax and
`git diff --check` passed. Preserve the existing uncommitted work.

**Latest observed server state:** a read-only check found `config/config.toml` already sets
`minimum_age_minutes = 15`, while deployed `app/ops/common.py` and the shipped config example
still default to 120. All 26 deployed payload checksums match their existing manifest.
The active explicit config takes precedence, so subsequent syncs use 15 minutes. No claim is
made about who changed that config: an earlier inspection saw 120, and the agent's deployment
attempt stopped at a busy lock before changing any server files.

**Pending:** deploy the revised default files/operator guide and regenerate the payload
manifest once installation/dataset locks are available. Recheck current config and preserve
explicit operator choices rather than overwriting them with defaults. Do not interrupt an
active job, rerun bootstrap or alter cron for this change. No sync or production upload was
run by the agent. The README metadata feature described below remains deployed.

### Dataset README metadata deployed (2026-11-19)

The user requested deployment of the metadata follow-up. The updated payload is now active
in the existing `~/icechunker` installation. Its 26 runtime files match the new manifest.
Deployment held the exclusive installation lock and existing dataset locks, verified the
previous payload before replacement, and retained rollback copies only until validation
succeeded. Temporary deployment/recovery material was removed afterwards.

Server checks passed: all payload checksums, installed Python imports for the new metadata
module and pipeline, configuration parsing, SDK support for conditional multipart completion,
CLI help, shell syntax and host-Python helper syntax. Configuration, credentials, durable
state, installed runtime metadata/dependencies and crontab were verified unchanged. Config
and key are now present; the configured datasets remain `roms_hiig` and `ww3_hawaii`.
WRF and reanalysis remain opt-in through the updated example; deployment did not enable them.

No bootstrap, dependency installation, sync/full verification, remote README publication or
cron activation was run. Metadata initialization still waits for the next successful transfer.
Source Cooperative conditional multipart publication still needs supervised production
validation; offline SDK checks do not establish that service behavior.

### Dataset README metadata follow-up (2026-11-19)

The approved README metadata follow-up adds `ops/dataset_readme.py` and connects it to sync.
Preserve all preceding uncommitted work. It maintains only a marked section in the remote
`<prefix>/<dataset>/README.md`, with separate complete listings of actual published Icechunk
root attributes and the latest completed NetCDF file's global attributes, including provenance.
NetCDF-3/4 global headers are read without science arrays. Initialization waits for the next
transfer; idle syncs reuse cached file attributes and can detect changed store metadata.

`readme-netcdf.json` binds attributes to an immutable copy identity; `pending-readme.json`
separates documentation retries from acknowledged data/store work. README errors fail sync;
retries reread current prose and conditionally write only changed content. Status shows pending
README work. Config now accepts `roms_hiig_reanalysis` with `update_store = false`; upload keys
retain `netcdf/v2.0/`, and metadata comes from its existing `v2.0` tag. No automatic reanalysis
store updater or repository verifier is added. The config example leaves reanalysis opt-in.

Operator/root/product READMEs and the deployment design explain these behaviors. No server
staging, bootstrap, production processing, remote README writes or cron changes were performed.
Conditional README writes need supervised Source Cooperative validation before activation.
Local validation: all **81 operations/deployment tests plus 10 upload/store authentication
tests passed** in the existing Python 3.12 pinned development environment. Coverage includes
real NetCDF-3/4 headers and HTTP range reads without array access, actual local Icechunk
snapshot/tag attributes, preservation/escaping, unchanged skips, conditional multipart
publication and conflict cleanup, config/version paths, read-only verify/dry runs, and a
README failure after a store commit followed by retry without another commit or checksum
download. Payload/deployment tests, Python compilation and `git diff --check` also passed.
Remote multipart/conditional support is not established by these offline tests.

### Current checkpoint for the next session — bootstrap defaults (2026-11-19)

**The simplification and bootstrap-defaults follow-up are implemented and staged. Preserve
all existing uncommitted work; do not repeat the completed fresh reset.** The authoritative
design is [`docs/design/deployable-icechunker.md`](../docs/design/deployable-icechunker.md);
operator instructions are in [`ops/README.md`](../ops/README.md), deployed as
`~/icechunker/README.md`.

Latest approved behavior:

- A successful `bootstrap.sh` copies `app/ops/config.example.toml` to
  `<root>/config/config.toml` only if absent, and creates an empty
  `<root>/config/source-coop.key` only if absent. Both new files are mode `600`, the directory
  is mode `700`, and files belong to the invoking user. Paths are relative to the chosen
  installation root, not the shell's working directory.
- Existing files/content are preserved, including an existing empty key. Exclusive creation
  prevents truncation on repeated installs or upgrades. The example is shipped code; generated
  config/key files are private operator files outside the payload manifest.
- Creating a placeholder is not credential provisioning. The human reviews config and fills
  in the key; `check` rejects an empty/invalid key and makes no network requests. Bootstrap
  never fetches credential values, runs processing jobs or installs cron.
- `ops/bootstrap.sh` delegates to `ops/install.py`; `initialize_config()` runs after dependency
  and application checks under the installation lock. Local/root READMEs and bootstrap
  help/output describe the new behavior. The design now records this as a reusable principle.

**Latest observed server state:** `~/icechunker` now contains a managed environment; do not
assume `.runtime/` is empty. Config and key were still absent at the last inspection. No
claim is made about who executed bootstrap or its full results. The follow-up staged
`bootstrap.sh`, `app/ops/install.py`, `README.md` and `MANIFEST.sha256` under an exclusive
installation lock, preserving existing files/state. All 25 runtime checksums and host-Python
helper/shell syntax passed afterwards; temporary update/recovery material was removed.
The agent did not execute server bootstrap or create server config/key files. The initial
staged-only measurements and empty-directory observations below are historical, not current.
No production processing/full verification or new cron activation was run by the agent.

**Validation:** the follow-up reran all 14 deployment tests successfully, including fresh config
contents, empty key, private modes and preservation of edited config/key on repeated installs.
These 14 are a subset of the prior 59 operations/deployment tests, not additional tests. The
previous full 59-test operations suite plus 10 auth tests passed before this follow-up; a new
real bootstrap and supervised production tests remain human work. This documentation-only
checkpoint makes no additional server changes and does not rerun bootstrap or processing.

**Next human action:** rerun `bash "$HOME/icechunker/bootstrap.sh"` to create the missing files,
review `config/config.toml`, and fill `config/source-coop.key` privately. Then follow the
operator guide: local `check`/`status`, supervised per-dataset dry runs and real new-transfer
validation, explicit full verification, and only then manual cron activation. An installed
environment alone does not establish working credentials or successful production processing.

### Initial simplification delivery and validation (2026-11-19)

The approved design in [`docs/design/deployable-icechunker.md`](../docs/design/deployable-icechunker.md)
is implemented. **Server bootstrap and activation remain human work.** No server dependencies,
config, API keys, processing jobs or new cron entries were provisioned/run by this implementation.
The existing uncommitted workspace was preserved; changes remain uncommitted.

- **Initial staging state (superseded by the checkpoint above):** `~/icechunker` contained `README.md`, `bootstrap.sh`, `icechunker`,
  `MANIFEST.sha256`, `app/`, empty `config/`, empty `logs/`, `state/seeds/`, and empty `.runtime/`.
  No setup/release/current trees or installed environment remained immediately after reset.
- **Unified command:** `help [command]`, global/per-command `--help`, `sync`, `check`,
  `verify --scope recent|full`, `status`, print-only `cron`, preview-first `clean [--apply]`.
  Help uses host Python without config, keys, network or science imports. Local readiness
  does not establish remote authentication. Cleanup excludes durable state, credentials,
  dependencies, logs and failed-install work, and shares the installation lock with jobs.
- **Implementation:** `ops/cli.py`, `ops/icechunker`, `ops/install.py`, simplified
  `ops/bootstrap.sh` and updated `layout.py`, `common.py`, `jobs.py`, `headers.py`.
  `ops/package.py` explicitly maps 25 runtime files, excluding development tests, notebooks,
  historical docs and old launchers. Old standalone scripts remain in the development repo;
  they are not deployed or supported as compatibility paths. Processing modules/reference
  math and array layout are reused. `pipeline.py` adds local permission/access readiness
  checks; its processing logic is preserved.
- **Installer:** pinned rclone/uv/Python and unchanged glibc-2.27 wheel lock; one app and one
  final-path environment; unchanged dependencies are reused. Changed installations retain
  only temporary recovery material under `.runtime/install-work/`, restore original paths on
  ordinary failure, and remove recovery/downloads/caches on success. Interrupted recovery
  journals stop another install and need inspection. Never execute a backup environment.
- **Seeds:** the previously validated 657 ROMS / 5,237 WW3 cached headers are bundled under
  `state/seeds/headers/`, with a separate eight-file SHA256 manifest. Adoption validates
  provenance/checksums/current object identities, then removes the compressed seed. It does
  not fabricate an MD5 ledger or full-verification result. Historical cache initialization
  remains explicit; a no-transfer sync still reads no source headers/science data.

**Local validation:** 59 operations/deployment tests plus four store-auth and six uploader-auth
checks pass. Coverage includes config-free help, local-only check, explicit payload contents,
sync/verification worker dispatch, invalid selections, repeated installation, successful/failed
upgrades, original-path restoration, cleanup preview,
locks/symlink escapes, immutable copies, selective headers/data, forced full-refresh failures,
snapshot reader checks and interrupted-publication recovery. A separate real local bootstrap
used checksum-verified tool downloads and the pinned wheel-only environment. Real repeated
installation and code upgrade succeeded. A deliberately invalid dependency upgrade failed at
wheel preflight after replacing the environment; rollback restored the original metadata,
runnable environment and durable state. `pip check`, scientific imports, help and status passed
after deleting caches. The task-created local installation was removed after these checks.
These are local results, not evidence of server bootstrap compatibility.

**Server reset and validation:** reinspection identified only the old `~/icechunker` deployment
and `/tmp/pacioos-rclone` helper; documented `~/pacioos-sync`, `~/.local/share/pacioos-sync`,
`~/.local/state/pacioos-sync` and `~/.config/pacioos-sync` locations were absent. Replacement
payload and tests were ready before deletion. Old bootstrap/dataset locks were acquired and
no running Icechunker processes were found, so no processes were killed. Removed only the
confirmed old root contents (`current`, both releases/setup packages, tools/interpreter/bin,
caches/downloads/tmp/run/data, old config/key files and state/seeds) and the temporary helper,
whose hash matched the tested pinned rclone binary. The exact commented PacIOOS cron block
was removed; the original crontab header was preserved and there are no scheduled jobs.
Source archives, forecast processes, unrelated jobs, the development repo and published stores
were not modified. Reset helpers were removed after use.

At initial staging, all 25 runtime and eight seed checksums, owner/modes (directories and
entrypoints `700`, other files `600`), shell syntax, host-Python 3.6 early-helper syntax and
all help forms passed. `.runtime/`, `config/` and `logs/` were then empty, and no job
lock/results were created by the help checks. Before reset the old deployment measured 878,964 KiB;
the final staged payload measured about 41.7 MiB (42,688 KiB). This compares an installed
deployment with a static payload; **it is not a prediction of post-bootstrap disk savings**,
and shared cache blocks must not be counted twice.

**Human next steps**, detailed in [`ops/README.md`](../ops/README.md), also delivered as
`~/icechunker/README.md`:

1. Read `~/icechunker/icechunker help` and the staged README, then run
   `bash "$HOME/icechunker/bootstrap.sh"` yourself. Use `--root` for a custom staged root.
2. Review the bootstrap-created `config/config.toml` for source/destination/limits, and fill
   the empty `config/source-coop.key` with the service-account key. Bootstrap creates missing
   files with mode `600` in a mode `700` directory and preserves existing contents. Old config/keys
   were intentionally removed by the authorized fresh reset.
3. Run `icechunker check`, `status`, then supervised `sync --dataset NAME --dry-run` for ROMS
   and WW3. Supervise a real new-transfer update and its anonymous snapshot validation.
   Review seed identity mismatches rather than forcing a historical scan during normal sync.
4. Run `icechunker verify --scope full` explicitly and review results/coverage, with realistic
   runtime limits. It audits metadata/references and samples science data, not every chunk
   or historical NetCDF byte. Routine success cannot clear a failed full audit.
5. Review `icechunker cron` and install chosen entries manually only after supervised tests.
   Monitor failures, skips/timeouts, pending transactions and age of the last full audit.

No general skill changes or external issue updates were needed for this implementation.

### Existing deployed implementation (before simplification)

**Historical only: the deployment described below was removed in the authorized fresh reset.**
The following describes the previously deployed implementation, not the delivered new layout.
The delivered implementation above supersedes conflicting preservation/migration guidance here.

- **Active installation:** `$HOME/icechunker/current`, currently pointing to
  `releases/incremental-933c3d56994c`. The latest setup package is
  `$HOME/icechunker/setup-20261118-incremental`. No re-bootstrap is needed for the active fix.
  All new provisioning stays under `$HOME/icechunker` (or a configured single root), including
  API keys and caches. Legacy installations were preserved; do not move virtual environments.
- **Normal command:** `~/icechunker/current/ops/run-sync`. Validate new/pending transfers only.
  With no incoming transfers, skip header reads, science sampling and store writes. Listings
  still enumerate existing objects to discover new ones; this is not full data verification.
- **Weekly command:** `~/icechunker/current/ops/verify-store --scope full`. This refreshes all
  source headers and audits historical metadata/references with science-data samples; it is
  not an exhaustive download of every historical NetCDF or virtual chunk. All-file MD5
  download verification remains the separate `upload/verify_source_coop_copy.py` operation.
- **Locking is built in:** normal and verification jobs share a nonblocking exclusive lock
  per dataset/destination under the configured state directory. No outer cron `flock` is
  needed. Overlap records a skip and returns nonzero; locks release when the process exits.
  Use the same configuration/state directory for every invocation. Legacy standalone
  upload/update scripts do not participate in these locks.
- **Human testing remains pending:** test an actual new transfer/update and the full weekly
  command after the fix. The installed no-transfer path passed an offline synthetic test;
  no production sync or full audit was run by the agent after activation. Bootstrap execution
  and cron setup remain reserved for the human. No cron entries were added or changed.
- **Validation and repository state:** 47 operations tests and 10 auth tests passed; both
  cached coordinate plans match the public stores. Code, docs and auth changes remain
  uncommitted in the shared workspace; preserve unrelated changes when preparing a commit/PR.
  The hotfix reuses the preceding release's environment through an in-root link; retain that
  environment until replaced, using `hotfix.json` to identify it. Operator guide: `ops/README.md`.

### Session history

- **Routine verification corrected and active, 2026-11-18.** The human's log showed zero
  transfers followed by reads of all 657 ROMS headers because the new installation's cache
  was empty (48 rows cached when inspected). `run-sync` now exits without header/science
  reads or store writes when no new/pending transfers exist. Incoming copies are tracked
  against `known-copies.json`, acknowledged only after publication succeeds, and MD5-downloaded
  only if not already verified. Science samples are restricted to incoming source URLs in
  the configured recent window. Planning reuses cached headers and grid/mask metadata;
  normal sync never silently fills a historical cache or rechecks every historical row.
  `verify-store --scope full` explicitly refreshes every source header, fails on fresh read
  errors even when old successful cache rows exist, compacts the cache, and performs the
  existing archive-wide coordinate/reference audit plus historical science samples.
  New `ops/headers.py` separates selective header checks from full verification. Previously
  validated caches (657 ROMS and 5,237 WW3 rows) are provided under `<root>/seeds/headers`,
  with source-copy identities/checksums; adoption is metadata reuse, not a new MD5 ledger
  or successful weekly verification. Cached plans match published coordinate metadata for
  both datasets (5,537 / 135,214 steps), checked locally without science-data reads.
  Staged package: `$HOME/icechunker/setup-20261118-incremental` (57 payload checksums verified).
  Activated code release: `incremental-933c3d56994c`, reusing the previous installed `.venv`
  via an in-root link; retain its previous release/environment (recorded in `hotfix.json`).
  Activation held bootstrap and dataset locks; no bootstrap, dependency installation,
  production sync, full verification or cron mutation was performed. The installed
  no-transfer path passed an offline synthetic check with network/header/data functions
  disabled. Local tests: 47 operations plus 10 auth tests pass.

- **Single-root provisioning staged, 2026-11-18.** The human confirmed the glibc-compatible
  bootstrap works, then requested every managed local file beneath a single root, with only
  user-managed cron entries outside. New default is `$HOME/icechunker`, configurable with
  `--root` (`--prefix` alias). The new static setup package is staged on the PacIOOS server
  at `$HOME/icechunker/setup-20261118`; all 47 payload file checksums verified, shell syntax
  passed there, and the host Python 3.6 parsed `ops/layout.py`. The agent did not run bootstrap,
  jobs or cron, or move/copy existing configuration/API keys. Legacy installations are intact.
  Run the new package's bootstrap manually to build a fresh environment at its final path;
  do not move the old virtual environments. The guide covers manual config/key/state migration.
  `ops/layout.py` enforces containment of setup, tools, interpreter, state, config and key
  paths, including symlinks. Bootstrap and job/tool launchers redirect XDG, uv/pip/rclone/CLI
  caches, bytecode and temporary files beneath the root without changing HOME. Manual tools
  use `<root>/bin/` wrappers; the optional Source Cooperative CLI uses an in-root file cache
  instead of the desktop keyring. `ops/common.py` applies the same containment and environment
  to direct Python jobs. Validation: 37 operations tests and 10 existing auth tests pass;
  bootstrap remains reserved for the human operator, including this new revision.

- **Original setup directory also patched, 2026-11-18.** The human still saw the old
  netCDF4 1.7.5.1.post1 source-build error. Inspection confirmed `setup-20261118` and the
  initial failed installed release still had the original pins; the separate `-glibc27`
  package was corrected. Copied the corrected bootstrap, lock and two READMEs into the
  original `$HOME/pacioos-sync/setup-20261118`, preserving backups in a private sibling
  `before-glibc27-inplace.*` directory and updating/verifying the package checksum manifest.
  Both staged setup directories now use netCDF4 1.7.4, h5py 3.15.1 and wheel-only installs.
  Retry explicitly with `bash "$HOME/pacioos-sync/setup-20261118/ops/bootstrap.sh"`, keeping
  the same path flags. The immutable failed installed release was not modified; a corrected
  bootstrap generates a new release identity. Bootstrap and cron remain the human's job.

- **Bootstrap wheel compatibility corrected, 2026-11-18.** The human's bootstrap attempt
  fell back to compiling netCDF4 because the server has glibc 2.27, while the original
  netCDF4 1.7.5.1.post1 and h5py 3.16.0 x86_64 wheels require glibc 2.28. The ops lock now
  pins netCDF4 1.7.4 and h5py 3.15.1, whose wheels support glibc 2.27. Bootstrap performs
  a wheel-only dry-run preflight and installs with `--only-binary :all:`; it never falls
  back to compiling science dependencies on the server. Every locked package's CPython
  3.12/glibc-2.27-compatible wheel downloaded successfully on the development host, a fresh
  wheel-only environment passed `pip check`, and all 35 operations/auth tests passed there.
  The corrected static package is staged at `$HOME/pacioos-sync/setup-20261118-glibc27` on
  the server; use its bootstrap with the same persistent path flags as before. Keep the
  original package and failed release intact. The agent still must not execute bootstrap,
  install packages on the server, run production jobs, or configure cron for this human test.

- **Automation implemented and staged for human testing, 2026-11-18.** New `ops/` contains
  persistent unprivileged bootstrap (pinned rclone/uv, Python 3.12, locked environment,
  optional Source Cooperative CLI), config example, local sync/verification runners,
  cron preview/install/remove, and the operator guide. A static package is on the server
  reached by the `pacioos` SSH alias at `$HOME/pacioos-sync/setup-20261118`; all 45 payload
  file checksums verified after transfer. No credentials, tools or environments were installed
  there, bootstrap was NOT run, no data processing jobs were run, and user crontab remained
  absent. **The user explicitly reserves bootstrap execution and cron setup for human testing.**
  Read `ops/README.md` for the first command and configurable persistent roots.
  Validation: 25 local operations tests (including real NetCDF/Icechunk reads via a synthetic
  local HTTP range server), four store-auth and six uploader-auth tests passed; shell syntax
  passed locally and on the server. Tool archive layouts and official checksums were checked
  locally. Actual bootstrap/download/library compatibility on the server is untested.
  Routine jobs validate a configurable recent window (past three days plus forecast horizon
  by default), including no-change runs and interrupted-commit recovery. Separate `verify-store
  --scope full` audits all historical metadata/source locations with sampled science reads;
  it is intended for weekly scheduling, not exhaustive chunk reads or all-file MD5 downloads.
  New copies are MD5-download verified before references are committed; preexisting published
  copies get an explicitly identified legacy baseline, not a fabricated verification ledger.
  Long-lived Source Cooperative service-account keys are allowed on the server (user decision);
  keep them private and outside code/logs. `docs/design/automation-plan.md` records the design.

- **Store catch-up completed, 2026-11-18 18:37 UTC.** Network access to Source Cooperative
  is restored. Recreated `/tmp/pacioos-store-venv` from `stores/requirements.txt` plus boto3
  (Python 3.12, Icechunk 2.3.1, VirtualiZarr 2.8.0, Zarr 3.4.2; `pip check` and all four
  offline store-auth tests pass). Both production dry runs were reviewed before applying
  their corresponding updates. Full header caches now cover all 657 ROMS and 5,237 WW3 files;
  preserve `stores/*/out/scan.jsonl` for incremental scans.
  - ROMS: added 16 steps, re-pointed 41 from the 2026-11-17 run; snapshot
    `XA93E152DH2YJ3KEZ3E0`, 5,537 steps through 2026-11-24T00Z, none uncovered.
    Anonymous validation: every time coordinate equals the plan; 40 planes across eight
    changed steps equal netCDF-C.
  - WW3: added 24 steps, re-pointed 157 from the 2026-11-16 run; snapshot
    `2SWWVCGZ5X3GW567FSGG`, 135,214 steps through 2026-11-23T18Z, 1,594 uncovered
    (unchanged). Anonymous validation: every time coordinate, including `best_step_flag`,
    equals the plan; 72 planes across eight changed steps equal netCDF-C.
  Both stores now include every copied run. No NetCDF copies were changed. The two store
  READMEs and `source-coop/README.md` were uploaded and verified byte-for-byte by anonymous
  public HTTPS reads at 18:37 UTC.
  `stores/icechunk_utils.py` supports the uploader's local API-key helper, preserving explicit
  CLI/cache selection and never falling back to another identity after exchange failure.
  `/tmp` environments may need recreating after cleanup/reboot.

- **Access restored and upload setup in progress, 2026-11-18.** Passwordless SSH via the
  `pacioos` alias works again. The current operator's service-account API key is stored locally
  outside the repo; its format/checksum and private file permissions passed, and exchanging
  it for temporary S3 credentials and signed ROMS/WW3 listings succeeded. Write access has
  not been tested. Installed rclone v1.76.0 at `/tmp/pacioos-rclone/rclone` (mode 700 in a
  mode-700 directory): official archive SHA-256 verified locally, remote binary SHA-256
  matched, and remote `rclone version` succeeded. This is a temporary directory and may need
  recreating after cleanup/reboot. The SSH wrapper now defaults to that neutral path, SSH
  alias `pacioos`, and local logs outside git at `~/pacioos-upload-logs/logs/`.
  API-key auth is now connected: `upload/source_coop_credentials.py` exchanges the local key
  for one-hour temporary credentials (boto3 required); the wrapper fetches once per batch,
  keeps credentials in memory, sends only temporary credentials over SSH, and stops starting
  files 30 minutes before expiry. It auto-selects the API key if the file exists; explicit
  `SOURCE_COOP_AUTH=api-key|cli` is supported. Six offline auth checks pass.
  **Live dry run, 2026-11-18 17:30 UTC:** ROMS has 656 matching completed copies and one new
  source file (`2026/hiig_forec_20261117.nc`); WW3 has 5,236 matching completed copies and one
  new source file (`2026/ww3hawaii_20261116.nc`). Both report zero changed, zero missing MD5,
  and zero too-new files. No NetCDFs were uploaded. Next: upload and verify these new copies,
  then update the stores. Source metadata check: the new ROMS file is 1,901,895,420 bytes,
  WW3 is 92,799,652 bytes; ROMS 11-16 and WW3 11-17 are absent from the current source folders
  (latest available files are ROMS 11-17 and WW3 11-16). Confirm missing runs with PacIOOS.
  **Catch-up completed, 2026-11-18 17:42 UTC:** both files uploaded with immutable writes
  (`PARALLEL=1`); zero failures or changed files. Both full public HTTPS downloads matched
  the source MD5 and byte count: ROMS `927253e317429c418d9addc8d1181dad`, WW3
  `f1c44fe81a7648b235b8d57c01560bf7`. Destination inventory: ROMS 657 files,
  1,249,578,666,176 bytes; WW3 5,237 files, 485,731,852,444 bytes; every NetCDF has a sidecar.
  Icechunk stores have NOT been updated for these two runs. Repo README and product README
  snapshot now reflect the new copies; publish the product README with the next store update.

## Earlier (2026-11-17)

- **Ready for the hackweek, 2026-11-17 (PR #29, merged).** The team note doc was brought up to
  date (stores, updaters, new agent prompts, #12/#14) and snapshotted as
  `docs/design/team-note.md`. The README now opens with "Start here": four numbered first steps
  (clone, start an agent, install the skill, a first prompt, then #4) and the four team docs
  with their snapshots. Issue #4 has a status line at the top of its body and a
  [status comment](https://github.com/ocean-icechunks/pacioos/issues/4#issuecomment-6933876409)
  (what exists, catch-up by hand, what is left, questions for PacIOOS). Eli added a ruleset on
  `main` (PR required); PacIOOS team members are not yet collaborators (Eli to add, Write
  access). Sharing of the Claude Docs is Eli's (Share button).
- **Catch-up copy and first production ROMS update, 2026-11-16 (PR #26, merged).**
  Run by the agent from the hub over the `pacioos` SSH alias (Eli asks the agent to run it, with
  her OK per run; `rclone` on the server is
  was at a person-specific temporary path; the current neutral convention is
  `/tmp/pacioos-rclone/rclone` (check availability before use); logs in `~/pacioos-upload-logs/logs/`, run with
  `LOG_DIR=$HOME/...`, not a quoted `~`). Dry run clean (0 without `.md5`, 0 changed); 9 files
  uploaded, copies now end 2026-11-15 for all three forecasts; all verified by downloaded MD5.
  **No 11-13 run** on the server for ROMS or WRF, and **WRF 11-12 is short** (67 hourly steps to
  11-15 00Z instead of 163; the copy matches the server) — ask PacIOOS, and note for #12.
  `update_store.py --dest production` then added 24 steps, re-pointed 41: snapshot
  `W2V6FPBAB0ET285V2XC0`, 5,521 steps to 2026-11-22T00Z, verified and opened anonymously. Store
  README and product README updated and re-uploaded (PR #26, merged).
- **WW3 updater and first production WW3 update, 2026-11-16 (PR #27, merged).** The diff /
  one-commit update / verify moved into `stores/best_series_update.py`, shared by
  `roms_hiig/update_store.py` and the new `ww3_hawaii/update_store.py` (time units read from the
  store; every coordinate on time rewritten, so `best_step_flag` too; verify finds the lead from
  the file's own time and **retries read errors**: Source Cooperative reset connections in three
  test runs in a row). Tests: ROMS 5/5 (pinned to runs through 11-12), WW3 6/6 (incl. a late
  cold-start run). Production: 96 appended, 157 re-pointed, snapshot `H4T38ERC0AV8DM92RAZG`,
  135,190 steps to 2026-11-22T18Z; covered steps = ERDDAP's 133,596. WRF (#12) can reuse the
  shared module.

Moved here from `ocean-icechunks/icechunks` on 2026-11-13 so the PacIOOS team can take it over
(history: that repo's PRs #35, #39, #42; issues transferred as #1–#4 here).

- **Copied to Source Cooperative and checked** (every file has a `.md5`; listings match the
  server; sampled downloads all matched): ROMS forecast `roms_hiig` (2025-01-01 to 2026-11-12),
  `wrf_hi`, `ww3_hawaii`, and `roms_hiig_reanalysis/netcdf/v2.0/` (4,380 files, 1,169.8 GB).
  Table in `README.md`. Copy done as #1 (closed).
- **Three stores built: the reanalysis (#11, closed), the ROMS forecast (#10, closed) and WW3
  (#13, closed 2026-11-16, PR #22).** Not built: #12 (WRF), #14 (all-runs view).
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
- **ROMS forecast store, #10: published 2026-11-14 (PR #20, merged; #10 closed).**
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

- **WW3 store, #13: published 2026-11-16 (PR #22, merged; #13 closed).**
  `ocean-icechunks/pacioos/ww3_hawaii/icechunk`, snapshot `ZRCNA5VTJJGRR12GECW0`, 135,094 hourly
  steps 2011-06-21T21Z..2026-11-18T18Z (1,594 uncovered), no tag. Validated anonymously: covered
  steps identical to ERDDAP's 133,500 times, 72 planes = netCDF-C, 12 points = ERDDAP. Viewer,
  README (with `cold_starts_2026.png`) and product README published. Decisions (Eli,
  2026-11-14): regular hourly axis; `z` a scalar; `best_step_flag` (1 cold-start run, 2 suspect
  2020 time label); **all metadata from ERDDAP, and the store must say so** (`metadata_source`,
  added to the ROMS stores too; reanalysis `v2.0` tag left on its old snapshot, Eli's call). The
  README's figure shows the Oct 2026 cold-start chain, and that runs *after* a cold start stay low
  but are unflagged. Code and team guide (with the file-vs-store attribute table):
  `stores/ww3_hawaii/how_store_created.md`. Eli checked the viewer; scratch
  store and viewer deleted 2026-11-16 (`build_store.py --dest scratch` recreates them).

## Open threads

- **Server access ended, 2026-11-17.** The `pacioos` SSH login refused this hub's key on
  2026-11-17 (publickey denied; the key is intact). Eli thinks the access was granted for 7 days
  (from about 2026-11-10). No catch-up until PacIOOS renews it or runs the upload themselves;
  the copies end 2026-11-15. Status for the hackweek is in a #4 comment (2026-11-17).

- **#10–#13 — virtual stores** serve the THREDDS "best" series (Eli, 2026-11-13: it is what
  PacIOOS serves). Facts that shape them, from the audit: WRF needs two groups (byte order changes
  2017-08-16); ties between runs go to the later file name (as THREDDS); 71 relabelled WRF runs,
  WW3 2020-04-27..05-04 probably a day early, and 81 WW3 cold starts (WW3: kept and flagged in
  `best_step_flag`; questions for PacIOOS in the audit doc). Only one-step (or one-depth-plane)
  chunks are possible in a best series. **#14**: the all-runs view, after the best stores.
- **No materialized rewrite.** Eli (2026-11-13): stores stay virtual. "Reprocessing" in the team
  report means rewriting the NetCDFs themselves (WRF 2010–17 first), a PacIOOS decision.
- **#9 — upload script fixed (PR #24, merged; #9 closed 2026-11-16).** A failed listing stops
  the run (exit 3; the SSH wrapper stops too), uploads use `--immutable`, and a copy without a
  `.md5` is checked by downloaded MD5, never re-uploaded. Measured on Source Cooperative: it keeps
  no mtime, so plain `copyto` overwrote identical bytes and `--immutable` refuses even identical
  bytes; an empty prefix lists with status 0, failures exit 1. Lesson filed as
  ocean-icechunks/ocean-icechunks-skills#15. `upload_over_ssh.sh` does not pass `DEST` (left
  as is). First run on the server 2026-11-16 (catch-up), clean.
- **Catch-up copy done 2026-11-16** (above); both stores updated. Until #4 is scheduled,
  catch-ups are by hand: the same wrapper, then each store's `update_store.py` (dry run first).
  Next store: WRF (#12).

- **#4 — daily auto-update** of forecast/WRF/WW3, the PacIOOS hackweek project (2026-11-17).
  Store side, measured 2026-11-14 (comments on #4): the best series needs an incremental update
  (resize + `set_virtual_refs` for 57 steps + rewrite the time coordinates), which matched a
  full build; `vz.to_icechunk` over an existing group raises `ContainsGroupError`. ERDDAP
  `roms_hiig` also ended at the 11-12 run on 2026-11-14, so there may be nothing new to catch up.
  **Working updaters** for ROMS and WW3 (`update_store.py` in each store folder, over
  `stores/best_series_update.py`; `--dry-run`), each with `test_update_store.py`; both used on
  production 2026-11-16. Left for the hackweek: schedule (the upload on the server, then the two
  updaters), a Source Cooperative role (Alex Kerney set up OISST's and can help), alerts, WRF.
  The copies fall behind whenever no one runs the upload, and the server's forecast archive is
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
  was brought up to date 2026-11-17 (stores, updaters, #12/#14) and snapshotted as
  `docs/design/team-note.md`; the audit doc's snapshot is `audit/report-pacioos.md`. Eli
  controls sharing (Share button); the repo snapshots are the fallback for readers without access.

## Notes

- [source-probe.md](../docs/design/source-probe.md) — public-server probe, sizes, chunking, options; corrections box at top
- [transfer-plan.md](../docs/design/transfer-plan.md) — snapshot of the transfer plan doc
- [virtual-icechunk-explainer.md](../docs/design/virtual-icechunk-explainer.md) — snapshot of the explainer doc
- [team-note.md](../docs/design/team-note.md) — snapshot of the team note doc (2026-11-17)
- [file-headers.md](../docs/design/file-headers.md) — what the copies' headers showed; why the store code is built as it is
- [audit/report.md](../audit/report.md) — full file audit (problems P1–P11, method, limitations)
