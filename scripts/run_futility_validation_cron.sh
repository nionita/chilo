#!/usr/bin/env bash
# Run one durable validation-shard phase under cron.  The lock is deliberately
# advisory and short-lived only in the sense that it lasts for the active
# probe; it prevents cron from starting a second per-root search.
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "usage: $0 <config.json> <run-dir>" >&2
    exit 2
fi

config_path=$1
run_dir=$2
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$run_dir/logs"

exec 9>"$run_dir/supervisor.lock"
if ! flock -n 9; then
    exit 0
fi

log_path="$run_dir/logs/cron.log"
blocked_path="$run_dir/BLOCKED"
failure_path="$run_dir/failures.json"
if [[ -e "$blocked_path" ]]; then
    exit 0
fi

timestamp=$(date --iso-8601=seconds)
printf '%s start config=%s\n' "$timestamp" "$config_path" >> "$log_path"
if python3 "$script_dir/run_futility_validation_shards.py" --config "$config_path" >> "$log_path" 2>&1; then
    rm -f "$failure_path"
    printf '%s success\n' "$(date --iso-8601=seconds)" >> "$log_path"
    exit 0
fi

count=1
if [[ -f "$failure_path" ]]; then
    previous=$(sed -n '1p' "$failure_path" || true)
    if [[ "$previous" =~ ^[0-9]+$ ]]; then
        count=$((previous + 1))
    fi
fi
printf '%s\n' "$count" > "$failure_path"
printf '%s failure count=%s\n' "$(date --iso-8601=seconds)" "$count" >> "$log_path"
if (( count >= 3 )); then
    printf 'blocked after %s consecutive failures; see logs/cron.log\n' "$count" > "$blocked_path"
    printf '%s BLOCKED\n' "$(date --iso-8601=seconds)" >> "$log_path"
fi
exit 1
