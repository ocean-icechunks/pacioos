# Deployable Icechunker principles and simplification plan

Approved and implemented 2026-11-19; bootstrap-defaults follow-up approved and implemented
the same day. See [`agent/handoff.md`](../../agent/handoff.md) for validation and the latest
observed server state. Bootstrap execution and activation remain human work. This document
is the implementation brief for a fresh agent and the reusable guidance for future tool
packages. It supersedes the deployment layout, migration, release-retention and command
interface in `automation-plan.md` and older handoff entries. Preserve their data-processing
safeguards where they do not conflict with the decisions below.

## Reusable packaging principles

1. **Optimize for the operator's understanding.** A person should immediately see how to
   get help, run a job, find configuration and read logs. Give commands descriptive names,
   keep the quick-start short, and explain which operations contact remote services.
2. **Own one removable directory.** Put code, downloaded tools, Python, environments,
   configuration, API keys, state, caches, bytecode and temporary files beneath one
   configurable persistent root. Reject path and symlink escapes. Do not modify HOME,
   shell profiles, user-wide executable directories or desktop credential stores.
   Preexisting OS prerequisites and read-only input data can remain outside. User-managed
   cron entries are the sole provisioning exception.
3. **Ship a deliberate runtime payload.** Use an explicit file manifest. Include only the
   processing modules, required metadata, dependency lock and operator documentation.
   Development tests, notebooks, historical design notes and copied repository trees belong
   in the development repository, not in repeated deployed setup directories.
4. **Keep one working installation.** Use one application copy and one active environment.
   Do not accumulate hashed releases, setup copies or permanent rollback versions. Temporary
   recovery material is allowed during an upgrade; restore on failure and remove it on success.
5. **Separate durable state from disposable files.** Header manifests, approval records,
   transfer/checksum ledgers, pending transactions and locks are operational state. They
   are not installer caches. Losing them can cause repeated downloads, forgotten recovery
   work or an unexpected historical scan. Cleanup must preserve them and credentials.
6. **Discard installation leftovers.** Delete downloaded archives and dependency installation
   caches after successful installation. Installed commands must work without those files.
   Keep any failure diagnostics in a clearly identified temporary work area, not a growing
   sequence of installation attempts.
7. **Make installation reproducible on the actual host.** Pin tools and dependencies, verify
   download checksums, and check wheel compatibility before installation. Prefer prebuilt
   dependencies; never unexpectedly compile scientific libraries on a live model server.
   Build virtual environments at their final paths; never relocate them after creation.
8. **Expose work and cost explicitly.** Local checks must not silently become network audits.
   Normal jobs should be proportional to incoming work. Historical verification must be an
   explicit command. File listings are discovery, not a claim of data verification.
9. **Make scheduled work self-contained and resumable.** Set the working directory and
   environment explicitly, lock conflicting operations internally, bound retries/runtime,
   and persist recovery state before remote commits. A retry must not forget an unvalidated
   commit or mistake deferred uploads for successful completion.
10. **Keep credentials private and errors visible.** Provision credential values separately, keep their
    values out of arguments/logs/examples, exchange them for temporary credentials at runtime,
    and never fall back silently to another identity. Record meaningful success/failure
    status without claiming that untested access paths or unverified data passed validation.
11. **Prepare editable defaults without overwriting operator choices.** A successful bootstrap
    should leave the files an operator needs to edit at predictable locations. Copy a missing
    config from the shipped example and create a missing private, empty key placeholder.
    Use exclusive creation so repeat installs cannot truncate existing files. Keep secret
    values out of templates and installation automation. Creating an empty key file is not
    credential provisioning or evidence that authentication works.

These principles are reusable beyond PacIOOS. The concrete paths, versions and dataset
behavior below are specific to this deployment; do not generalize them blindly.

## Approved layout

Default root: `$HOME/icechunker`, configurable with `--root`.

```text
icechunker/
  README.md          # quick start, operations, troubleshooting
  bootstrap.sh       # install or update
  icechunker         # main command
  app/               # one copy of required processing code
  config/            # config.toml and private key placeholder; operator supplies key value
  logs/              # operational and installation logs
  state/             # manifests, ledgers, journals and locks
  .runtime/          # managed implementation details
    bin/             # rclone, uv, optional Source Cooperative CLI
    python/          # managed interpreter
    venv/            # one active Python environment
    installed.json   # tool/dependency versions and installation status
    cache/
    tmp/
    install-work/    # temporary installation/recovery material
```

Remove the old `current`, `releases`, `setup-*`, top-level `downloads`, `tools`, `python`,
`cache`, `seeds`, `run` and `data` interface. Consolidate their necessary contents according
to the layout above. This must reduce duplication, not merely hide the same release trees.
Do not promise a disk-space reduction based on adding up directories: installed files may
share storage with dependency caches. Measure the result after cleanup.

Keep header seeds beneath `state/` until successfully adopted. Validate provenance and
object identities before adoption; afterwards remove the redundant compressed seed. Seed
reuse is not a new full verification or a fabricated byte-verification ledger.

## Bootstrap defaults contract

On successful bootstrap, beneath the selected installation root:

- If `config/config.toml` is absent, copy the contents of `app/ops/config.example.toml`
  into it. Do not require a separate manual copy step.
- If `config/source-coop.key` is absent, create an empty file. Never generate, fetch or
  populate a credential value during bootstrap.
- Create both new files with mode `600`, owned by the invoking job user, and keep the
  containing `config/` directory mode `700`.
- Preserve existing config/key files and their contents on repeat installs and upgrades.
  An existing empty file also remains untouched. Use exclusive creation rather than a
  check followed by an overwriting write.
- Resolve these paths against the installation root, including a custom `--root`, not the
  caller's current working directory. Apply the existing path/symlink containment checks.

`ops/bootstrap.sh` delegates installation to the host-Python-compatible `ops/install.py`;
`initialize_config()` implements these defaults after dependency and application checks,
while the installation lock is held. The example stays in the explicit runtime manifest;
generated config/key files are private operator files, never added to the payload manifest.

The operator then reviews the config and fills the key file. An empty placeholder is not
ready for use: local `icechunker check` must reject it until a valid key is supplied. This
local check does not establish remote authentication. Explain this sequence in the deployed
README and bootstrap help/output. Staging revised scripts alone must not create config/key
files or run bootstrap on the operator's behalf.

## Main command contract

| Command | Behavior |
| --- | --- |
| `icechunker help [command]` | Usage, options, defaults and examples; also support global and per-command `--help` |
| `icechunker sync` | Upload eligible immutable copies, verify incoming/pending transfers, update the store and validate applicable incoming data |
| `icechunker check` | Local readiness only: config, paths, permissions, key format, tools/imports and source-folder access |
| `icechunker verify --scope recent` | Explicit remote checks of the recent forecast window |
| `icechunker verify --scope full` | Explicit historical repository audit, intended for weekly use |
| `icechunker status` | Installed versions, important paths, last results, pending work and outstanding failures; never key contents |
| `icechunker cron` | Print suggested entries referencing the unified command; do not install them |
| `icechunker clean` | Preview disposable files; deletion requires `--apply` |

Preserve existing applicable options, including `--dataset`, `--config`, sync `--dry-run`,
and verification `--scope recent|full` (default `recent`). Do not add compatibility wrappers,
old command aliases or a cron-install/remove interface to the deployed payload.

Help must work without configuration, credentials or network access and exit successfully.
Handle help before configuration loading, credential checks or scientific-stack imports.
`check` makes no network requests or credential exchanges and does not claim remote
authentication works. `verify` reads published data and writes local results/logs; it must
not upload files or modify the published Icechunk repository.

Explain that full verification refreshes every source header and checks the complete
coordinate/reference plan with historical science-data samples. It does not read every
virtual chunk or download every historical NetCDF byte for byte. The existing all-file
copy-checking script is a separate exhaustive operation; do not silently add its cost to
the weekly repository audit.

## Processing behavior to preserve

- NetCDF copies are write-once. Never overwrite/delete them or change destination layout
  as part of this local packaging work. Preserve source-file age checks and low-priority,
  conservative transfer concurrency on the forecast server.
- The default `minimum_age_minutes` is **15** (updated 2026-11-19), measured from a source
  file's last modification time, not its forecast date. Apply the same default in config
  loading, the shipped config example and the standalone uploader's `MIN_AGE_MINUTES`.
  This configurable waiting period reduces the risk of copying an unfinished file; it is
  not proof of completion or a measured PacIOOS production-time guarantee. Explicit config
  values override the default, and updating shipped defaults must not silently rewrite an
  operator's existing configuration.
- Normal sync verifies only new/pending transfers. With no incoming work, skip header
  reads, science-data sampling and Icechunk writes. Listings may enumerate all object names.
  Never refill an empty historical cache implicitly during normal sync.
- Persist checksum results separately from publication acknowledgment. A crash after a
  checksum succeeds must still retry an unpublished store update; it must not re-download
  a matching previously verified copy.
- Reuse validated header/grid metadata for planning. Bound routine science samples to
  incoming sources in the configured recent window: default past three days plus the
  forecast horizon. Keep historical verification/cache initialization explicit.
- Preserve snapshot-pinned anonymous reader validation and recovery after interruption
  between commit and validation. Keep routine and full audit results independent.
- Sync and verification share a nonblocking exclusive lock per dataset/destination.
  Overlap records a skip and returns nonzero. No outer cron `flock` is needed.
- Preserve the existing root-containment environment, temporary credential refresh,
  no-identity-fallback behavior, runtime limits, log retention and partial-work reporting.
- ROMS forecast and WW3 support store updates. ROMS reanalysis supports immutable copies and
  dataset README metadata, without automatic store updates or repository audits. WRF supports
  immutable copies only; its existing team-managed store and README are excluded from automation.
  Reanalysis keeps `netcdf/v2.0/` and reads its existing Icechunk `v2.0` tag for documentation.
- After successful copy/store validation, reconcile the dataset README's marked global-attribute
  section with actual published snapshot attributes and the latest completed file's global
  header. Preserve surrounding prose and skip unchanged writes. Initialize on the next transfer;
  idle syncs reuse cached file attributes and may read published root metadata, never source
  headers or science arrays. Select the representative file by filename date, then key.
- Cache file attributes with immutable copy identity. Persist pending README work before
  acknowledging validated copies, independently of store transactions. A README failure fails
  sync and retries without duplicate checksum downloads or store commits. Read the current README
  on every attempt, use conditional writes to protect concurrent edits, and reject ambiguous
  section markers. `verify` remains read-only remotely; dry runs publish nothing.
- The separate build-bundle publisher must preflight all README destinations before uploads
  and refuse destinations containing generated metadata markers, including incomplete markers.
  Unmanaged READMEs use conditional multipart completion to detect concurrent edits. Keep the
  exact committed-byte publication contract; editing managed README prose is a separate reviewed
  operation that preserves the generated section. Bundle dry runs may preview uncommitted
  files without credentials, but actual uploads require clean committed inputs. Exclude
  development tests and publish the API-key helper beside the shared credential module.

## Fresh installation and deployment boundaries

The user explicitly chose a fresh start. **Do not implement migration, compatibility
wrappers or preservation of old command paths.** Bootstrap prepares missing config and an
empty private key file; the operator reviews configuration and supplies the credential value.
The authorized removal of the old deployment and its PacIOOS cron block was completed on
2026-11-19. It superseded earlier instructions to retain legacy installations for migration.
Do not treat that completed reset as permission to delete the new installation or repeat the
reset. Preserve current config, credentials, environments and durable state on later updates.

The original implementation/reset sequence (completed; see handoff for results):

1. Read the current handoff and inspect the uncommitted workspace. Refactor the deployment
   layer and command entrypoint; reuse the existing processing logic. Build the new payload
   and validate it locally before removing the working server deployment.
2. On the server, identify the exact existing Icechunker jobs, deployment directories and
   associated cron entries. Stop only Icechunker jobs. Remove only confirmed PacIOOS tool
   artifacts/cron entries; preserve unrelated cron tasks, provider forecast processes,
   source NetCDF archives, the development repository and published Source Cooperative data.
3. Stage the replacement package beneath the chosen single root. No configuration, keys,
   state or environments need to be migrated from the removed installation. Validated
   public header seeds may be included as initialization material.
4. Leave execution of bootstrap, configuration review, API-key value provisioning, supervised
   production tests and installation of new cron entries to the human operator. Do not run production sync,
   historical verification or automatic credential provisioning while staging the package.

Later upgrades retain one active installation. Hold installation/dataset locks, prepare
needed downloads, and keep temporary recovery material inside `.runtime/install-work/`.
Reuse an unchanged environment; for dependency changes build at the final environment path
and restore the old installation at its original paths on failure. Do not execute a renamed
backup environment. After success, remove recovery copies, obsolete dependencies and caches.
Never prune anything still referenced by the active interpreter/environment.

## Host compatibility and development starting points

The observed target is unprivileged Linux x86_64 with glibc 2.27 and host Python 3.6.
Bootstrap's early path/environment helpers must work with that host Python. Processing uses
managed Python 3.12.12. Working pins include rclone 1.76.0, uv 0.13.9, Icechunk 2.3.1,
VirtualiZarr 2.8.0, netCDF4 1.7.4 and h5py 3.15.1. The original netCDF4 1.7.5.1.post1 and
h5py 3.16.0 pins lacked suitable glibc-2.27 wheels. Retain the wheel-only preflight and
installation policy; don't accidentally restore the failing pins from older requirements.
Source Cooperative CLI is optional; API-key automation does not need it.

The implementation lives in `ops/`. `bootstrap.sh` delegates installation/environment and
config-default creation to `install.py`, using `layout.py` for containment/environment rules.
The `icechunker` launcher and `cli.py` expose the unified interface; `jobs.py` and `common.py`
handle command execution/config/locking. `package.py` defines the explicit runtime manifest.
Legacy `launch.sh`, `tool.sh` and old standalone command wrappers are superseded and excluded
from this implementation and its payload. Data processing lives in `pipeline.py`, `headers.py`, `validation.py`,
`upload/` and `stores/`. Package only required imports/metadata. Keep the
development tests in the repository even though they are excluded from the payload.
Do not rewrite model selection, computed virtual references or array layout for this refactor.

## Acceptance checks

- Global help, `help <command>` and every subcommand's `--help` work with absent config/keys
  and network disabled; `check` remains local-only.
- Fresh and repeated installation leave one application and one environment, with no
  permanent setup/archive/release duplicates. All paths remain inside a custom root too.
- Bootstrap creates the missing example-derived config and empty key at the chosen root,
  with file mode `600` and directory mode `700`; repeat installs preserve edited config and
  populated keys. Empty placeholders remain unusable until the operator supplies a valid key.
- Failed upgrades restore runnable commands and unchanged configuration/state. Successful
  upgrades remove recovery material and obsolete dependencies.
- Installed commands work after removing disposable caches. `clean` defaults to preview,
  requires `--apply`, excludes credentials/durable state/live dependencies, and respects locks.
- Normal no-transfer runs perform zero header/science reads. New-transfer runs inspect only
  incoming headers/data, reuse historical metadata, and recover failed publication correctly.
- Explicit full verification refreshes every header and rejects new read failures rather
  than accepting old cached successes. It cannot clear a failure merely through a later
  routine success.
- Existing locking, immutable-copy, credential-privacy and snapshot-recovery tests continue
  passing. Add CLI, payload, install-idempotence, cleanup and upgrade-failure tests.
- Verify the staged payload's file manifest, permissions, host-compatible shell/helper
  syntax, contents and operator README. Record what was tested locally versus on the server;
  do not claim a production run or bootstrap test that the agent did not perform.
