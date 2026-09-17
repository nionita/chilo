#!/usr/bin/env bash
# Run at most one durable futility-campaign work unit under a non-blocking lock.
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "Usage: $0 CONFIG {search|validate|all} [MAX_WORK_UNITS=1]" >&2
    exit 2
fi

config=$1
phase=$2
max_work_units=${3:-1}
script_dir=$(cd -- "$(dirname -- "$0")" && pwd -P)
read -r store_root run_id < <(python3 - "$config" <<'PY'
import json
import sys
from pathlib import Path

config = Path(sys.argv[1]).expanduser().resolve()
raw = json.loads(config.read_text(encoding="utf-8"))
root = Path(raw["store_root"]).expanduser()
if not root.is_absolute():
    root = (config.parent / root).resolve()
print(root, raw["run_id"])
PY
)
run_dir="$store_root/evals/$run_id"
mkdir -p -- "$run_dir"
exec flock -n "$run_dir/campaign.lock" \
    python3 "$script_dir/run_futility_campaign.py" --config "$config" --phase "$phase" --max-work-units "$max_work_units" \
    >>"$run_dir/cron.log" 2>&1
