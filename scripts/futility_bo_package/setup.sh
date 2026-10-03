#!/usr/bin/env bash
set -euo pipefail
package_root=$(cd -- "$(dirname -- "$0")" && pwd -P)
cd "$package_root"
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONPATH="$package_root/vendor:$package_root/scripts"
bash verify-package.sh
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
fi
numpy_version=$(.venv/bin/python -c 'import sys; v=sys.version_info; print("2.5.3" if v[:2]==(3,14) else "2.2.6" if v.major==3 and 10<=v.minor<=13 else "unsupported")')
if [[ "$numpy_version" == unsupported ]]; then
    echo 'Use Python 3.10–3.14; newer versions require numerical qualification' >&2
    exit 2
fi
if ! .venv/bin/python -c "import numpy; assert numpy.__version__ == '$numpy_version'" 2>/dev/null; then
    if [[ -f numerics-check.json ]]; then
        echo 'Existing verified environment changed; restore it rather than updating an active pilot' >&2
        exit 2
    fi
    .venv/bin/python -m pip install "numpy==$numpy_version"
fi
.venv/bin/python -B verify-numerics.py
.venv/bin/python -B scripts/run_futility_bo.py --config config/pilot.json --dry-run
