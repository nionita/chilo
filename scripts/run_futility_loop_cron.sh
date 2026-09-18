#!/usr/bin/env bash
# The Python runner owns the process lock; cron only recovers interruptions.
set -euo pipefail
if [[ $# -ne 1 ]]; then
    echo "Usage: bash $0 CONFIG" >&2
    exit 2
fi
script_dir=$(cd -- "$(dirname -- "$0")" && pwd -P)
exec python3 "$script_dir/run_futility_loop.py" run --config "$1"
