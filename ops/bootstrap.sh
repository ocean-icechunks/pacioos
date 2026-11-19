#!/usr/bin/env bash
# Install and create missing private config/key placeholders; preserve existing files.
# Never provisions credential values, runs processing jobs or changes cron.
set -euo pipefail
umask 077
payload=$(cd "$(dirname "$0")" && pwd -P)
exec python3 -B "$payload/app/ops/install.py" --payload "$payload" "$@"
