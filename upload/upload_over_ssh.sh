#!/usr/bin/env bash
#
# upload_over_ssh.sh — run upload_to_source_coop.sh on a remote server, from your own machine.
#
# PacIOOS staff running the upload on their own server do not need this file: run
# upload_to_source_coop.sh there directly. This is for someone with only a read-only login on
# the server, who can't (or shouldn't) leave files or Source Cooperative keys there:
#
#   * The upload script is sent over SSH and run from memory. It is not saved on the server.
#   * Fresh, short-lived Source Cooperative keys are made HERE, using a local API key or CLI, and
#     sent over the same connection for each run. They are never written to the server's disk.
#   * Each run stops starting new files after RUN_HOURS (default 10), or earlier if the keys
#     have less time left than that, so they never run out mid-run. Then this script starts the
#     next run with fresh keys, until nothing is left. Files already finished are skipped, so a
#     dropped connection costs little.
#   * Everything the upload prints is saved here, in LOG_DIR.
#
#   ./upload_over_ssh.sh --dry-run roms_hiig ww3_hawaii
#
# Settings (environment variables):
#   SSH_HOST        SSH target (default: pacioos, configured in ~/.ssh/config)
#   REMOTE_RCLONE   rclone on the server (default: /tmp/pacioos-rclone/rclone)
#   PARALLEL        files at once (default 2)
#   RUN_HOURS       hours per run before fresh keys (default 10)
#   MAX_RUNS        give up after this many runs (default 20)
#   LOG_DIR         where logs go (default: ~/pacioos-upload-logs/logs, outside git)
#   SOURCE_COOP     the source-coop CLI here (default: source-coop)
#   SOURCE_COOP_AUTH auto (default), api-key, or cli; auto prefers an existing API-key file
#   SOURCE_COOP_API_KEY_FILE local key file (default: ~/.source-coop/pacioos.key)
#   SOURCE_COOP_ROLE_ARN STS role (default: arn:aws:iam::ocean-icechunks:role/FullAccess)
#   VERSION         passed on to upload_to_source_coop.sh (version folder; normally unset)
#
# Any arguments are passed on to upload_to_source_coop.sh (product names, --dry-run).

set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
SSH_HOST=${SSH_HOST:-pacioos}
REMOTE_RCLONE=${REMOTE_RCLONE:-/tmp/pacioos-rclone/rclone}
PARALLEL=${PARALLEL:-2}
RUN_HOURS=${RUN_HOURS:-10}
MAX_RUNS=${MAX_RUNS:-20}
LOG_DIR=${LOG_DIR:-$HOME/pacioos-upload-logs/logs}
SOURCE_COOP=${SOURCE_COOP:-source-coop}
SOURCE_COOP_AUTH=${SOURCE_COOP_AUTH:-auto}
SOURCE_COOP_API_KEY_FILE=${SOURCE_COOP_API_KEY_FILE:-$HOME/.source-coop/pacioos.key}
SOURCE_COOP_ROLE_ARN=${SOURCE_COOP_ROLE_ARN:-arn:aws:iam::ocean-icechunks:role/FullAccess}
if [[ $SOURCE_COOP_AUTH == auto ]]; then
  if [[ -e $SOURCE_COOP_API_KEY_FILE ]]; then SOURCE_COOP_AUTH=api-key; else SOURCE_COOP_AUTH=cli; fi
fi
case $SOURCE_COOP_AUTH in
  api-key|cli) ;;
  *) echo "SOURCE_COOP_AUTH must be auto, api-key, or cli" >&2; exit 3 ;;
esac
mkdir -p "$LOG_DIR"
log="$LOG_DIR/upload-$(date -u +%Y%m%dT%H%MZ).log"
echo "Logging to $log"

# Fetch once per run. Temporary credentials stay in shell memory, not a file or log.
fetch_credentials() {
  if [[ $SOURCE_COOP_AUTH == api-key ]]; then
    python3 "$here/source_coop_credentials.py" \
      --key-file "$SOURCE_COOP_API_KEY_FILE" --role-arn "$SOURCE_COOP_ROLE_ARN"
  else
    "$SOURCE_COOP" creds
  fi
}

key_hours_left() {
  printf '%s' "$credentials" | python3 -c '
import json, sys
from datetime import datetime, timezone
c = json.load(sys.stdin)
for field in ("AccessKeyId", "SecretAccessKey", "SessionToken"):
    if not isinstance(c.get(field), str) or not c[field]:
        raise SystemExit("Missing temporary credential field: " + field)
expiry = datetime.fromisoformat(c["Expiration"].replace("Z", "+00:00"))
print("%.4f" % ((expiry - datetime.now(timezone.utc)).total_seconds() / 3600))'
}

# What one run sends over SSH: keys, settings, then the upload script inside { }. The braces
# make bash read the whole script before running any of it, so nothing the script runs can
# accidentally read the rest of the stream.
remote_input() {
  printf '%s' "$credentials" | python3 -c '
import json, shlex, sys
c = json.load(sys.stdin)
for name, field in (("AWS_ACCESS_KEY_ID", "AccessKeyId"),
                    ("AWS_SECRET_ACCESS_KEY", "SecretAccessKey"),
                    ("AWS_SESSION_TOKEN", "SessionToken")):
    print("export " + name + "=" + shlex.quote(c[field]))' || return 3
  printf 'export RCLONE=%q PARALLEL=%q MAX_HOURS=%q VERSION=%q\n' \
    "$REMOTE_RCLONE" "$PARALLEL" "$hours" "${VERSION:-}"
  printf '{\nexec </dev/null\n'
  cat "$here/upload_to_source_coop.sh"
  printf '\n}\n'
}

need_login() {
  echo "=== Could not get valid Source Cooperative temporary credentials ($SOURCE_COOP_AUTH)." | tee -a "$log"
  if [[ $SOURCE_COOP_AUTH == api-key ]]; then
    echo "=== Check the local API-key file, service-account access, network, and boto3 installation." | tee -a "$log"
  else
    echo "=== Log in again (source-coop login), then rerun; finished files are skipped." | tee -a "$log"
  fi
  exit 3
}

for run in $(seq 1 "$MAX_RUNS"); do
  credentials=$(fetch_credentials) || need_login
  left=$(key_hours_left) || need_login
  # CLI credentials may be cached; API-key exchanges always issue fresh credentials.
  if [[ $SOURCE_COOP_AUTH == cli ]] && awk -v l="$left" 'BEGIN { exit !(l < 1) }'; then
    echo "=== keys expire in $left h; waiting for them to expire so fresh ones are issued" | tee -a "$log"
    sleep $(awk -v l="$left" 'BEGIN { s = int(l * 3600) + 90; print (s > 90 ? s : 90) }')
    credentials=$(fetch_credentials) || need_login
    left=$(key_hours_left) || need_login
  fi
  awk -v l="$left" 'BEGIN { exit !(l > 0.5) }' || need_login
  # Stop starting new files half an hour before the keys expire (a file takes a few minutes).
  hours=$(awk -v l="$left" -v r="$RUN_HOURS" 'BEGIN { h = l - 0.5; if (h > r) h = r; printf "%.2f", h }')
  echo "=== run $run, $(date -u '+%F %T UTC'); keys good for $left h; this run starts files for $hours h" \
    | tee -a "$log"
  status=0
  remote_input | ssh -o BatchMode=yes -o ServerAliveInterval=60 "$SSH_HOST" bash -s -- "$@" \
    2>&1 | tee -a "$log" || status=$?
  last=$(grep '^Finished' "$log" | tail -1 || true)
  if [[ $status -eq 0 && $last == *" 0 failed, 0 left"* ]]; then
    echo "=== all done" | tee -a "$log"; exit 0
  fi
  if [[ $status -eq 4 ]]; then   # files changed on the server: rerunning won't help, a person decides
    echo "=== stopped: some files CHANGED since they were uploaded (see the CHANGED lines above)." \
      | tee -a "$log"; exit 4
  fi
  if [[ $status -eq 3 ]]; then   # could not list Source Cooperative: nothing uploaded; a person checks
    echo "=== stopped: the upload could not list what is already on Source Cooperative (see above)." \
      "Nothing was uploaded. Check the keys and the connection, then rerun." | tee -a "$log"; exit 3
  fi
  [[ " $* " == *" --dry-run "* ]] && exit "$status"
  echo "=== run $run ended (status $status): ${last:-no summary, connection probably dropped}." \
       "Starting again in 60 s." | tee -a "$log"
  sleep 60
done
echo "=== gave up after $MAX_RUNS runs; see $log" | tee -a "$log"; exit 1
