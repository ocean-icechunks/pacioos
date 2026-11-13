#!/usr/bin/env bash
#
# upload_over_ssh.sh — run upload_to_source_coop.sh on a remote server, from your own machine.
#
# PacIOOS staff running the upload on their own server do not need this file: run
# upload_to_source_coop.sh there directly. This is for someone with only a read-only login on
# the server, who can't (or shouldn't) leave files or Source Cooperative keys there:
#
#   * The upload script is sent over SSH and run from memory. It is not saved on the server.
#   * Fresh, short-lived Source Cooperative keys are made HERE, with `source-coop creds`, and
#     sent over the same connection for each run. They are never written to the server's disk.
#   * Each run stops starting new files after RUN_HOURS (default 10), or earlier if the keys
#     have less time left than that, so they never run out mid-run. Then this script starts the
#     next run with fresh keys, until nothing is left. Files already finished are skipped, so a
#     dropped connection costs little.
#   * Everything the upload prints is saved here, in LOG_DIR.
#
#   SSH_HOST=myserver REMOTE_RCLONE=/tmp/me-rclone/rclone ./upload_over_ssh.sh roms_hiig wrf_hi
#
# Settings (environment variables):
#   SSH_HOST        required: what you would type after `ssh` (a ~/.ssh/config alias works)
#   REMOTE_RCLONE   rclone on the server (default: rclone)
#   PARALLEL        files at once (default 2)
#   RUN_HOURS       hours per run before fresh keys (default 10)
#   MAX_RUNS        give up after this many runs (default 20)
#   LOG_DIR         where logs go (default: ./logs next to this script)
#   SOURCE_COOP     the source-coop CLI here (default: source-coop)
#   VERSION         passed on to upload_to_source_coop.sh (version folder; normally unset)
#
# Any arguments are passed on to upload_to_source_coop.sh (product names, --dry-run).

set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
: "${SSH_HOST:?set SSH_HOST to the server to connect to}"
REMOTE_RCLONE=${REMOTE_RCLONE:-rclone}
PARALLEL=${PARALLEL:-2}
RUN_HOURS=${RUN_HOURS:-10}
MAX_RUNS=${MAX_RUNS:-20}
LOG_DIR=${LOG_DIR:-$here/logs}
SOURCE_COOP=${SOURCE_COOP:-source-coop}
mkdir -p "$LOG_DIR"
log="$LOG_DIR/upload-$(date -u +%Y%m%dT%H%MZ).log"
echo "Logging to $log"

# Hours until the current Source Cooperative keys expire (prints only the number, never the keys).
key_hours_left() {
  local exp
  exp=$("$SOURCE_COOP" creds 2>/dev/null |
        python3 -c 'import json,sys; print(json.load(sys.stdin)["Expiration"])' 2>/dev/null) || return 1
  [[ -n $exp ]] || return 1
  awk -v s="$(( $(date -d "$exp" +%s) - $(date +%s) ))" 'BEGIN { printf "%.2f", s / 3600 }'
}

# What one run sends over SSH: keys, settings, then the upload script inside { }. The braces
# make bash read the whole script before running any of it, so nothing the script runs can
# accidentally read the rest of the stream.
remote_input() {
  "$SOURCE_COOP" creds --format env                 # export AWS_ACCESS_KEY_ID=... etc.
  printf 'export RCLONE=%q PARALLEL=%q MAX_HOURS=%q VERSION=%q\n' \
    "$REMOTE_RCLONE" "$PARALLEL" "$hours" "${VERSION:-}"
  printf '{\nexec </dev/null\n'
  cat "$here/upload_to_source_coop.sh"
  printf '\n}\n'
}

need_login() {
  echo "=== Could not get Source Cooperative keys: the login has probably expired." | tee -a "$log"
  echo "=== Log in again (source-coop login), then rerun this script; finished files are skipped." \
    | tee -a "$log"
  exit 3
}

for run in $(seq 1 "$MAX_RUNS"); do
  left=$(key_hours_left) || need_login
  if awk -v l="$left" 'BEGIN { exit !(l < 1) }'; then   # under an hour: let them expire, then renew
    echo "=== keys expire in $left h; waiting for them to expire so fresh ones are issued" | tee -a "$log"
    sleep $(awk -v l="$left" 'BEGIN { s = int(l * 3600) + 90; print (s > 90 ? s : 90) }')
    left=$(key_hours_left) || need_login
  fi
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
  [[ " $* " == *" --dry-run "* ]] && exit "$status"
  echo "=== run $run ended (status $status): ${last:-no summary, connection probably dropped}." \
       "Starting again in 60 s." | tee -a "$log"
  sleep 60
done
echo "=== gave up after $MAX_RUNS runs; see $log" | tee -a "$log"; exit 1
