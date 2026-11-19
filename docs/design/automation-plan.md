# PacIOOS bootstrap and scheduled sync plan

**Historical design, superseded for packaging on 2026-11-19:** read
[`deployable-icechunker.md`](deployable-icechunker.md) for the approved simplification and
reusable design principles. Its single command/help interface, one active installation,
temporary-only installer/recovery files, fresh reset and absence of compatibility wrappers
replace this document's release-tree, migration and retention proposals. The simplification
is implemented; see the current design and handoff for deployment status. Existing data-safety
and incremental-verification rules remain.

Approved direction, 2026-11-18. The implementation is now in `ops/`, staged for human testing;
bootstrap, production job execution and cron activation have not been performed as part of
staging. See [`ops/README.md`](../../ops/README.md) for the delivered commands and scope.
Build an unprivileged,
persistent installation that uploads immutable NetCDF copies and updates the ROMS and WW3
virtual Icechunk stores. WRF initially supports uploads only. Keep normal validation bounded
to recent data; run historical validation separately, probably weekly.

## Installation and configuration

Default install root: `$HOME/icechunker`, configurable with `--root` (or `--prefix`). This
single-root requirement supersedes the earlier separate XDG-style install/config/state roots.
Every provisioned local file belongs inside it, including setup sources, API keys, dependency
caches, bytecode and temporary files. Only the user's cron entries live outside. Relative
configuration paths resolve against the root; reject absolute paths and symlinks escaping it.
Source model files are read-only inputs and may remain outside.

| Location | Contents |
| --- | --- |
| `<install>/tools/` | Versioned rclone, uv, optional Source Cooperative CLI |
| `<install>/python/` | Managed Python 3.12 when an existing compatible interpreter is not selected |
| `<install>/releases/<revision>/` | Pinned repository code and its locked Python environment |
| `<install>/current` | Link to the validated release |
| `<install>/setup-<revision>/` | Staged setup scripts and guide |
| `<install>/config/` | Configuration and separately provisioned service-account key |
| `<install>/state/` | Header caches, verification ledger, progress journal, locks and logs |
| `<install>/cache/`, `<install>/tmp/`, `<install>/run/` | Tool caches, bytecode, temporary files and private runtime files |
| `<install>/bin/` | Manual tool wrappers that apply the same contained environment |

No runtime dependency may live under `/tmp`. Temporary download staging also stays inside
the root. The installed interpreter, environment, executables and state must survive
restarts. An explicitly supplied interpreter must resolve inside the root too. Support
another writable persistent filesystem without root access. Keep HOME unchanged; redirect
XDG, uv/pip/rclone/CLI caches, credential files and Python bytecode with their environment
settings. Do not add executable links or edit shell profiles outside the root.

The existing installation in the legacy directories remains intact until the human has
tested the new one. Rebuild environments at the new path instead of moving them. Migrate
configuration, keys and optional state manually into the new root, then clean up legacy
directories separately. Removing the root cleans up the new installation after the user
stops jobs and removes its cron entries.

`ops/bootstrap.sh` will install pinned tool versions from official releases, check download
checksums, install locked Python dependencies including boto3, run `pip check`, and exercise
imports and executable versions. Detect OS, architecture and binary compatibility before
selecting downloads. Report missing system prerequisites instead of attempting sudo.

Bootstrap is repeatable: matching installations are reused, and upgrades create a new release
before switching `current`. Keep the preceding release for rollback. Do not move a Python
environment after creating it; its interpreter paths must remain valid. Scheduling is a
separate operation. Jobs never update tools, dependencies or code automatically.

`ops/config.example` will cover install and state paths, source folders, dataset selection,
bucket and prefixes, public endpoint, key path and role, source-file minimum age, upload and
header-scan concurrency, batch/runtime limits, verification lookback, sample budget, schedule,
log retention and alert configuration. Keep secrets out of the configuration example.

## Server credentials

Long-lived Source Cooperative service-account keys are allowed on the PacIOOS server for
unattended jobs. This supersedes the earlier prohibition in the upload instructions. Use an
operating-team service account with access to the required product, owned by the job user;
keep the key outside git in a mode-700 directory with a mode-600 file. Provision and rotate
the key separately from bootstrap. Never place its value in arguments, cron, logs or generated
configuration.

Reuse `upload/source_coop_credentials.py` to exchange the key for temporary S3 credentials.
Keep temporary credentials in process memory/environment and refresh between bounded batches.
The API-key path is the default for cron; Source Cooperative's CLI is optional for manual
operation. A failed exchange must stop the job without falling back to another identity.
The SSH wrapper remains available for externally initiated transfers.

## Routine pipeline

Proposed command: `ops/run-sync --config /absolute/path/config`.

For each dataset, acquire a shared job lock, upload eligible NetCDFs, download and verify new
copies against their MD5 and size, compute the store update, commit, then validate the recent
window anonymously. Keep all stages for a dataset in one ordered invocation rather than
relying on separately timed upload and update cron entries. Allow unaffected datasets to
continue after a dataset fails, but return a nonzero overall status.

Preserve immutable writes, source-age checks, low-priority I/O and conservative upload
concurrency. Use a durable ledger of verified file identities/checksums to avoid downloading
the entire NetCDF archive on every run. An upload's sidecar alone is not a byte-for-byte
verification result. Gate store references on verified, complete files. Keep NetCDF copy
verification distinct from Icechunk repository validation.

An uploader exit status of zero can still mean files were deferred by its runtime limit.
Record deferred work and resume with fresh credentials within a bounded job budget. Report
remaining backlog separately from successful publication. Do not declare all work complete
because a batch exited successfully. Preserve header caches outside the release checkout so
only newly discovered or previously failed headers normally need scanning.

## Routine recent-window validation

Default `VERIFY_LOOKBACK_DAYS=3`, configurable. Anchor the past window to the job's UTC start
time, not the store's last timestamp: a stale store must not move its own health window back.
Include all available forecast times after that cutoff through the newest expected forecast
horizon. Report missing recent runs and stale coverage with configurable tolerances for model
completion delays. Do not silently fall back to older data when the recent window is empty.

Reopen the committed snapshot anonymously through its public URL. Within this window:

- Compare time, forecast origin, lead time and WW3 flags with the planned best series; check
  cadence, duplicates and unexpected coverage loss.
- Compare a bounded, deterministic selection of real science-data planes with netCDF-C reads.
  Include the newest run, daily/run transitions, the first and last covered window steps,
  and samples across the recent past and forecast horizon. Record the variables, timestamps
  and sample budget actually checked. An uncovered step must have the expected missing data.
- Check that published coverage and the latest run meet configured freshness expectations.

Run this check for incoming or pending transfers, including retries that make no additional
commit. With no new or pending transfers, normal sync performs no source data checks. This
2026-11-18 correction supersedes the earlier proposal to sample old recent-window files on
every no-change run. Sample science data only from incoming source files; full historical
checks and cache initialization belong to the explicit full-verification command. Keep cheap append-only and
no-coverage-loss checks on every update; do not run historical data sampling, full-archive
audits or long performance queries in this path. Planning may still inspect the full small
coordinate arrays and cached manifests to identify late arrivals correctly. A late historical
change outside the recent window is recorded for the next historical audit, not described as
having passed recent-window data validation.

Persist intended changes and the validation scope before committing. After interruption,
reconcile the journal against the actual branch snapshot and finish pending validation before
recording success. Otherwise a rerun can take the existing no-change path and forget that the
previous commit never passed validation. Pin validation to a snapshot and record its ID.

The current shared updater already samples changed steps rather than reading every science
chunk, but compares all time coordinates and returns early on a no-change run. Implement an
explicit recent-window verifier and recovery behavior rather than simply skipping verification.

## Periodic historical validation

Proposed separate command: `ops/verify-store --scope full --config /absolute/path/config`.
It is read-only and independently schedulable, initially weekly. It shares the dataset lock
with updates and validates a recorded snapshot. A normal sync never invokes this command.

Reconcile the complete source inventory, verified-copy ledger, cached manifests and committed
coordinates; check best-run selection, flags, dimensions, types, codecs, virtual prefixes and
coverage throughout history. Read historical science-data samples across every group, the
first and last data, transition boundaries and representative historical intervals. Reuse the
existing build validators where appropriate, without confusing optional ERDDAP availability
with required source-copy comparisons.

Document that full scope means an archive-wide audit with sampled science-data comparisons,
not exhaustive reading of every virtual chunk. If exhaustive chunk validation is needed,
provide an explicitly selected additional mode and its own resource budget. Likewise, a full
NetCDF byte-for-byte recheck is a separate copy-verification operation.

Track last successful recent validation and last successful historical audit independently.
A failed historical audit remains visible after a later successful routine update. Report
findings and preserve data; never overwrite originals or reset a branch automatically.

## Cron and operations

Generate a user-crontab fragment using absolute launchers and configuration paths. Suggested
starting cadence: normal sync every three hours; full store audit weekly. Confirm the server
timezone, model completion times and acceptable load before choosing exact times. Avoid
depending on implementation-specific cron timezone variables without checking support.

Illustrative entries, with actual persistent paths substituted by the installer:

```cron
17 */3 * * * "/absolute/install/current/ops/run-sync" --config "/absolute/config/config"
47 2 * * 0 "/absolute/install/current/ops/verify-store" --scope full --config "/absolute/config/config"
```

Both launchers set their working directory and environment explicitly and manage dated logs.
Locks must work on the chosen filesystem and protect both cron and manual runs. Record lock
contention as skipped/deferred work, and monitor repeated skips. Bound retries and runtime,
retain logs without needing root logrotate configuration, and preserve useful failures.
Alert on failed jobs, stale published coverage, backlog and overdue weekly validation.

Provide explicit cron install/remove commands that manage only a marked PacIOOS block and
preserve unrelated entries. Bootstrap only prints the proposed schedule. No server deployment,
key provisioning or cron activation is part of this planning change.

## Implementation and acceptance

1. Add bootstrap, locked dependencies, configuration example and prerequisite checks. Test
   repeat installation, alternate paths, checksum failures, interrupted installation and
   upgrade rollback under an unprivileged account.
2. Add the local credential-aware upload runner, durable ledger and shared locks. Exercise
   missing sidecars, changed originals, credential expiry and deferred batches against scratch
   storage. Allow destination configuration consistently across upload, planning and reading;
   the existing store destinations are hardcoded. Refuse a missing production store rather
   than accidentally creating one.
3. Separate recent and full store validation, including no-change checks and recovery after a
   commit. Test a broken recent reference, a stale store, a historical defect outside the
   recent window, and interruption between commit and validation. Confirm only the full audit
   reports the historical defect and that routine success does not clear that failure.
4. Generate cron configuration and document upgrades, key rotation, recovery, logs and
   disabling jobs. Test the launcher with a minimal cron-like environment and restart it with
   tools and state intact. Confirm overlap cannot produce concurrent writes.
5. Run a supervised production cycle, measure routine and weekly resource use, then enable
   the selected schedule. Keep WRF store updates disabled until its updater exists.

## References

- [Source Cooperative automated access](https://docs.source.coop/automated-access): service
  accounts and runtime API-key exchange without requiring the CLI.
- [rclone downloads](https://rclone.org/downloads/): official binary distributions.
- [uv Python management](https://docs.astral.sh/uv/guides/install-python/): installing a
  compatible interpreter without depending on the server's system Python.
- [crontab documentation](https://man7.org/linux/man-pages/man5/crontab.5.html): user schedules,
  execution environment and timezone considerations.
