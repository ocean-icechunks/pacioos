# Copying PacIOOS model files to Source Cooperative

These scripts copy PacIOOS's model output, the original NetCDF files unchanged, from the server
that holds them to the `ocean-icechunks/pacioos` product on
[Source Cooperative](https://source.coop/ocean-icechunks/pacioos). Icechunk stores are then
built over the copies, so readers use Source Cooperative instead of the PacIOOS server.

| File | What it is for | Where it runs |
| --- | --- | --- |
| `upload_to_source_coop.sh` | the upload | on the server that holds the files |
| `verify_source_coop_copy.py` | checks the copies, byte for byte | anywhere; it needs no login |
| `upload_over_ssh.sh` | runs the upload from another machine, over a read-only SSH login | that other machine |
| `source_coop_credentials.py` | exchanges a local service-account API key for temporary upload credentials (requires `boto3`) | the job host, including the PacIOOS server; currently called by the SSH wrapper and store helper |

## Products

| Product | Folder on the PacIOOS server | On Source Cooperative | Files | Size |
| --- | --- | --- | --- | --- |
| `roms_hiig` (forecast) | `/export/data/model/ocn/roms_forecast/hiig` | `pacioos/roms_hiig/netcdf/` | 652 | 1.24 TB |
| `wrf_hi` | `/export/data/model/atm/wrf_hi` | `pacioos/wrf_hi/netcdf/` | 5,607 | 0.94 TB |
| `ww3_hawaii` | `/export/data/model/ore/ww3/hawaii` | `pacioos/ww3_hawaii/netcdf/` | 5,232 | 0.49 TB |
| `roms_hiig_reanalysis` | `/export/data/model/ocn/roms_reanalysis/hiig` | `pacioos/roms_hiig_reanalysis/netcdf/v2.0/` | 4,380 | 1.17 TB |
| `roms_hiig_assim` (hindcast) | `/export/data/model/ocn/roms_assim/hiig` | `pacioos/roms_hiig_assim/netcdf/` (**not uploaded yet**) | 4,045 | 3.37 TB |

Counts as of 2026-11-12. The first four were copied and checked by 2026-11-13; the hindcast
is waiting on a decision about which years to keep. Product names are PacIOOS's THREDDS/ERDDAP dataset IDs.

The public WRF archive now starts on 2017-08-16. The uploader skips older WRF runs.

**Layout.** Each dataset has its own folder on Source Cooperative, with the original files under
`netcdf/` and the Icechunk store built over them under `icechunk/`:

```
pacioos/roms_hiig/netcdf/2026/hiig_forec_20261109.nc      (+ .md5)
pacioos/roms_hiig/icechunk/
```

The year folders on the PacIOOS server are kept as they are under `netcdf/`. To add another
product, add a line to `SOURCE_DIR` near the top of `upload_to_source_coop.sh`, or name it on
the command line as `name=/folder`.

**Versions.** A product released in versions, so far only the reanalysis, gets one folder per
version: `netcdf/v2.0/`, later `netcdf/v3.0/`. The version is set in `PRODUCT_VERSION` in the
script. The reanalysis files carry no version number of their own, so `v2.0` comes from
PacIOOS's THREDDS description. To upload a new version, run with `VERSION=v3.0` (and the new
folder, if it has one, as `roms_hiig_reanalysis=/new/folder`). The old version's copies are not
touched. What to do when versions or files change is worked through in
[issue #2](https://github.com/ocean-icechunks/pacioos/issues/2).

## Running the upload on the PacIOOS server

1. **Get `rclone`.** It is one program file, and needs no installation or root. Download the
   Linux zip from <https://rclone.org/downloads/>, check it against the published `SHA256SUMS`,
   and unzip it anywhere you like.
2. **Get Source Cooperative upload keys.** For unattended jobs, use a service-account API
   key as described below; it may be stored on this server. The local job runner in
   [`ops/`](../ops/README.md) exchanges it for temporary credentials automatically after
   you bootstrap and configure it. For manual runs, the
   [`source-coop` CLI](https://github.com/source-cooperative/source-coop-cli) is another option:
   - `eval "$(source-coop creds --format env)"`, which gives keys for about 12 hours, or
   - set up the AWS profile described at the top of `upload_to_source_coop.sh`. It gets fresh
     keys by itself, which is better for long runs.
3. **See what it would do,** without uploading anything:
   ```bash
   RCLONE=/path/to/rclone ./upload_to_source_coop.sh --dry-run roms_hiig
   ```
4. **Run it,** saving the output:
   ```bash
   RCLONE=/path/to/rclone ./upload_to_source_coop.sh roms_hiig wrf_hi ww3_hawaii 2>&1 | tee -a upload.log
   ```

**What it does for each file:**
- **Skips** the file if it is already on Source Cooperative, or if it changed in the last 15 minutes
  (it may still be being written).
- **Never overwrites a finished copy.** If a file's size on the server no longer matches its
  copy, it prints `CHANGED`, leaves both alone, and exits with status 4 at the end. The
  Icechunk stores point into these copies, so a person decides what the change is (a new
  version, or a correction). A change that keeps the same size is not noticed. The upload
  itself uses rclone's `--immutable`, so even a mistake in that logic cannot replace an object
  already on Source Cooperative.
- **Stops before uploading anything if it cannot list Source Cooperative** (expired keys,
  network): exit status 3. A failed listing must not be mistaken for an empty destination.
- **Computes its MD5 checksum, then uploads it.** Both steps run at the lowest CPU and disk
  priority, so the server's own work comes first.
- **Checks the uploaded size, then uploads a small `<file>.md5`** next to it. A `.md5` file
  means that file's upload finished.
- **A copy without its `.md5`** (an earlier run stopped just after uploading it) is not
  uploaded again: the script downloads it to compute its MD5, writes the `.md5` if it matches
  the file on the server, and prints `CHANGED` if not.

You can stop the script at any time (Ctrl+C) and run it again: it carries on where it left off.
For the same reason, running it once a day after the model runs finish uploads just the new
files.

**Load on the server.** In a test on 2026-11-11, two files at a time (`PARALLEL=2`, the default)
used about 20% of one CPU core and 170 MB of memory, and added about 30–50 MB/s of outgoing
network traffic. Each file is read from disk once. To lighten the load, use `PARALLEL=1`; to
stop, press Ctrl+C.

## Checking the copies

```bash
python3 verify_source_coop_copy.py pacioos/roms_hiig/netcdf/                 # every file
python3 verify_source_coop_copy.py pacioos/roms_hiig/netcdf/ --sample 20     # a random 20
python3 verify_source_coop_copy.py pacioos/ --list-only               # what's there, no downloads
```

It downloads each file over public HTTPS, computes its MD5, and compares it with the `.md5`
file. Run it on a machine other than the PacIOOS server, since the downloads use that
machine's network.

## Running it from another machine (`upload_over_ssh.sh`)

The default SSH target is `pacioos` (set up in your local SSH config), the remote binary is
`/tmp/pacioos-rclone/rclone`, and logs are saved locally to `~/pacioos-upload-logs/logs/`,
outside the repository. All three can be overridden with `SSH_HOST`, `REMOTE_RCLONE`, and
`LOG_DIR`. These paths do not depend on a person's name. The remote binary must exist before
running the wrapper; changing the default does not install or move it.

This is how the first copy was made (Nov 2026), by someone with a read-only login on the PacIOOS
server. The upload script and short-lived keys are sent over SSH for each run, and nothing is
saved on the server except the `rclone` program the run uses. Runs stop starting new files half
an hour before the keys expire, and the next run starts with fresh keys. The logs are kept on
the machine running it. Setup and settings are described at the top of the script.

### Service-account API key on the job host

For a current Source Cooperative service-account key (starting with `sck_`), keep the key at
`~/.source-coop/pacioos.key` on the machine running the job, outside this repository. Create the
directory with mode `700` and the key file with mode `600`. The file contains only the key,
optionally followed by a newline. Long-lived service-account keys are permitted on the
PacIOOS server for unattended jobs (approved 2026-11-18). Provision a key owned by the
operating team; keep it out of git, logs, and cron command lines. The SSH workflow can still
keep its key on the initiating machine and send only temporary credentials to the server.

Source Cooperative documents exchanging these keys for temporary S3 credentials at
<https://docs.source.coop/automated-access>. The service account needs read/write access to
`ocean-icechunks/pacioos`. The wrapper automatically uses the API-key file if present, otherwise
it uses the browser-login `source-coop` CLI. Set `SOURCE_COOP_AUTH=api-key` or `cli` to select
explicitly. An API-key failure stops the wrapper before SSH; it never falls back to another
identity after a failed exchange.

The API-key helper requires local Python 3 and `boto3`. It checks key format, checksum,
ownership, and private permissions before exchanging the key at the fixed Source Cooperative
STS endpoint. Temporary credentials are kept in memory and sent over SSH stdin, never written
to disk. Each exchange requests one hour, so each upload batch starts files for at most about
30 minutes before fetching fresh credentials. In the SSH workflow the long-lived key stays
on the initiating machine; in a local scheduled workflow it stays on the job host.

Persistent bootstrap and cron instructions are in [`ops/README.md`](../ops/README.md), with
the design in [`automation-plan.md`](../docs/design/automation-plan.md). The new local runner
separates routine recent-window Icechunk validation from a periodic historical audit. Existing
standalone update scripts retain their earlier validation behavior. Bootstrap and cron
activation are left to the human operator; staging the package does not run either.

Optional settings: `SOURCE_COOP_API_KEY_FILE` overrides the local key path, and
`SOURCE_COOP_ROLE_ARN` overrides the default `arn:aws:iam::ocean-icechunks:role/FullAccess`.
The service account's Example usage menu supplies its role ARN. An API key identifies the
account; the role selects FullAccess or ReadOnly and cannot grant access the account lacks.
An older Access Key ID / Secret Access Key pair is a different credential format; do not put
that pair in the single-key file.

```bash
PARALLEL=1 bash upload/upload_over_ssh.sh --dry-run roms_hiig ww3_hawaii
# After reviewing the dry run, omit --dry-run to upload missing files.
```

Offline authentication checks: `python3 -m unittest discover -s upload -p 'test_upload_auth.py'`.

## Things about Source Cooperative that `rclone` needs told

Each of these was found by testing in November 2026. All are set in
`upload_to_source_coop.sh`, so there's nothing to do; this list explains why those lines are
there.

| Setting | Without it |
| --- | --- |
| `sign_accept_encoding = false` | every request fails with `SignatureDoesNotMatch` |
| `list_version = 2` | listings say "directory not found" |
| `no_check_bucket = true` | uploads fail with `Missing object key` |
| `upload_cutoff = 0`, streaming cutoff 0 | uploads sent in one piece fail with "headers present in the request which were not signed" |
| `chunk_size = 64M` | requests over about 100 MB are refused (`413`) |

Source Cooperative also drops the checksum `rclone` normally stores with a file. That is why
the scripts keep the `.md5` files instead.

Speeds also depend on distance. From the PacIOOS server, uploads to Source Cooperative go
through Cloudflare in Honolulu, at about 20 MB/s per file. A copy pulled over SSH to a
mainland machine got under 1 MB/s.
