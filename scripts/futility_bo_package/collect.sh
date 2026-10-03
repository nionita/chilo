#!/usr/bin/env bash
set -euo pipefail
package_root=$(cd -- "$(dirname -- "$0")" && pwd -P)
cd "$package_root"
export PYTHONPATH="$package_root/vendor:$package_root/scripts"
read -r store_root run_id < <(.venv/bin/python - "$package_root/config/pilot.json" <<'PY'
import json,sys
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text())
print(c['store_root'],c['run_id'])
PY
)
target="${1:-$package_root/bo-d5-pilot1-results.tgz}"
if [[ -e "$target" ]]; then
    echo "Refusing to overwrite $target" >&2
    exit 2
fi
tar -czf "$target" -C "$store_root" "evals/$run_id" -C "$package_root" \
    package_manifest.json package-files.sha256 config/pilot.json numerics-check.json
sha256sum "$target"
