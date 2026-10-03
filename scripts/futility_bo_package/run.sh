#!/usr/bin/env bash
set -euo pipefail
package_root=$(cd -- "$(dirname -- "$0")" && pwd -P)
cd "$package_root"
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONPATH="$package_root/vendor:$package_root/scripts"
test -x .venv/bin/python || { echo 'Run bash setup.sh first' >&2; exit 2; }
test -f numerics-check.json || { echo 'Run bash setup.sh to verify the numerical environment' >&2; exit 2; }
bash verify-package.sh
exec .venv/bin/python -B scripts/run_futility_bo.py --config config/pilot.json --resume "$@"
