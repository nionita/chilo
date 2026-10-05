#!/usr/bin/env bash
set -euo pipefail
package_root=$(cd -- "$(dirname -- "$0")" && pwd -P)
cd "$package_root"
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONPATH="$package_root/vendor:$package_root/scripts"
sha256sum -c package-files.sha256
previous_config=${1:-/home/ubuntu/futility-loop-spsa150b-c0014-linux/config/loop.json}
if [[ ! -x .venv/bin/python ]]; then python3 -m venv .venv; fi
numpy_version=$(.venv/bin/python -c 'import sys; v=sys.version_info; print("2.5.3" if v[:2]==(3,14) else "2.2.6" if v.major==3 and 10<=v.minor<=13 else "unsupported")')
if [[ "$numpy_version" == unsupported ]]; then echo 'Use Python 3.10–3.14' >&2; exit 2; fi
if ! .venv/bin/python -c "import numpy; assert numpy.__version__ == '$numpy_version'" 2>/dev/null; then
    test ! -f numerics-check.json || { echo 'Restore the verified runtime; do not update an active phase' >&2; exit 2; }
    .venv/bin/python -m pip install "numpy==$numpy_version"
fi
.venv/bin/python -B configure.py --previous-config "$previous_config"
.venv/bin/python -B verify-numerics.py --loop-config config/loop.json
./loop.sh reconfigure
./loop.sh import-validation --validation-dir /home/ubuntu/futility-validation/evals/bo-d5-pilot4-bo0001-validation/validation
echo 'BO upgrade ready; loop is still stopped. Start explicitly with nohup ./loop.sh resume.'
