#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${ROOT_DIR}/requirements-nnue.txt"
"${VENV_DIR}/bin/pip" install --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple torch

echo "Created ${VENV_DIR}"
echo "Activate with: source ${VENV_DIR}/bin/activate"
