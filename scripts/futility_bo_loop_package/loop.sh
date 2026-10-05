#!/usr/bin/env bash
set -euo pipefail
package_root=$(cd -- "$(dirname -- "$0")" && pwd -P)
cd "$package_root"
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONPATH="$package_root/vendor:$package_root/scripts"
test -f numerics-check.json || { echo 'Run setup.sh before loop commands' >&2; exit 2; }
exec .venv/bin/python -B scripts/run_futility_loop.py "$@" --config "$package_root/config/loop.json"
