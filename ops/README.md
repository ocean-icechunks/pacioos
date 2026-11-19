# Icechunker operator guide

Icechunker copies eligible PacIOOS NetCDFs unchanged to Source Cooperative and updates the
existing ROMS forecast and WW3 virtual Icechunk stores. ROMS reanalysis supports copies and
README metadata without automatic store updates. WRF supports copies only: the PacIOOS team
owns its existing store and README, and Icechunker does not modify either. Source NetCDFs are read-only
inputs; published copies are write-once. The command never creates a missing production store.

The simplified runtime and README metadata feature have been deployed. Bootstrap,
configuration/API-key provisioning, supervised production tests and new cron activation
belong to the operator. Consult the repository handoff for the latest observed deployment
state; deployment alone does not establish that production access or processing works.

## Obtain and stage the payload

No coding agent is needed to deploy Icechunker. The repository's `ops/` directory is a
development directory, not an installation package. `ops/package.py` selects the required
runtime files from `ops/`, `upload/` and `stores/`, arranges them for installation and writes
`MANIFEST.sha256`. Tests, old launchers, notebooks and development documentation are excluded.
The payload contains source code and dependency locks; bootstrap downloads and installs the
pinned dependencies on the server. It contains no operator config, keys or runtime state.

### Download the rolling main payload

Download `icechunker-main.tar.gz` and `icechunker-main.tar.gz.sha256` from the
[Icechunker main prerelease](https://github.com/ocean-icechunks/pacioos/releases/tag/icechunker-main).
The download URLs stay the same:

- [Payload archive](https://github.com/ocean-icechunks/pacioos/releases/download/icechunker-main/icechunker-main.tar.gz)
- [Archive SHA256](https://github.com/ocean-icechunks/pacioos/releases/download/icechunker-main/icechunker-main.tar.gz.sha256)

The **Icechunker payload** workflow builds and validates pull requests against `main` with
read-only permissions. On a push to `main`, a separate job replaces these assets after payload
validation succeeds. The workflow can also be started from `main` using **Run workflow** in the
[Actions tab](https://github.com/ocean-icechunks/pacioos/actions). The publication job checks that
the validated commit is still at the tip of `main`. The release notes record the source commit, and the
`icechunker-main` tag moves to that commit. This is a rolling prerelease, not a versioned release.
GitHub Actions artifacts must expire, so the workflow publishes release assets instead;
these have no automatic expiration. The repository must allow mutable releases and permit
the workflow's `GITHUB_TOKEN` to write contents and update the `icechunker-main` tag.
If a download overlaps replacement and its checksum differs, download both files again.

The tar archive preserves executable permissions and contains the installation files inside
a single `icechunker/` directory. Copy both files to the server under `~/icechunker/.runtime/install-work/` using
your normal SSH/SCP access. Create that directory privately first:

```bash
# On the server; use the job user's account.
umask 077
mkdir -p "$HOME/icechunker/.runtime/install-work"
chmod 700 "$HOME/icechunker"
```

### Or generate the payload locally

On a workstation with Python 3 and a checkout of the desired repository revision, run from
the repository root. No scientific dependencies or credentials are needed:

```bash
# Choose a new build directory for each build; package.py rejects an existing destination.
umask 077
build_dir="$HOME/icechunker/.runtime/install-work/local-build"
mkdir -p "$build_dir"
python3 ops/package.py "$build_dir/icechunker"
(cd "$build_dir/icechunker" && sha256sum -c MANIFEST.sha256)
tar -czf "$build_dir/icechunker-local.tar.gz" -C "$build_dir" icechunker
(cd "$build_dir" && sha256sum icechunker-local.tar.gz > icechunker-local.tar.gz.sha256)
```

Copy the archive and checksum to the server's `~/icechunker/.runtime/install-work/`, created
as above (replace `USER@SERVER` with your SSH destination):

```bash
scp "$build_dir/icechunker-local.tar.gz" "$build_dir/icechunker-local.tar.gz.sha256" \
  USER@SERVER:icechunker/.runtime/install-work/
```

Packaging copies only the explicit runtime manifest; do not copy `ops/` wholesale.
Validated historical header seeds are optional specialist initialization material and are
not included in the rolling main payload or these instructions.

### Stage a fresh installation

On the server, set `archive` to the downloaded or locally built filename:

```bash
cd "$HOME/icechunker/.runtime/install-work"
archive=icechunker-main.tar.gz  # For a local build, use icechunker-local.tar.gz.
sha256sum -c "$archive.sha256"
tar -xzf "$archive" --strip-components=1 -C "$HOME/icechunker"
cd "$HOME/icechunker"
sha256sum -c MANIFEST.sha256
```

The `--strip-components=1` option removes the enclosing `icechunker/` directory, so the
installation files land directly in the chosen root. Use this extraction destination only
for a fresh installation. For an existing installation,
follow **Later upgrades and recovery** below so bootstrap can lock and replace the active app.
After verification, continue with **First use**. For a custom root, substitute it in all paths
and pass that same root to bootstrap. The server needs Python 3.6+, curl, tar, sha256sum and
the Linux prerequisites described below. Bootstrap and production activation run as the job
user without sudo. Successful bootstrap removes the temporary install-work downloads.

## First use

The default root is `~/icechunker`. Read help before doing anything else:

```bash
"$HOME/icechunker/icechunker" help
"$HOME/icechunker/icechunker" help verify
bash "$HOME/icechunker/bootstrap.sh" --help
```

Run bootstrap yourself:

```bash
bash "$HOME/icechunker/bootstrap.sh"
```

On successful bootstrap, missing `config/config.toml` is copied from
`app/ops/config.example.toml`, and missing `config/source-coop.key` is created empty. Both
new files have mode `600` in a mode `700` directory; existing files and their contents are
preserved on repeat runs and upgrades. Paths are relative to the installation root, not the
invoking shell’s working directory.

Edit `config/config.toml` for the source folders, datasets, destination, concurrency and limits.
Fill the empty placeholder with your Source Cooperative service-account key in
`~/icechunker/config/source-coop.key`, owned by the job user, mode `600`, in a mode `700`
directory. The file contains only the key and an optional newline. Never put its value in
arguments, cron, logs or the code package. The empty placeholder is not a usable credential;
`check` will fail until you supply a valid key. Bootstrap never obtains credential values.

Paths in config resolve relative to the root. Absolute managed paths and symlinks must stay
inside it; source model folders may remain outside. The key defaults beside the chosen
`--config` file. Newline and `%` in managed/cron paths are rejected; spaces are supported.
A custom root requires staging the payload inside that root and passing it to bootstrap:

```bash
bash "$HOME/my-icechunker/bootstrap.sh" --root "$HOME/my-icechunker"
"$HOME/my-icechunker/icechunker" help
```

Commands infer their root from their location. No shell-profile changes or user-wide
executables are needed. The root contains one app, one environment, and the following paths:

```text
README.md, bootstrap.sh, icechunker
app/                   processing modules, metadata, config example and lock
config/                private config and key
logs/                  job logs and bootstrap diagnostics
state/                 headers, ledgers, pending transactions, results, locks and seeds
.runtime/bin/          rclone, uv, optional Source Cooperative CLI
.runtime/python/       managed interpreter
.runtime/venv/         environment built at this final path
.runtime/installed.json
.runtime/cache/, .runtime/tmp/, .runtime/install-work/
```

Bootstrap pins rclone 1.76.0, uv 0.13.9 and Python 3.12.12, checks tool download SHA256s,
and performs a wheel-only dependency preflight and install. The lock retains netCDF4 1.7.4
and h5py 3.15.1 for the target's glibc 2.27. It will not compile scientific dependencies.
Host prerequisites are Linux x86_64/aarch64, Python 3.6+, curl and ordinary system libraries.
The observed server is x86_64; this revision's server bootstrap remains untested.
`--python` accepts an existing Python 3.12.12 inside the root. `--with-source-cli` installs
the optional pinned CLI, which automation does not require.

Caches, temporary files and auxiliary tool data remain beneath `.runtime/`; HOME stays
unchanged. The visible interface is the `icechunker` command. For manual CLI use, take care
to use the same contained environment (`app/ops/layout.py environment ROOT` prints it).
The optional CLI needs `DBUS_SESSION_BUS_ADDRESS=unix:path=ROOT/.runtime/run/no-session-bus`
to select its file cache rather than the desktop keyring. Do not use desktop credential stores.

## Commands and supervised testing

All help works without config, keys, scientific libraries or network. `help COMMAND` and
`COMMAND --help` show options, defaults and examples.

| Command | Cost and effect |
| --- | --- |
| `check` | Local config, permissions, key format, imports, tools and source-folder access; no credential exchange or network. Does not establish remote authentication. |
| `status` | Local installed versions/paths, last results, pending work and outstanding failures. Never prints key contents. |
| `sync --dry-run` | Contacts services and exchanges credentials; lists differences without remote writes. Can populate local planning metadata. |
| `sync` | Uploads immutable copies, verifies incoming/pending copies, updates existing stores, validates the committed snapshot and reconciles dataset README metadata. |
| `verify --scope recent` | Reads published data in the recent forecast window; records local results, never uploads or changes stores. Default scope is recent. |
| `verify --scope full` | Refreshes every source header and audits the full coordinate/reference plan with historical science samples. Explicit weekly work. |
| `cron` | Prints suggestions only; never edits crontab. |
| `clean` | Previews cache/tmp cleanup. `--apply` deletes those paths under an exclusive installation lock. |

After provisioning, run these yourself:

```bash
ICECHUNKER="$HOME/icechunker/icechunker"
"$ICECHUNKER" check
"$ICECHUNKER" status
"$ICECHUNKER" sync --dataset roms_hiig --dry-run
"$ICECHUNKER" sync --dataset ww3_hawaii --dry-run
```

Then supervise a real new-transfer `sync --dataset NAME`, confirm its publication and reader
validation, and run `verify --scope full` explicitly before scheduling. Use production only
when intending production operations. Development tests use temporary local stores.
Repeat `--dataset` to select datasets; omitting it runs all configured datasets sequentially.
`--config` selects another in-root TOML file. A dataset failure does not prevent other selected
datasets from running; any failure makes the overall exit code nonzero.

Previously validated public header seeds may be supplied under `state/seeds/headers/`.
Adoption checks their checksum, provenance and current object identities before reuse,
reads no historical NetCDFs, and removes the adopted compressed seed. It creates neither a
byte-verification ledger nor a successful full-audit result. With no usable seed/cache,
initialize explicitly through `verify --scope full`. Normal sync refuses to scan history to
fill a missing cache. Seed identity mismatches need operator investigation or a full audit.

## Processing safeguards and verification limits

The default `minimum_age_minutes = 15` skips new files modified within the last 15 minutes.
This configurable waiting period reduces the chance of copying a file still being written.
Source-file age checks, low-priority reads and conservative transfer concurrency protect the
forecast server. API keys exchange for temporary credentials in memory; bounded upload batches
refresh credentials and stop starting files before expiry. Authentication never silently
falls back to another identity. Deferred files or changed originals produce failure.

Normal sync checks only new/pending transfers. With none, it skips source headers, science
samples and store writes. Object listings still enumerate names for discovery. An initial
baseline records existing published identities without claiming historical MD5 downloads.
The separate checksum ledger prevents repeated downloads of already verified matching copies;
publication acknowledgment occurs only after update/validation succeeds.

Planning reuses validated header/grid metadata. Routine science samples are restricted to
incoming source files in the configured window: past three days plus the forecast horizon,
anchored to UTC job start. Defaults include eight samples (minimum four) and a maximum source
age of 72 hours. Whole-series planning still uses cached metadata and memory for manifests.

After a commit, a fresh anonymous reader checks that exact snapshot. Pending-update journals
and unique commit tokens let retries recover interrupted publication before another write.
Failures retain pending work. Never delete a journal or reset a branch to make a retry pass.
Historical changes outside the routine window are recorded for the full audit.

Full verification refreshes every source header, rejects fresh read errors even when old
successful rows exist, audits the inventory and complete coordinate/reference plan, and
samples historical science data. It does **not** read every virtual chunk or download every
historical NetCDF byte for byte. Exhaustive copy checking is the separate repository tool
`upload/verify_source_coop_copy.py`, excluded from this runtime payload and budgeted separately.
Routine and full results are independent; routine success cannot clear a failed full audit.
WRF and ROMS reanalysis have no automatic repository audit/update; `verify` reports that
these datasets are skipped. The existing reanalysis store remains readable.

## Dataset README metadata

After a successful transfer, sync maintains a **Global metadata attributes** section in
`<prefix>/<dataset>/README.md` on Source Cooperative. It lists every published Icechunk root
attribute with its snapshot ID and every global attribute from the latest completed NetCDF
copy (selected by filename date, then object key), with a public file link. These are separate
sources: the stores can add ERDDAP metadata absent from the files, and file attributes can
vary between runs. Empty attribute sets are stated explicitly. WRF README automation is
disabled even if WRF uploads are configured; no file headers or store attributes are read
for its documentation, and existing pending README state is left for operator review.

Only the section between `<!-- icechunker:global-attributes:start -->` and
`<!-- icechunker:global-attributes:end -->` is generated. Existing prose is preserved; a
missing README gets a minimal heading. Duplicate, reversed or unmatched markers fail the job
instead of risking an edit to the wrong content. Markdown text and attribute values are escaped.

Initialization waits for the dataset's next completed transfer. There is no implicit backfill
on an idle sync. At initialization, one latest completed file's global header is read from its
public copy, using bounded cached ranges; no science arrays are read. The result is stored in
`readme-netcdf.json` against the immutable copy identity. Later idle syncs reuse that cache,
read published Icechunk root metadata, and compare with the current remote README. Unchanged
content is not uploaded. Older backfills never replace metadata from a newer file.

A README failure fails sync but retains `pending-readme.json`; validated copies are already
acknowledged separately, so retrying avoids duplicate checksum downloads or store commits.
`status` displays pending README work. Retry the normal sync; do not delete its state files.
Every attempt reads the README afresh and uses multipart upload, as required by Source
Cooperative, without optional SDK checksum headers. Completion uses an ETag condition (or
a create-only condition for a missing object), so concurrent edits produce a retryable failure.
Failed uploads are aborted when possible. Service support for these conditional writes still
needs a supervised production check. Credentials are refreshed
in memory, and only the dataset README key is writable through this publisher. Dry runs report
changes without remote writes or acknowledging README work. `verify` never publishes READMEs.

The separate development publisher `stores/publish_bundle.py` refuses to overwrite READMEs
containing this section's markers and checks all README destinations before any upload.
It uses conditional multipart completion for unmanaged READMEs to detect concurrent changes.
Compare live prose with git before publishing. A managed README needs a separate reviewed
prose update that preserves its generated section; the bundle does not merge it automatically.

To include static reanalysis, uncomment `[datasets.roms_hiig_reanalysis]` in the config example
and set its source folder. It defaults to `update_store = false`, preserves the uploader's
`netcdf/v2.0/` layout, and documents the existing Icechunk `v2.0` tag. Enabling its unsupported
store updater is rejected. No reanalysis header backfill, store rebuild or tag move is implicit.

## Scheduling, logs and cleanup

```bash
"$HOME/icechunker/icechunker" cron
```

Review the printed fragment, cron daemon timezone, completion times and mail/monitoring.
Default suggestions are sync every three hours and full verification Sunday at 02:47.
Configure numeric five-field `sync_schedule` and `full_verify_schedule` in TOML. Install new
entries manually only after supervised tests. Set `MAILTO` separately if local mail works.
There is no cron install/remove command. Do not run old standalone scripts concurrently.

Jobs set their own working directory/environment and lock each dataset/destination internally;
no outer cron `flock` is needed. Overlap records a skip and returns nonzero. Commands also hold
a shared installation lock; bootstrap and cleanup require it exclusively. Dataset runtime
limits stop the worker process group, including uploader/scanner children. Job logs live in
`logs/` with configurable retention (default 30 days); bootstrap records diagnostics there.
Inspect stdout/stderr too, especially download failures. Monitor failures, timeouts, repeated
skips, pending transactions, stale coverage and the age of `last-success-full.json`.

```bash
"$HOME/icechunker/icechunker" clean
"$HOME/icechunker/icechunker" clean --apply
```

Cleanup preserves config/credentials, durable state, logs, live tools/interpreter/environment
and failed-install work. Successful installation removes archives, dependency caches and
recovery material automatically. Installed commands work without those caches.

## Later upgrades and recovery

Obtain an archive and checksum using the instructions above, and copy them into
`~/icechunker/.runtime/install-work/`. Extract into a new staging directory, preserving the
active application until bootstrap acquires its installation lock:

```bash
cd "$HOME/icechunker/.runtime/install-work"
archive=icechunker-main.tar.gz  # Or icechunker-local.tar.gz.
sha256sum -c "$archive.sha256"
mkdir -m 700 payload  # Must be new; inspect an existing staging directory before proceeding.
tar -xzf "$archive" --strip-components=1 -C payload
(cd payload && sha256sum -c MANIFEST.sha256)
```

Then run the staged bootstrap:

```bash
cd "$HOME/icechunker"
bash "$HOME/icechunker/.runtime/install-work/payload/bootstrap.sh" --root "$HOME/icechunker"
```

Bootstrap holds the installation lock, downloads/checks tools, keeps temporary recovery copies
inside install-work and replaces the single app. It reuses an unchanged environment. A changed
lock builds the replacement at `.runtime/venv/`; a failure restores the previous files at their
original paths. It never executes a renamed backup environment. Config/state remain untouched.
Successful installation removes its incoming package, recovery copies and downloads.
There are no permanent releases, rollback versions or compatibility wrappers.

Ordinary installation errors restore automatically. A power loss or forced kill may leave
`.runtime/install-work/recovery/journal.json`; bootstrap refuses to overwrite it. Stop jobs
and inspect that journal and `logs/bootstrap.log` before restoring each recorded original to
its original path. Do not run recovery copies. Preserve config, state and interpreter paths.
Ask for assistance if restoration is uncertain. This is temporary recovery, not migration.

The November 2026 simplification uses a fresh reset of confirmed old PacIOOS tool artifacts
and their cron block. Credentials/config are provisioned again; old paths are unsupported.
To uninstall later, stop only Icechunker jobs, remove only its cron entries, then delete the
chosen root. Source archives, forecast processes and published stores are independent and
must remain untouched.

## Development and validation

The repository keeps development tests and historical scripts. Only the explicit manifest in
`ops/package.py` defines the runtime payload; old standalone launchers are not shipped.
See **Obtain and stage the payload** for the standard build and deployment steps. Specialist
builds can use `python3 ops/package.py NEW_DIRECTORY --seeds VALIDATED_HEADER_DIRECTORY`.
Verify `MANIFEST.sha256` and, if present,
`state/seeds/MANIFEST.sha256` from that root before initial use. Adopted compressed seeds
are intentionally removed; their original seed manifest no longer describes the consumed files.

```bash
PYTHONPATH=ops:upload python -m unittest discover -s ops -p 'test_*.py'
PYTHONPATH=stores:upload python -m unittest discover -s stores -p test_icechunk_auth.py
PYTHONPATH=upload python -m unittest discover -s upload -p test_upload_auth.py
bash -n ops/bootstrap.sh ops/icechunker
```

Tests use mocks, synthetic data and a local HTTP range server. Separate local installation
checks exercise real pinned downloads and a wheel-only environment. Read the current handoff
for exact local/server checks and staging results; neither establishes production success.

Validation of this revision (2026-11-19): 59 operations/deployment tests and 10 authentication
tests passed locally. A real local pinned wheel-only bootstrap, repeated install, code upgrade
and deliberately failed dependency upgrade passed; restoration preserved the environment and
state. Imports and `pip check` passed after cache removal. The server payload's 25 runtime
files and eight seed files passed SHA256 checks, ownership/permissions, host-Python 3.6 helper
syntax, shell syntax and all help forms at the final root. Server bootstrap, credential
exchange, production processing/full verification and new cron activation remain untested
and reserved for the human operator.
